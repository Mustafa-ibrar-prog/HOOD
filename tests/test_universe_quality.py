"""Tests for cross-universe data-quality reporting (Phase 5, section 4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.data.bar import Bar
from src.data.store import HistoricalDataStore
from src.data.universe import Universe, UniverseMember
from src.data.universe_quality import render_universe_quality_report, run_universe_quality_report, usable_symbols


def _bars(symbol: str, n: int) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol=symbol, timeframe="day", open=100, high=101, low=99, close=100.5, volume=1000)
        for i in range(n)
    ]


def test_symbol_with_no_data_is_marked_unavailable_not_dropped(tmp_path):
    store = HistoricalDataStore(tmp_path)
    store.save("AAPL", "day", _bars("AAPL", 200))
    universe = Universe(name="X", description="", members=(UniverseMember("AAPL", "equity", "tech"), UniverseMember("ZZZZ", "equity", "tech")), inclusion_rules=(), exclusion_rules=())
    summaries = run_universe_quality_report(store, universe, "day")
    assert len(summaries) == 2  # both symbols reported, none silently dropped
    zzzz = next(s for s in summaries if s.symbol == "ZZZZ")
    assert zzzz.available is False
    assert "no day data" in zzzz.reason_unavailable


def test_symbol_below_min_bars_is_unavailable_with_reason(tmp_path):
    store = HistoricalDataStore(tmp_path)
    store.save("AAPL", "day", _bars("AAPL", 50))
    universe = Universe(name="X", description="", members=(UniverseMember("AAPL", "equity", "tech"),), inclusion_rules=(), exclusion_rules=())
    summaries = run_universe_quality_report(store, universe, "day", min_bars_required=100)
    assert summaries[0].available is False
    assert "50 bars" in summaries[0].reason_unavailable


def test_symbol_with_enough_clean_data_is_available(tmp_path):
    store = HistoricalDataStore(tmp_path)
    store.save("AAPL", "day", _bars("AAPL", 200))
    universe = Universe(name="X", description="", members=(UniverseMember("AAPL", "equity", "tech"),), inclusion_rules=(), exclusion_rules=())
    summaries = run_universe_quality_report(store, universe, "day", min_bars_required=100)
    assert summaries[0].available is True
    assert usable_symbols(summaries) == ["AAPL"]


def test_render_report_lists_every_symbol():
    from src.data.universe_quality import SymbolQualitySummary

    summaries = [
        SymbolQualitySummary(symbol="AAPL", available=True, reason_unavailable=None, date_range=None, bar_count=200, quality_report=None, source="hood"),
        SymbolQualitySummary(symbol="ZZZZ", available=False, reason_unavailable="no data", date_range=None, bar_count=0, quality_report=None, source="none"),
    ]
    text = render_universe_quality_report(summaries)
    assert "AAPL" in text
    assert "ZZZZ" in text
    assert "Usable: 1/2" in text
