from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

import pandas as pd

from fxresearch.data.instruments import pip_size
from fxresearch.engine.indicators import atr
from fxresearch.engine.simulator import simulate_trade
from fxresearch.structure.aoi import Aoi, AoiHandler
from fxresearch.structure.candles import BULLISH_ENGULFING, tier1_pattern
from fxresearch.structure.market_structure import BEARISH, BULLISH, StructureReader, StructureState

LATEST_SCORES = (2.0, 2.4)
WEEKLY_CLUSTER_MULT = 1.3
PREFERRED_RR = 1.8
CLOSE_CONFIRM_REASON = "1H close beyond 4H trigger"


@dataclass(frozen=True)
class V3Config:

    session_start: int = 8
    session_end: int = 20
    exclude_hour: tuple[int, ...] = ()
    bias_mode: str = "two_of_three"
    require_d4_agree: bool = False
    require_1h_tier1_confirmation: bool = False
    atr_buffer: float = 0.25
    min_sl_atr: float = 0.8
    max_sl_atr: float = 2.5
    min_rr: float = 1.25
    max_rr: float = 2.5
    lookback_pivots: int = 80
    cluster_tolerance_atr: float = 0.75
    exclude_trigger: tuple[str, ...] = (BULLISH_ENGULFING,)
    stop_tf: str = "any"
    max_hold_hours: int = 72


@dataclass(frozen=True)
class V3Trade:

    instrument: str
    symbol: str
    direction: str
    signal_time_4h: str
    confirm_time_1h: str
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
    trigger_pattern_4h: str
    confirmation_1h: str
    entry_aoi: str
    target_aoi: str
    entry_aoi_touches: int
    target_aoi_touches: int


