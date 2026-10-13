from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from fxresearch.data.instruments import pip_size
from fxresearch.engine.indicators import atr
from fxresearch.engine.simulator import simulate_trade
from fxresearch.structure.aoi import RESISTANCE, SUPPORT, Aoi, AoiHandler
from fxresearch.structure.candles import tier1_pattern
from fxresearch.structure.market_structure import BEARISH, BULLISH, StructureReader, StructureState

ENHANCED_PAIRS = {"GBPJPY", "USDCAD", "GBPUSD", "NZDUSD", "XAUUSD", "XPTUSD"}
MIN_PRE_1H_BARS = 80
MIN_EMA_BARS = 55
EMA_SPANS = (20, 50)


@dataclass(frozen=True)
class V1Config:

    enhanced_all_pairs: bool = False
    atr_buffer: float = 0.25
    min_sl_atr: float = 0.6
    max_sl_atr: float = 2.0
    tp_atr: float = 2.0
    min_rr: float = 1.0
    max_rr: float = 0.0
    max_hold_hours: int = 48
    enhanced_start_hour_utc3: int = 10
    enhanced_end_hour_utc3: int = 18


@dataclass(frozen=True)
class V1Trade:

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
    tp_atr: float
    rr_planned: float
    atr_1h: float
    bias_w: str
    bias_d: str
    bias_4h: str
    stop_tf: str
    stop_structure_price: float
    trigger_pattern: str
    level_reason: str
    target_reason: str


