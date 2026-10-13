from __future__ import annotations

import pandas as pd

# broker server midnight is 17:00 new york, so the dst rule follows new york
BROKER_DST_REFERENCE = "America/New_York"
BROKER_OFFSET_FROM_REFERENCE = pd.Timedelta(hours=7)

OHLC = ("Open", "High", "Low", "Close")

# label, minutes, pandas resample rule
TF_LADDER = [
    ("5m", 5, "5min"),
    ("15m", 15, "15min"),
    ("30m", 30, "30min"),
    ("1h", 60, "1h"),
    ("4h", 240, "4h"),
    ("1d", 1440, "1D"),
]
BASE_MINUTES = {"m5": 5, "m15": 15, "m30": 30, "h1": 60}


class BrokerClock:

    def __init__(self, dst_reference: str = BROKER_DST_REFERENCE,
                 offset: pd.Timedelta = BROKER_OFFSET_FROM_REFERENCE) -> None:
        self.dst_reference = dst_reference
        self.offset = offset

    def to_broker_time(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty: return df.copy()
        if df.index.tz is None: raise ValueError("to_broker_time expects a UTC tz-aware index")

        ref = df.index.tz_convert(self.dst_reference)
        broker = ref.tz_localize(None) + self.offset

        out = df.copy()
        out.index = broker
        out = out.sort_index()

        # the autumn fall-back hour repeats one label a year, keep the first
        return out[~out.index.duplicated(keep="first")]

    def resample(self, df: pd.DataFrame, rule: str, origin: str = "start_day") -> pd.DataFrame:
        if df.empty: return df.copy()

        # origin start_day anchors 4h and daily buckets to broker midnight
        agg = {
            "Open": df["Open"].resample(rule, origin=origin).first(),
            "High": df["High"].resample(rule, origin=origin).max(),
            "Low": df["Low"].resample(rule, origin=origin).min(),
            "Close": df["Close"].resample(rule, origin=origin).last(),
        }
        return pd.DataFrame(agg)[list(OHLC)].dropna()

    def build_frames(self, h1_utc: pd.DataFrame) -> dict[str, pd.DataFrame]:
        h1 = self.to_broker_time(h1_utc)
        if h1.empty: return {"1h": h1, "4h": h1, "1d": h1, "1wk": h1}

        four_h = self.resample(h1, "4h")
        daily = self.resample(h1, "1D")
        weekly = self._weekly(daily)

        return {"1h": h1, "4h": four_h, "1d": daily, "1wk": weekly}

    def build_frames_tf(self, base_utc: pd.DataFrame, base_tf: str) -> dict[str, pd.DataFrame]:
        base_min = BASE_MINUTES.get(base_tf)
        if base_min is None:
            raise ValueError(f"unsupported base_tf {base_tf!r}; expected one of {list(BASE_MINUTES)}")

        base = self.to_broker_time(base_utc)
        if base.empty: return {label: base for label, minutes, _ in TF_LADDER if minutes >= base_min} | {"1wk": base}

        out: dict[str, pd.DataFrame] = {}
        for label, minutes, rule in TF_LADDER:
            if minutes < base_min: continue
            out[label] = base.copy() if minutes == base_min else self.resample(base, rule)

        daily = out.get("1d")
        if daily is not None and not daily.empty:
            out["1wk"] = self._weekly(daily)

        return out

    def _weekly(self, daily: pd.DataFrame) -> pd.DataFrame:
        # friday-labelled weekly candle spanning the broker mon to fri week
        return pd.DataFrame({
            "Open": daily["Open"].resample("W-FRI").first(),
            "High": daily["High"].resample("W-FRI").max(),
            "Low": daily["Low"].resample("W-FRI").min(),
            "Close": daily["Close"].resample("W-FRI").last(),
        }).dropna()

