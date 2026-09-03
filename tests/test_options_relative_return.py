"""Phase 22, Part 6 (Theme A/D) — OPTION_UNDERLYING_RELATIVE_RETURN:
rolling_beta (an empirical realized slope, explicitly NOT a Greek),
naive_excess_return, and beta_scaled_excess_return."""

from __future__ import annotations

import pytest

from src.options.relative_return import beta_scaled_excess_return, naive_excess_return, rolling_beta


def test_rolling_beta_recovers_exact_slope_for_a_perfect_linear_relationship():
    # option_return = 2.0 * underlying_return, exactly, every period
    underlying = [0.01, -0.02, 0.03, -0.01, 0.02, 0.015, -0.005]
    option = [2.0 * u for u in underlying]
    out = rolling_beta(option, underlying, 4)
    assert out[0] is None and out[1] is None and out[2] is None
    assert out[3] == pytest.approx(2.0, abs=1e-9)
    assert out[-1] == pytest.approx(2.0, abs=1e-9)


def test_rolling_beta_none_before_window():
    out = rolling_beta([0.01, 0.02], [0.01, 0.02], 3)
    assert out == [None, None]


def test_rolling_beta_none_on_missing_observation_in_window():
    option = [0.01, 0.02, None, 0.03]
    underlying = [0.01, 0.02, 0.03, 0.03]
    out = rolling_beta(option, underlying, 3)
    assert out[2] is None  # window would need index 2 which needs indices 0,1,2 -- but window at i=2 needs i>=window-1=2
    assert out[3] is None  # window [1,2,3] includes the None at index 2


def test_rolling_beta_none_for_degenerate_flat_underlying():
    option = [0.01, 0.02, -0.01, 0.03]
    underlying = [0.0, 0.0, 0.0, 0.0]  # zero variance
    out = rolling_beta(option, underlying, 3)
    assert out[2] is None
    assert out[3] is None


def test_rolling_beta_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        rolling_beta([1.0], [1.0, 2.0], 2)


def test_rolling_beta_rejects_small_window():
    with pytest.raises(ValueError):
        rolling_beta([1.0, 2.0], [1.0, 2.0], 1)


def test_naive_excess_return_is_plain_subtraction():
    assert naive_excess_return(0.05, 0.02) == pytest.approx(0.03)
    assert naive_excess_return(-0.01, -0.03) == pytest.approx(0.02)


def test_naive_excess_return_none_propagates():
    assert naive_excess_return(None, 0.02) is None
    assert naive_excess_return(0.05, None) is None


def test_beta_scaled_excess_return_matches_manual_computation():
    assert beta_scaled_excess_return(0.10, 0.03, 2.0) == pytest.approx(0.10 - 2.0 * 0.03)


def test_beta_scaled_excess_return_none_propagates():
    assert beta_scaled_excess_return(None, 0.02, 1.0) is None
    assert beta_scaled_excess_return(0.05, None, 1.0) is None
    assert beta_scaled_excess_return(0.05, 0.02, None) is None


def test_beta_scaled_excess_return_reduces_to_naive_when_beta_is_one():
    opt, und = 0.07, 0.02
    assert beta_scaled_excess_return(opt, und, 1.0) == pytest.approx(naive_excess_return(opt, und))
