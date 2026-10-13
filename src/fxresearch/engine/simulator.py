from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pandas as pd


@dataclass(frozen=True)
class TradeExit:

    time: pd.Timestamp
    price: float
    reason: str


def simulate_trade(candles: pd.DataFrame, entry_index: int, direction: str, entry: float, stop: float,
                   target: float, max_hold_hours: int) -> TradeExit:
    entry_time = candles.index[entry_index]
    deadline = entry_time + timedelta(hours=max_hold_hours)

    for j in range(entry_index, len(candles)):
        ts = candles.index[j]
        row = candles.iloc[j]
        if ts > deadline:
            prev = candles.iloc[j - 1]
            return TradeExit(candles.index[j - 1], float(prev.Close), "time_exit")

        high = float(row.High)
        low = float(row.Low)
        if direction == "long":
            stop_hit = low <= stop
            target_hit = high >= target
        else:
            stop_hit = high >= stop
            target_hit = low <= target

        # a candle that touches both is counted as the stop, the conservative fill
        if stop_hit: return TradeExit(ts, stop, "sl")
        if target_hit: return TradeExit(ts, target, "tp")

    last = candles.iloc[-1]
    return TradeExit(candles.index[-1], float(last.Close), "end_of_data")
