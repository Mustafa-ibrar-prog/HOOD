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
