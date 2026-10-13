from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from fxresearch.data.instruments import pip_size
from fxresearch.engine.indicators import atr
from fxresearch.engine.simulator import simulate_trade
from fxresearch.structure.aoi import Aoi, AoiHandler
from fxresearch.structure.candles import tier1_pattern
from fxresearch.structure.market_structure import BEARISH, BULLISH, StructureReader, StructureState

LATEST_SCORES = (1.0, 1.25)
WEEKLY_CLUSTER_MULT = 1.35
PREFERRED_RR = 1.8


@dataclass(frozen=True)
class V2Config:

    session_start: int = 10
    session_end: int = 18
    exclude_hour: tuple[int, ...] = ()
    require_d4_agree: bool = False
    atr_buffer: float = 0.25
    min_sl_atr: float = 0.8
    max_sl_atr: float = 2.0
    min_rr: float = 1.0
    max_rr: float = 2.5
    lookback_pivots: int = 80
    cluster_tolerance_atr: float = 0.75
    require_corner_cluster: bool = False
    prefer_cluster_target: bool = False
    confirm_longs: bool = False
    exclude_trigger: tuple[str, ...] = ()
    max_hold_hours: int = 48


@dataclass(frozen=True)
class V2Trade:

    mode: str
    instrument: str
    symbol: str
    direction: str
    signal_time: str
    entry_time: str
    exit_time: str
    entry: float
    stop_loss: float
    take_profit: float
    exit_price: float
    exit_reason: str
    r_result: float
    risk: float
    risk_pips: float
    sl_atr: float
    rr_planned: float
    atr_1h: float
    bias_w: str
    bias_d: str
    bias_4h: str
    stop_tf: str
    stop_structure_price: float
    trigger_pattern: str
    entry_aoi: str
    entry_aoi_tf: str
    entry_aoi_touches: int
    target_aoi: str
    target_aoi_tf: str
    target_aoi_touches: int
    corner_score: float


