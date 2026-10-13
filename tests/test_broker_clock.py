from __future__ import annotations

import pandas as pd
import pytest

from markers import requires_data
from fxresearch.clock.broker_clock import BrokerClock
from fxresearch.clock.verification import INSTRUMENT, BrokerClockVerifier
from fxresearch.data.dukascopy import DukascopyHandler


def utc_bars(start: str, hours: int) -> pd.DataFrame:
    index = pd.date_range(start, periods=hours, freq="1h", tz="UTC")
    values = [float(i) for i in range(hours)]
    return pd.DataFrame({"Open": values, "High": [v + 0.5 for v in values],
                         "Low": [v - 0.5 for v in values], "Close": [v + 0.25 for v in values]}, index=index)


@pytest.mark.parametrize("utc_open, broker_open", [
    ("2020-06-30 21:00", "2020-07-01 00:00"),
    ("2020-12-14 22:00", "2020-12-15 00:00"),
])
def test_broker_midnight_is_17_new_york_in_both_dst_regimes(utc_open: str, broker_open: str) -> None:
    broker = BrokerClock().to_broker_time(utc_bars(utc_open, 1))
    assert broker.index[0] == pd.Timestamp(broker_open)


def test_four_hour_candles_anchor_to_broker_midnight() -> None:
    clock = BrokerClock()
    frames = clock.build_frames(utc_bars("2020-12-14 22:00", 8))
    four_h = frames["4h"]

    assert list(four_h.index.hour) == [0, 4]
    first = four_h.iloc[0]
    assert first.Open == 0.0
    assert first.High == 3.5
    assert first.Low == -0.5
    assert first.Close == 3.25


def test_naive_index_is_rejected() -> None:
    naive = utc_bars("2020-01-06 00:00", 2).tz_localize(None)
    with pytest.raises(ValueError):
        BrokerClock().to_broker_time(naive)


def test_weekly_candles_are_labelled_on_friday() -> None:
    weekly = BrokerClock().build_frames(utc_bars("2021-03-07 22:00", 24 * 12))["1wk"]
    assert set(weekly.index.dayofweek) == {4}


@requires_data
@pytest.mark.parametrize("section", ["check_boundaries", "check_daily_close", "check_candle_integrity",
                                     "check_weekly", "check_realignment"])
def test_broker_clock_on_real_data(section: str) -> None:
    verifier = BrokerClockVerifier(BrokerClock(), DukascopyHandler().load(INSTRUMENT, "h1"))
    result = getattr(verifier, section)()

    assert result.checks, f"{section} produced no checks"
    failed = [f"{check.label} ({check.detail})" for check in result.checks if not check.ok]
    assert not failed, failed