class FourHourCornerStrategy:

    def __init__(self, config: V3Config, reader: StructureReader, aois: AoiHandler) -> None:
        self.config = config

        self.reader = reader
        self.aois = aois

    def simulate(self, instrument: str, symbol: str, frames: dict) -> list[V3Trade]:
        candles = frames["4h"]
        trades: list[V3Trade] = []
        last_exit: pd.Timestamp | None = None
        atr_1h_series = atr(frames["1h"])

        for i in range(2, len(candles) - self._bars_needed_after_signal()):
            signal_time = candles.index[i]
            if not self._in_session(signal_time): continue
            if last_exit and signal_time <= last_exit: continue

            result = self._evaluate_bar(instrument, symbol, frames, candles, i, atr_1h_series)
            if result is None: continue

            trade, last_exit = result
            trades.append(trade)

        return trades

    def corner_aois(self, frames: dict, signal_time: pd.Timestamp, price: float, atr_1h: float,
                    lookback_pivots: int, tolerance_atr: float) -> list[Aoi]:
        return self.aois.build_corner_aois(frames, signal_time, price, atr_1h, lookback_pivots, tolerance_atr,
                                           LATEST_SCORES, WEEKLY_CLUSTER_MULT)

    def find_entry_aoi(self, aois: list[Aoi], candle: pd.Series, direction: str, atr_1h: float) -> Aoi | None:
        # v3 enters only at clean latest corners, never at clusters
        latest = [aoi for aoi in aois if aoi.kind == "latest_corner"]
        return self.aois.best_reaction(latest, candle, direction, atr_1h)

    def find_target_aoi(self, aois: list[Aoi], direction: str, entry: float, risk: float, min_rr: float,
                        max_rr: float) -> Aoi | None:
        candidates = self.aois.target_candidates(aois, direction, entry, risk, min_rr, max_rr)
        if not candidates: return None

        # clusters first, then the rr closest to 1.8
        candidates.sort(key=lambda item: (item[0].touches < 2, abs(item[1] - PREFERRED_RR), -item[0].score))
        return candidates[0][0]

    def _evaluate_bar(self, instrument: str, symbol: str, frames: dict, candles: pd.DataFrame, i: int,
                      atr_1h_series: pd.Series) -> tuple[V3Trade, pd.Timestamp] | None:
        signal_time = candles.index[i]
        current_atr = atr_1h_series[atr_1h_series.index < signal_time].dropna()
        if current_atr.empty: return None
        atr_1h = float(current_atr.iloc[-1])
        if not self._atr_usable(atr_1h): return None

        states = self.reader.active_states(frames, signal_time)
        direction = self.reader.direction_from_bias(self.config.bias_mode, states)
        if not direction: return None
        if self.config.require_d4_agree and not self._d4_agrees(direction, states): return None

        pattern = tier1_pattern(candles.iloc[i - 1], candles.iloc[i], direction)
        if not pattern or pattern in self.config.exclude_trigger: return None

        aois = self.corner_aois(frames, signal_time, float(candles.iloc[i].Close), atr_1h,
                                self.config.lookback_pivots, self.config.cluster_tolerance_atr)
        entry_aoi = self.find_entry_aoi(aois, candles.iloc[i], direction, atr_1h)
        if not entry_aoi: return None

        confirm_time, confirm_reason = self._confirm(frames["1h"], candles, i, direction)
        if confirm_time is None: return None

        entry_index = self._entry_index(i)
        entry = float(candles.iloc[entry_index].Open)

        stop = self.reader.pick_stop(states, direction, entry, atr_1h, self.config.atr_buffer,
                                     self.config.min_sl_atr, self.config.max_sl_atr, self.config.stop_tf)
        if stop is None: return None

        target_aoi = self.find_target_aoi(aois, direction, entry, stop.risk, self.config.min_rr, self.config.max_rr)
        if not target_aoi: return None
        target = float(target_aoi.price)
        rr = abs(target - entry) / stop.risk

        outcome = simulate_trade(candles, entry_index, direction, entry, stop.stop, target, self.config.max_hold_hours)
        r_result = (outcome.price - entry) / stop.risk if direction == "long" else (entry - outcome.price) / stop.risk

        trade = V3Trade(
            instrument=instrument, symbol=symbol, direction=direction,
            signal_time_4h=signal_time.isoformat(), confirm_time_1h=confirm_time.isoformat(),
            entry_time=candles.index[entry_index].isoformat(), exit_time=outcome.time.isoformat(),
            entry=round(entry, 6), stop_loss=round(stop.stop, 6), take_profit=round(target, 6),
            exit_price=round(outcome.price, 6), exit_reason=outcome.reason,
            r_result=round(r_result, 4), risk=round(stop.risk, 6),
            risk_pips=round(stop.risk / pip_size(instrument), 2), sl_atr=round(stop.sl_atr, 3),
            rr_planned=round(rr, 3), atr_1h=round(atr_1h, 6),
            bias_w=states["W"].state, bias_d=states["D"].state, bias_4h=states["4H"].state,
            stop_tf=stop.tf, trigger_pattern_4h=pattern, confirmation_1h=confirm_reason,
            entry_aoi=entry_aoi.describe(), target_aoi=target_aoi.describe(),
            entry_aoi_touches=int(entry_aoi.touches), target_aoi_touches=int(target_aoi.touches),
        )
        return trade, outcome.time

    def _bars_needed_after_signal(self) -> int:
        return 1

    def _session_hour(self, signal_time: pd.Timestamp) -> int:
        # the original v3 shifted utc by a fixed +3, which ignores dst
        return (signal_time.hour + 3) % 24

    def _in_session(self, signal_time: pd.Timestamp) -> bool:
        hour = self._session_hour(signal_time)
        if not (self.config.session_start <= hour <= self.config.session_end): return False
        return not (self.config.exclude_hour and hour in self.config.exclude_hour)

    def _atr_usable(self, atr_1h: float) -> bool:
        return True

    def _d4_agrees(self, direction: str, states: dict[str, StructureState]) -> bool:
        if direction == "long": return states["D"].state == BULLISH and states["4H"].state == BULLISH
        return states["D"].state == BEARISH and states["4H"].state == BEARISH

    def _entry_index(self, i: int) -> int:
        return i + 1

    def _confirm(self, one_h: pd.DataFrame, candles: pd.DataFrame, i: int,
                 direction: str) -> tuple[pd.Timestamp | None, str]:
        # as written: confirms inside (signal open, next open] but enters at the next open, a look-ahead bug
        window = one_h[(one_h.index > candles.index[i]) & (one_h.index <= candles.index[i + 1])]
        if len(window) < 2: return None, ""

        trigger = candles.iloc[i]
        prev = None
        for ts, candle in window.iterrows():
            if direction == "long":
                close_confirm = float(candle.Close) > float(trigger.High)
            else:
                close_confirm = float(candle.Close) < float(trigger.Low)

            pattern = (tier1_pattern(prev, candle, direction) or "") if prev is not None else ""
            if self.config.require_1h_tier1_confirmation:
                if pattern: return ts, f"1H Tier1 {pattern}"
            elif close_confirm or pattern:
                return ts, CLOSE_CONFIRM_REASON if close_confirm else f"1H Tier1 {pattern}"

            prev = candle

        return None, ""


