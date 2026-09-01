"""Tests for performance metrics (Phase 3, section 14), against hand-
verifiable synthetic data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.backtesting.journal import BacktestTrade
from src.backtesting.metrics import compute_benchmark_comparison, compute_performance_metrics
from src.backtesting.portfolio import EquityPoint


def _point(day: int, equity: float, *, peak: float | None = None) -> EquityPoint:
    peak = peak if peak is not None else equity
    drawdown = equity - peak
    drawdown_pct = drawdown / peak if peak > 0 else 0.0
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
    return EquityPoint(timestamp=ts, equity=equity, cash=equity, positions_value=0.0, gross_exposure=0.0, net_exposure=0.0, drawdown=drawdown, drawdown_pct=drawdown_pct)


def _trade(net_pnl: float, **overrides) -> BacktestTrade:
    defaults = dict(
        trade_id="TR", backtest_id="BT", strategy="s", symbol="AAPL",
        entry_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), entry_price=100.0,
        exit_timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc), exit_price=101.0,
        quantity=1, gross_pnl=net_pnl, fees=0.0, slippage=0.0, net_pnl=net_pnl,
        holding_period_minutes=1440.0, entry_reason="", exit_reason="", risk_decision="APPROVED",
    )
    defaults.update(overrides)
    return BacktestTrade(**defaults)


def test_total_return_matches_simple_arithmetic():
    curve = [_point(0, 10_000, peak=10_000), _point(1, 11_000, peak=11_000)]
    metrics = compute_performance_metrics(equity_curve=curve, trades=[], starting_cash=10_000)
    assert metrics.returns.total_return_pct == pytest.approx(10.0)


def test_max_drawdown_detected_correctly():
    curve = [_point(0, 10_000, peak=10_000), _point(1, 12_000, peak=12_000), _point(2, 9_000, peak=12_000)]
    metrics = compute_performance_metrics(equity_curve=curve, trades=[], starting_cash=10_000)
    assert metrics.drawdown.max_drawdown_pct == pytest.approx((9_000 - 12_000) / 12_000 * 100)
    assert metrics.drawdown.max_drawdown_usd == pytest.approx(-3_000)


def test_no_drawdown_when_equity_only_rises():
    curve = [_point(i, 10_000 + i * 100, peak=10_000 + i * 100) for i in range(5)]
    metrics = compute_performance_metrics(equity_curve=curve, trades=[], starting_cash=10_000)
    assert metrics.drawdown.max_drawdown_pct == pytest.approx(0.0)
    assert metrics.drawdown.max_drawdown_duration_bars == 0


def test_trade_statistics_win_rate_and_profit_factor():
    trades = [_trade(100.0), _trade(50.0), _trade(-30.0)]
    metrics = compute_performance_metrics(equity_curve=[], trades=trades, starting_cash=10_000)
    stats = metrics.trades
    assert stats.trade_count == 3
    assert stats.winning_trades == 2
    assert stats.losing_trades == 1
    assert stats.win_rate == pytest.approx(2 / 3)
    assert stats.average_win == pytest.approx(75.0)
    assert stats.average_loss == pytest.approx(-30.0)
    assert stats.largest_win == pytest.approx(100.0)
    assert stats.largest_loss == pytest.approx(-30.0)
    assert stats.profit_factor == pytest.approx(150.0 / 30.0)
    assert stats.expectancy == pytest.approx((100 + 50 - 30) / 3)


def test_trade_statistics_empty_trades_is_safe():
    metrics = compute_performance_metrics(equity_curve=[], trades=[], starting_cash=10_000)
    assert metrics.trades.trade_count == 0
    assert metrics.trades.profit_factor is None


def test_profit_factor_none_when_no_losses():
    trades = [_trade(100.0), _trade(50.0)]
    metrics = compute_performance_metrics(equity_curve=[], trades=trades, starting_cash=10_000)
    assert metrics.trades.profit_factor is None  # gross_loss == 0 -> undefined, not fabricated infinity


def test_max_losing_streak():
    trades = [_trade(10.0), _trade(-5.0), _trade(-5.0), _trade(-5.0), _trade(10.0)]
    metrics = compute_performance_metrics(equity_curve=[], trades=trades, starting_cash=10_000)
    assert metrics.loss_analysis.max_losing_streak == 3


def test_portfolio_exposure_and_concentration():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    point = EquityPoint(
        timestamp=ts, equity=10_000, cash=2_000, positions_value=8_000, gross_exposure=8_000, net_exposure=8_000,
        drawdown=0.0, drawdown_pct=0.0, open_position_count=2, position_weights={"AAPL": 0.5, "SOFI": 0.3},
    )
    metrics = compute_performance_metrics(equity_curve=[point], trades=[], starting_cash=10_000)
    assert metrics.portfolio.average_exposure_pct == pytest.approx(80.0)
    assert metrics.portfolio.max_concurrent_positions == 2
    assert metrics.portfolio.max_concentration_pct == pytest.approx(50.0)


def test_benchmark_comparison_computes_excess_return():
    strategy_curve = [_point(0, 10_000, peak=10_000), _point(1, 11_000, peak=11_000)]
    benchmark_curve = [_point(0, 10_000, peak=10_000), _point(1, 10_500, peak=10_500)]
    comparison = compute_benchmark_comparison(
        benchmark_symbol="SPY", benchmark_curve=benchmark_curve, strategy_curve=strategy_curve, starting_cash=10_000
    )
    assert comparison.strategy_total_return_pct == pytest.approx(10.0)
    assert comparison.benchmark_total_return_pct == pytest.approx(5.0)
    assert comparison.excess_return_pct == pytest.approx(5.0)


def test_benchmark_comparison_none_on_empty_curves():
    assert compute_benchmark_comparison(benchmark_symbol="SPY", benchmark_curve=[], strategy_curve=[], starting_cash=10_000) is None
