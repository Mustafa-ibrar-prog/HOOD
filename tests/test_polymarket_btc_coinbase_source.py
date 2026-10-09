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

import pytest

from src.polymarket.btc_coinbase_source import CoinbaseBtcQuoteSource, CoinbaseBtcQuoteSourceError


class _FakeHttpResponse:
    def __init__(self, body: bytes):
        self._body = body

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
