from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from fxresearch.analysis.report import ReportWriter, announce
from fxresearch.context import ResearchContext
from fxresearch.data.instruments import pip_size
from fxresearch.engine.indicators import atr
from fxresearch.engine.metrics import SPLIT_YEAR
from fxresearch.engine.simulator import simulate_trade
from fxresearch.paths import REPORTS_DIR
from fxresearch.strategies.edge import WARMUP, bracket
from fxresearch.structure.corners import Corner

# signal tf -> [signal, one up, two up] as (ohlc key, state key, hours per bar); corners come from the two up tfs
TFS = {
    "4h": [("4h", "4H", 4), ("1d", "D", 24), ("1wk", "W", 168)],
    "1h": [("1h", "1H", 1), ("4h", "4H", 4), ("1d", "D", 24)],
}
BIAS_LABELS = {"4h": "Daily+4H", "1h": "4H+1H"}
CORNER_LABELS = {"4h": "Daily/Weekly", "1h": "4H/Daily"}


@dataclass(frozen=True)
class TimeframeConfig:

    target_rr: float = 5.0
    stop_atr: float = 1.0
    aoi_tol: float = 0.75
    bias_mode: str = "trend2"
    entry_offset: int = 1
    max_hold_bars: int = 60


@dataclass(frozen=True)
class TimeframeTrade:

    instrument: str
    year: int
    entry_time: str
    r_net: float
    exit_reason: str


class TimeframeFrames:

    def __init__(self, instrument: str, signal_tf: str, context: ResearchContext) -> None:
        self.instrument = instrument
        self.signal_tf = signal_tf

        self.context = context

        self.ok = False
        self.frames: dict = {}
        self.c = pd.DataFrame()
        self.times = pd.DatetimeIndex([])
        self.o = self.hi = self.lo = self.cl = self.atr = np.array([])
        self.sig_hours = 0
        self.pip = pip_size(instrument)
        self.states: list[np.ndarray] = []
        self.corners: list[list[Corner]] = []
        self.load()

    def load(self) -> None:
        self.frames = self.context.builder.build(self.instrument)
        levels = TFS[self.signal_tf]
        candles = self.frames.get(levels[0][0])
        self.ok = candles is not None and not candles.empty and len(candles) > WARMUP + 5
        if not self.ok: return

        self.c = candles
        self.times = candles.index
        self.o, self.hi = candles["Open"].to_numpy(), candles["High"].to_numpy()
        self.lo, self.cl = candles["Low"].to_numpy(), candles["Close"].to_numpy()
        self.atr = atr(candles).to_numpy()
        self.sig_hours = levels[0][2]

        timelines = self.frames["states"]
        self.states = [self.context.reader.closed_states(self.times, timelines[level[1]]) for level in levels]

        pivots = dict(self.frames["pivots"])
        if "4H" not in pivots:
            pivots["4H"] = self.context.pivots.find_alternating(self.frames["4h"], 2, 2)
        self.corners = self.context.corners.fresh_corners(self.times, pivots, [levels[1][1], levels[2][1]])


