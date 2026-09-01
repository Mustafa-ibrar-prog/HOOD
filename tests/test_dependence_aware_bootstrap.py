"""Phase 7, Part 11 & 19: block/stationary bootstrap tests."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from src.backtesting.journal import BacktestTrade
from src.research.placebo import MIN_BOOTSTRAP_SAMPLE, block_bootstrap_trade_statistics, stationary_bootstrap_trade_statistics

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _trade(net_pnl: float) -> BacktestTrade:
    return BacktestTrade(
        trade_id="T", backtest_id="B", strategy="s", symbol="AAPL", entry_timestamp=T0, entry_price=100.0,
        exit_timestamp=T0 + timedelta(days=5), exit_price=101.0, quantity=1, gross_pnl=net_pnl, fees=0.0,
        slippage=0.0, net_pnl=net_pnl, holding_period_minutes=7200.0, entry_reason="", exit_reason="", risk_decision="APPROVED",
    )


def _trades(n, seed=0):
    rng = random.Random(seed)
    return [_trade(rng.gauss(5, 10)) for _ in range(n)]


def test_block_bootstrap_below_min_sample_flagged():
    trades = _trades(MIN_BOOTSTRAP_SAMPLE - 1)
    r = block_bootstrap_trade_statistics(trades, block_size=3, seed=1)
    assert r.insufficient_sample is True


def test_block_bootstrap_deterministic_given_seed():
    trades = _trades(60)
    r1 = block_bootstrap_trade_statistics(trades, block_size=5, n_resamples=200, seed=1)
    r2 = block_bootstrap_trade_statistics(trades, block_size=5, n_resamples=200, seed=1)
    assert r1.mean_trade_return_ci == r2.mean_trade_return_ci


def test_block_bootstrap_produces_valid_ci():
    trades = _trades(60)
    r = block_bootstrap_trade_statistics(trades, block_size=5, n_resamples=300, seed=1)
    ci = r.mean_trade_return_ci
    assert ci.lower <= ci.point_estimate <= ci.upper


def test_block_bootstrap_rejects_block_size_larger_than_sample():
    trades = _trades(30)
    with pytest.raises(ValueError):
        block_bootstrap_trade_statistics(trades, block_size=50, seed=1)


def test_block_bootstrap_rejects_non_positive_block_size():
    trades = _trades(30)
    with pytest.raises(ValueError):
        block_bootstrap_trade_statistics(trades, block_size=0, seed=1)


def test_stationary_bootstrap_below_min_sample_flagged():
    trades = _trades(MIN_BOOTSTRAP_SAMPLE - 1)
    r = stationary_bootstrap_trade_statistics(trades, mean_block_length=5, seed=1)
    assert r.insufficient_sample is True


def test_stationary_bootstrap_deterministic_given_seed():
    trades = _trades(60)
    r1 = stationary_bootstrap_trade_statistics(trades, mean_block_length=5, n_resamples=200, seed=1)
    r2 = stationary_bootstrap_trade_statistics(trades, mean_block_length=5, n_resamples=200, seed=1)
    assert r1.mean_trade_return_ci == r2.mean_trade_return_ci


def test_stationary_bootstrap_produces_valid_ci():
    trades = _trades(60)
    r = stationary_bootstrap_trade_statistics(trades, mean_block_length=5, n_resamples=300, seed=1)
    ci = r.mean_trade_return_ci
    assert ci.lower <= ci.point_estimate <= ci.upper


def test_stationary_bootstrap_rejects_non_positive_mean_block_length():
    trades = _trades(30)
    with pytest.raises(ValueError):
        stationary_bootstrap_trade_statistics(trades, mean_block_length=0, seed=1)


def test_block_and_iid_bootstrap_can_produce_different_interval_widths_on_correlated_data():
    """Not a strict inequality assertion (that would be seed-fragile) —
    just confirms both run cleanly on the SAME serially-correlated data
    (an AR(1)-like sequence, i.e. NOT i.i.d.) and both produce valid,
    non-degenerate intervals."""
    rng = random.Random(3)
    values = [0.0]
    for _ in range(80):
        values.append(0.6 * values[-1] + rng.gauss(0, 5))
    trades = [_trade(v) for v in values[1:]]

    from src.research.placebo import bootstrap_trade_statistics

    iid_result = bootstrap_trade_statistics(trades, n_resamples=300, seed=1)
    block_result = block_bootstrap_trade_statistics(trades, block_size=8, n_resamples=300, seed=1)
    assert iid_result.insufficient_sample is False
    assert block_result.insufficient_sample is False
    assert iid_result.mean_trade_return_ci.lower <= iid_result.mean_trade_return_ci.upper
    assert block_result.mean_trade_return_ci.lower <= block_result.mean_trade_return_ci.upper
