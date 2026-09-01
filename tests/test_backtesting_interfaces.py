"""Tests for the Phase-3-facing backtesting interfaces: confirms the
HistoricalDataStore-backed adapter satisfies the HistoricalBarSource
protocol and correctly filters by date range. No engine logic exists yet
— see src/backtesting/interfaces.py's module docstring."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.backtesting.interfaces import BacktestConfig, HistoricalBarSource, StoreBackedBarSource
from src.data.bar import Bar
from src.data.store import HistoricalDataStore


def _bars(n=10):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="AAPL", timeframe="day", open=100, high=101, low=99, close=100.5, volume=100)
        for i in range(n)
    ]


def test_store_backed_bar_source_satisfies_protocol(tmp_path):
    store = HistoricalDataStore(tmp_path)
    store.save("AAPL", "day", _bars())
    source = StoreBackedBarSource(store)
    assert isinstance(source, HistoricalBarSource)


def test_store_backed_bar_source_filters_by_date_range(tmp_path):
    store = HistoricalDataStore(tmp_path)
    store.save("AAPL", "day", _bars(10))
    source = StoreBackedBarSource(store)
    got = source.get_bars("AAPL", "day", date(2026, 1, 2), date(2026, 1, 4))
    assert len(got) == 3
    assert got[0].timestamp.date() == date(2026, 1, 2)
    assert got[-1].timestamp.date() == date(2026, 1, 4)


def test_backtest_config_is_a_plain_data_holder():
    cfg = BacktestConfig(
        symbols=("AAPL",), timeframe="day", start=date(2023, 1, 1), end=date(2024, 1, 1),
        data_version="dv", feature_version="fv",
    )
    assert cfg.symbols == ("AAPL",)
    assert cfg.strategy_version is None
    assert cfg.initial_capital_usd == 0.0
