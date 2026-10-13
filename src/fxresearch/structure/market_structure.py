from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from fxresearch.structure.pivots import Pivot, PivotHandler, bar_close_times

BULLISH = "bullish"
BEARISH = "bearish"
NEUTRAL = "neutral"
PRICE_COLUMNS = ("last_high", "last_low", "protected_high", "protected_low")


@dataclass(frozen=True)
class StopChoice:

    tf: str
    structure_price: float
    stop: float
    risk: float
    sl_atr: float


@dataclass(frozen=True)
class StructureState:

    state: str
    last_high: float | None = None
    last_low: float | None = None
    protected_high: float | None = None
    protected_low: float | None = None


NEUTRAL_STATE = StructureState(NEUTRAL)


class StructureHandler:

    def __init__(self, pivots: PivotHandler) -> None:
        self.pivots = pivots

    def build_timeline(self, df: pd.DataFrame, left: int = 2, right: int = 2) -> pd.DataFrame:
        if df.empty: return pd.DataFrame()

        confirmed = self.pivots.find_alternating(df, left, right)
        close_times = bar_close_times(df.index)
        closes = df["Close"].to_numpy(dtype=float)
        pivot_idx = 0

        state = NEUTRAL
        last_high: Pivot | None = None
        last_low: Pivot | None = None
        protected_high: Pivot | None = None
        protected_low: Pivot | None = None
        rows = []

        for pos, ts in enumerate(df.index):
            # consume every pivot that is confirmed by this candle's close
            bar_close = close_times[pos]
            while pivot_idx < len(confirmed) and confirmed[pivot_idx].confirm <= bar_close:
                pivot = confirmed[pivot_idx]
                if pivot.kind == "H":
                    last_high = pivot
                else:
                    last_low = pivot
                pivot_idx += 1

            # a close beyond the last swing sets the trend and protects the opposite swing
            close = float(closes[pos])
            if last_high is not None and last_low is not None and close > last_high.price:
                state = BULLISH
                protected_low = last_low
                protected_high = last_high
            elif last_high is not None and last_low is not None and close < last_low.price:
                state = BEARISH
                protected_high = last_high
                protected_low = last_low

            # a close through the protected swing flips the trend
            if state == BULLISH and protected_low is not None and close < protected_low.price:
                state = BEARISH
                protected_high = last_high
            elif state == BEARISH and protected_high is not None and close > protected_high.price:
                state = BULLISH
                protected_low = last_low

            rows.append({
                "time": ts,
                "state": state,
                "last_high": self._price_or_nan(last_high),
                "last_low": self._price_or_nan(last_low),
                "protected_high": self._price_or_nan(protected_high),
                "protected_low": self._price_or_nan(protected_low),
            })

        return pd.DataFrame(rows).set_index("time")

    def _price_or_nan(self, pivot: Pivot | None) -> float:
        return float(pivot.price) if pivot is not None else math.nan


class StructureReader:

    def __init__(self, fast_lookup: bool = False) -> None:
        self.fast_lookup = fast_lookup

    def state_at(self, timeline: pd.DataFrame, signal_time: pd.Timestamp) -> StructureState:
        if self.fast_lookup: return self._state_by_search(timeline, signal_time)
        return self._state_by_mask(timeline, signal_time)

    def active_states(self, frames: dict, signal_time: pd.Timestamp) -> dict[str, StructureState]:
        timelines = frames["states"]
        return {key: self.state_at(timelines[key], signal_time) for key in ("W", "D", "4H", "1H")}

    def direction_from_bias(self, mode: str, states: dict[str, StructureState]) -> str | None:
        top = [states["W"].state, states["D"].state, states["4H"].state]
        bullish = top.count(BULLISH)
        bearish = top.count(BEARISH)

        if mode == "strict":
            if bullish == 3: return "long"
            if bearish == 3: return "short"
            return None

        if bullish >= 2 and bearish <= 1: return "long"
        if bearish >= 2 and bullish <= 1: return "short"
        return None

    def stop_candidates(self, states: dict[str, StructureState], direction: str,
                        entry: float) -> list[tuple[str, float, str]]:
        candidates: list[tuple[str, float, str]] = []
        keys = ("protected_low", "last_low") if direction == "long" else ("protected_high", "last_high")

        for tf in ("1H", "4H"):
            for key in keys:
                price = getattr(states[tf], key)
                if price is None: continue

                price = float(price)
                if direction == "long" and price < entry:
                    candidates.append((tf, price, key))
                elif direction == "short" and price > entry:
                    candidates.append((tf, price, key))

        if direction == "long": return sorted(candidates, key=lambda item: entry - item[1])
        return sorted(candidates, key=lambda item: item[1] - entry)

    def pick_stop(self, states: dict[str, StructureState], direction: str, entry: float, atr_1h: float,
                  atr_buffer: float, min_sl_atr: float, max_sl_atr: float, stop_tf: str = "any") -> StopChoice | None:
        # nearest swing stop, pushed out by an atr buffer, that lands inside the allowed atr band
        for tf, structure_price, _ in self.stop_candidates(states, direction, entry):
            if stop_tf != "any" and tf != stop_tf: continue

            if direction == "long":
                stop = structure_price - atr_buffer * atr_1h
            else:
                stop = structure_price + atr_buffer * atr_1h
            risk = abs(entry - stop)
            sl_atr = risk / atr_1h
            if min_sl_atr <= sl_atr <= max_sl_atr: return StopChoice(tf, structure_price, stop, risk, sl_atr)

        return None

    def closed_states(self, bar_times: pd.DatetimeIndex, timeline: pd.DataFrame) -> np.ndarray:
        if timeline.empty: return np.array([NEUTRAL] * len(bar_times), dtype=object)

        # re-key each htf state to its bar close so a forming daily or weekly bar is never visible
        close_times = bar_close_times(timeline.index)
        keyed = pd.DataFrame({"state": timeline["state"].to_numpy(), "ct": close_times}).sort_values("ct")
        left = pd.DataFrame({"t": bar_times})
        merged = pd.merge_asof(left, keyed, left_on="t", right_on="ct", direction="backward", allow_exact_matches=True)

        return merged["state"].astype(str).fillna(NEUTRAL).to_numpy()

    def _state_by_mask(self, timeline: pd.DataFrame, signal_time: pd.Timestamp) -> StructureState:
        prior = timeline[timeline.index < signal_time]
        if prior.empty: return NEUTRAL_STATE
        return self._row_state(prior.iloc[-1])

    def _state_by_search(self, timeline: pd.DataFrame, signal_time: pd.Timestamp) -> StructureState:
        if timeline is None or timeline.empty: return NEUTRAL_STATE

        pos = timeline.index.searchsorted(signal_time, side="left")
        if pos == 0: return NEUTRAL_STATE

        return self._row_state(timeline.iloc[pos - 1])

    def _row_state(self, row: pd.Series) -> StructureState:
        prices = {name: self._price_or_none(row, name) for name in PRICE_COLUMNS}
        return StructureState(str(row["state"]), **prices)

    def _price_or_none(self, row: pd.Series, name: str) -> float | None:
        value = float(row[name])
        return None if math.isnan(value) else value

