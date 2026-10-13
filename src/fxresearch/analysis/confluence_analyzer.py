from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd

from fxresearch.analysis.report import ReportWriter, announce
from fxresearch.costs.cost_model import CostModel
from fxresearch.data.instruments import DEFAULT_PIP_SIZE, PIP_SIZE
from fxresearch.engine.metrics import SPLIT_YEAR

CONFLUENCES = ["bias2", "bias3", "d4", "trigger", "latest_aoi", "cluster_aoi",
               "h1_close", "h1_pattern", "struct_stop", "target_ok", "session",
               "regime_high", "regime_low"]
CORE_STACK = ["d4", "trigger", "latest_aoi", "cluster_aoi", "h1_close", "struct_stop", "target_ok", "session"]
TRUST_N = 1000
FLAG_N = 300
A_RR = {"a_R_0p5R": 0.5, "a_R_0p75R": 0.75, "a_R_1R": 1.0, "a_R_1p5R": 1.5, "a_R_2R": 2.0}


def breakeven(rr: float) -> float:
    return 100 / (1 + rr)


def win_stats(r: pd.Series) -> tuple[int, float, float]:
    r = r.dropna()
    if r.empty: return 0, float("nan"), float("nan")
    return len(r), 100 * (r > 0).mean(), float(r.mean())


