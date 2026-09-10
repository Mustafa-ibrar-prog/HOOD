"""Phase 42 -- deterministic, bounded near-the-money strike targeting.
Covers 'option pagination' / 'current-price strike coverage' from the
Phase 42 test list."""

from __future__ import annotations

import pytest

from src.paper_trading.near_the_money import compute_target_strikes, infer_common_strike_increment


def test_infer_increment_bands_are_monotonic_and_positive():
    prices = [1, 10, 24.99, 25, 50, 99.99, 100, 300, 499.99, 500, 1000]
    increments = [infer_common_strike_increment(p) for p in prices]
    assert all(i > 0 for i in increments)
    assert increments == sorted(increments)  # coarser increments for higher prices, never finer


def test_infer_increment_rejects_non_positive_price():
    with pytest.raises(ValueError):
        infer_common_strike_increment(0)
    with pytest.raises(ValueError):
        infer_common_strike_increment(-5)


def test_target_strikes_include_the_nearest_the_money_strike():
    plan = compute_target_strikes(332.95)
    nearest = min(plan.strikes, key=lambda s: abs(s - 332.95))
    assert nearest == 330.0 or nearest == 335.0  # $5 increment, both equally near-ish


def test_target_strikes_matches_real_observed_googl_strikes_from_phase41():
    """Regression: Phase 41's real automatic cycle (2026-09-10-slot0024)
    manually targeted GOOGL strikes 330/335 at a $332.95 price -- this
    formalized function must reproduce (a superset of) that."""
    plan = compute_target_strikes(332.95, max_strikes=2)
    assert set(plan.strikes) == {330.0, 335.0}


def test_target_strikes_matches_real_observed_nvda_strikes_from_phase41():
    plan = compute_target_strikes(218.65, max_strikes=2)
    assert set(plan.strikes) == {215.0, 220.0}


def test_target_strikes_are_bounded_by_max_strikes():
    plan = compute_target_strikes(709.26, max_strikes=4)
    assert len(plan.strikes) <= 4


def test_target_strikes_never_unbounded_even_with_a_huge_moneyness_band():
    plan = compute_target_strikes(500.0, moneyness_band=5.0, max_strikes=6)
    assert len(plan.strikes) <= 6


def test_target_strikes_all_within_the_configured_moneyness_band():
    price = 218.65
    band = 0.10
    plan = compute_target_strikes(price, moneyness_band=band, max_strikes=20)
    low, high = price * (1 - band), price * (1 + band)
    assert all(low <= s <= high for s in plan.strikes)


def test_target_strikes_are_ascending_and_unique():
    plan = compute_target_strikes(75.9, max_strikes=6)
    assert list(plan.strikes) == sorted(set(plan.strikes))


def test_target_strikes_respects_an_explicit_strike_increment_override():
    plan = compute_target_strikes(100.0, strike_increment=1.0, max_strikes=4)
    assert plan.strike_increment == 1.0
    assert all(s == round(s) for s in plan.strikes)  # whole-dollar strikes at a $1 increment


def test_target_strikes_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        compute_target_strikes(0)
    with pytest.raises(ValueError):
        compute_target_strikes(100, moneyness_band=0)
    with pytest.raises(ValueError):
        compute_target_strikes(100, max_strikes=0)
    with pytest.raises(ValueError):
        compute_target_strikes(100, strike_increment=0)


def test_low_priced_underlying_gets_a_fine_grained_increment():
    plan = compute_target_strikes(18.5, max_strikes=6)
    assert plan.strike_increment == 1.0


def test_high_priced_underlying_gets_a_coarse_increment():
    plan = compute_target_strikes(758.12, max_strikes=6)
    assert plan.strike_increment == 10.0