class BrokerCornerStrategy(FourHourCornerStrategy):

    def _bars_needed_after_signal(self) -> int:
        # trigger at i, confirm during i + 1, enter at the open of i + 2
        return 2

    def _session_hour(self, signal_time: pd.Timestamp) -> int:
        # frames are already on the broker clock
        return signal_time.hour

    def _atr_usable(self, atr_1h: float) -> bool:
        return math.isfinite(atr_1h) and atr_1h > 0

    def _entry_index(self, i: int) -> int:
        return i + 2

    def _confirm(self, one_h: pd.DataFrame, candles: pd.DataFrame, i: int,
                 direction: str) -> tuple[pd.Timestamp | None, str]:
        # only a 1h close beyond the trigger extreme, inside the bar after the trigger
        window = one_h[(one_h.index >= candles.index[i + 1]) & (one_h.index < candles.index[i + 2])]
        if window.empty: return None, ""

        trigger = candles.iloc[i]
        for ts, candle in window.iterrows():
            if direction == "long" and float(candle.Close) > float(trigger.High): return ts, CLOSE_CONFIRM_REASON
            if direction == "short" and float(candle.Close) < float(trigger.Low): return ts, CLOSE_CONFIRM_REASON

        return None, ""


def summarize_v3(trades: list[V3Trade]) -> dict:
    if not trades: return {"trade_count": 0}

    wins = [t for t in trades if t.r_result > 0]
    losses = [t for t in trades if t.r_result < 0]
    by_instrument = {}
    for instrument in sorted({t.instrument for t in trades}):
        subset = [t for t in trades if t.instrument == instrument]
        by_instrument[instrument] = {
            "trades": len(subset),
            "win_rate": round(100 * sum(t.r_result > 0 for t in subset) / len(subset), 2),
            "net_R": round(sum(t.r_result for t in subset), 3),
            "avg_R": round(statistics.mean(t.r_result for t in subset), 3),
        }

    return {
        "trade_count": len(trades),
        "win_rate": round(100 * len(wins) / len(trades), 2),
        "net_R": round(sum(t.r_result for t in trades), 3),
        "avg_R": round(statistics.mean(t.r_result for t in trades), 3),
        "median_R": round(statistics.median(t.r_result for t in trades), 3),
        "avg_win_R": round(statistics.mean([t.r_result for t in wins]), 3) if wins else 0,
        "avg_loss_R": round(statistics.mean([t.r_result for t in losses]), 3) if losses else 0,
        "profit_factor_R": round(sum(t.r_result for t in wins) / abs(sum(t.r_result for t in losses)), 3)
        if losses else None,
        "by_instrument": by_instrument,
    }
