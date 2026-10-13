from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from fxresearch.analysis.report import ReportWriter, announce
from fxresearch.context import ResearchContext
from fxresearch.costs.cost_model import STANDARD
from fxresearch.data.instruments import KEEP12, pip_size
from fxresearch.engine.indicators import atr
from fxresearch.engine.metrics import SPLIT_YEAR
from fxresearch.engine.simulator import simulate_trade
from fxresearch.paths import REPORTS_DIR
from fxresearch.strategies.edge import WARMUP, bracket
from fxresearch.structure.aoi import RESISTANCE, SUPPORT
from fxresearch.structure.corners import Corner
from fxresearch.structure.pivots import bar_close_times

# signal tf -> [signal, one up, two up] as (ohlc key, state key, hours per bar)
TFS = {
    "4h": [("4h", "4H", 4.0), ("1d", "D", 24.0), ("1wk", "W", 168.0)],
    "1h": [("1h", "1H", 1.0), ("4h", "4H", 4.0), ("1d", "D", 24.0)],
    "30m": [("30m", "30M", 0.5), ("1h", "1H", 1.0), ("4h", "4H", 4.0)],
    "15m": [("15m", "15M", 0.25), ("1h", "1H", 1.0), ("4h", "4H", 4.0)],
    "5m": [("5m", "5M", 1 / 12), ("15m", "15M", 0.25), ("1h", "1H", 1.0)],
}

# lower signal tfs: (base file tag, [(state key, frame)], [(pivot key, frame)])
LOWER_TF_BUILDS = {
    "30m": ("m15", [("30M", "30m"), ("1H", "1h"), ("4H", "4h")], [("1H", "1h"), ("4H", "4h")]),
    "15m": ("m15", [("15M", "15m"), ("1H", "1h"), ("4H", "4h")], [("1H", "1h"), ("4H", "4h")]),
    "5m": ("m5", [("5M", "5m"), ("15M", "15m"), ("1H", "1h")], [("15M", "15m"), ("1H", "1h")]),
}
PIVOT_SOURCES = {"4H": "4h", "1H": "1h", "15M": "15m", "5M": "5m", "D": "1d", "W": "1wk"}

# round-number grid: 50 pips for jpy pairs and for the rest
ROUND_STEP = {"JPY": 0.5, "FX": 0.0050}
ATR_RANK_WINDOW = 500
ATR_RANK_MIN = 100
KELLY_GRID = np.linspace(0.005, 0.6, 300)


@dataclass
class IntradayConfig:

    signal_tf: str = "1h"
    instruments: list[str] = field(default_factory=lambda: list(KEEP12))
    bias_mode: str = "d4"
    aoi_source: str = "corners"
    aoi_tol: float = 0.75
    stop_atr: float = 1.0
    target_rr: float = 5.0
    entry_offset: int = 1
    max_hold_bars: int = 60
    min_risk_pips: float = 0.0
    vol_pct: float = 0.0
    session: list[int] | None = None
    ema_trend: int = 0

    def variant(self, **changes: object) -> IntradayConfig:
        changed = copy.copy(self)
        for key, value in changes.items():
            setattr(changed, key, value)
        return changed


@dataclass(frozen=True)
class IntradayTrade:

    instrument: str
    year: int
    entry_time: str
    direction: str
    r_gross: float
    cost_r: float
    r_net: float
    risk_pips: float
    aoi: str
    exit_reason: str


