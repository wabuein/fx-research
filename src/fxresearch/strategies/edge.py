from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from fxresearch.costs.cost_model import STANDARD, CostModel
from fxresearch.data.instruments import pip_size
from fxresearch.engine.indicators import atr
from fxresearch.engine.simulator import simulate_trade
from fxresearch.structure.corners import Corner, CornerHandler
from fxresearch.structure.market_structure import BEARISH, BULLISH, StructureReader

WARMUP = 60
CORNER_TIMEFRAMES = ("D", "W")


@dataclass(frozen=True)
class EdgeConfig:

    bias_mode: str = "d4"
    aoi_tol: float = 0.75
    stop_atr: float = 1.0
    target_rr: float = 2.0
    entry_offset: int = 1
    max_hold_hours: int = 240


# the configuration the parity gate and the live bot use, a research baseline, not a validated edge
LOCKED_CONFIG = EdgeConfig(bias_mode="d4", aoi_tol=0.75, stop_atr=1.0, target_rr=5.0,
                           entry_offset=1, max_hold_hours=240)


@dataclass(frozen=True)
class EdgeSignal:

    direction: str
    atr: float
    risk: float
    aoi: Corner


@dataclass(frozen=True)
class EdgeTrade:

    instrument: str
    direction: str
    signal_time: str
    entry_time: str
    exit_time: str
    year: int
    entry: float
    stop: float
    target: float
    exit_price: float
    exit_reason: str
    r_gross: float
    cost_r: float
    r_net: float
    risk_pips: float
    atr: float
    aoi: str

    def to_row(self) -> dict:
        return {
            "instrument": self.instrument, "direction": self.direction,
            "signal_time": self.signal_time, "entry_time": self.entry_time,
            "exit_time": self.exit_time, "year": self.year,
            "entry": self.entry, "stop": self.stop, "target": self.target,
            "exit_price": self.exit_price, "exit_reason": self.exit_reason,
            "r_gross": self.r_gross, "cost_R": self.cost_r, "r_net": self.r_net,
            "risk_pips": self.risk_pips, "atr": self.atr, "aoi": self.aoi,
        }


def bias_direction(mode: str, weekly: str, daily: str, four_hour: str) -> str | None:
    if mode == "d4":
        if daily == BULLISH and four_hour == BULLISH: return "long"
        if daily == BEARISH and four_hour == BEARISH: return "short"
        return None

    top = [weekly, daily, four_hour]
    bull, bear = top.count(BULLISH), top.count(BEARISH)
    need = 3 if mode == "bias3" else 2
    if bull >= need and bear <= (3 - need): return "long"
    if bear >= need and bull <= (3 - need): return "short"
    return None


def bracket(entry: float, direction: str, risk: float, target_rr: float) -> tuple[float, float]:
    if direction == "long": return entry - risk, entry + target_rr * risk
    return entry + risk, entry - target_rr * risk


class EdgeFrames:

    def __init__(self, instrument: str, frames: dict, reader: StructureReader, corners: CornerHandler) -> None:
        self.instrument = instrument
        self.frames = frames

        self.reader = reader
        self.corner_handler = corners

        self.ok = False
        self.c4: pd.DataFrame = pd.DataFrame()
        self.times: pd.DatetimeIndex = pd.DatetimeIndex([])
        self.o = self.hi = self.lo = self.cl = self.atr = np.array([])
        self.sw = self.sd = self.s4 = np.array([])
        self.pip = pip_size(instrument)
        self.corners: list[list[Corner]] = []
        self.load()

    def load(self) -> None:
        c4 = self.frames["4h"]
        self.ok = not (c4.empty or len(c4) < WARMUP + 5)
        if not self.ok: return

        self.c4 = c4
        self.times = c4.index
        self.o, self.hi = c4["Open"].to_numpy(), c4["High"].to_numpy()
        self.lo, self.cl = c4["Low"].to_numpy(), c4["Close"].to_numpy()
        self.atr = atr(c4).to_numpy()

        # htf states as known at each 4h bar, using only htf bars that have closed
        states = self.frames["states"]
        self.sw = self.reader.closed_states(self.times, states["W"])
        self.sd = self.reader.closed_states(self.times, states["D"])
        self.s4 = self.reader.closed_states(self.times, states["4H"])

        # pivot confirm is already a close timestamp, so no re-keying is needed here
        self.corners = self.corner_handler.fresh_corners(self.times, self.frames["pivots"], CORNER_TIMEFRAMES)


