"""Phase 35, Parts I-K — robustness breakdowns, falsification, and the
underlying-vs-option comparison, on synthetic BacktestTrade lists."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.backtesting.journal import BacktestTrade
from src.options.phase35_option_trade_matching import MatchedOptionTrade
from src.options.phase35_statistical_validation import (
    leave_one_period_out,
    leave_one_symbol_out,
    outlier_analysis,
    simple_trade_stats,
    symbol_by_symbol_breakdown,
    underlying_vs_option_rows,
    year_by_year_breakdown,
)


def _trade(symbol, year, net_pnl, entry_price=1.5, exit_price=2.0):
    return BacktestTrade(
        trade_id=f"TR-{symbol}-{year}", backtest_id="BT-1", strategy="MOMENTUM_BREAKOUT_EXISTING_V1", symbol=symbol,
        entry_timestamp=datetime(year, 1, 10, tzinfo=timezone.utc), entry_price=entry_price,
        exit_timestamp=datetime(year, 1, 20, tzinfo=timezone.utc), exit_price=exit_price,
        quantity=100, gross_pnl=net_pnl, fees=0.0, slippage=0.0, net_pnl=net_pnl,
        holding_period_minutes=14400.0, entry_reason="test", exit_reason="test", risk_decision="APPROVED",
    )


def test_simple_trade_stats_empty():
    stats = simple_trade_stats([])
    assert stats.n_trades == 0
    assert stats.mean_net_pnl is None


def test_simple_trade_stats_basic():
    trades = [_trade("A", 2020, 100.0), _trade("A", 2020, -50.0)]
    stats = simple_trade_stats(trades)
    assert stats.n_trades == 2
    assert stats.win_rate == 0.5
    assert stats.total_net_pnl == 50.0
    assert stats.profit_factor == 2.0


def test_year_by_year_breakdown_groups_by_entry_year():
    trades = [_trade("A", 2020, 10.0), _trade("A", 2021, 20.0), _trade("B", 2021, -5.0)]
    breakdown = year_by_year_breakdown(trades)
    assert set(breakdown) == {2020, 2021}
    assert breakdown[2021].n_trades == 2


def test_symbol_by_symbol_breakdown_uses_underlying_not_option_id():
    trades = [_trade("OPT1", 2020, 10.0), _trade("OPT2", 2020, 20.0)]
    matched = [
        MatchedOptionTrade("AAPL", date(2020, 1, 10), "OPT1", date(2020, 2, 10), 100.0, {}, (), 0),
        MatchedOptionTrade("GOOG", date(2020, 1, 10), "OPT2", date(2020, 2, 10), 100.0, {}, (), 0),
    ]
    breakdown = symbol_by_symbol_breakdown(trades, matched)
    assert set(breakdown) == {"AAPL", "GOOG"}


def test_leave_one_symbol_out_excludes_the_named_symbol():
    trades = [_trade("OPT1", 2020, 10.0), _trade("OPT2", 2020, 20.0)]
    matched = [
        MatchedOptionTrade("AAPL", date(2020, 1, 10), "OPT1", date(2020, 2, 10), 100.0, {}, (), 0),
        MatchedOptionTrade("GOOG", date(2020, 1, 10), "OPT2", date(2020, 2, 10), 100.0, {}, (), 0),
    ]
    result = leave_one_symbol_out(trades, matched)
    assert result["AAPL"].n_trades == 1  # excludes AAPL's own trade, leaves GOOG's
    assert result["AAPL"].total_net_pnl == 20.0


def test_leave_one_period_out_excludes_the_named_year():
    trades = [_trade("A", 2020, 10.0), _trade("A", 2021, 20.0)]
    result = leave_one_period_out(trades)
    assert result[2020].n_trades == 1
    assert result[2020].total_net_pnl == 20.0


def test_outlier_analysis_flags_top_contributor():
    trades = [_trade("A", 2020, 1000.0)] + [_trade("A", 2020, 1.0) for _ in range(99)]
    analysis = outlier_analysis(trades)
    assert analysis.top1pct_contribution_fraction is not None
    assert analysis.top1pct_contribution_fraction > 0.8  # the single $1000 trade dominates
    assert analysis.stats_excluding_largest_winner.total_net_pnl == 99.0


def test_underlying_vs_option_rows_computes_real_underlying_return():
    trades = [_trade("OPT1", 2020, 50.0, entry_price=1.0, exit_price=1.5)]
    matched = [MatchedOptionTrade("AAPL", date(2020, 1, 10), "OPT1", date(2020, 2, 10), 100.0, {}, (), 0)]
    series = {"AAPL": [(date(2020, 1, 10), 100.0), (date(2020, 1, 20), 105.0)]}
    rows = underlying_vs_option_rows(trades, matched, series)
    assert len(rows) == 1
    assert abs(rows[0].underlying_return_pct - 0.05) < 1e-9
    assert abs(rows[0].option_return_pct - 0.5) < 1e-9