class IntradayFrames:

    def __init__(self, instrument: str, signal_tf: str, context: ResearchContext, frames: dict | None = None) -> None:
        self.instrument = instrument
        self.signal_tf = signal_tf

        self.context = context

        self.ok = False
        self.frames: dict = frames if frames is not None else {}
        self.c = pd.DataFrame()
        self.times = pd.DatetimeIndex([])
        self.o = self.hi = self.lo = self.cl = self.atr = self.atr_pct = self.hours = np.array([])
        self.sig_hours = 0.0
        self.pip = pip_size(instrument)
        self.states: list[np.ndarray] = []
        self.corners: list[list[Corner]] = []
        self.intraday: list[list[Corner]] = []
        self.load()

    def load(self) -> None:
        if not self.frames:
            self.frames = self._build_frames()

        levels = TFS[self.signal_tf]
        candles = self.frames.get(levels[0][0])
        self.ok = candles is not None and not candles.empty and len(candles) > WARMUP + 50
        if not self.ok: return

        self.c = candles
        self.times = candles.index
        self.o, self.hi = candles["Open"].to_numpy(), candles["High"].to_numpy()
        self.lo, self.cl = candles["Low"].to_numpy(), candles["Close"].to_numpy()
        self.atr = atr(candles).to_numpy()
        self.sig_hours = levels[0][2]
        self.hours = candles.index.hour.to_numpy()

        # rank of the current atr inside its trailing window, used by the volatility filter
        self.atr_pct = pd.Series(self.atr).rolling(ATR_RANK_WINDOW, min_periods=ATR_RANK_MIN).rank(pct=True).to_numpy()

        timelines = self.frames["states"]
        self.states = [self.context.reader.closed_states(self.times, timelines[level[1]]) for level in levels]
        self.corners = self._swing_corners([levels[1][1], levels[2][1]])
        self.intraday = self._intraday_levels()

    def _build_frames(self) -> dict:
        if self.signal_tf in ("4h", "1h"): return self.context.builder.build(self.instrument)

        base_tag, state_tfs, pivot_tfs = LOWER_TF_BUILDS[self.signal_tf]
        base_utc = self.context.data.load(self.instrument, base_tag)
        frames = self.context.clock.build_frames_tf(base_utc, base_tag)
        signal_key = TFS[self.signal_tf][0][0]
        if frames.get(signal_key) is None or frames[signal_key].empty: return frames

        structure = self.context.structure
        frames["states"] = {key: structure.build_timeline(frames[src], 2, 2)
                            for key, src in state_tfs if src in frames and not frames[src].empty}
        if "1wk" in frames and not frames["1wk"].empty:
            frames["states"]["W"] = structure.build_timeline(frames["1wk"], 1, 1)
        if "1d" in frames and not frames["1d"].empty:
            frames["states"]["D"] = structure.build_timeline(frames["1d"], 2, 2)
        frames["pivots"] = {key: self.context.pivots.find_alternating(frames[src], 2, 2)
                            for key, src in pivot_tfs if src in frames and not frames[src].empty}
        return frames

    def _swing_corners(self, keys: list[str]) -> list[list[Corner]]:
        pivots = dict(self.frames["pivots"])

        for key in keys:
            if key in pivots: continue
            source = self.frames.get(PIVOT_SOURCES[key])
            if source is not None and not source.empty:
                pivots[key] = self.context.pivots.find_alternating(source, 2, 2)

        return self.context.corners.fresh_corners(self.times, pivots, keys)

    def _intraday_levels(self) -> list[list[Corner]]:
        levels: list[list[Corner]] = [[] for _ in range(len(self.times))]

        # previous closed daily and weekly high and low as of each signal bar
        for frame, tag in ((self.frames.get("1d"), "pdH/L"), (self.frames.get("1wk"), "pwH/L")):
            if frame is None or frame.empty: continue

            positions = bar_close_times(frame.index).searchsorted(self.times, side="right")
            highs, lows = frame["High"].to_numpy(), frame["Low"].to_numpy()
            for i in range(len(self.times)):
                k = int(positions[i]) - 1
                if k < 0: continue
                levels[i].append(Corner(float(highs[k]), RESISTANCE, tag))
                levels[i].append(Corner(float(lows[k]), SUPPORT, tag))

        # the three round numbers nearest the close
        step = ROUND_STEP["JPY"] if self.pip >= 0.01 else ROUND_STEP["FX"]
        for i in range(len(self.times)):
            base_level = round(self.cl[i] / step) * step
            for m in (-1, 0, 1):
                level = base_level + m * step
                levels[i].append(Corner(level, SUPPORT, "round"))
                levels[i].append(Corner(level, RESISTANCE, "round"))

        return levels