class EdgeStrategy:

    def __init__(self, config: EdgeConfig, costs: CostModel, corners: CornerHandler,
                 account: str = STANDARD) -> None:
        self.config = config
        self.account = account

        self.costs = costs
        self.corners = corners

    def with_config(self, **changes: object) -> EdgeStrategy:
        return EdgeStrategy(replace(self.config, **changes), self.costs, self.corners, self.account)

    def signal_at(self, frames: EdgeFrames, i: int) -> EdgeSignal | None:
        # the single decision both the backtest and the live bot call, using bars up to and including i
        a = frames.atr[i]
        if not np.isfinite(a) or a <= 0: return None

        direction = bias_direction(self.config.bias_mode, frames.sw[i], frames.sd[i], frames.s4[i])
        if not direction: return None

        match = self.corners.react_at(frames.corners[i], float(frames.lo[i]), float(frames.hi[i]),
                                      float(frames.cl[i]), direction, a, self.config.aoi_tol)
        if match is None: return None

        risk = self.config.stop_atr * a
        if risk <= 0: return None

        return EdgeSignal(direction, float(a), float(risk), match)

    def simulate(self, frames: EdgeFrames, cost_mult: float = 1.0) -> list[EdgeTrade]:
        if not frames.ok: return []

        trades: list[EdgeTrade] = []
        last_exit = None
        offset = self.config.entry_offset

        for i in range(WARMUP, len(frames.c4) - offset - 1):
            if last_exit is not None and frames.times[i] <= last_exit: continue

            signal = self.signal_at(frames, i)
            if signal is None: continue

            trade, last_exit = self._open_trade(frames, i, signal, cost_mult)
            trades.append(trade)

        return trades

    def run_all(self, frames_list: list[EdgeFrames], cost_mult: float = 1.0) -> list[EdgeTrade]:
        return [trade for frames in frames_list for trade in self.simulate(frames, cost_mult)]

    def _open_trade(self, frames: EdgeFrames, i: int, signal: EdgeSignal,
                    cost_mult: float) -> tuple[EdgeTrade, pd.Timestamp]:
        t = frames.times[i]
        entry_index = i + self.config.entry_offset
        entry = float(frames.o[entry_index])
        stop, target = bracket(entry, signal.direction, signal.risk, self.config.target_rr)

        outcome = simulate_trade(frames.c4, entry_index, signal.direction, entry, stop, target,
                                 self.config.max_hold_hours)
        if signal.direction == "long":
            r = (outcome.price - entry) / signal.risk
        else:
            r = (entry - outcome.price) / signal.risk
        cost = self.costs.cost_r(frames.instrument, signal.risk / frames.pip, cost_mult, self.account)

        trade = EdgeTrade(
            instrument=frames.instrument, direction=signal.direction,
            signal_time=t.isoformat(), entry_time=frames.times[entry_index].isoformat(),
            exit_time=outcome.time.isoformat(), year=int(t.year),
            entry=round(entry, 6), stop=round(stop, 6), target=round(target, 6),
            exit_price=round(outcome.price, 6), exit_reason=outcome.reason,
            r_gross=round(r, 4), cost_r=round(cost, 4), r_net=round(r - cost, 4),
            risk_pips=round(signal.risk / frames.pip, 2), atr=round(signal.atr, 6),
            aoi=f"{signal.aoi.tf} {signal.direction} {signal.aoi.price:.5f}",
        )
        return trade, outcome.time

