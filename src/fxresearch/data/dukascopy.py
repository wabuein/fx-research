from __future__ import annotations

from pathlib import Path

import pandas as pd

from fxresearch.paths import DATA_DIR

OHLC_COLUMNS = ["Open", "High", "Low", "Close"]
RENAMES = {"open": "Open", "high": "High", "low": "Low", "close": "Close"}


class DukascopyHandler:

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.data_dir = data_dir

    def csv_path(self, instrument: str, tf: str) -> Path:
        return self.data_dir / f"{instrument}_{tf}.csv"

    def ask_path(self, instrument: str, tf: str) -> Path:
        return self.data_dir / f"{instrument}_{tf}_ask.csv"

    def has(self, instrument: str, tf: str) -> bool:
        return self.csv_path(instrument, tf).exists()

    def load(self, instrument: str, tf: str) -> pd.DataFrame:
        path = self.csv_path(instrument, tf)
        if not path.exists(): return pd.DataFrame(columns=OHLC_COLUMNS)

        df = pd.read_csv(path)
        if df.empty: return pd.DataFrame(columns=OHLC_COLUMNS)

        return self._normalize(df)

    def _normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        # dukascopy-node csv header is timestamp,open,high,low,close with a utc epoch in ms
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp")
        df = df.rename(columns=RENAMES)
        df = df[OHLC_COLUMNS].dropna()

        return df[~df.index.duplicated(keep="last")].sort_index()

