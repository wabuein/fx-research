from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# a pivot is known once the rightmost window candle has closed
CONFIRM_AT_CLOSE = "close"
# deliberately leaky: stamps the confirm at that candle's open, one bar early, used only by the look-ahead test
CONFIRM_AT_OPEN = "open"


@dataclass(frozen=True, slots=True)
class Pivot:

    kind: str
    time: pd.Timestamp
    confirm: pd.Timestamp
    confirm_bar: pd.Timestamp
    price: float


def bar_close_times(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if len(index) == 0: return pd.DatetimeIndex([])

    # an open-labelled candle closes at the next open, the last one at open + median span
    close_times = index.to_series().shift(-1)
    span = index.to_series().diff().median() if len(index) >= 2 else pd.Timedelta(days=1)
    if pd.isna(span):
        span = pd.Timedelta(days=1)
    close_times.iloc[-1] = index[-1] + span

    return pd.DatetimeIndex(close_times.to_numpy())


class PivotHandler:

    def __init__(self, confirm_at: str = CONFIRM_AT_CLOSE) -> None:
        self.confirm_at = confirm_at

    def find_pivots(self, df: pd.DataFrame, left: int = 2, right: int = 2) -> list[Pivot]:
        out: list[Pivot] = []
        if len(df) < left + right + 1: return out

        idx = df.index
        highs = df["High"].to_numpy(dtype=float)
        lows = df["Low"].to_numpy(dtype=float)
        close_times = bar_close_times(df.index)

        for i in range(left, len(df) - right):
            high = float(highs[i])
            low = float(lows[i])

            if high >= float(np.max(highs[i - left: i + right + 1])):
                out.append(Pivot("H", idx[i], self._confirm_time(idx, close_times, i + right), idx[i + right], high))
            if low <= float(np.min(lows[i - left: i + right + 1])):
                out.append(Pivot("L", idx[i], self._confirm_time(idx, close_times, i + right), idx[i + right], low))

        return sorted(out, key=lambda pivot: (pivot.confirm, pivot.time))

    def alternate(self, pivots: list[Pivot]) -> list[Pivot]:
        # prefix-stable: once a pivot is emitted, later same-type pivots never revise it
        compressed: list[Pivot] = []

        for pivot in pivots:
            if not compressed or pivot.kind != compressed[-1].kind:
                compressed.append(pivot)

        return compressed

    def find_alternating(self, df: pd.DataFrame, left: int = 2, right: int = 2) -> list[Pivot]:
        return self.alternate(self.find_pivots(df, left, right))

    def _confirm_time(self, idx: pd.DatetimeIndex, close_times: pd.DatetimeIndex, position: int) -> pd.Timestamp:
        if self.confirm_at == CONFIRM_AT_OPEN: return idx[position]
        return close_times[position]

