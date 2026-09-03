"""Phase 19, Part 19 — causal option moneyness tests."""

from __future__ import annotations

import math

import pytest

from src.options.moneyness import (
    MoneynessBucket,
    MoneynessObservation,
    classify_moneyness,
    log_moneyness,
    moneyness_ratio,
)


def test_log_moneyness_at_the_money_is_zero():
    assert log_moneyness(100.0, 100.0) == pytest.approx(0.0)


def test_log_moneyness_matches_formula():
    assert log_moneyness(110.0, 100.0) == pytest.approx(math.log(1.1))


def test_log_moneyness_rejects_nonpositive_inputs():
    with pytest.raises(ValueError):
        log_moneyness(0.0, 100.0)
    with pytest.raises(ValueError):
        log_moneyness(100.0, -5.0)


def test_moneyness_ratio():
    assert moneyness_ratio(120.0, 100.0) == pytest.approx(1.2)


def test_call_deep_itm():
    assert classify_moneyness(200.0, 100.0, "call") == MoneynessBucket.DEEP_ITM


def test_call_deep_otm():
    assert classify_moneyness(50.0, 100.0, "call") == MoneynessBucket.DEEP_OTM


def test_put_deep_itm_is_when_underlying_below_strike():
    assert classify_moneyness(50.0, 100.0, "put") == MoneynessBucket.DEEP_ITM


def test_put_deep_otm_is_when_underlying_above_strike():
    assert classify_moneyness(200.0, 100.0, "put") == MoneynessBucket.DEEP_OTM


def test_near_atm_symmetric_for_call_and_put():
    assert classify_moneyness(100.5, 100.0, "call") == MoneynessBucket.NEAR_ATM
    assert classify_moneyness(100.5, 100.0, "put") == MoneynessBucket.NEAR_ATM


def test_invalid_call_put_rejected():
    with pytest.raises(ValueError):
        classify_moneyness(100.0, 100.0, "both")


def test_moneyness_observation_compute():
    obs = MoneynessObservation.compute(underlying_price=110.0, strike=100.0, call_put="call")
    assert obs.bucket in (MoneynessBucket.ITM, MoneynessBucket.DEEP_ITM)
    assert obs.log_moneyness_value == pytest.approx(math.log(1.1))
    assert obs.moneyness_ratio_value == pytest.approx(1.1)
