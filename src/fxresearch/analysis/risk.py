from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from fxresearch.analysis.report import ReportWriter, announce
from fxresearch.costs.cost_model import CostModel
from fxresearch.paths import REPORTS_DIR

COST_MULT = 1.5
N_MC = 5000
RISK_GRID = [0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02]
SEED = 20260615
MAX_TOLERATED_P95_DD = 0.25


class RiskModel:

    def __init__(self, costs: CostModel, trades_path: Path = REPORTS_DIR / "edge_trades_edge_base.csv",
                 reports_dir: Path = REPORTS_DIR) -> None:
        self.trades_path = trades_path
        self.reports_dir = reports_dir

        self.costs = costs

        self.trades = pd.DataFrame()
        self.monthly = pd.Series(dtype=float)
        self.report = ReportWriter()
        self.load()

    def load(self) -> None:
        d = pd.read_csv(self.trades_path)
        d["net"] = d["r_gross"] - np.array([self.costs.cost_r(i, rp, COST_MULT)
                                            for i, rp in zip(d["instrument"], d["risk_pips"])])
        d["entry"] = pd.to_datetime(d["entry_time"])
        d["exit"] = pd.to_datetime(d["exit_time"])
        d["ym"] = d["entry"].dt.to_period("M")

        # months with no trades count as flat months
        monthly = d.groupby("ym")["net"].sum()
        all_months = pd.period_range(monthly.index.min(), monthly.index.max(), freq="M")
        self.monthly = monthly.reindex(all_months, fill_value=0.0)
        self.trades = d

    def concurrency(self) -> dict:
        events = []
        for _, row in self.trades.iterrows():
            events.append((row["entry"], 1))
            events.append((row["exit"], -1))

        # closes sort before opens on a tie
        events.sort(key=lambda event: (event[0], event[1]))
        current = peak = 0
        occupancy = []
        for _, delta in events:
            current += delta
            peak = max(peak, current)
            occupancy.append(current)

        occupancy = np.array(occupancy)
        return {"max_concurrent": int(peak),
                "avg_when_open": float(occupancy[occupancy > 0].mean()) if (occupancy > 0).any() else 0.0,
                "p95_concurrent": int(np.percentile(occupancy, 95))}

    def equity_path(self, monthly_r: np.ndarray, risk: float) -> tuple[np.ndarray, float, float]:
        returns = np.clip(risk * monthly_r, -0.99, None)
        equity = np.cumprod(1 + returns)
        peak = np.maximum.accumulate(equity)
        max_dd = float(((peak - equity) / peak).max())
        cagr = float(equity[-1] ** (12 / len(equity)) - 1)
        return equity, cagr, max_dd

    def run(self) -> None:
        monthly_r = self.monthly.values
        n = len(monthly_r)
        rng = np.random.default_rng(SEED)
        conc = self.concurrency()
        out = self.report.out

        out("# Risk & position-sizing model: 12-pair edge, net @1.5x cost (~Pepperstone Standard)")
        out(f"{self.trades.shape[0]} trades over {n} months ({n / 12:.1f}y). "
            f"Per-trade outcome avg {self.trades['net'].mean():+.3f}R, monthly R avg {monthly_r.mean():+.2f} "
            f"(green months {100 * (monthly_r > 0).mean():.0f}%).")
        out(f"Concurrency: up to **{conc['max_concurrent']} positions open at once** "
            f"(95th pct {conc['p95_concurrent']}, avg-when-open {conc['avg_when_open']:.1f}). "
            f"Correlated FX pairs -> they can draw down together, so size for the cluster.")
        out("")

        out("## Risk-per-trade sweep (real path + Monte Carlo of 5000 month-bootstraps)")
        out(f"{'risk/trade':>11}{'CAGR':>8}{'realMaxDD':>11}{'MC medDD':>10}{'MC 95%DD':>10}"
            f"{'P(DD>30%)':>11}{'P(DD>50%)':>11}{'P(end<start)':>13}")
        results = [self._sweep_row(monthly_r, risk, rng) for risk in RISK_GRID]
        out("")

        # the highest risk whose 95th percentile drawdown stays inside the tolerance
        safe = [row for row in results if row[4] <= MAX_TOLERATED_P95_DD]
        chosen = safe[-1] if safe else results[0]
        out(f"## Recommendation: risk ~{chosen[0] * 100:.2f}% per trade")
        out(f"  -> ~{chosen[1] * 100:.0f}%/yr CAGR, real max DD {chosen[2] * 100:.0f}%, "
            f"95th-pct DD {chosen[4] * 100:.0f}%, risk of a >50% DD {chosen[6]:.1f}%, "
            f"chance of losing over a random {n / 12:.0f}y {chosen[7]:.0f}%.")
        out("  Rule of thumb: with up to "
            f"{conc['max_concurrent']} correlated positions open, {chosen[0] * 100:.2f}% each means up to "
            f"~{conc['max_concurrent'] * chosen[0] * 100:.0f}% gross risk on at once in a worst-case cluster.")
        out("")

        equity, _, _ = self.equity_path(monthly_r, chosen[0])
        month_returns = chosen[0] * monthly_r
        out(f"## Monthly profile at {chosen[0] * 100:.2f}% risk/trade")
        out(f"  green months {100 * (month_returns > 0).mean():.0f}%  |  median month {np.median(month_returns) * 100:+.2f}%  "
            f"|  avg {month_returns.mean() * 100:+.2f}%  |  best {month_returns.max() * 100:+.1f}%  "
            f"|  worst {month_returns.min() * 100:+.1f}%")
        out(f"  total growth over {n / 12:.1f}y: {(equity[-1] - 1) * 100:+.0f}%  (equity x{equity[-1]:.2f})")
        out("")
        out("Caveats: monthly-block bootstrap preserves within-month correlation but not "
            "cross-month regime persistence; drawdown is on realized monthly equity (intra-"
            "trade open DD can be deeper). Costs @1.5x are an estimate of Pepperstone Standard.")

        path = self.reports_dir / "edge_risk_sizing.md"
        self.report.save(path)
        print()
        announce(path)

    def _sweep_row(self, monthly_r: np.ndarray, risk: float, rng: np.random.Generator) -> tuple:
        n = len(monthly_r)
        _, cagr, max_dd = self.equity_path(monthly_r, risk)

        # bootstrap whole months so correlated same-month losses stay together
        cagrs, max_dds, ended_down = np.empty(N_MC), np.empty(N_MC), 0
        for k in range(N_MC):
            equity, c, m = self.equity_path(monthly_r[rng.integers(0, n, n)], risk)
            cagrs[k], max_dds[k] = c, m
            if equity[-1] < 1.0:
                ended_down += 1

        row = (risk, cagr, max_dd, np.median(max_dds), np.percentile(max_dds, 95),
               100 * (max_dds > 0.30).mean(), 100 * (max_dds > 0.50).mean(), 100 * ended_down / N_MC)
        self.report.out(f"{risk * 100:>10.2f}%{cagr * 100:>7.1f}%{max_dd * 100:>10.1f}%{row[3] * 100:>9.1f}%"
                        f"{row[4] * 100:>9.1f}%{row[5]:>10.1f}%{row[6]:>10.1f}%{row[7]:>12.1f}%")
        return row

