"""Phase 11, Part 27, 28: block/stationary bootstrap on a return series."""

from __future__ import annotations

import pytest

from src.research.return_series_bootstrap import block_bootstrap_return_series, stationary_bootstrap_return_series


def _returns(n: int) -> list[float]:
    return [0.01 if i % 3 else -0.02 for i in range(n)]


def test_block_bootstrap_reports_a_ci_around_the_observed_mean():
    returns = _returns(60)
    report = block_bootstrap_return_series(returns, block_size=5, n_resamples=500, seed=1)
    assert not report.insufficient_sample
    assert report.sample_size == 60
    ci = report.mean_trade_return_ci
    assert ci is not None
    assert ci.lower <= ci.point_estimate <= ci.upper


def test_stationary_bootstrap_reports_a_ci():
    returns = _returns(60)
    report = stationary_bootstrap_return_series(returns, mean_block_length=5.0, n_resamples=500, seed=1)
    assert not report.insufficient_sample
    ci = report.sharpe_like_ci
    assert ci is not None
    assert ci.lower <= ci.point_estimate <= ci.upper


def test_insufficient_sample_reported_below_min():
    report = block_bootstrap_return_series([0.01, -0.01, 0.02], block_size=1, n_resamples=100, seed=1)
    assert report.insufficient_sample


def test_deterministic_given_seed():
    returns = _returns(50)
    r1 = block_bootstrap_return_series(returns, block_size=4, n_resamples=200, seed=99)
    r2 = block_bootstrap_return_series(returns, block_size=4, n_resamples=200, seed=99)
    assert r1 == r2


def test_block_size_larger_than_series_rejected():
    returns = _returns(30)
    with pytest.raises(ValueError):
        block_bootstrap_return_series(returns, block_size=31, n_resamples=100, seed=1)


def test_invalid_mean_block_length_rejected():
    with pytest.raises(ValueError):
        stationary_bootstrap_return_series(_returns(30), mean_block_length=0, n_resamples=100, seed=1)
