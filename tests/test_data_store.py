"""Tests for HistoricalDataStore: save/load round-trips, metadata,
deduplication, incremental upsert, and needs_download's
duplicate-download-avoidance logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.data.store import HistoricalDataStore, HistoricalDataStoreError


def _bar(day: int, close: float = 100.0) -> Bar:
    return Bar(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day),
        symbol="AAPL",
        timeframe="day",
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=1000 + day,
    )


def test_load_missing_dataset_returns_empty_list(tmp_path):
    store = HistoricalDataStore(tmp_path)
    assert store.load("AAPL", "day") == []
    assert store.load_metadata("AAPL", "day") is None


def test_save_then_load_round_trips(tmp_path):
    store = HistoricalDataStore(tmp_path)
    bars = [_bar(i) for i in range(5)]
    meta = store.save("aapl", "day", bars)
    assert meta.symbol == "AAPL"
    assert meta.record_count == 5
    loaded = store.load("AAPL", "day")
    assert loaded == bars


def test_save_dedupes_and_sorts(tmp_path):
    store = HistoricalDataStore(tmp_path)
    unordered_with_dupe = [_bar(2), _bar(0), _bar(1), _bar(0, close=999)]  # a later dupe of day 0 wins
    meta = store.save("AAPL", "day", unordered_with_dupe)
    loaded = store.load("AAPL", "day")
    assert [b.timestamp for b in loaded] == sorted(b.timestamp for b in loaded)
    assert meta.record_count == 3
    assert loaded[0].close == 999  # last-seen wins on a timestamp collision


def test_metadata_has_correct_range_and_deterministic_version(tmp_path):
    store = HistoricalDataStore(tmp_path)
    bars = [_bar(i) for i in range(3)]
    meta1 = store.save("AAPL", "day", bars)
    # Re-saving identical content produces the identical data_version.
    meta2 = store.save("AAPL", "day", bars)
    assert meta1.data_version == meta2.data_version
    assert meta1.start_timestamp == bars[0].timestamp
    assert meta1.end_timestamp == bars[-1].timestamp


def test_upsert_merges_new_bars_into_existing(tmp_path):
    store = HistoricalDataStore(tmp_path)
    store.save("AAPL", "day", [_bar(0), _bar(1)])
    store.upsert("AAPL", "day", [_bar(2), _bar(3)])
    loaded = store.load("AAPL", "day")
    assert len(loaded) == 4
    assert [b.timestamp.day for b in loaded] == [1, 2, 3, 4]


def test_upsert_new_bars_win_on_timestamp_collision(tmp_path):
    store = HistoricalDataStore(tmp_path)
    store.save("AAPL", "day", [_bar(0, close=100.0)])
    store.upsert("AAPL", "day", [_bar(0, close=105.0)])  # a fresh re-fetch of the same bar
    loaded = store.load("AAPL", "day")
    assert len(loaded) == 1
    assert loaded[0].close == 105.0


def test_needs_download_true_when_nothing_stored(tmp_path):
    store = HistoricalDataStore(tmp_path)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 5, tzinfo=timezone.utc)
    assert store.needs_download("AAPL", "day", start, end) is True


def test_needs_download_false_when_range_fully_covered(tmp_path):
    store = HistoricalDataStore(tmp_path)
    bars = [_bar(i) for i in range(10)]
    store.save("AAPL", "day", bars)
    assert store.needs_download("AAPL", "day", bars[2].timestamp, bars[7].timestamp) is False


def test_needs_download_true_when_range_extends_past_stored_data(tmp_path):
    store = HistoricalDataStore(tmp_path)
    bars = [_bar(i) for i in range(5)]
    store.save("AAPL", "day", bars)
    later = bars[-1].timestamp + timedelta(days=30)
    assert store.needs_download("AAPL", "day", bars[0].timestamp, later) is True


def test_list_datasets(tmp_path):
    store = HistoricalDataStore(tmp_path)
    store.save("AAPL", "day", [_bar(0)])
    store.save("AAPL", "5minute", [_bar(0)])
    store.save("SOFI", "day", [_bar(0)])
    assert store.list_datasets() == [("AAPL", "5minute"), ("AAPL", "day"), ("SOFI", "day")]


def test_corrupted_data_file_raises_not_silently_empty(tmp_path):
    store = HistoricalDataStore(tmp_path)
    store.save("AAPL", "day", [_bar(0)])
    path = store._data_path("AAPL", "day")
    path.write_text("{not valid json\n")
    with pytest.raises(HistoricalDataStoreError):
        store.load("AAPL", "day")


def test_corrupted_metadata_file_raises(tmp_path):
    store = HistoricalDataStore(tmp_path)
    store.save("AAPL", "day", [_bar(0)])
    path = store._meta_path("AAPL", "day")
    path.write_text("not json at all")
    with pytest.raises(HistoricalDataStoreError):
        store.load_metadata("AAPL", "day")


def test_save_with_no_bars_is_safe(tmp_path):
    store = HistoricalDataStore(tmp_path)
    meta = store.save("AAPL", "day", [])
    assert meta.record_count == 0
    assert store.load("AAPL", "day") == []
