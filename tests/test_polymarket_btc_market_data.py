"""Tests for the BTC price-history buffer (btc_market_data.py) -- the
seam that turns individually-fed (price, timestamp) samples into real
OHLC bars, with no fabricated volume/history. See that module's
docstring for why this is a fed buffer rather than a live poller."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.market.models import PriceBar
from src.polymarket.btc_market_data import (
    BtcFeedRefresher,
    BtcFeedRefreshResult,
    BtcPriceHistoryStore,
    BtcPriceHistoryStoreError,
    bootstrap_btc_price_history,
    compute_feed_status,
    extract_mark_price,
)

_BASE = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)


class _FakeDirectSource:
    """A deterministic, in-memory fake of DirectBtcQuoteSource --
    requirement: the provider interface must be replaceable by a fake
    in tests, with no real network/HTTP dependency anywhere."""

    name = "fake-direct"

    def __init__(self, candles: list[PriceBar] | None = None, *, raise_exc: Exception | None = None):
        self._candles = list(candles or [])
        self.raise_exc = raise_exc
        self.call_count = 0
        self.call_limits: list[int] = []

    def set_candles(self, candles: list[PriceBar]) -> None:
        self._candles = list(candles)

    def get_recent_candles(self, *, limit: int) -> list[PriceBar]:
        self.call_count += 1
        self.call_limits.append(limit)
        if self.raise_exc is not None:
            raise self.raise_exc
        return self._candles[-limit:] if limit and limit < len(self._candles) else list(self._candles)


def _real_candles(n: int, *, start: datetime = _BASE, interval_seconds: int = 60, base: float = 100.0, volume: float = 2.5) -> list[PriceBar]:
    """Builds REAL (never-interpolated) candles with distinguishable
    open/high/low/close/volume per bar, for precise round-trip assertions."""
    bars = []
    for i in range(n):
        price = base + i
        bars.append(PriceBar(
            start_time=start + timedelta(seconds=i * interval_seconds),
            open=price, high=price + 0.5, low=price - 0.5, close=price + 0.2,
            volume=volume + i * 0.001, interpolated=False,
        ))
    return bars


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


# --- record_bars / get_bars: REAL candles always preferred over quote-derived bars --

def test_record_bars_stores_real_ohlcv_exactly(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    candles = _real_candles(3)
    written = store.record_bars(candles)

    assert written == 3
    bars = store.get_bars(interval_seconds=60, now=_BASE + timedelta(seconds=3 * 60 + 5))
    assert len(bars) == 3
    for real, stored in zip(candles, bars):
        assert stored.start_time == real.start_time
        assert stored.open == real.open and stored.high == real.high
        assert stored.low == real.low and stored.close == real.close
        assert stored.volume == real.volume  # real fractional volume preserved, never zeroed


def test_record_bars_upserts_by_timestamp_idempotently(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    store.record_bars(_real_candles(3))
    # Re-recording an overlapping, slightly different batch replaces
    # the overlap rather than duplicating it.
    updated = _real_candles(3, base=500.0)
    store.record_bars(updated)

    bars = store.get_bars(interval_seconds=60, now=_BASE + timedelta(seconds=3 * 60 + 5))
    assert len(bars) == 3  # not 6 -- same 3 buckets, just replaced
    assert bars[0].open == 500.0


def test_real_bar_takes_precedence_over_quote_derived_bar_for_the_same_bucket(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    store.record_quote(1.0, at=_BASE + timedelta(seconds=5))  # would otherwise aggregate to a quote-bar
    real = _real_candles(1)[0]
    store.record_bars([real])

    bars = store.get_bars(interval_seconds=60, now=_BASE + timedelta(seconds=65))
    assert len(bars) == 1
    assert bars[0].open == real.open  # the real candle won, not the quote-derived open=1.0
    assert bars[0].volume == real.volume  # real volume, not the quote path's hardcoded 0


def test_record_bars_empty_list_is_a_noop(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    assert store.record_bars([]) == 0
    assert store.load_real_bars() == []


def test_real_bars_restart_safe_across_fresh_store_instances(tmp_path):
    path = tmp_path / "btc.json"
    BtcPriceHistoryStore(path).record_bars(_real_candles(3))
    fresh = BtcPriceHistoryStore(path)
    bars = fresh.get_bars(interval_seconds=60, now=_BASE + timedelta(seconds=3 * 60 + 5))
    assert len(bars) == 3


def test_real_bars_corrupted_file_fails_closed(tmp_path):
    path = tmp_path / "btc.json"
    BtcPriceHistoryStore(path).record_bars(_real_candles(1))
    bars_path = tmp_path / "btc.bars.json"
    bars_path.write_text("not json")
    with pytest.raises(BtcPriceHistoryStoreError):
        BtcPriceHistoryStore(path).load_real_bars()


# --- compute_feed_status: FRESH / STALE / UNAVAILABLE --------------------------

def test_feed_status_unavailable_when_no_bars_at_all():
    status = compute_feed_status([], max_bar_age_seconds=300, source="coinbase", now=_BASE)
    assert status.status == "UNAVAILABLE"
    assert status.source is None
    assert status.last_bar_time is None
    assert status.bar_age_seconds is None


def test_feed_status_fresh_within_threshold():
    bars = _real_candles(3)
    now = bars[-1].start_time + timedelta(seconds=30)  # well within a 300s threshold
    status = compute_feed_status(bars, max_bar_age_seconds=300, source="coinbase", now=now)
    assert status.status == "FRESH"
    assert status.source == "coinbase"
    assert status.last_bar_time == bars[-1].start_time
    assert status.bar_age_seconds == pytest.approx(30, abs=1)


def test_feed_status_stale_once_newest_bar_exceeds_threshold():
    bars = _real_candles(3)
    now = bars[-1].start_time + timedelta(seconds=301)  # just past a 300s threshold
    status = compute_feed_status(bars, max_bar_age_seconds=300, source="coinbase", now=now)
    assert status.status == "STALE"
    assert status.bar_age_seconds == pytest.approx(301, abs=1)


# --- bootstrap_btc_price_history ------------------------------------------------

def test_bootstrap_records_enough_candles_for_the_minimum(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    source = _FakeDirectSource(_real_candles(40))
    written = bootstrap_btc_price_history(store, source, min_bars=35)

    assert written == 40
    bars = store.get_bars(interval_seconds=60, now=_BASE + timedelta(seconds=40 * 60 + 5))
    assert len(bars) == 40  # real history, none fabricated to fill a gap


def test_bootstrap_with_fewer_than_required_bars_still_stores_what_exists(tmp_path):
    """The provider only had 20 real candles -- never pad to 35 with
    fabricated ones; downstream (assess_btc_market) is responsible for
    recognizing "not enough" and reporting INSUFFICIENT_DATA."""
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    source = _FakeDirectSource(_real_candles(20))
    written = bootstrap_btc_price_history(store, source, min_bars=35)

    assert written == 20
    bars = store.get_bars(interval_seconds=60, now=_BASE + timedelta(seconds=20 * 60 + 5))
    assert len(bars) == 20


def test_bootstrap_is_idempotent_on_restart_with_fresh_data(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    source = _FakeDirectSource(_real_candles(40))
    bootstrap_btc_price_history(store, source, min_bars=35)
    # A "restart" re-runs bootstrap against the same (now slightly
    # overlapping) provider data -- must not duplicate or corrupt history.
    written_again = bootstrap_btc_price_history(store, source, min_bars=35)

    assert written_again == 40
    bars = store.get_bars(interval_seconds=60, now=_BASE + timedelta(seconds=40 * 60 + 5))
    assert len(bars) == 40


def test_bootstrap_provider_failure_never_raises(tmp_path):
    """Requirement: a temporarily unavailable BTC provider must not
    crash the bot, even at startup."""
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    source = _FakeDirectSource(raise_exc=RuntimeError("network down"))
    written = bootstrap_btc_price_history(store, source, min_bars=35)

    assert written == 0
    assert store.get_bars(interval_seconds=60, now=_BASE) == []


def test_bootstrap_provider_returns_nothing(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    source = _FakeDirectSource([])
    assert bootstrap_btc_price_history(store, source, min_bars=35) == 0


# --- BtcFeedRefresher: new-minute cadence, no spamming -------------------------

def test_refresher_does_not_call_the_provider_twice_within_the_same_minute(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    source = _FakeDirectSource(_real_candles(5))
    refresher = BtcFeedRefresher(store, source)

    now = _BASE + timedelta(seconds=10)
    results = []
    for _ in range(5):  # simulate 5 Polymarket poll cycles within the same minute
        results.append(refresher.maybe_refresh(now=now))
        now += timedelta(seconds=2)

    assert source.call_count == 1  # cached/reused -- never spammed
    assert results[0].attempted is True
    assert all(r.attempted is False for r in results[1:])  # same-minute calls are explicit no-attempt skips


def test_refresher_calls_again_once_a_new_minute_arrives(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    source = _FakeDirectSource(_real_candles(5))
    refresher = BtcFeedRefresher(store, source)

    first = refresher.maybe_refresh(now=_BASE)
    second = refresher.maybe_refresh(now=_BASE + timedelta(seconds=30))  # still the same minute
    third = refresher.maybe_refresh(now=_BASE + timedelta(minutes=1, seconds=5))  # a new minute

    assert source.call_count == 2
    assert first.attempted is True
    assert second.attempted is False
    assert third.attempted is True


def test_refresher_attempted_result_reports_the_real_newest_candle_time_and_age(tmp_path):
    """Requirement: every refresh attempt/result must report the
    newest candle's timestamp and its age relative to the request
    time -- not just "something was recorded"."""
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    candles = _real_candles(5)  # newest candle's start_time == _BASE + 4*60s
    source = _FakeDirectSource(candles)
    refresher = BtcFeedRefresher(store, source)

    now = _BASE + timedelta(minutes=4, seconds=45)  # 45s after the newest candle opened
    result = refresher.maybe_refresh(now=now)

    assert result.attempted is True
    assert result.candles_recorded == 5
    assert result.newest_candle_time == candles[-1].start_time
    assert result.candle_age_seconds == pytest.approx(45.0)
    assert result.error is None
    assert result.now == now


def test_refresher_provider_failure_never_raises_and_keeps_existing_data(tmp_path):
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    source = _FakeDirectSource(_real_candles(5))
    refresher = BtcFeedRefresher(store, source)
    refresher.maybe_refresh(now=_BASE)
    before = store.get_bars(interval_seconds=60, now=_BASE + timedelta(seconds=5 * 60 + 5))

    source.raise_exc = RuntimeError("provider hiccup")
    result = refresher.maybe_refresh(now=_BASE + timedelta(minutes=1, seconds=5))

    assert result.attempted is True  # a real attempt was made -- never silently indistinguishable from a skip
    assert result.candles_recorded == 0  # swallowed, never raised
    assert result.newest_candle_time is None
    assert result.candle_age_seconds is None
    assert result.error == "RuntimeError: provider hiccup"  # the exact provider error, never discarded
    after = store.get_bars(interval_seconds=60, now=_BASE + timedelta(seconds=5 * 60 + 5))
    assert after == before  # existing persisted data untouched by the failed attempt


def test_refresher_empty_candle_response_is_attempted_with_no_error(tmp_path):
    """A provider call that succeeds but returns nothing (a genuinely
    different case from a transport/parse failure) must still be
    reported as `attempted=True` with `error=None` -- never confused
    with either a same-minute skip or a provider exception."""
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    source = _FakeDirectSource([])
    refresher = BtcFeedRefresher(store, source)

    result = refresher.maybe_refresh(now=_BASE)

    assert result.attempted is True
    assert result.candles_recorded == 0
    assert result.error is None
    assert result.newest_candle_time is None


def test_refresher_persistence_failure_is_reported_not_raised(tmp_path, monkeypatch):
    """A failure PERSISTING successfully-fetched candles (e.g. a disk/
    IO problem) is a genuinely different failure mode from a provider
    transport error -- must still never raise, and must still be
    reported with its own error message (not silently indistinguishable
    from "provider returned nothing")."""
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    candles = _real_candles(5)
    source = _FakeDirectSource(candles)
    refresher = BtcFeedRefresher(store, source)

    def _boom(bars):
        raise OSError("disk full")

    monkeypatch.setattr(store, "record_bars", _boom)
    result = refresher.maybe_refresh(now=_BASE)

    assert result.attempted is True
    assert result.candles_recorded == 0
    assert result.newest_candle_time == candles[-1].start_time  # known even though persistence failed
    assert "disk full" in result.error


def test_refresher_accepts_a_different_provider_implementation(tmp_path):
    """Requirement: the provider interface can be replaced by a
    different implementation with zero changes to the refresher or
    bootstrap code -- only the object passed in differs."""
    class _AnotherFakeSource:
        name = "another-fake"

        def __init__(self, candles):
            self._candles = candles

        def get_recent_candles(self, *, limit: int):
            return self._candles[-limit:] if limit and limit < len(self._candles) else list(self._candles)

    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    source = _AnotherFakeSource(_real_candles(5))
    refresher = BtcFeedRefresher(store, source)
    result = refresher.maybe_refresh(now=_BASE)

    assert isinstance(result, BtcFeedRefreshResult)
    assert result.candles_recorded == 5
    assert len(store.get_bars(interval_seconds=60, now=_BASE + timedelta(seconds=5 * 60 + 5))) == 5
