from __future__ import annotations

import pandas as pd

ATR_LENGTH = 14


def atr(df: pd.DataFrame, length: int = ATR_LENGTH) -> pd.Series:
    true_range = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - df["Close"].shift()).abs(),
            (df["Low"] - df["Close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(length, min_periods=max(3, length // 2)).mean()
