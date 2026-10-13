from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from fxresearch.analysis.report import ReportWriter, announce
from fxresearch.context import ResearchContext
from fxresearch.data.instruments import DUKA_SYMBOLS
from fxresearch.engine.metrics import SPLIT_YEAR
from fxresearch.paths import REPORTS_DIR
from fxresearch.strategies.v1_structure_atr import StructureAtrStrategy, V1Config
from fxresearch.strategies.v2_corner_aoi import CornerAoiStrategy, V2Config
from fxresearch.strategies.v3_4h_corner import FourHourCornerStrategy, V3Config
from fxresearch.structure.candles import BULLISH_ENGULFING
from fxresearch.structure.pivots import bar_close_times

# the ema only needs a few hundred bars to converge, bounding it keeps 11 years of 1h tractable
EMA_TAIL = 260

# sessions are neutralised so the comparison is about core logic, not a trading window
V1_HONEST = V1Config(enhanced_all_pairs=True, atr_buffer=0.25, min_sl_atr=0.6, max_sl_atr=2.0, tp_atr=2.0,
                     min_rr=1.0, max_rr=0.0, max_hold_hours=48, enhanced_start_hour_utc3=0,
                     enhanced_end_hour_utc3=24)
V2_HONEST = V2Config(session_start=0, session_end=23, exclude_hour=(), require_d4_agree=False, atr_buffer=0.25,
                     min_sl_atr=0.8, max_sl_atr=2.0, min_rr=1.0, max_rr=2.5, lookback_pivots=80,
                     cluster_tolerance_atr=0.75, require_corner_cluster=False, prefer_cluster_target=False,
                     confirm_longs=False, exclude_trigger=(), max_hold_hours=48)
V3_HONEST = V3Config(session_start=0, session_end=23, exclude_hour=(), bias_mode="two_of_three",
                     require_d4_agree=False, require_1h_tier1_confirmation=False, atr_buffer=0.25, min_sl_atr=0.8,
                     max_sl_atr=2.5, min_rr=1.25, max_rr=2.5, lookback_pivots=80, cluster_tolerance_atr=0.75,
                     exclude_trigger=(BULLISH_ENGULFING,), stop_tf="any", max_hold_hours=72)

EDGE_REFERENCE = [
    "REFERENCE (distilled edge after the pivot fix, KEEP12 pairs, 1x cost, see reports/edge_gauntlet.md):",
    "  d4 + fresh corner + 5R single:  PF 0.96  avg -0.0307R  total -42R  OOS_PF 0.87",
]


@dataclass(frozen=True)
class ComparisonTrade:

    instrument: str
    entry_time: str
    r_result: float
    risk_pips: float
    year: int


