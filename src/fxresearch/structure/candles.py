from __future__ import annotations

import pandas as pd

BULLISH_ENGULFING = "Bullish Engulfing"
BEARISH_ENGULFING = "Bearish Engulfing"
HAMMER = "Hammer/Pin Bar"
SHOOTING_STAR = "Shooting Star"


def tier1_pattern(prev: pd.Series, candle: pd.Series, direction: str) -> str | None:
    return tier1_from_values(float(prev.Open), float(prev.Close), float(candle.Open), float(candle.High),
                             float(candle.Low), float(candle.Close), direction)


def tier1_from_values(po: float, pc: float, o: float, h: float, l: float, c: float, direction: str) -> str | None:
    rng = max(h - l, 1e-12)
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l

    if direction == "long":
        if pc < po and c > o and min(o, c) <= min(po, pc) and max(o, c) >= max(po, pc): return BULLISH_ENGULFING
        if lower >= max(body * 2, rng * 0.45) and upper <= max(body * 0.8, rng * 0.2) and c >= l + rng * 0.6: return HAMMER
        return None

    if pc > po and c < o and min(o, c) <= min(po, pc) and max(o, c) >= max(po, pc): return BEARISH_ENGULFING
    if upper >= max(body * 2, rng * 0.45) and lower <= max(body * 0.8, rng * 0.2) and c <= l + rng * 0.4: return SHOOTING_STAR
    return None
