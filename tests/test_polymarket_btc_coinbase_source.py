"""Tests for the Coinbase direct BTC candle client
(btc_coinbase_source.py). Never makes a real network call -- every
test monkeypatches urllib.request.urlopen with a deterministic fake
response, confirmed against Coinbase's documented candle row shape
([time, low, high, open, close, volume], newest-first) -- see that
module's docstring for why this sandbox cannot verify against a live
response (egress policy blocks api.exchange.coinbase.com)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest

from src.polymarket.btc_coinbase_source import CoinbaseBtcQuoteSource, CoinbaseBtcQuoteSourceError


class _FakeHttpResponse:
    def __init__(self, body: bytes, *, status: int = 200):
        self._body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self) -> bytes:
        return self._body


def _patch_urlopen(monkeypatch, *, body: bytes | None = None, raise_exc: Exception | None = None, capture: list | None = None):
    def fake_urlopen(request, timeout=None):
        if capture is not None:
            capture.append(request)
        if raise_exc is not None:
            raise raise_exc
        return _FakeHttpResponse(body)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)


def _rows(*prices_newest_first: tuple[int, float]) -> bytes:
    """Builds a Coinbase-shaped response body: each tuple is
    (unix_time, close) -- low/high/open/volume derived deterministically
    from close so tests can assert on them precisely."""
    rows = []
    for time_s, close in prices_newest_first:
        rows.append([time_s, close - 1.0, close + 1.0, close - 0.5, close, 2.5])
    return json.dumps(rows).encode()


def test_parses_real_shaped_response_oldest_first(monkeypatch):
    body = _rows((1700000120, 100.2), (1700000060, 99.2), (1700000000, 98.2))  # newest-first, as Coinbase returns
    _patch_urlopen(monkeypatch, body=body)
    source = CoinbaseBtcQuoteSource()

    bars = source.get_recent_candles(limit=10)

    assert [b.close for b in bars] == [98.2, 99.2, 100.2]  # re-sorted oldest-first
    assert bars[0].start_time.timestamp() == 1700000000
    assert bars[-1].start_time.timestamp() == 1700000120


def test_preserves_real_fractional_volume_exactly(monkeypatch):
    body = json.dumps([[1700000000, 97.5, 98.5, 98.0, 98.2, 1.23456789]]).encode()
    _patch_urlopen(monkeypatch, body=body)
    source = CoinbaseBtcQuoteSource()

    bars = source.get_recent_candles(limit=10)

    assert bars[0].volume == pytest.approx(1.23456789)  # never rounded/truncated to an int
    assert bars[0].interpolated is False


def test_limit_truncates_to_the_most_recent(monkeypatch):
    body = _rows((1700000180, 103.0), (1700000120, 102.0), (1700000060, 101.0), (1700000000, 100.0))
    _patch_urlopen(monkeypatch, body=body)
    source = CoinbaseBtcQuoteSource()

    bars = source.get_recent_candles(limit=2)

    assert [b.close for b in bars] == [102.0, 103.0]  # the 2 most recent, oldest-first


def test_transport_failure_raises_not_crashes_silently(monkeypatch):
    _patch_urlopen(monkeypatch, raise_exc=urllib.error.URLError("connection refused"))
    source = CoinbaseBtcQuoteSource()
    with pytest.raises(CoinbaseBtcQuoteSourceError):
        source.get_recent_candles(limit=10)


def test_malformed_json_raises(monkeypatch):
    _patch_urlopen(monkeypatch, body=b"not json")
    source = CoinbaseBtcQuoteSource()
    with pytest.raises(CoinbaseBtcQuoteSourceError):
        source.get_recent_candles(limit=10)


def test_non_list_response_raises(monkeypatch):
    _patch_urlopen(monkeypatch, body=json.dumps({"error": "bad request"}).encode())
    source = CoinbaseBtcQuoteSource()
    with pytest.raises(CoinbaseBtcQuoteSourceError):
        source.get_recent_candles(limit=10)


def test_malformed_row_length_raises(monkeypatch):
    body = json.dumps([[1700000000, 97.5, 98.5]]).encode()  # only 3 fields, not 6
    _patch_urlopen(monkeypatch, body=body)
    source = CoinbaseBtcQuoteSource()
    with pytest.raises(CoinbaseBtcQuoteSourceError):
        source.get_recent_candles(limit=10)


def test_requests_the_configured_product_and_one_minute_granularity(monkeypatch):
    captured: list = []
    body = _rows((1700000000, 100.0))
    _patch_urlopen(monkeypatch, body=body, capture=captured)
    source = CoinbaseBtcQuoteSource(product_id="BTC-USD")
    source.get_recent_candles(limit=10)

    assert len(captured) == 1
    assert "BTC-USD" in captured[0].full_url
    assert "granularity=60" in captured[0].full_url


# --- Live-incident fix: explicit, now-anchored start/end on every call -----
# Root cause of the stuck-feed incident: every request used the IDENTICAL
# URL every time (no start/end at all) -- Coinbase's own documented
# behavior is that omitting either one means BOTH are ignored, leaving the
# exact window undefined and identical request-to-request, exactly what a
# caching layer would serve a stale cached response to. These tests lock
# in the fix: every request now carries an explicit, unique, now-anchored
# start/end.

def test_request_includes_explicit_start_and_end_anchored_to_now(monkeypatch):
    captured: list = []
    body = _rows((1700000000, 100.0))
    _patch_urlopen(monkeypatch, body=body, capture=captured)
    source = CoinbaseBtcQuoteSource()
    now = datetime(2026, 10, 9, 18, 44, 0, tzinfo=timezone.utc)

    source.get_recent_candles(limit=5, now=now)

    query = urllib.parse.parse_qs(urllib.parse.urlparse(captured[0].full_url).query)
    assert query["end"] == [now.isoformat()]
    start = datetime.fromisoformat(query["start"][0])
    assert start < now  # a real window, not a degenerate/empty one
    assert (now - start).total_seconds() == pytest.approx(60 * (5 + 5))  # limit + buffer candles' worth


def test_two_calls_one_minute_apart_produce_different_request_urls(monkeypatch):
    """Directly reproduces (and proves fixed) the live symptom: every
    refresh used to send the EXACT same URL, request after request, with
    no time-varying parameter at all -- exactly what let a stale cached
    response go undetected for minutes."""
    captured: list = []
    body = _rows((1700000000, 100.0))
    _patch_urlopen(monkeypatch, body=body, capture=captured)
    source = CoinbaseBtcQuoteSource()

    source.get_recent_candles(limit=5, now=datetime(2026, 10, 9, 18, 42, 0, tzinfo=timezone.utc))
    source.get_recent_candles(limit=5, now=datetime(2026, 10, 9, 18, 43, 0, tzinfo=timezone.utc))
    source.get_recent_candles(limit=5, now=datetime(2026, 10, 9, 18, 44, 0, tzinfo=timezone.utc))

    urls = [c.full_url for c in captured]
    assert len(set(urls)) == 3  # every single request is genuinely unique


def test_defaults_now_to_the_real_wall_clock_when_not_given(monkeypatch):
    captured: list = []
    body = _rows((1700000000, 100.0))
    _patch_urlopen(monkeypatch, body=body, capture=captured)
    source = CoinbaseBtcQuoteSource()
    before = datetime.now(timezone.utc)

    source.get_recent_candles(limit=5)

    after = datetime.now(timezone.utc)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(captured[0].full_url).query)
    end = datetime.fromisoformat(query["end"][0])
    assert before <= end <= after


def test_request_and_response_details_are_logged(monkeypatch, caplog):
    body = _rows((1700000120, 100.2), (1700000060, 99.2))
    _patch_urlopen(monkeypatch, body=body)
    source = CoinbaseBtcQuoteSource()
    now = datetime(2026, 10, 9, 18, 44, 0, tzinfo=timezone.utc)

    with caplog.at_level("INFO", logger="src.polymarket.btc_coinbase_source"):
        source.get_recent_candles(limit=5, now=now)

    messages = [r.getMessage() for r in caplog.records]
    request_logs = [m for m in messages if "coinbase candles request:" in m]
    response_logs = [m for m in messages if "coinbase candles response:" in m]
    assert len(request_logs) == 1
    assert "'start'" in request_logs[0] and "'end'" in request_logs[0]  # provider URL parameters
    assert len(response_logs) == 1
    assert "status=200" in response_logs[0]  # HTTP response status
    assert "rows=2" in response_logs[0]  # number of candles returned
    assert "2023-11-14T22:15:20+00:00" in response_logs[0]  # newest_in_raw_response (1700000120)


def test_transport_failure_is_logged_with_request_params(monkeypatch, caplog):
    _patch_urlopen(monkeypatch, raise_exc=urllib.error.URLError("connection refused"))
    source = CoinbaseBtcQuoteSource()

    with caplog.at_level("WARNING", logger="src.polymarket.btc_coinbase_source"):
        with pytest.raises(CoinbaseBtcQuoteSourceError):
            source.get_recent_candles(limit=5)

    messages = [r.getMessage() for r in caplog.records]
    assert any("request failed" in m and "'start'" in m for m in messages)


# --- get_historical_candles: real HISTORICAL (not just recent) pulls ------

def _fake_urlopen_from_range(monkeypatch, *, capture: list | None = None):
    """A fake transport that, given ANY request's own start/end params,
    synthesizes one real-shaped 1-minute-candle row per minute boundary
    in that exact window -- so a multi-chunk historical pull can be
    tested without hand-building each chunk's expected response body."""
    def fake_urlopen(request, timeout=None):
        if capture is not None:
            capture.append(request)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        start = datetime.fromisoformat(query["start"][0])
        end = datetime.fromisoformat(query["end"][0])
        rows = []
        t = start.replace(second=0, microsecond=0)
        if t < start:
            t += timedelta(minutes=1)
        while t < end:
            price = 100.0 + (t.timestamp() % 1000) / 100.0
            rows.append([int(t.timestamp()), price - 1.0, price + 1.0, price - 0.5, price, 2.5])
            t += timedelta(minutes=1)
        rows.reverse()  # Coinbase returns newest-first
        return _FakeHttpResponse(json.dumps(rows).encode())
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)