class StructureAtrStrategy:

    def __init__(self, config: V1Config, reader: StructureReader, aois: AoiHandler,
                 ema_tail: int | None = None) -> None:
        self.config = config
        self.ema_tail = ema_tail

        self.reader = reader
        self.aois = aois

    def backtest(self, instrument: str, symbol: str, frames: dict, mode: str) -> list[V1Trade]:
        candles = frames["exec"]
        trades: list[V1Trade] = []
        if candles.empty or frames["1h"].empty or frames["1d"].empty: return trades
        if mode == "enhanced" and not self.config.enhanced_all_pairs and instrument not in ENHANCED_PAIRS:
            return trades

        last_exit: pd.Timestamp | None = None
        atr_1h_series = atr(frames["1h"])

        for i in range(2, len(candles) - 1):
            signal_time = candles.index[i]
            if mode == "enhanced" and not self._in_enhanced_session(signal_time): continue
            if last_exit and signal_time <= last_exit: continue

            result = self._evaluate_bar(instrument, symbol, frames, mode, candles, i, atr_1h_series)
            if result is None: continue

            trade, last_exit = result
            trades.append(trade)

        return trades

    def _evaluate_bar(self, instrument: str, symbol: str, frames: dict, mode: str, candles: pd.DataFrame,
                      i: int, atr_1h_series: pd.Series) -> tuple[V1Trade, pd.Timestamp] | None:
        signal_time = candles.index[i]
        pre_1h = frames["1h"][frames["1h"].index < signal_time]
        if len(pre_1h) < MIN_PRE_1H_BARS: return None

        current_atr = atr_1h_series[atr_1h_series.index < signal_time].dropna()
        if current_atr.empty: return None
        atr_1h = float(current_atr.iloc[-1])
        if not math.isfinite(atr_1h) or atr_1h <= 0: return None

        states = self.reader.active_states(frames, signal_time)
        direction = self.reader.direction_from_bias(mode, states)
        if not direction: return None
        if mode == "enhanced" and self._against_d4(direction, states): return None

        signal = candles.iloc[i]
        pattern = tier1_pattern(candles.iloc[i - 1], signal, direction)
        if not pattern: return None

        entry_index = self._entry_index(mode, direction, candles, i, signal)
        if entry_index is None: return None
        entry = float(candles.iloc[entry_index].Open)

        candidates = self.reader.stop_candidates(states, direction, entry)
        if not candidates: return None

        aoi_ok, aoi_reason, aoi_levels = True, "", []
        if mode == "enhanced":
            aoi_ok, aoi_reason, aoi_levels = self._aoi_reaction(frames, signal_time, signal, direction, atr_1h)
            if not aoi_ok: return None

        chosen = self._choose_stop(mode, candidates, signal, pre_1h, direction, entry, atr_1h, aoi_ok, aoi_reason)
        if chosen is None: return None
        stop_tf, structure_price, stop, risk, sl_atr, level_reason = chosen

        target_distance = self.config.tp_atr * atr_1h
        target = entry + target_distance if direction == "long" else entry - target_distance
        target_reason = f"{self.config.tp_atr:.2f} x 1H ATR"

        if mode == "enhanced":
            opposing = self._nearest_opposing(aoi_levels, direction, entry)
            if not opposing: return None

            opposing_rr = abs(opposing.price - entry) / risk
            if not (self.config.min_rr <= opposing_rr <= self.config.max_rr): return None

            target = opposing.price
            target_distance = abs(target - entry)
            target_reason = (f"Opposing {opposing.tf} {opposing.kind} {opposing.side} "
                             f"{opposing.price:.5f} x{opposing.touches}")

        rr_planned = target_distance / risk
        if rr_planned < self.config.min_rr: return None
        if self.config.max_rr and rr_planned > self.config.max_rr: return None

        outcome = simulate_trade(candles, entry_index, direction, entry, stop, target, self.config.max_hold_hours)
        r_result = (outcome.price - entry) / risk if direction == "long" else (entry - outcome.price) / risk

        trade = V1Trade(
            mode=mode, instrument=instrument, symbol=symbol, direction=direction,
            signal_time=signal_time.isoformat(), entry_time=candles.index[entry_index].isoformat(),
            exit_time=outcome.time.isoformat(),
            entry=round(entry, 6), stop_loss=round(stop, 6), take_profit=round(target, 6),
            exit_price=round(outcome.price, 6), exit_reason=outcome.reason,
            r_result=round(r_result, 4), risk=round(risk, 6), risk_pips=round(risk / pip_size(instrument), 2),
            sl_atr=round(sl_atr, 3), tp_atr=round(self.config.tp_atr, 3), rr_planned=round(rr_planned, 3),
            atr_1h=round(atr_1h, 6),
            bias_w=states["W"].state, bias_d=states["D"].state, bias_4h=states["4H"].state,
            stop_tf=stop_tf, stop_structure_price=round(structure_price, 6),
            trigger_pattern=pattern, level_reason=level_reason, target_reason=target_reason,
        )
        return trade, outcome.time

    def _in_enhanced_session(self, signal_time: pd.Timestamp) -> bool:
        hour_utc3 = (signal_time.hour + 3) % 24
        return self.config.enhanced_start_hour_utc3 <= hour_utc3 <= self.config.enhanced_end_hour_utc3

    def _against_d4(self, direction: str, states: dict[str, StructureState]) -> bool:
        if direction == "long": return states["D"].state == BEARISH and states["4H"].state == BEARISH
        return direction == "short" and states["D"].state == BULLISH and states["4H"].state == BULLISH

    def _entry_index(self, mode: str, direction: str, candles: pd.DataFrame, i: int, signal: pd.Series) -> int | None:
        if not (mode == "enhanced" and direction == "long"): return i + 1

        # enhanced longs wait for a confirmation candle that closes above the trigger high
        if i + 2 >= len(candles): return None
        if float(candles.iloc[i + 1].Close) <= float(signal.High): return None
        return i + 2

    def _choose_stop(self, mode: str, candidates: list[tuple[str, float, str]], signal: pd.Series,
                     pre_1h: pd.DataFrame, direction: str, entry: float, atr_1h: float, aoi_ok: bool,
                     aoi_reason: str) -> tuple | None:
        for tf, structure_price, _ in candidates:
            level_ok, level_reason = self._level_reaction(signal, direction, structure_price, atr_1h)
            ema_ok, ema_reason = self._ema_reaction(signal, pre_1h, direction, atr_1h)
            if mode == "enhanced":
                level_ok = level_ok or aoi_ok
            if not level_ok and not ema_ok: continue

            buffer = self.config.atr_buffer * atr_1h
            stop = structure_price - buffer if direction == "long" else structure_price + buffer
            risk = abs(entry - stop)
            sl_atr = risk / atr_1h
            if not (self.config.min_sl_atr <= sl_atr <= self.config.max_sl_atr): continue

            if ema_ok:
                level_reason = (level_reason + "; " if level_reason else "") + ema_reason
            if aoi_reason:
                level_reason = (level_reason + "; " if level_reason else "") + "AOI: " + aoi_reason
            return tf, structure_price, stop, risk, sl_atr, level_reason

        return None

    def _level_reaction(self, candle: pd.Series, direction: str, stop_level: float,
                        atr_1h: float) -> tuple[bool, str]:
        proximity = 0.6 * atr_1h
        if direction == "long":
            touched = float(candle.Low) <= stop_level + proximity
            rejected = float(candle.Close) > stop_level
        else:
            touched = float(candle.High) >= stop_level - proximity
            rejected = float(candle.Close) < stop_level

        if touched and rejected: return True, f"reacted within 0.60 ATR of {stop_level:.5f}"
        return False, ""

    def _ema_reaction(self, candle: pd.Series, pre_1h: pd.DataFrame, direction: str,
                      atr_1h: float) -> tuple[bool, str]:
        if len(pre_1h) < MIN_EMA_BARS: return False, ""

        # the comparison harness bounds the ema history to keep 11 years tractable
        history = pre_1h.tail(self.ema_tail) if self.ema_tail else pre_1h
        proximity = 0.35 * atr_1h
        reasons = []

        for span in EMA_SPANS:
            ema = float(history["Close"].ewm(span=span, adjust=False).mean().iloc[-1])
            if direction == "long":
                hit = float(candle.Low) <= ema + proximity and float(candle.Close) > ema
            else:
                hit = float(candle.High) >= ema - proximity and float(candle.Close) < ema
            if hit:
                reasons.append(f"1H EMA{span} {ema:.5f}")

        if reasons: return True, "EMA reaction: " + ", ".join(reasons)
        return False, ""

    def _aoi_reaction(self, frames: dict, signal_time: pd.Timestamp, candle: pd.Series, direction: str,
                      atr_1h: float) -> tuple[bool, str, list[Aoi]]:
        latest, clusters = self.aois.build_v1_levels(frames, signal_time, atr_1h, float(candle.Close))
        levels = latest + clusters
        tolerance = 0.75 * atr_1h
        matched: list[str] = []

        for level in levels:
            touches = f" x{level.touches}" if level.touches > 1 else ""
            if direction == "long" and level.side == SUPPORT:
                if float(candle.Low) <= level.price + tolerance and float(candle.Close) > level.price:
                    matched.append(f"{level.tf} {level.kind} support {level.price:.5f}" + touches)
            elif direction == "short" and level.side == RESISTANCE:
                if float(candle.High) >= level.price - tolerance and float(candle.Close) < level.price:
                    matched.append(f"{level.tf} {level.kind} resistance {level.price:.5f}" + touches)

        return bool(matched), "; ".join(matched[:4]), levels

    def _nearest_opposing(self, levels: list[Aoi], direction: str, entry: float) -> Aoi | None:
        if direction == "long":
            candidates = [level for level in levels if level.side == RESISTANCE and float(level.price) > entry]
            return min(candidates, key=lambda level: float(level.price) - entry) if candidates else None

        candidates = [level for level in levels if level.side == SUPPORT and float(level.price) < entry]
        return min(candidates, key=lambda level: entry - float(level.price)) if candidates else None

