"""Tests for leave-one-symbol/group-out analysis (Phase 5, section 10)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.backtesting.journal import BacktestTrade
from src.research.leave_one_out import leave_one_group_out, leave_one_symbol_out

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _trade(symbol: str, net_pnl: float) -> BacktestTrade:
    return BacktestTrade(
        trade_id="T", backtest_id="B", strategy="s", symbol=symbol, entry_timestamp=T0, entry_price=100.0,
        exit_timestamp=T0 + timedelta(days=1), exit_price=101.0, quantity=1, gross_pnl=net_pnl, fees=0.0,
        slippage=0.0, net_pnl=net_pnl, holding_period_minutes=1440.0, entry_reason="", exit_reason="", risk_decision="APPROVED",
    )


def test_removing_the_dominant_symbol_flips_the_sign():
    # AAPL alone accounts for all the positive P&L; without it, expectancy goes negative.
    trades = [_trade("AAPL", 1000.0)] + [_trade("JPM", -1.0) for _ in range(5)]
    report = leave_one_symbol_out(trades, starting_cash=10_000.0)
    assert "AAPL" in report.sign_flips_without
    assert report.max_expectancy_swing is not None
    assert report.max_expectancy_swing > 0


def test_evenly_distributed_result_has_no_sign_flips():
    trades = [_trade(s, 10.0) for s in ["AAPL", "JPM", "XOM", "MSFT", "GOOGL"]]
    report = leave_one_symbol_out(trades, starting_cash=10_000.0)
    assert report.sign_flips_without == ()


def test_leave_one_out_full_metrics_matches_all_trades():
    trades = [_trade("AAPL", 10.0), _trade("JPM", -5.0)]
    report = leave_one_symbol_out(trades, starting_cash=10_000.0)
    assert report.full_metrics.trades.trade_count == 2


def test_leave_one_out_empty_trades_is_safe():
    report = leave_one_symbol_out([], starting_cash=10_000.0)
    assert report.results == ()
    assert report.max_expectancy_swing is None


def test_leave_one_group_out_removes_whole_sector():
    trades = [_trade("AAPL", 100.0), _trade("MSFT", 100.0), _trade("JPM", -10.0)]
    groups = {"technology": ("AAPL", "MSFT"), "financials": ("JPM",)}
    report = leave_one_group_out(trades, groups, starting_cash=10_000.0)
    tech_removed = next(r for r in report.results if r.excluded_key == "technology")
    assert tech_removed.remaining_trade_count == 1
    assert tech_removed.metrics_without.trades.trade_count == 1