class HonestComparison:

    def __init__(self, context: ResearchContext, instruments: list[str], reports_dir: Path = REPORTS_DIR) -> None:
        self.instruments = instruments
        self.reports_dir = reports_dir

        self.context = context
        self.v1 = StructureAtrStrategy(V1_HONEST, context.reader, context.aois, ema_tail=EMA_TAIL)
        self.v2 = CornerAoiStrategy(V2_HONEST, context.reader, context.aois)
        self.v3 = FourHourCornerStrategy(V3_HONEST, context.reader, context.aois)

        self.frames: dict[str, dict] = {}
        self.report = ReportWriter()

    def run(self) -> None:
        self._load_frames()

        print("Running V1 two_of_three ...", flush=True)
        v1_trades = self._run_all(lambda inst, symbol, fr: self.v1.backtest(inst, symbol, fr, "two_of_three"))
        print("Running V1 enhanced ...", flush=True)
        v1e_trades = self._run_all(lambda inst, symbol, fr: self.v1.backtest(inst, symbol, fr, "enhanced"))
        print("Running V2 two_of_three ...", flush=True)
        v2_trades = self._run_all(lambda inst, symbol, fr: self.v2.simulate(inst, symbol, fr, "two_of_three"))
        print("Running V3 as-written ...", flush=True)
        v3_trades = self._run_all(lambda inst, symbol, fr: self.v3.simulate(inst, symbol, fr))

        configs = [("V1 Structure+ATR (2of3)", v1_trades), ("V1 Structure+ATR (enhanced)", v1e_trades),
                   ("V2 Corner-AOI (2of3)", v2_trades), ("V3 4H-Corner (as written)", v3_trades)]
        self._write_table(configs)
        self._write_cost_sensitivity(configs)

        path = self.reports_dir / "strategy_honest_comparison.md"
        self.report.save(path)
        print()
        announce(path)

    def build_frames(self, instrument: str) -> dict | None:
        h1 = self.context.data.load(instrument, "h1")
        frames = self.context.clock.build_frames(h1)
        if frames["1h"].empty or frames["4h"].empty: return None

        structure = self.context.structure
        timelines = {
            "W": structure.build_timeline(frames["1wk"], 1, 1),
            "D": structure.build_timeline(frames["1d"], 2, 2),
            "4H": structure.build_timeline(frames["4h"], 2, 2),
            "1H": structure.build_timeline(frames["1h"], 2, 2),
        }

        # re-key every timeline to its bar close, so a bias is only visible once its bar has closed
        frames["states"] = {key: self._keyed_by_close(timeline) for key, timeline in timelines.items()}
        frames["pivots"] = {
            "W": self.context.pivots.find_alternating(frames["1wk"], 1, 1),
            "D": self.context.pivots.find_alternating(frames["1d"], 2, 2),
        }
        frames["15m"] = pd.DataFrame()
        frames["exec"] = frames["1h"]
        return frames

    def aggregate(self, trades: list[ComparisonTrade], mult: float = 1.0, mask: str | None = None) -> dict:
        subset = trades
        if mask == "is": subset = [t for t in trades if t.year < SPLIT_YEAR]
        if mask == "oos": subset = [t for t in trades if t.year >= SPLIT_YEAR]
        if not subset: return {"n": 0, "PF": 0, "win%": 0, "avg": 0, "total": 0, "green_mo%": 0}

        costs = self.context.costs
        r = np.array([t.r_result - costs.cost_r(t.instrument, t.risk_pips, mult) for t in subset])
        gross_win, gross_loss = r[r > 0].sum(), abs(r[r < 0].sum())
        months = pd.DataFrame({"ym": [pd.Timestamp(t.entry_time).strftime("%Y-%m") for t in subset], "r": r})
        by_month = months.groupby("ym")["r"].sum()

        return {
            "n": len(r),
            "win%": round(100 * (r > 0).mean(), 1),
            "PF": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
            "avg": round(float(r.mean()), 4),
            "total": round(float(r.sum()), 0),
            "green_mo%": round(100 * (by_month > 0).mean(), 1),
        }

    def _load_frames(self) -> None:
        print(f"Building honest frames for {len(self.instruments)} instruments ...", flush=True)
        for instrument in self.instruments:
            frames = self.build_frames(instrument)
            if frames is not None:
                self.frames[instrument] = frames
        print(f"  {len(self.frames)} ready", flush=True)

    def _run_all(self, simulate: Callable[[str, str, dict], list[Any]]) -> list[ComparisonTrade]:
        trades = []
        for instrument, frames in self.frames.items():
            trades += [self._normalize(t) for t in simulate(instrument, DUKA_SYMBOLS.get(instrument, instrument), frames)]
        return trades

    def _normalize(self, trade: Any) -> ComparisonTrade:
        return ComparisonTrade(trade.instrument, trade.entry_time, float(trade.r_result), float(trade.risk_pips),
                               pd.Timestamp(trade.entry_time).year)

    def _keyed_by_close(self, timeline: pd.DataFrame) -> pd.DataFrame:
        if timeline.empty: return timeline

        keyed = timeline.copy()
        keyed.index = bar_close_times(timeline.index)
        return keyed

    def _write_table(self, configs: list[tuple[str, list[ComparisonTrade]]]) -> None:
        out = self.report.out
        out("# Honest head-to-head: V1 / V2 / V3, broker candles, look-ahead-free, net 1x cost")
        out(f"{'strategy':<30}{'n':>6}{'PF':>6}{'win%':>7}{'avgR':>9}{'totR':>7}{'green%':>8}"
            f"{'OOS_PF':>8}{'OOS_tot':>9}")

        for label, trades in configs:
            m, mo = self.aggregate(trades), self.aggregate(trades, mask="oos")
            if m["n"] == 0:
                out(f"{label:<30}     0   (no trades)")
                continue

            pf = "inf" if m["PF"] == float("inf") else f"{m['PF']:.2f}"
            oos_pf = "inf" if mo["PF"] == float("inf") else f"{mo['PF']:.2f}"
            out(f"{label:<30}{m['n']:>6}{pf:>6}{m['win%']:>7}{m['avg']:>+9.4f}{m['total']:>7.0f}"
                f"{m['green_mo%']:>7}%{oos_pf:>8}{mo['total']:>9.0f}")

        out("")
        for line in EDGE_REFERENCE:
            out(line)
        out("")

    def _write_cost_sensitivity(self, configs: list[tuple[str, list[ComparisonTrade]]]) -> None:
        out = self.report.out
        out("Cost sensitivity (avg net R/trade):")
        out(f"{'strategy':<30}{'0.5x':>9}{'1x':>9}{'2x':>9}")

        for label, trades in configs:
            if not trades: continue
            out(f"{label:<30}{self.aggregate(trades, 0.5)['avg']:>+9.4f}{self.aggregate(trades, 1.0)['avg']:>+9.4f}"
                f"{self.aggregate(trades, 2.0)['avg']:>+9.4f}")

