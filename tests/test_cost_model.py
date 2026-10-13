from __future__ import annotations

import pytest

from fxresearch.costs.cost_model import RAW, CostModel


def test_standard_cost_is_spread_over_risk() -> None:
    assert CostModel().cost_r("EURUSD", 10.0) == pytest.approx(0.52 / 10.0)


def test_raw_cost_adds_a_fixed_commission() -> None:
    assert CostModel().cost_r("EURUSD", 10.0, account=RAW) == pytest.approx((0.52 * 1.1 + 0.70) / 10.0)


def test_cost_multiplier_scales_only_the_spread_on_raw() -> None:
    model = CostModel()
    assert model.cost_r("USDJPY", 20.0, 1.5, RAW) == pytest.approx((1.00 * 1.1 * 1.5 + 1.05) / 20.0)


def test_tighter_stops_pay_more_cost_in_r() -> None:
    model = CostModel()
    assert model.cost_r("GBPJPY", 10.0) > model.cost_r("GBPJPY", 40.0)


def test_unknown_instrument_and_zero_risk() -> None:
    model = CostModel()
    assert model.cost_r("ABCXYZ", 10.0) == pytest.approx(1.5 / 10.0)
    assert model.cost_r("EURUSD", 0.0) == 0.0
