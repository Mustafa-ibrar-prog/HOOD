"""Tests for position/cash accounting and portfolio valuation (Phase 3,
sections 8-10)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.backtesting.portfolio import Portfolio, PortfolioError


def test_buy_fill_updates_cash_and_position():
    p = Portfolio(starting_cash=10_000.0)
    p.apply_buy_fill(symbol="AAPL", quantity=10, execution_price=100.0, fees=1.0)
    assert p.cash == pytest.approx(10_000.0 - 1000.0 - 1.0)
    assert p.positions["AAPL"].quantity == 10
    assert p.positions["AAPL"].avg_entry_price == pytest.approx(100.0)


def test_buy_fill_weighted_average_entry_price_on_adding_to_position():
    p = Portfolio(starting_cash=100_000.0)
    p.apply_buy_fill(symbol="AAPL", quantity=10, execution_price=100.0, fees=0.0)
    p.apply_buy_fill(symbol="AAPL", quantity=10, execution_price=110.0, fees=0.0)
    assert p.positions["AAPL"].quantity == 20
    assert p.positions["AAPL"].avg_entry_price == pytest.approx(105.0)


def test_buy_fill_rejects_insufficient_cash():
    p = Portfolio(starting_cash=100.0)
    with pytest.raises(PortfolioError, match="insufficient cash"):
        p.apply_buy_fill(symbol="AAPL", quantity=10, execution_price=100.0, fees=0.0)


def test_buy_fill_allowed_with_negative_cash_when_explicitly_configured():
    p = Portfolio(starting_cash=100.0, allow_negative_cash=True)
    p.apply_buy_fill(symbol="AAPL", quantity=10, execution_price=100.0, fees=0.0)
    assert p.cash < 0


def test_sell_fill_computes_realized_pnl_and_updates_cash():
    p = Portfolio(starting_cash=10_000.0)
    p.apply_buy_fill(symbol="AAPL", quantity=10, execution_price=100.0, fees=0.0)
    realized = p.apply_sell_fill(symbol="AAPL", quantity=10, execution_price=110.0, fees=1.0)
    assert realized == pytest.approx(100.0 - 1.0)  # (110-100)*10 - 1 fee
    assert "AAPL" not in p.positions  # fully closed, removed
    assert p.realized_pnl_total == pytest.approx(99.0)


def test_sell_fill_partial_reduction_keeps_remaining_position():
    p = Portfolio(starting_cash=10_000.0)
    p.apply_buy_fill(symbol="AAPL", quantity=10, execution_price=100.0, fees=0.0)
    p.apply_sell_fill(symbol="AAPL", quantity=4, execution_price=110.0, fees=0.0)
    assert p.positions["AAPL"].quantity == 6
    assert p.positions["AAPL"].avg_entry_price == pytest.approx(100.0)  # unchanged by a partial sell


def test_sell_fill_rejects_selling_more_than_owned():
    p = Portfolio(starting_cash=10_000.0)
    p.apply_buy_fill(symbol="AAPL", quantity=5, execution_price=100.0, fees=0.0)
    with pytest.raises(PortfolioError, match="selling more than owned"):
        p.apply_sell_fill(symbol="AAPL", quantity=6, execution_price=100.0, fees=0.0)


def test_sell_fill_rejects_selling_a_symbol_never_held():
    p = Portfolio(starting_cash=10_000.0)
    with pytest.raises(PortfolioError):
        p.apply_sell_fill(symbol="AAPL", quantity=1, execution_price=100.0, fees=0.0)


def test_mark_to_market_computes_equity_and_drawdown():
    p = Portfolio(starting_cash=10_000.0)
    p.apply_buy_fill(symbol="AAPL", quantity=10, execution_price=100.0, fees=0.0)
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    point = p.mark_to_market(prices={"AAPL": 120.0}, timestamp=t)
    assert point.equity == pytest.approx(9000.0 + 1200.0)
    assert point.positions_value == pytest.approx(1200.0)
    assert point.drawdown_pct == 0.0  # new peak, no drawdown yet
    assert point.open_position_count == 1
    assert point.position_weights["AAPL"] == pytest.approx(1200.0 / point.equity)


def test_mark_to_market_tracks_drawdown_after_a_decline():
    p = Portfolio(starting_cash=10_000.0)
    p.apply_buy_fill(symbol="AAPL", quantity=10, execution_price=100.0, fees=0.0)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    p.mark_to_market(prices={"AAPL": 150.0}, timestamp=t0)  # peak = 10500
    point = p.mark_to_market(prices={"AAPL": 90.0}, timestamp=t1)  # equity drops to 9900
    assert point.drawdown < 0
    assert point.drawdown_pct < 0


def test_mark_to_market_never_uses_a_price_not_supplied():
    p = Portfolio(starting_cash=10_000.0)
    p.apply_buy_fill(symbol="AAPL", quantity=10, execution_price=100.0, fees=0.0)
    with pytest.raises(PortfolioError, match="no price supplied"):
        p.mark_to_market(prices={}, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_starting_cash_must_be_non_negative():
    with pytest.raises(ValueError):
        Portfolio(starting_cash=-1.0)
