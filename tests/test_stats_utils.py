from __future__ import annotations

import math

from src.research.stats_utils import normal_cdf, sharpe_ratio_from_returns, t_statistic, t_test_p_value, two_tailed_p_value_from_z


def test_normal_cdf_at_zero_is_half():
    assert abs(normal_cdf(0.0) - 0.5) < 1e-9


def test_normal_cdf_is_monotonic():
    assert normal_cdf(-2) < normal_cdf(-1) < normal_cdf(0) < normal_cdf(1) < normal_cdf(2)


def test_two_tailed_p_value_at_z_zero_is_one():
    assert abs(two_tailed_p_value_from_z(0.0) - 1.0) < 1e-9


def test_two_tailed_p_value_shrinks_as_z_grows():
    assert two_tailed_p_value_from_z(1.0) > two_tailed_p_value_from_z(2.0) > two_tailed_p_value_from_z(3.0)


def test_t_statistic_none_for_single_value():
    assert t_statistic([1.0]) is None


def test_t_statistic_none_for_zero_variance():
    assert t_statistic([5.0, 5.0, 5.0]) is None


def test_t_statistic_positive_for_positive_mean():
    assert t_statistic([1.0, 2.0, 3.0, 4.0, 5.0]) > 0


def test_t_test_p_value_small_for_strong_consistent_signal():
    values = [1.0] * 50  # zero variance -> t_statistic is None -> p_value None
    assert t_test_p_value(values) is None
    values2 = [1.0 + 0.01 * ((-1) ** i) for i in range(50)]
    p = t_test_p_value(values2)
    assert p is not None and p < 0.01


def test_sharpe_ratio_from_returns_matches_manual_calculation():
    returns = [0.01, -0.005, 0.02, 0.0, 0.015]
    sr = sharpe_ratio_from_returns(returns, periods_per_year=252)
    from src.research.analysis import mean, stdev
    expected = (mean(returns) / stdev(returns)) * math.sqrt(252)
    assert abs(sr - expected) < 1e-9