class CornerAoiStrategy:

    def __init__(self, config: V2Config, reader: StructureReader, aois: AoiHandler) -> None:
        self.config = config

        self.reader = reader
        self.aois = aois

    def simulate(self, instrument: str, symbol: str, frames: dict, mode: str) -> list[V2Trade]:
        candles = frames["exec"]
        if candles.empty or frames["1h"].empty or frames["1d"].empty: return []

        trades: list[V2Trade] = []
        last_exit: pd.Timestamp | None = None
        atr_1h_series = atr(frames["1h"])

        for i in range(2, len(candles) - 1):
            signal_time = candles.index[i]
            if not self._in_session(signal_time): continue
            if last_exit and signal_time <= last_exit: continue

            result = self._evaluate_bar(instrument, symbol, frames, mode, candles, i, atr_1h_series)
            if result is None: continue

            trade, last_exit = result
            trades.append(trade)

        return trades

    def build_aois(self, frames: dict, signal_time: pd.Timestamp, price: float, atr_1h: float) -> list[Aoi]:
        aois = self.aois.build_corner_aois(frames, signal_time, price, atr_1h, self.config.lookback_pivots,
                                           self.config.cluster_tolerance_atr, LATEST_SCORES, WEEKLY_CLUSTER_MULT)
        tolerance = self.aois.corner_tolerance(price, atr_1h, self.config.cluster_tolerance_atr)
        return self.aois.dedupe(aois, tolerance)

    def _evaluate_bar(self, instrument: str, symbol: str, frames: dict, mode: str, candles: pd.DataFrame,
                      i: int, atr_1h_series: pd.Series) -> tuple[V2Trade, pd.Timestamp] | None:
        signal_time = candles.index[i]
        current_atr = atr_1h_series[atr_1h_series.index < signal_time].dropna()
        if current_atr.empty: return None
        atr_1h = float(current_atr.iloc[-1])
        if not math.isfinite(atr_1h) or atr_1h <= 0: return None

        states = self.reader.active_states(frames, signal_time)
        direction = self.reader.direction_from_bias(mode, states)
        if not direction: return None
        if self.config.require_d4_agree and not self._d4_agrees(direction, states): return None

        signal = candles.iloc[i]
        pattern = tier1_pattern(candles.iloc[i - 1], signal, direction)
        if not pattern: return None
        if pattern in self.config.exclude_trigger: return None

        entry_index = self._entry_index(direction, candles, i, signal)
        if entry_index is None: return None
        entry = float(candles.iloc[entry_index].Open)

        # v2 scores its aois around the entry price, not the signal close
        aois = self.build_aois(frames, signal_time, entry, atr_1h)
        entry_aoi = self._find_entry_aoi(aois, signal, direction, atr_1h)
        if not entry_aoi: return None

        stop = self.reader.pick_stop(states, direction, entry, atr_1h, self.config.atr_buffer,
                                     self.config.min_sl_atr, self.config.max_sl_atr)
        if stop is None: return None

        target_aoi = self._find_target_aoi(aois, direction, entry, stop.risk)
        if not target_aoi: return None
        target = float(target_aoi.price)
        rr = abs(target - entry) / stop.risk

        outcome = simulate_trade(candles, entry_index, direction, entry, stop.stop, target, self.config.max_hold_hours)
        r_result = (outcome.price - entry) / stop.risk if direction == "long" else (entry - outcome.price) / stop.risk

        trade = V2Trade(
            mode=mode, instrument=instrument, symbol=symbol, direction=direction,
            signal_time=signal_time.isoformat(), entry_time=candles.index[entry_index].isoformat(),
            exit_time=outcome.time.isoformat(),
            entry=round(entry, 6), stop_loss=round(stop.stop, 6), take_profit=round(target, 6),
            exit_price=round(outcome.price, 6), exit_reason=outcome.reason,
            r_result=round(r_result, 4), risk=round(stop.risk, 6),
            risk_pips=round(stop.risk / pip_size(instrument), 2), sl_atr=round(stop.sl_atr, 3),
            rr_planned=round(rr, 3), atr_1h=round(atr_1h, 6),
            bias_w=states["W"].state, bias_d=states["D"].state, bias_4h=states["4H"].state,
            stop_tf=stop.tf, stop_structure_price=round(stop.structure_price, 6), trigger_pattern=pattern,
            entry_aoi=entry_aoi.describe(), entry_aoi_tf=entry_aoi.tf, entry_aoi_touches=int(entry_aoi.touches),
            target_aoi=target_aoi.describe(), target_aoi_tf=target_aoi.tf,
            target_aoi_touches=int(target_aoi.touches),
            corner_score=round(float(entry_aoi.score) + float(target_aoi.score), 3),
        )
        return trade, outcome.time

    def _in_session(self, signal_time: pd.Timestamp) -> bool:
        hour_utc3 = (signal_time.hour + 3) % 24
        start, end = self.config.session_start, self.config.session_end

        # a window like 22 to 2 wraps past midnight
        if start <= end:
            in_window = start <= hour_utc3 <= end
        else:
            in_window = hour_utc3 >= start or hour_utc3 <= end
        return in_window and hour_utc3 not in self.config.exclude_hour

    def _d4_agrees(self, direction: str, states: dict[str, StructureState]) -> bool:
        if direction == "long": return states["D"].state == BULLISH and states["4H"].state == BULLISH
        return states["D"].state == BEARISH and states["4H"].state == BEARISH

    def _entry_index(self, direction: str, candles: pd.DataFrame, i: int, signal: pd.Series) -> int | None:
        if not (self.config.confirm_longs and direction == "long"): return i + 1

        if i + 2 >= len(candles): return None
        if float(candles.iloc[i + 1].Close) <= float(signal.High): return None
        return i + 2

    def _find_entry_aoi(self, aois: list[Aoi], candle: pd.Series, direction: str, atr_1h: float) -> Aoi | None:
        eligible = [aoi for aoi in aois if not (self.config.require_corner_cluster and aoi.touches < 2)]
        return self.aois.best_reaction(eligible, candle, direction, atr_1h)

    def _find_target_aoi(self, aois: list[Aoi], direction: str, entry: float, risk: float) -> Aoi | None:
        candidates = self.aois.target_candidates(aois, direction, entry, risk, self.config.min_rr, self.config.max_rr)
        if not candidates: return None

        if self.config.prefer_cluster_target:
            candidates.sort(key=lambda item: (item[0].touches < 2, -item[0].score, abs(item[1] - PREFERRED_RR)))
        else:
            candidates.sort(key=lambda item: abs(item[1] - PREFERRED_RR))
        return candidates[0][0]

