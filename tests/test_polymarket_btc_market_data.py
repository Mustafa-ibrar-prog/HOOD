"""Tests for the BTC price-history buffer (btc_market_data.py) -- the
seam that turns individually-fed (price, timestamp) samples into real
OHLC bars, with no fabricated volume/history. See that module's
docstring for why this is a fed buffer rather than a live poller."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.polymarket.btc_market_data import (
    BtcPriceHistoryStore,
    BtcPriceHistoryStoreError,
    extract_mark_price,
)

_BASE = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)


def test_empty_store_returns_no_bars(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    assert store.get_bars(interval_seconds=60, now=_BASE) == []


def test_record_quote_rejects_non_positive_price(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    with pytest.raises(ValueError):
        store.record_quote(0.0, at=_BASE)
    with pytest.raises(ValueError):
        store.record_quote(-5.0, at=_BASE)


def test_single_bucket_aggregates_into_one_closed_bar(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    store.record_quote(100.0, at=_BASE)
    store.record_quote(105.0, at=_BASE + timedelta(seconds=10))
    store.record_quote(95.0, at=_BASE + timedelta(seconds=20))
    store.record_quote(102.0, at=_BASE + timedelta(seconds=30))

    bars = store.get_bars(interval_seconds=60, now=_BASE + timedelta(seconds=61))
    assert len(bars) == 1
    bar = bars[0]
    assert bar.open == 100.0
    assert bar.high == 105.0
    assert bar.low == 95.0
    assert bar.close == 102.0
    assert bar.volume == 0  # never fabricated -- get_crypto_quotes has no volume field


def test_in_progress_bucket_is_never_returned(tmp_path):
    """The bucket containing `now` is still open -- including it would
    mean the "final" bar for that minute keeps changing shape as more
    quotes land, which is never safe to feed into an indicator that's
    supposed to be deterministic for a given point in time."""
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    store.record_quote(100.0, at=_BASE)
    bars = store.get_bars(interval_seconds=60, now=_BASE + timedelta(seconds=30))  # same bucket as the sample
    assert bars == []


def test_multiple_buckets_produce_multiple_bars_in_order(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    for i in range(12):  # 12 samples, 10s apart -> spans 2 one-minute buckets
        store.record_quote(100.0 + i, at=_BASE + timedelta(seconds=i * 10))
    bars = store.get_bars(interval_seconds=60, now=_BASE + timedelta(seconds=130))
    assert len(bars) == 2
    assert bars[0].start_time < bars[1].start_time
    assert bars[0].close < bars[1].open  # price was rising across the boundary


def test_bars_reflect_only_fed_samples_never_interpolated(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    store.record_quote(100.0, at=_BASE)
    bars = store.get_bars(interval_seconds=60, now=_BASE + timedelta(seconds=61))
    assert bars[0].interpolated is False


def test_retention_prunes_old_samples(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json", retention_seconds=60)
    store.record_quote(100.0, at=_BASE)
    # A much later quote should push the first one out of the retention window.
    store.record_quote(200.0, at=_BASE + timedelta(seconds=3600))
    samples = store.load()
    assert len(samples) == 1
    assert samples[0].price == 200.0


def test_corrupted_file_fails_closed(tmp_path):
    path = tmp_path / "btc.json"
    path.write_text("not json")
    store = BtcPriceHistoryStore(path)
    with pytest.raises(BtcPriceHistoryStoreError):
        store.load()


def test_store_round_trips_across_fresh_instances(tmp_path):
    """Restart-safety: a brand-new store instance pointed at the same
    file sees the same history -- persisted, not in-memory."""
    path = tmp_path / "btc.json"
    BtcPriceHistoryStore(path).record_quote(100.0, at=_BASE)
    fresh = BtcPriceHistoryStore(path)
    assert len(fresh.load()) == 1
    assert fresh.load()[0].price == 100.0


def test_get_bars_rejects_non_positive_interval(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    store.record_quote(100.0, at=_BASE)
    with pytest.raises(ValueError):
        store.get_bars(interval_seconds=0, now=_BASE + timedelta(seconds=61))


# --- extract_mark_price: parsing the real get_crypto_quotes response shape ---

def test_extract_mark_price_finds_matching_symbol():
    response = {"results": [
        {"symbol": "BTCUSD", "mark_price": "67123.45", "bid_price": "67120.00", "ask_price": "67126.00"},
        {"symbol": "ETHUSD", "mark_price": "3000.00"},
    ]}
    assert extract_mark_price(response, "BTC-USD") == pytest.approx(67123.45)


def test_extract_mark_price_returns_none_when_symbol_absent():
    response = {"results": [{"symbol": "ETHUSD", "mark_price": "3000.00"}]}
    assert extract_mark_price(response, "BTC-USD") is None


def test_extract_mark_price_returns_none_when_mark_missing():
    response = {"results": [{"symbol": "BTCUSD", "bid_price": "67120.00"}]}
    assert extract_mark_price(response, "BTC-USD") is None