class TimeframeStudy:

    def __init__(self, config: TimeframeConfig, context: ResearchContext, instruments: list[str],
                 reports_dir: Path = REPORTS_DIR) -> None:
        self.config = config
        self.instruments = instruments
        self.reports_dir = reports_dir

        self.context = context

        self.report = ReportWriter()

    def bias(self, states: list[str]) -> str | None:
        # trend2 needs the signal and one-up tf to agree, trend3 adds the two-up tf
        need = states[:3] if self.config.bias_mode == "trend3" else states[:2]
        if all(state == "bullish" for state in need): return "long"
        if all(state == "bearish" for state in need): return "short"
        return None

    def simulate(self, frames: TimeframeFrames, cost_mult: float = 1.0) -> list[TimeframeTrade]:
        if not frames.ok: return []

        config = self.config
        hold_hours = int(pd.Timedelta(hours=config.max_hold_bars * frames.sig_hours).total_seconds() // 3600)
        trades: list[TimeframeTrade] = []
        last_exit = None

        for i in range(WARMUP, len(frames.times) - config.entry_offset - 1):
            t = frames.times[i]
            if last_exit is not None and t <= last_exit: continue

            a = frames.atr[i]
            if not np.isfinite(a) or a <= 0: continue

            direction = self.bias([states[i] for states in frames.states])
            if not direction: continue

            match = self.context.corners.react_at(frames.corners[i], float(frames.lo[i]), float(frames.hi[i]),
                                                  float(frames.cl[i]), direction, a, config.aoi_tol)
            if match is None: continue

            entry_index = i + config.entry_offset
            entry = float(frames.o[entry_index])
            risk = config.stop_atr * a
            if risk <= 0: continue

            stop, target = bracket(entry, direction, risk, config.target_rr)
            outcome = simulate_trade(frames.c, entry_index, direction, entry, stop, target, hold_hours)
            r = (outcome.price - entry) / risk if direction == "long" else (entry - outcome.price) / risk
            cost = self.context.costs.cost_r(frames.instrument, risk / frames.pip, cost_mult)

            trades.append(TimeframeTrade(frames.instrument, int(t.year), frames.times[entry_index].isoformat(),
                                         round(r - cost, 4), outcome.reason))
            last_exit = outcome.time

        return trades

    def weekly_stats(self, trades: list[TimeframeTrade]) -> dict:
        if not trades: return {}

        df = pd.DataFrame({"entry_time": [t.entry_time for t in trades], "r_net": [t.r_net for t in trades]})
        df["week"] = pd.to_datetime(df["entry_time"]).dt.strftime("%G-W%V")
        weeks = df.groupby("week")["r_net"].agg(["sum", "count"])
        return {
            "trades": len(df),
            "active_weeks": len(weeks),
            "trades_per_active_week": df.shape[0] / len(weeks),
            "winning_week_pct": 100 * (weeks["sum"] > 0).mean(),
            "avg_R_per_active_week": weeks["sum"].mean(),
            "median_R_per_active_week": weeks["sum"].median(),
            "best_week": weeks["sum"].max(),
            "worst_week": weeks["sum"].min(),
            "total_R": df["r_net"].sum(),
        }

    def profit_factor(self, trades: list[TimeframeTrade]) -> float:
        r = np.array([t.r_net for t in trades])
        gross_win, gross_loss = r[r > 0].sum(), abs(r[r < 0].sum())
        return gross_win / gross_loss if gross_loss > 0 else float("inf")

    def run(self) -> None:
        config = self.config
        out = self.report.out
        out(f"# Timeframe comparison: fresh-corner trend edge, target {config.target_rr}R, "
            f"stop {config.stop_atr}xATR, bias {config.bias_mode}, hold {config.max_hold_bars} bars")
        out("Net of 1x modeled cost. 'winning week' = an active week (>=1 trade) that nets R>0.")
        out("")

        for signal_tf in ("4h", "1h"):
            print(f"Building {signal_tf} frames ...", flush=True)
            loaded = [TimeframeFrames(instrument, signal_tf, self.context) for instrument in self.instruments]
            self._report_tf(signal_tf, [frames for frames in loaded if frames.ok])

        path = self.reports_dir / "edge_timeframe_weekly.md"
        self.report.save(path)
        announce(path)

    def _report_tf(self, signal_tf: str, frames_list: list[TimeframeFrames]) -> None:
        out = self.report.out
        trades = self._run_all(frames_list, 1.0)
        if not trades:
            out(f"## signal = {signal_tf}: no trades")
            return

        weekly = self.weekly_stats(trades)
        weekly_is = self.weekly_stats([t for t in trades if t.year < SPLIT_YEAR])
        weekly_oos = self.weekly_stats([t for t in trades if t.year >= SPLIT_YEAR])
        half_cost = np.array([t.r_net for t in self._run_all(frames_list, 0.5)])
        double_cost = np.array([t.r_net for t in self._run_all(frames_list, 2.0)])
        avg_1x = np.mean([t.r_net for t in trades])

        out(f"## signal = {signal_tf}   (bias {BIAS_LABELS[signal_tf]}, corners {CORNER_LABELS[signal_tf]})")
        out(f"  trades={weekly['trades']}  active weeks={weekly['active_weeks']}  "
            f"trades/active week={weekly['trades_per_active_week']:.2f}")
        out(f"  WINNING WEEKS: {weekly['winning_week_pct']:.1f}%  (IS {weekly_is['winning_week_pct']:.1f}% / "
            f"OOS {weekly_oos['winning_week_pct']:.1f}%)")
        out(f"  R per active week: avg {weekly['avg_R_per_active_week']:+.3f}  "
            f"median {weekly['median_R_per_active_week']:+.3f}  "
            f"best {weekly['best_week']:+.1f}  worst {weekly['worst_week']:+.1f}")
        out(f"  total R={weekly['total_R']:.0f}  PF={self.profit_factor(trades):.2f}  avg R/trade={avg_1x:+.4f}")
        out(f"  cost sensitivity avg R/trade: 0.5x={half_cost.mean():+.4f}  1x={avg_1x:+.4f}  "
            f"2x={double_cost.mean():+.4f}  (2x total {double_cost.sum():.0f}R)")
        out("")

    def _run_all(self, frames_list: list[TimeframeFrames], cost_mult: float) -> list[TimeframeTrade]:
        return [trade for frames in frames_list for trade in self.simulate(frames, cost_mult)]

