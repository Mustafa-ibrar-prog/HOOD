"""Phase 7, Part 5 & 19: PBO, DSR, effective-trials tests."""

from __future__ import annotations

import random

from src.research.overfitting_metrics import (
    _inverse_normal_cdf,
    deflated_sharpe_ratio,
    effective_number_of_trials,
    probability_of_backtest_overfitting,
)
from src.research.stats_utils import normal_cdf


def test_inverse_normal_cdf_round_trips_normal_cdf():
    for p in (0.001, 0.01, 0.1, 0.5, 0.9, 0.99, 0.999):
        z = _inverse_normal_cdf(p)
        assert abs(normal_cdf(z) - p) < 1e-6


# --- PBO -------------------------------------------------------------------------------


def test_pbo_not_applicable_below_two_variants():
    r = probability_of_backtest_overfitting([[1, 2, 3, 4]])
    assert r.applicable is False
    assert "variant" in r.reason


def test_pbo_not_applicable_with_odd_periods():
    r = probability_of_backtest_overfitting([[1, 2, 3, 4, 5], [6, 7, 8, 9, 10]])  # 5 periods: >= min_periods, but odd
    assert r.applicable is False
    assert "even" in r.reason.lower()


def test_pbo_not_applicable_below_min_periods():
    r = probability_of_backtest_overfitting([[1, 2], [3, 4]], min_periods=4)
    assert r.applicable is False


def test_pbo_near_half_for_pure_noise_variants():
    random.seed(1)
    noise = [[random.gauss(0, 1) for _ in range(8)] for _ in range(10)]
    r = probability_of_backtest_overfitting(noise)
    assert r.applicable is True
    assert 0.2 <= r.pbo <= 0.8  # loose bound — pure noise should be roughly coin-flip, not a tight assertion on a random seed


def test_pbo_near_zero_for_one_consistently_dominant_variant():
    random.seed(2)
    variants = [[random.gauss(0, 1) for _ in range(8)] for _ in range(9)]
    variants.append([10.0 + random.gauss(0, 0.01) for _ in range(8)])  # always wins, huge margin
    r = probability_of_backtest_overfitting(variants)
    assert r.pbo == 0.0


def test_pbo_variants_must_share_period_count():
    r = probability_of_backtest_overfitting([[1, 2, 3, 4], [1, 2, 3, 4, 5, 6]])
    assert r.applicable is False


# --- Deflated Sharpe Ratio ---------------------------------------------------------------


def test_dsr_not_applicable_below_min_observations():
    r = deflated_sharpe_ratio([0.01] * 10, n_trials=5)
    assert r.applicable is False


def test_dsr_not_applicable_below_two_trials():
    random.seed(3)
    returns = [random.gauss(0.001, 0.01) for _ in range(100)]
    r = deflated_sharpe_ratio(returns, n_trials=1)
    assert r.applicable is False


def test_dsr_not_applicable_zero_variance():
    r = deflated_sharpe_ratio([0.01] * 40, n_trials=5)
    assert r.applicable is False


def test_dsr_decreases_as_number_of_trials_grows():
    """The central point of deflation: the SAME observed return series
    looks less impressive the more trials were searched to find it."""
    random.seed(7)
    returns = [random.gauss(0.0008, 0.01) for _ in range(300)]
    dsr_few = deflated_sharpe_ratio(returns, n_trials=2)
    dsr_many = deflated_sharpe_ratio(returns, n_trials=5000)
    assert dsr_few.applicable and dsr_many.applicable
    assert dsr_many.deflated_sharpe_ratio <= dsr_few.deflated_sharpe_ratio


def test_dsr_result_in_valid_probability_range():
    random.seed(9)
    returns = [random.gauss(0.0005, 0.01) for _ in range(200)]
    r = deflated_sharpe_ratio(returns, n_trials=50)
    if r.applicable:
        assert 0.0 <= r.deflated_sharpe_ratio <= 1.0


def test_dsr_reproducible_given_same_inputs():
    random.seed(11)
    returns = [random.gauss(0.0006, 0.012) for _ in range(150)]
    r1 = deflated_sharpe_ratio(returns, n_trials=100)
    r2 = deflated_sharpe_ratio(returns, n_trials=100)
    assert r1.deflated_sharpe_ratio == r2.deflated_sharpe_ratio


# --- effective number of trials -----------------------------------------------------------


def test_effective_trials_not_applicable_below_two_variants():
    r = effective_number_of_trials([[1, 2, 3]])
    assert r.applicable is False


def test_effective_trials_near_one_for_identical_variants():
    same = [[1.0, 2.0, 3.0, 4.0, 5.0]] * 5
    r = effective_number_of_trials(same)
    assert r.applicable is True
    assert abs(r.effective_trials - 1.0) < 1e-6


def test_effective_trials_near_nominal_for_uncorrelated_variants():
    random.seed(13)
    variants = [[random.gauss(0, 1) for _ in range(200)] for _ in range(5)]
    r = effective_number_of_trials(variants)
    assert r.applicable is True
    assert r.effective_trials > 3.0  # should stay close to the nominal 5, well above the fully-correlated floor of 1