class ConfluenceAnalyzer:

    def __init__(self, costs: CostModel, samples_path: Path, out_path: Path) -> None:
        self.samples_path = samples_path
        self.out_path = out_path

        self.costs = costs

        self.df = pd.DataFrame()
        self.a_cols: list[str] = []
        self.report = ReportWriter()
        self.load()

    def load(self) -> None:
        self.df = self._add_costs(pd.read_csv(self.samples_path))
        # older sample files may not carry every target column
        self.a_cols = [column for column in A_RR if column in self.df.columns]

    def run(self) -> None:
        df = self.df
        is_mask = df["year"] < SPLIT_YEAR
        oos_mask = df["year"] >= SPLIT_YEAR
        out = self.report.out

        out(f"# Confluence ranking ({len(df):,} candidates, "
            f"{df['instrument'].nunique()} instruments, {int(df['year'].min())}-{int(df['year'].max())})")
        out(f"IS {int(df['year'].min())}-{SPLIT_YEAR - 1}: {int(is_mask.sum()):,} | "
            f"OOS {SPLIT_YEAR}-{int(df['year'].max())}: {int(oos_mask.sum()):,}")
        out("Win% = % of trades with R>0. Lens A = fixed 1xATR stop. "
            "'net' = after per-instrument modeled cost.")
        out("")

        self._baselines()
        self._single_lift(oos_mask)
        self._stack_depth()
        for size in (2, 3):
            self._combos(size, is_mask, oos_mask)
        self._slices()

        self.report.save(self.out_path)
        print()
        announce(self.out_path)

    def _add_costs(self, df: pd.DataFrame) -> pd.DataFrame:
        pip = df["instrument"].map(PIP_SIZE).fillna(DEFAULT_PIP_SIZE)

        # cost in r is per round trip; lens a risks 1x atr, lens b risks sl_atr x atr
        risk_pips_a = df["atr"] / pip
        risk_pips_b = df["sl_atr"] * df["atr"] / pip
        cost_a = np.array([self.costs.cost_r(i, rp) for i, rp in zip(df["instrument"], risk_pips_a)])
        cost_b = np.array([self.costs.cost_r(i, rp) for i, rp in zip(df["instrument"], risk_pips_b.fillna(0))])
        df["cost_a"] = cost_a
        df["cost_b"] = cost_b
        for column in A_RR:
            if column in df:
                df[column + "_net"] = df[column] - cost_a
        df["b_R_net"] = df["b_R"] - cost_b
        df["regime_high"] = df["regime"] == "high"
        df["regime_low"] = df["regime"] == "low"
        return df

    def _baselines(self) -> None:
        df, out = self.df, self.report.out
        out("## 1. No-filter baselines (the null to beat)")
        out(f"{'lens':<16}{'n':>8}{'win%':>8}{'BE%':>7}{'avgR':>9}{'net win%':>10}{'net avgR':>10}")
        for column in self.a_cols:
            n, w, a = win_stats(df[column])
            _, nw, na = win_stats(df[column + "_net"])
            out(f"{('A @' + str(A_RR[column]) + 'R'):<16}{n:>8}{w:>8.1f}{breakeven(A_RR[column]):>7.1f}{a:>9.3f}"
                f"{nw:>10.1f}{na:>10.3f}")
        n, w, a = win_stats(df["b_R"])
        _, nw, na = win_stats(df["b_R_net"])
        out(f"{'B struct+AOI':<16}{n:>8}{w:>8.1f}{'~':>7}{a:>9.3f}{nw:>10.1f}{na:>10.3f}")
        out("")
        out("BE% = breakeven win rate for that RR (win% must clear it net of cost to profit). "
            "A baseline at BE% means no directional edge before confluences.")
        out("")

    def _single_lift(self, oos_mask: pd.Series) -> None:
        df, out = self.df, self.report.out
        out("## 2. Single-confluence lift (Lens A @1R, present vs absent)")
        out(f"{'confluence':<14}{'n_pres':>8}{'win% pres':>11}{'win% abs':>10}{'lift':>7}"
            f"{'net avgR':>10}{'OOS win%':>10}")

        ranked = []
        for confluence in CONFLUENCES:
            present = df[df[confluence] == True]
            absent = df[df[confluence] == False]
            n_present, win_present, _ = win_stats(present["a_R_1R"])
            _, win_absent, _ = win_stats(absent["a_R_1R"])
            _, _, net_present = win_stats(present["a_R_1R_net"])
            _, win_oos, _ = win_stats(df[(df[confluence] == True) & oos_mask]["a_R_1R"])
            lift = win_present - win_absent if np.isfinite(win_present) and np.isfinite(win_absent) else float("nan")
            ranked.append((confluence, n_present, win_present, win_absent, lift, net_present, win_oos))

        for c, n_present, wp, wa, lift, net, wo in sorted(ranked, key=lambda x: -(x[4] if np.isfinite(x[4]) else -99)):
            out(f"{c:<14}{n_present:>8}{wp:>11.1f}{wa:>10.1f}{lift:>+7.1f}{net:>10.3f}{wo:>10.1f}")
        out("")
        out("lift = win%(present) - win%(absent). Positive & OOS-stable = a real, "
            "tradeable confluence. Near-zero = decoration.")
        out("")

    def _stack_depth(self) -> None:
        df, out = self.df, self.report.out
        out("## 3. Win rate vs number of confluences present (the win-rate/RR frontier)")
        depth = df[CORE_STACK].sum(axis=1)
        out(f"using core set: {CORE_STACK}")
        out(f"{'#conf':>6}{'n':>9}{'w@0.5':>7}{'w@.75':>7}{'w@1R':>7}{'w@1.5':>7}{'w@2R':>7}"
            f"{'net@0.5':>9}{'net@1R':>9}")

        for k in range(0, len(CORE_STACK) + 1):
            m = depth == k
            n = int(m.sum())
            if n == 0: continue

            wins = {column: win_stats(df[m][column])[1] for column in self.a_cols}
            net_half = win_stats(df[m]["a_R_0p5R_net"])[2]
            net_one = win_stats(df[m]["a_R_1R_net"])[2]
            out(f"{k:>6}{n:>9}{wins['a_R_0p5R']:>7.1f}{wins['a_R_0p75R']:>7.1f}{wins['a_R_1R']:>7.1f}"
                f"{wins['a_R_1p5R']:>7.1f}{wins['a_R_2R']:>7.1f}{net_half:>9.3f}{net_one:>9.3f}")

        out("")
        out("Win% rises as the target tightens (0.5R) but so does the breakeven (66.7%). "
            "The only thing that matters is net@: positive = the stack actually pays.")
        out("")

    def _combo_rows(self, size: int, is_mask: pd.Series, oos_mask: pd.Series) -> list[dict]:
        df = self.df
        rows = []

        for combo in itertools.combinations(CONFLUENCES, size):
            m = np.ones(len(df), bool)
            for confluence in combo:
                m &= (df[confluence] == True).to_numpy()
            n = int(m.sum())
            if n < FLAG_N: continue

            subset = df[m]
            wins = {column: win_stats(subset[column])[1] for column in self.a_cols}
            nets = {column: win_stats(subset[column + "_net"])[2] for column in self.a_cols}
            best = max(self.a_cols, key=lambda column: nets[column] if np.isfinite(nets[column]) else -9)
            _, win_is, _ = win_stats(subset[is_mask.to_numpy()[m]][best])
            _, win_oos, _ = win_stats(subset[oos_mask.to_numpy()[m]][best])
            net_is = win_stats(subset[is_mask.to_numpy()[m]][best + "_net"])[2]
            net_oos = win_stats(subset[oos_mask.to_numpy()[m]][best + "_net"])[2]
            rows.append({"combo": combo, "n": n, "wins": wins, "nets": nets, "best": best,
                         "wis": win_is, "wos": win_oos, "net_is": net_is, "net_oos": net_oos})

        return rows

    def _combos(self, size: int, is_mask: pd.Series, oos_mask: pd.Series) -> None:
        out = self.report.out
        rows = self._combo_rows(size, is_mask, oos_mask)
        trusted = [r for r in rows if r["n"] >= TRUST_N]
        flagged = [r for r in rows if FLAG_N <= r["n"] < TRUST_N]

        out(f"## 4.{size}a. {size}-stacks by HIGHEST win rate (tight 0.5R target)")
        out(f"{'stack':<32}{'n':>7}{'win@0.5':>8}{'BE=66.7':>8}{'net@0.5':>9}{'net@1R':>8}")
        for r in sorted(trusted, key=lambda r: -r["wins"]["a_R_0p5R"])[:12]:
            out(f"{'+'.join(r['combo']):<32}{r['n']:>7}{r['wins']['a_R_0p5R']:>8.1f}"
                f"{'':>8}{r['nets']['a_R_0p5R']:>9.3f}{r['nets']['a_R_1R']:>8.3f}")
        out("")

        out(f"## 4.{size}b. {size}-stacks by BEST net expectancy (its best target)")
        out(f"{'stack':<30}{'n':>7}{'tgt':>6}{'win%':>7}{'net R':>8}{'IS net':>8}{'OOS net':>8}")
        for tag, group in [("trusted n>=1000", trusted), ("flagged 300-1000", flagged)]:
            out(f"-- {tag} --")
            ordered = sorted(group, key=lambda r: -(r["nets"][r["best"]] if np.isfinite(r["nets"][r["best"]]) else -9))
            for r in ordered[:10]:
                best = r["best"]
                both_positive = (np.isfinite(r["net_is"]) and np.isfinite(r["net_oos"])
                                 and r["net_is"] > 0 and r["net_oos"] > 0)
                robust = "" if both_positive else "  (not both halves +)"
                out(f"{'+'.join(r['combo']):<30}{r['n']:>7}{A_RR[best]:>6}{r['wins'][best]:>7.1f}"
                    f"{r['nets'][best]:>8.3f}{r['net_is']:>8.3f}{r['net_oos']:>8.3f}{robust}")
            out("")

    def _slices(self) -> None:
        df, out = self.df, self.report.out
        out("## 5. Where the edge lives (Lens A @1R win%, net avgR)")

        for by in ["instrument", "hour", "regime", "dow", "trig_type", "dir"]:
            out(f"### by {by}")
            groups = []
            for value, subset in df.groupby(by):
                n, w, _ = win_stats(subset["a_R_1R"])
                _, _, net = win_stats(subset["a_R_1R_net"])
                groups.append((value, n, w, net))
            for value, n, w, net in sorted(groups, key=lambda x: -(x[2] if np.isfinite(x[2]) else -1)):
                if n < FLAG_N: continue
                out(f"  {str(value):<14}n={n:>7}  win%={w:>5.1f}  netR={net:>+.3f}")
            out("")