class IntradayStrategy:

    def __init__(self, context: ResearchContext) -> None:
        self.context = context

    def simulate(self, frames: IntradayFrames, config: IntradayConfig, cost_mult: float = 1.0,
                 account: str = STANDARD) -> list[IntradayTrade]:
        if not frames.ok: return []

        hold_hours = int(config.max_hold_bars * frames.sig_hours)
        use_corners = config.aoi_source in ("corners", "both")
        use_intraday = config.aoi_source in ("intraday", "both")
        ema = None
        if config.ema_trend:
            ema = pd.Series(frames.cl).ewm(span=config.ema_trend, adjust=False).mean().to_numpy()

        trades: list[IntradayTrade] = []
        last_exit = None
        for i in range(WARMUP, len(frames.times) - config.entry_offset - 1):
            t = frames.times[i]
            if last_exit is not None and t <= last_exit: continue

            a = frames.atr[i]
            if not np.isfinite(a) or a <= 0: continue
            if not self._passes_filters(frames, config, i): continue

            direction = self._bias(frames.states[0][i], frames.states[1][i])
            if not direction: continue
            if ema is not None and direction == "long" and frames.cl[i] < ema[i]: continue
            if ema is not None and direction == "short" and frames.cl[i] > ema[i]: continue

            levels = (frames.corners[i] if use_corners else []) + (frames.intraday[i] if use_intraday else [])
            match = self.context.corners.react_at(levels, float(frames.lo[i]), float(frames.hi[i]),
                                                  float(frames.cl[i]), direction, a, config.aoi_tol)
            if match is None: continue

            entry_index = i + config.entry_offset
            entry = float(frames.o[entry_index])
            risk = config.stop_atr * a
            risk_pips = risk / frames.pip
            if risk <= 0 or risk_pips < config.min_risk_pips: continue

            stop, target = bracket(entry, direction, risk, config.target_rr)
            outcome = simulate_trade(frames.c, entry_index, direction, entry, stop, target, hold_hours)
            r = (outcome.price - entry) / risk if direction == "long" else (entry - outcome.price) / risk
            cost = self.context.costs.cost_r(frames.instrument, risk_pips, cost_mult, account)

            trades.append(IntradayTrade(
                instrument=frames.instrument, year=int(t.year), entry_time=frames.times[entry_index].isoformat(),
                direction=direction, r_gross=round(r, 4), cost_r=round(cost, 4), r_net=round(r - cost, 4),
                risk_pips=round(risk_pips, 1), aoi=match.tf, exit_reason=outcome.reason,
            ))
            last_exit = outcome.time

        return trades

    def run_universe(self, frames_list: list[IntradayFrames], config: IntradayConfig, cost_mult: float = 1.0,
                     account: str = STANDARD) -> list[IntradayTrade]:
        return [trade for frames in frames_list for trade in self.simulate(frames, config, cost_mult, account)]

    def _passes_filters(self, frames: IntradayFrames, config: IntradayConfig, i: int) -> bool:
        # broker-hour session window, then the trailing atr percentile floor
        if config.session and not (config.session[0] <= frames.hours[i] <= config.session[1]): return False
        if config.vol_pct <= 0: return True

        rank = frames.atr_pct[i]
        return np.isfinite(rank) and rank * 100 >= config.vol_pct

    def _bias(self, signal_state: str, one_up_state: str) -> str | None:
        # every bias mode reduces to the signal tf and the tf above it agreeing
        if signal_state == "bullish" and one_up_state == "bullish": return "long"
        if signal_state == "bearish" and one_up_state == "bearish": return "short"
        return None


class IntradayStats:

    def kelly_growth(self, r: np.ndarray, trades_per_year: float) -> tuple[float, float]:
        if len(r) < 30: return 0.0, float("nan")

        best_f, best_g = 0.0, -1e9
        for f in KELLY_GRID:
            v = 1 + f * r
            if (v <= 0).any(): break
            g = float(np.mean(np.log(v)))
            if g > best_g:
                best_g, best_f = g, f

        half = best_f / 2
        v = 1 + half * r
        growth = float(np.exp(trades_per_year * np.mean(np.log(v))) - 1) if (v > 0).all() else float("nan")
        return best_f, growth

    def summarize(self, trades: list[IntradayTrade], years_span: float) -> dict:
        if not trades: return {"n": 0}

        r = np.array([t.r_net for t in trades])
        gross = np.array([t.r_gross for t in trades])
        wins, losses = r[r > 0].sum(), abs(r[r < 0].sum())
        equity = np.cumsum(r)
        drawdown = float((np.maximum.accumulate(equity) - equity).max())
        trades_per_year = len(r) / years_span if years_span > 0 else 0
        kelly, growth = self.kelly_growth(r, trades_per_year)

        return {"n": len(r), "win%": round(100 * (r > 0).mean(), 1),
                "net": round(float(r.sum()), 1), "avg": round(float(r.mean()), 4),
                "gross_avg": round(float(gross.mean()), 4), "avg_cost": round(float(gross.mean() - r.mean()), 4),
                "PF": round(float(wins / losses), 2) if losses > 0 else float("inf"),
                "maxDD": round(drawdown, 1), "tpy": round(trades_per_year, 0),
                "kelly": round(kelly, 3), "growth_halfK": round(growth, 3),
                "median_risk_pips": round(float(np.median([t.risk_pips for t in trades])), 1)}

    def describe(self, m: dict) -> str:
        if m.get("n", 0) == 0: return "n=0"

        pf = "inf" if m["PF"] == float("inf") else f"{m['PF']:.2f}"
        growth = "nan" if not np.isfinite(m["growth_halfK"]) else f"{m['growth_halfK'] * 100:+.0f}%/yr"
        return (f"n={m['n']:>5} tpy={m['tpy']:>4.0f} win={m['win%']:>4}% net={m['net']:>7}R "
                f"gross={m['gross_avg']:>+.4f} avg={m['avg']:>+.4f} cost={m['avg_cost']:.4f} PF={pf:>5} "
                f"DD={m['maxDD']:>6}R rpips={m['median_risk_pips']:>5} halfK={growth}")

    def years_of(self, trades: list[IntradayTrade]) -> float:
        if not trades: return 1.0
        entries = pd.to_datetime([t.entry_time for t in trades])
        return max(0.25, (entries.max() - entries.min()).days / 365.25)


