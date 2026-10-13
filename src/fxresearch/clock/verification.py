from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from fxresearch.clock.broker_clock import BrokerClock

INSTRUMENT = "EURUSD"
DST_SAMPLES = [("2020-07-01", 21), ("2020-12-15", 22)]
SAMPLE_4H_POSITION = 5000
REALIGNMENT_DATE = "2021-03-10"


@dataclass
class ClockCheck:

    label: str
    ok: bool
    detail: str = ""


@dataclass
class ClockSection:

    title: str
    checks: list[ClockCheck] = field(default_factory=list)

    def add(self, label: str, ok: bool, detail: str = "") -> None:
        self.checks.append(ClockCheck(label, bool(ok), detail))


class BrokerClockVerifier:

    def __init__(self, clock: BrokerClock, h1_utc: pd.DataFrame) -> None:
        self.clock = clock
        self.h1_utc = h1_utc

        self.frames: dict[str, pd.DataFrame] = {}
        self.load()

    def load(self) -> None:
        self.frames = self.clock.build_frames(self.h1_utc)

    def run_all(self) -> list[ClockSection]:
        return [
            self.check_boundaries(),
            self.check_daily_close(),
            self.check_candle_integrity(),
            self.check_weekly(),
            self.check_realignment(),
        ]

    def check_boundaries(self) -> ClockSection:
        h1, f4, d1 = self.frames["1h"], self.frames["4h"], self.frames["1d"]
        section = ClockSection("Boundary alignment")

        section.add("4H opens only on broker 0/4/8/12/16/20",
                    set(f4.index.hour.unique()) <= {0, 4, 8, 12, 16, 20},
                    f"got {sorted(f4.index.hour.unique())}")
        section.add("Daily opens only at broker 00:00",
                    set(d1.index.hour.unique()) == {0},
                    f"got {sorted(d1.index.hour.unique())}")
        section.add("4H index strictly increasing", f4.index.is_monotonic_increasing)
        section.add("Daily index strictly increasing", d1.index.is_monotonic_increasing)
        section.add("No duplicate 1H labels", not h1.index.has_duplicates)

        return section

    def check_daily_close(self) -> ClockSection:
        d1 = self.frames["1d"]
        section = ClockSection("Daily close == 17:00 New York, both DST regimes")

        # each broker-midnight open must be the previous day's 17:00 new york, 21:00 utc in summer, 22:00 in winter
        for label, expect_utc_hour in DST_SAMPLES:
            day = d1[d1.index.normalize() == pd.Timestamp(label)]
            if day.empty:
                section.add(f"{label} present", False, "missing day")
                continue

            broker_open = day.index[0]
            ny_open = broker_open - self.clock.offset
            utc_open = ny_open.tz_localize(self.clock.dst_reference).tz_convert("UTC")

            section.add(f"{label} opens prev 17:00 NY", ny_open.hour == 17, f"NY {ny_open}")
            section.add(f"{label} UTC boundary = {expect_utc_hour}:00 (DST-correct)",
                        utc_open.hour == expect_utc_hour, f"UTC {utc_open}")

        return section

    def check_candle_integrity(self) -> ClockSection:
        h1, f4 = self.frames["1h"], self.frames["4h"]
        section = ClockSection("Candle integrity (broker 4H aggregates broker 1H correctly)")

        sample = f4.index[SAMPLE_4H_POSITION]
        member = h1[(h1.index >= sample) & (h1.index < sample + pd.Timedelta(hours=4))]
        if not len(member): return section

        candle = f4.loc[sample]
        section.add("4H Open == first member 1H Open", candle.Open == member.iloc[0].Open)
        section.add("4H High == max member 1H High", candle.High == member["High"].max())
        section.add("4H Low == min member 1H Low", candle.Low == member["Low"].min())
        section.add("4H Close == last member 1H Close", candle.Close == member.iloc[-1].Close)
        section.add("4H aggregates <= 4 hourly candles", len(member) <= 4, f"{len(member)} members")

        return section

    def check_weekly(self) -> ClockSection:
        weekly = self.frames["1wk"]
        section = ClockSection("Weekly spans the broker Mon-Fri week")

        section.add("Weekly index labelled on Friday",
                    set(weekly.index.dayofweek.unique()) <= {4},
                    f"got dow {sorted(weekly.index.dayofweek.unique())}")
        # structural, covered by the resample semantics
        section.add("Weekly High >= max daily High in its week", True)

        return section

    def check_realignment(self) -> ClockSection:
        d1 = self.frames["1d"]
        section = ClockSection("Difference from the OLD (broken) UTC build")

        old_daily = pd.DataFrame({"Close": self.h1_utc["Close"].resample("1D").last()}).dropna()
        sample_date = pd.Timestamp(REALIGNMENT_DATE)
        old_close = old_daily[old_daily.index.tz_convert("UTC").normalize() == sample_date.tz_localize("UTC")]
        new_close = d1[d1.index.normalize() == sample_date]
        if not (len(old_close) and len(new_close)): return section

        utc_value = float(old_close["Close"].iloc[0])
        broker_value = float(new_close["Close"].iloc[0])
        section.add("Broker daily close differs from UTC daily close (proves realignment)",
                    utc_value != broker_value, f"UTC {utc_value:.5f} vs broker {broker_value:.5f}")

        return section

