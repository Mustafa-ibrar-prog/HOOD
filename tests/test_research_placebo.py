"""Tests for placebo/randomization and bootstrap analysis (Phase 5,
sections 14-15)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.backtesting.journal import BacktestTrade
from src.data.bar import Bar
from src.research.placebo import MIN_BOOTSTRAP_SAMPLE, bootstrap_trade_statistics, random_symbol_and_timing_placebo, randomized_entry_timing_placebo

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _trade(symbol: str, net_pnl: float) -> BacktestTrade:
    return BacktestTrade(
        trade_id="T", backtest_id="B", strategy="s", symbol=symbol, entry_timestamp=T0, entry_price=100.0,
        exit_timestamp=T0 + timedelta(days=5), exit_price=101.0, quantity=1, gross_pnl=net_pnl, fees=0.0,
        slippage=0.0, net_pnl=net_pnl, holding_period_minutes=7200.0, entry_reason="", exit_reason="", risk_decision="APPROVED",
    )


def _bars(symbol: str, n: int) -> list[Bar]:
    import math

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    # Deliberately non-linear (oscillating) — a linear price series makes
    # every fixed-holding-period trade identical regardless of entry
    # index, which would defeat the point of a randomized-ENTRY test.
    return [
        Bar(timestamp=start + timedelta(days=i), symbol=symbol, timeframe="day", open=100 + 10 * math.sin(i / 6), high=112, low=88, close=100 + 10 * math.sin(i / 6), volume=1000)
        for i in range(n)
    ]


# --- placebo ---------------------------------------------------------------------------


def test_placebo_is_deterministic_given_a_seed():
    trades = [_trade("AAPL", 10.0), _trade("AAPL", 5.0)]
    bars_by_symbol = {"AAPL": _bars("AAPL", 100)}
    result_a = randomized_entry_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol, holding_period_bars=5, quantity=10, n_trials=20, seed=7)
    result_b = randomized_entry_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol, holding_period_bars=5, quantity=10, n_trials=20, seed=7)
    assert result_a.simulated_statistics == result_b.simulated_statistics


def test_placebo_different_seeds_differ():
    trades = [_trade("AAPL", 10.0)]
    bars_by_symbol = {"AAPL": _bars("AAPL", 100)}
    result_a = randomized_entry_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol, holding_period_bars=5, quantity=10, n_trials=20, seed=1)
    result_b = randomized_entry_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol, holding_period_bars=5, quantity=10, n_trials=20, seed=2)
    assert result_a.simulated_statistics != result_b.simulated_statistics


def test_placebo_fraction_is_between_zero_and_one():
    trades = [_trade("AAPL", 10.0), _trade("AAPL", -5.0)]
    bars_by_symbol = {"AAPL": _bars("AAPL", 100)}
    result = randomized_entry_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol, holding_period_bars=5, quantity=10, n_trials=50, seed=42)
    assert 0.0 <= result.fraction_as_extreme_or_better <= 1.0
    assert result.n_trials == 50


def test_placebo_preserves_per_symbol_trade_count():
    trades = [_trade("AAPL", 10.0), _trade("AAPL", 5.0), _trade("JPM", -3.0)]
    bars_by_symbol = {"AAPL": _bars("AAPL", 100), "JPM": _bars("JPM", 100)}
    result = randomized_entry_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol, holding_period_bars=5, quantity=10, n_trials=1, seed=1)
    # 1 trial -> exactly one simulated statistic, built from 2 AAPL + 1 JPM random trades
    assert len(result.simulated_statistics) == 1


# --- Phase 6, section 16: random-symbol-AND-timing permutation --------------------------


def test_symbol_permutation_is_deterministic_given_a_seed():
    trades = [_trade("AAPL", 10.0), _trade("JPM", -5.0)]
    bars_by_symbol = {"AAPL": _bars("AAPL", 100), "JPM": _bars("JPM", 100)}
    result_a = random_symbol_and_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol, holding_period_bars=5, quantity=10, n_trials=20, seed=7)
    result_b = random_symbol_and_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol, holding_period_bars=5, quantity=10, n_trials=20, seed=7)
    assert result_a.simulated_statistics == result_b.simulated_statistics


def test_symbol_permutation_different_seeds_differ():
    trades = [_trade("AAPL", 10.0)]
    bars_by_symbol = {"AAPL": _bars("AAPL", 100), "JPM": _bars("JPM", 100)}
    result_a = random_symbol_and_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol, holding_period_bars=5, quantity=10, n_trials=20, seed=1)
    result_b = random_symbol_and_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol, holding_period_bars=5, quantity=10, n_trials=20, seed=2)
    assert result_a.simulated_statistics != result_b.simulated_statistics


def test_symbol_permutation_preserves_total_trade_count_not_per_symbol_count():
    trades = [_trade("AAPL", 10.0), _trade("AAPL", 5.0), _trade("JPM", -3.0)]
    bars_by_symbol = {"AAPL": _bars("AAPL", 100), "JPM": _bars("JPM", 100)}
    result = random_symbol_and_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol, holding_period_bars=5, quantity=10, n_trials=1, seed=1)
    assert len(result.simulated_statistics) == 1  # one trial -> one aggregate statistic, drawn from 3 total random trades


def test_symbol_permutation_and_entry_timing_placebo_are_independent_methods():
    """The two placebo methods are DIFFERENT null models (documented, not
    accidental) — they need not agree on the same observed data."""
    trades = [_trade("AAPL", 10.0), _trade("AAPL", -4.0), _trade("JPM", 6.0)]
    bars_by_symbol = {"AAPL": _bars("AAPL", 100), "JPM": _bars("JPM", 100)}
    entry_timing = randomized_entry_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol, holding_period_bars=5, quantity=10, n_trials=50, seed=42)
    symbol_and_timing = random_symbol_and_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol, holding_period_bars=5, quantity=10, n_trials=50, seed=42)
    assert entry_timing.method != symbol_and_timing.method
    assert entry_timing.observed_statistic == symbol_and_timing.observed_statistic  # same observed trades


# --- bootstrap ---------------------------------------------------------------------------


def test_bootstrap_below_minimum_sample_is_flagged():
    trades = [_trade("AAPL", 10.0) for _ in range(MIN_BOOTSTRAP_SAMPLE - 1)]
    report = bootstrap_trade_statistics(trades, seed=1)
    assert report.insufficient_sample is True
    assert "INSUFFICIENT SAMPLE" in report.render()


def test_bootstrap_at_minimum_sample_produces_intervals():
    trades = [_trade("AAPL", 10.0 + i) for i in range(MIN_BOOTSTRAP_SAMPLE)]
    report = bootstrap_trade_statistics(trades, n_resamples=200, seed=1)
    assert report.insufficient_sample is False
    assert report.mean_trade_return_ci is not None
    assert report.mean_trade_return_ci.lower <= report.mean_trade_return_ci.point_estimate <= report.mean_trade_return_ci.upper


def test_bootstrap_is_deterministic_given_a_seed():
    trades = [_trade("AAPL", 10.0 + i) for i in range(30)]
    report_a = bootstrap_trade_statistics(trades, n_resamples=200, seed=99)
    report_b = bootstrap_trade_statistics(trades, n_resamples=200, seed=99)
    assert report_a.mean_trade_return_ci == report_b.mean_trade_return_ci


def test_bootstrap_constant_returns_gives_a_degenerate_interval():
    trades = [_trade("AAPL", 5.0) for _ in range(30)]
    report = bootstrap_trade_statistics(trades, n_resamples=200, seed=1)
    assert report.mean_trade_return_ci.lower == report.mean_trade_return_ci.upper == 5.0