class IntradayStudy:

    def __init__(self, config: IntradayConfig, context: ResearchContext, reports_dir: Path = REPORTS_DIR) -> None:
        self.config = config
        self.reports_dir = reports_dir

        self.context = context
        self.strategy = IntradayStrategy(context)
        self.stats = IntradayStats()

        self.frames_list: list[IntradayFrames] = []
        self.report = ReportWriter(flush=True)

    def load(self) -> None:
        signal_tf = self.config.signal_tf
        print(f"Building {signal_tf} frames for {len(self.config.instruments)} instruments ...", flush=True)
        loaded = [IntradayFrames(instrument, signal_tf, self.context) for instrument in self.config.instruments]
        self.frames_list = [frames for frames in loaded if frames.ok]
        print(f"  {len(self.frames_list)} ready\n", flush=True)

    def run(self, scan: bool, tag: str) -> None:
        self.load()
        config = self.config
        levels = TFS[config.signal_tf]
        out = self.report.out

        out(f"# Intraday edge: signal TF = {config.signal_tf}")
        out(f"bias ({levels[1][0]}&{levels[0][0]})  corners ({levels[1][0]}/{levels[2][0]})  "
            f"universe = {len(self.frames_list)} FX pairs.  Net of calibrated cost.")
        out("")

        if scan:
            self._scan()
        else:
            self.report_config(config, f"{config.signal_tf} {config.aoi_source} tol{config.aoi_tol} "
                                       f"stop{config.stop_atr} rr{config.target_rr} volpct{config.vol_pct} "
                                       f"riskfloor{config.min_risk_pips} sess{config.session} ema{config.ema_trend}")

        if not tag: return
        path = self.reports_dir / f"edge_intraday_{tag}.md"
        self.report.save(path)
        print()
        announce(path)

    def report_config(self, config: IntradayConfig, label: str) -> dict | None:
        out = self.report.out
        stats = self.stats
        full = self.strategy.run_universe(self.frames_list, config, 1.0)
        if not full:
            out(f"### {label}: NO TRADES")
            out("")
            return None

        span = stats.years_of(full)
        is_trades = [t for t in full if t.year < SPLIT_YEAR]
        oos_trades = [t for t in full if t.year >= SPLIT_YEAR]
        out(f"### {label}")
        out(f"  full @1x   {stats.describe(stats.summarize(full, span))}")
        out(f"  IS  @1x    {stats.describe(stats.summarize(is_trades, stats.years_of(is_trades)))}")
        out(f"  OOS @1x    {stats.describe(stats.summarize(oos_trades, stats.years_of(oos_trades)))}")

        for mult in (1.5, 2.0):
            trades = self.strategy.run_universe(self.frames_list, config, mult)
            oos = [t for t in trades if t.year >= SPLIT_YEAR]
            summary = stats.summarize(trades, span)
            out(f"  full @{mult}x  net={summary['net']:>7}R avg={summary['avg']:>+.4f} "
                f"PF={summary['PF']:.2f} | OOS avg={stats.summarize(oos, stats.years_of(oos))['avg']:>+.4f}")

        out("")
        return stats.summarize(full, span)

    def _scan(self) -> None:
        out = self.report.out
        variant: Callable[..., IntradayConfig] = self.config.variant

        out("## SCAN: isolate which levers fix the cost problem intraday")
        self.report_config(variant(), "baseline: corners, 5R, 1xATR, 60-bar hold (naive port)")

        out("## A) TARGET x HOLD: does the fractal runner need a different target/hold intraday?")
        out("##    (gross tells us if any directional edge exists before cost)")
        for hold in (60, 120, 240):
            for rr in (1.5, 2.0, 3.0, 5.0):
                self.report_config(variant(target_rr=rr, max_hold_bars=hold), f"corners rr{rr} hold{hold}bars")

        out("## B) AOI SOURCE (best target/hold from A applied later by hand):")
        self.report_config(variant(aoi_source="intraday"), "intraday AOIs only (5R/60)")
        self.report_config(variant(aoi_source="both"), "both AOIs (5R/60)")

        out("## C) COST ENGINEERING (corners, 5R/60):")
        for vol_pct in (50, 70, 85):
            self.report_config(variant(vol_pct=vol_pct), f"corners + vol-pct>={vol_pct}")
        for stop in (1.5, 2.0):
            self.report_config(variant(stop_atr=stop), f"corners + stop {stop}xATR")
        for floor in (8, 15):
            self.report_config(variant(min_risk_pips=floor), f"corners + min-risk-pips {floor}")

        out("## D) MOMENTUM / SESSION (corners, 5R/60):")
        self.report_config(variant(ema_trend=50), "corners + 50-EMA trend filter")
        self.report_config(variant(session=[9, 17]), "corners + session 9-17 EET")

