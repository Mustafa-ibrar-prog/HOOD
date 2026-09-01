"""Tests for subgroup analysis (Phase 5, section 9)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.backtesting.journal import BacktestTrade
from src.data.universe import Universe, UniverseMember
from src.research.cross_sectional import by_sector, by_symbol, by_volatility_bucket, by_year, concentration_summary

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
T1 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _trade(symbol: str, entry_ts, net_pnl: float) -> BacktestTrade:
    return BacktestTrade(
        trade_id="T", backtest_id="B", strategy="s", symbol=symbol, entry_timestamp=entry_ts, entry_price=100.0,
        exit_timestamp=entry_ts + timedelta(days=1), exit_price=101.0, quantity=1, gross_pnl=net_pnl, fees=0.0,
        slippage=0.0, net_pnl=net_pnl, holding_period_minutes=1440.0, entry_reason="", exit_reason="", risk_decision="APPROVED",
    )


def test_by_symbol_buckets_correctly():
    trades = [_trade("AAPL", T0, 10.0), _trade("AAPL", T0, -5.0), _trade("JPM", T0, 20.0)]
    result = by_symbol(trades, starting_cash=10_000.0)
    assert result["AAPL"].trade_count == 2
    assert result["AAPL"].net_pnl_total == 5.0
    assert result["JPM"].trade_count == 1


def test_by_sector_uses_universe_mapping():
    u = Universe(name="X", description="", members=(UniverseMember("AAPL", "equity", "technology"), UniverseMember("JPM", "equity", "financials")), inclusion_rules=(), exclusion_rules=())
    trades = [_trade("AAPL", T0, 10.0), _trade("JPM", T0, -5.0)]
    result = by_sector(trades, u, starting_cash=10_000.0)
    assert result["technology"].net_pnl_total == 10.0
    assert result["financials"].net_pnl_total == -5.0


def test_by_sector_unclassified_when_symbol_not_in_universe():
    u = Universe(name="X", description="", members=(UniverseMember("AAPL", "equity", "technology"),), inclusion_rules=(), exclusion_rules=())
    trades = [_trade("MYSTERY", T0, 5.0)]
    result = by_sector(trades, u, starting_cash=10_000.0)
    assert "unclassified" in result


def test_by_year_separates_years():
    trades = [_trade("AAPL", T0, 10.0), _trade("AAPL", T1, -5.0)]
    result = by_year(trades, starting_cash=10_000.0)
    assert set(result.keys()) == {"2024", "2025"}
    assert result["2024"].net_pnl_total == 10.0


def test_by_volatility_bucket_ranks_symbols():
    vol_by_symbol = {"LOW": 0.01, "MED": 0.05, "HIGH": 0.20}
    trades = [_trade("LOW", T0, 1.0), _trade("MED", T0, 2.0), _trade("HIGH", T0, 3.0)]
    result = by_volatility_bucket(trades, vol_by_symbol, starting_cash=10_000.0, n_buckets=3)
    assert len(result) == 3


def test_concentration_summary_sums_to_one():
    trades = [_trade("AAPL", T0, 60.0), _trade("JPM", T0, 40.0)]
    conc = concentration_summary(trades)
    assert abs(sum(conc.values()) - 1.0) < 1e-9
    assert conc["AAPL"] == 0.6


def test_concentration_summary_handles_zero_total():
    trades = [_trade("AAPL", T0, 10.0), _trade("JPM", T0, -10.0)]
    conc = concentration_summary(trades)
    assert conc["AAPL"] == 0.0  # total is 0 -> defined as 0, not a division error
