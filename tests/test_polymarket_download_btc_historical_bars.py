"""Tests for scripts/download_btc_historical_bars.py -- the CLI that
downloads real historical BTC 1-minute candles (via
CoinbaseBtcQuoteSource.get_historical_candles) and saves/merges them
into a local JSON file the backtest script's --bars-file can load.
Never makes a real network call -- CoinbaseBtcQuoteSource itself is
replaced with a deterministic fake throughout."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.download_btc_historical_bars as downloader  # noqa: E402
from src.market.models import PriceBar  # noqa: E402
from src.polymarket.btc_coinbase_source import CoinbaseBtcQuoteSourceError  # noqa: E402

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeSource:
    def __init__(self, *, product_id: str = "BTC-USD"):
        self.product_id = product_id
        self.calls: list[dict] = []
        self.bars: list[PriceBar] = []
        self.raise_exc: Exception | None = None

    def get_historical_candles(self, *, start, end, request_delay_seconds=0.0):
        self.calls.append({"start": start, "end": end, "request_delay_seconds": request_delay_seconds})
        if self.raise_exc is not None:
            raise self.raise_exc
        return [b for b in self.bars if start <= b.start_time < end]


def _bars(n: int, *, start: datetime = _START, price: float = 65_000.0) -> list[PriceBar]:
    return [
        PriceBar(start_time=start + timedelta(minutes=i), open=price + i, high=price + i + 1, low=price + i - 1, close=price + i, volume=1.0)
        for i in range(n)
    ]


def _run(monkeypatch, argv, *, fake: "_FakeSource | None" = None) -> tuple[int, "_FakeSource"]:
    fake = fake or _FakeSource()
    monkeypatch.setattr(downloader, "CoinbaseBtcQuoteSource", lambda product_id="BTC-USD": fake)
    monkeypatch.setattr(sys, "argv", ["download_btc_historical_bars.py", *argv])
    rc = downloader.main()
    return rc, fake


def test_downloads_and_saves_real_shaped_bars(monkeypatch, tmp_path, capsys):
    fake = _FakeSource()
    fake.bars = _bars(5)
    output = tmp_path / "bars.json"

    rc, _ = _run(monkeypatch, ["--start", "2026-01-01", "--end", "2026-01-01T00:05:00", "--output", str(output)], fake=fake)

    assert rc == 0
    saved = json.loads(output.read_text())
    assert len(saved) == 5
    assert saved[0]["start_time"] == _START.isoformat()
    assert {"start_time", "open", "high", "low", "close", "volume"} <= saved[0].keys()
    assert "Downloaded 5" in capsys.readouterr().out


def test_rerun_merges_and_deduplicates_with_existing_output(monkeypatch, tmp_path):
    output = tmp_path / "bars.json"
    fake1 = _FakeSource()
    fake1.bars = _bars(5, start=_START)
    _run(monkeypatch, ["--start", "2026-01-01T00:00:00", "--end", "2026-01-01T00:05:00", "--output", str(output)], fake=fake1)

    # Second run overlaps the first by 2 minutes and extends 3 further.
    fake2 = _FakeSource()
    fake2.bars = _bars(5, start=_START + timedelta(minutes=3))
    rc, _ = _run(monkeypatch, ["--start", "2026-01-01T00:03:00", "--end", "2026-01-01T00:08:00", "--output", str(output)], fake=fake2)

    assert rc == 0
    saved = json.loads(output.read_text())
    timestamps = [row["start_time"] for row in saved]
    assert len(timestamps) == len(set(timestamps))  # no duplicates despite the overlap
    assert len(saved) == 8  # 0..7 minutes, 8 distinct one-minute bars total


def test_start_not_before_end_is_rejected(monkeypatch, tmp_path, capsys):
    output = tmp_path / "bars.json"
    rc, _ = _run(monkeypatch, ["--start", "2026-01-01T00:05:00", "--end", "2026-01-01T00:00:00", "--output", str(output)])
    assert rc == 2
    assert not output.exists()
    assert "must be before" in capsys.readouterr().err


def test_provider_failure_mid_download_writes_nothing_new(monkeypatch, tmp_path, capsys):
    output = tmp_path / "bars.json"
    output.write_text(json.dumps([{"start_time": _START.isoformat(), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}]))
    fake = _FakeSource()
    fake.raise_exc = CoinbaseBtcQuoteSourceError("boom")

    rc, _ = _run(monkeypatch, ["--start", "2026-01-02", "--end", "2026-01-03", "--output", str(output)], fake=fake)

    assert rc == 1
    assert "download failed" in capsys.readouterr().err
    # The pre-existing file is completely untouched by the failed attempt.
    assert json.loads(output.read_text()) == [{"start_time": _START.isoformat(), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}]


def test_zero_candles_returned_is_not_an_error(monkeypatch, tmp_path, capsys):
    output = tmp_path / "bars.json"
    rc, _ = _run(monkeypatch, ["--start", "2026-01-01", "--end", "2026-01-02", "--output", str(output)])
    assert rc == 0
    assert not output.exists()
    assert "zero candles" in capsys.readouterr().err


def test_request_delay_seconds_is_forwarded_to_the_source(monkeypatch, tmp_path):
    fake = _FakeSource()
    fake.bars = _bars(3)
    output = tmp_path / "bars.json"

    _run(monkeypatch, [
        "--start", "2026-01-01T00:00:00", "--end", "2026-01-01T00:03:00",
        "--output", str(output), "--request-delay-seconds", "1.25",
    ], fake=fake)

    assert fake.calls[0]["request_delay_seconds"] == 1.25


def test_parse_datetime_accepts_z_suffix_and_naive_strings_as_utc():
    assert downloader._parse_datetime("2026-01-01T00:00:00Z") == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert downloader._parse_datetime("2026-01-01") == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert downloader._parse_datetime("2026-01-01T05:00:00+05:00") == datetime(2026, 1, 1, tzinfo=timezone.utc)