def test_historical_candles_covers_the_full_range_oldest_first(monkeypatch):
    _fake_urlopen_from_range(monkeypatch)
    source = CoinbaseBtcQuoteSource()
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc)  # 10 one-minute candles, well under one chunk

    bars = source.get_historical_candles(start=start, end=end)

    assert len(bars) == 10
    assert bars[0].start_time == start
    assert bars[-1].start_time == end - timedelta(minutes=1)
    assert bars == sorted(bars, key=lambda b: b.start_time)  # oldest first


def test_historical_candles_pages_across_multiple_chunks(monkeypatch):
    captured: list = []
    _fake_urlopen_from_range(monkeypatch, capture=captured)
    source = CoinbaseBtcQuoteSource()
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    # 301 minutes -- one more candle than fits in a single 300-candle chunk.
    end = start + timedelta(minutes=301)

    bars = source.get_historical_candles(start=start, end=end)

    assert len(bars) == 301
    assert len(captured) == 2  # had to page: 300 + 1
    assert bars[0].start_time == start
    assert bars[-1].start_time == end - timedelta(minutes=1)
    # No duplicate timestamps even though chunk boundaries could overlap.
    assert len(bars) == len({b.start_time for b in bars})


def test_historical_candles_rejects_a_start_not_before_end():
    source = CoinbaseBtcQuoteSource()
    same = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        source.get_historical_candles(start=same, end=same)
    with pytest.raises(ValueError):
        source.get_historical_candles(start=same, end=same - timedelta(minutes=1))


def test_historical_candles_chunk_failure_raises_not_a_partial_silent_result(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeHttpResponse(json.dumps([[1700000000, 99.0, 101.0, 99.5, 100.0, 1.0]]).encode())
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    source = CoinbaseBtcQuoteSource()
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=600)  # forces at least 2 chunks

    with pytest.raises(CoinbaseBtcQuoteSourceError):
        source.get_historical_candles(start=start, end=end)


def test_historical_candles_never_sleeps_by_default(monkeypatch):
    """request_delay_seconds defaults to 0 -- tests (and a short,
    single-chunk real pull) must never actually block."""
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))
    _fake_urlopen_from_range(monkeypatch)
    source = CoinbaseBtcQuoteSource()
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=600)  # 2 chunks

    source.get_historical_candles(start=start, end=end)

    assert sleep_calls == []


def test_historical_candles_respects_a_nonzero_request_delay(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))
    _fake_urlopen_from_range(monkeypatch)
    source = CoinbaseBtcQuoteSource()
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=600)  # 2 chunks -- 1 inter-chunk delay

    source.get_historical_candles(start=start, end=end, request_delay_seconds=0.5)

    assert sleep_calls == [0.5]
