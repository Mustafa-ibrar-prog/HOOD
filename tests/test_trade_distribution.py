"""Tests for Phase 6, section 10's trade-return distribution analysis."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.backtesting.journal import BacktestTrade
from src.research.trade_distribution import trade_return_distribution

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _trade(symbol: str, net_pnl: float) -> BacktestTrade:
    return BacktestTrade(
        trade_id="T", backtest_id="B", strategy="s", symbol=symbol, entry_timestamp=T0, entry_price=100.0,
        exit_timestamp=T0 + timedelta(days=5), exit_price=101.0, quantity=1, gross_pnl=net_pnl, fees=0.0,
        slippage=0.0, net_pnl=net_pnl, holding_period_minutes=7200.0, entry_reason="", exit_reason="", risk_decision="APPROVED",
    )


def test_empty_trades_returns_a_zeroed_distribution():
    dist = trade_return_distribution([])
    assert dist.trade_count == 0
    assert dist.stdev is None
    assert dist.pct_pnl_from_top_1pct_trades is None


def test_mean_and_median_on_simple_values():
    trades = [_trade("AAPL", v) for v in (10.0, 20.0, 30.0, 40.0, 50.0)]
    dist = trade_return_distribution(trades)
    assert dist.mean == 30.0
    assert dist.median == 30.0
    assert dist.trade_count == 5


def test_percentiles_are_ordered():
    trades = [_trade("AAPL", float(v)) for v in range(1, 101)]
    dist = trade_return_distribution(trades)
    assert dist.p5 < dist.p25 < dist.p50 < dist.p75 < dist.p95


def test_a_single_dominant_trade_shows_up_in_top_1pct_share():
    trades = [_trade("AAPL", 1.0) for _ in range(99)] + [_trade("AAPL", 1000.0)]
    dist = trade_return_distribution(trades)
    # top 1% of 100 trades = 1 trade = the $1000 one; total = 99*1 + 1000 = 1099
    assert dist.pct_pnl_from_top_1pct_trades > 90.0


def test_largest_contributing_symbol_is_identified():
    trades = [_trade("AAPL", 500.0), _trade("MSFT", 10.0), _trade("MSFT", -5.0)]
    dist = trade_return_distribution(trades)
    assert dist.largest_contributing_symbol == "AAPL"
    assert dist.pct_pnl_from_largest_contributing_symbol > 90.0


def test_broadly_distributed_pnl_shows_low_concentration():
    trades = [_trade(f"SYM{i}", 10.0) for i in range(20)]
    dist = trade_return_distribution(trades)
    assert dist.pct_pnl_from_largest_contributing_symbol < 10.0
    assert dist.pct_pnl_from_top_5pct_trades < 10.0
