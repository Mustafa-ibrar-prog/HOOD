"""Tests for BacktestTradeJournal (Phase 3, section 13)."""

from __future__ import annotations

from datetime import datetime, timezone

from src.backtesting.journal import BacktestTrade, BacktestTradeJournal


def _trade(**overrides) -> BacktestTrade:
    defaults = dict(
        trade_id="TR-1", backtest_id="BT-1", strategy="ma-crossover-example", symbol="AAPL",
        entry_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), entry_price=100.0,
        exit_timestamp=datetime(2026, 1, 5, tzinfo=timezone.utc), exit_price=110.0,
        quantity=10, gross_pnl=100.0, fees=1.0, slippage=0.5, net_pnl=99.0,
        holding_period_minutes=5760.0, entry_reason="crossover up", exit_reason="crossover down",
        risk_decision="APPROVED",
    )
    defaults.update(overrides)
    return BacktestTrade(**defaults)


def test_record_and_load_round_trip(tmp_path):
    journal = BacktestTradeJournal(tmp_path / "trades.jsonl")
    trade = _trade()
    journal.record_trade(trade)
    loaded = journal.load_all()
    assert len(loaded) == 1
    assert loaded[0] == trade


def test_trades_are_appended_not_overwritten(tmp_path):
    journal = BacktestTradeJournal(tmp_path / "trades.jsonl")
    journal.record_trade(_trade(trade_id="TR-1"))
    journal.record_trade(_trade(trade_id="TR-2"))
    assert len(journal.load_all()) == 2


def test_for_backtest_filters_by_backtest_id(tmp_path):
    journal = BacktestTradeJournal(tmp_path / "trades.jsonl")
    journal.record_trade(_trade(trade_id="TR-1", backtest_id="BT-1"))
    journal.record_trade(_trade(trade_id="TR-2", backtest_id="BT-2"))
    journal.record_trade(_trade(trade_id="TR-3", backtest_id="BT-1"))
    bt1 = journal.for_backtest("BT-1")
    assert {t.trade_id for t in bt1} == {"TR-1", "TR-3"}


def test_load_all_on_missing_file_is_empty(tmp_path):
    journal = BacktestTradeJournal(tmp_path / "does-not-exist.jsonl")
    assert journal.load_all() == []
