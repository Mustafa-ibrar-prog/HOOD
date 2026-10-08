"""Tests for scripts/feed_btc_quote.py -- the interim, agent/human-
assisted bridge that records one real BTC quote sample at a time (see
btc_market_data.py's module docstring on why there's no automated
poller)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.feed_btc_quote import main  # noqa: E402
from src.polymarket.btc_market_data import BtcPriceHistoryStore  # noqa: E402


def _env(tmp_path, **overrides):
    env = {"POLYMARKET_BTC_PRICE_HISTORY_FILE": str(tmp_path / "btc.json")}
    env.update(overrides)
    return env


def _run(monkeypatch, tmp_path, argv, **env_overrides) -> int:
    monkeypatch.setattr(sys, "argv", ["feed_btc_quote.py", *argv])
    for key, value in _env(tmp_path, **env_overrides).items():
        monkeypatch.setenv(key, value)
    return main()


def test_feed_with_explicit_price_records_one_sample(monkeypatch, tmp_path, capsys):
    rc = _run(monkeypatch, tmp_path, ["feed", "--price", "67123.45"])
    assert rc == 0
    assert "67123.45" in capsys.readouterr().out
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    samples = store.load()
    assert len(samples) == 1
    assert samples[0].price == 67123.45


def test_feed_with_explicit_timestamp(monkeypatch, tmp_path):
    rc = _run(monkeypatch, tmp_path, ["feed", "--price", "100.0", "--at", "2026-01-01T00:00:00+00:00"])
    assert rc == 0
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    assert store.load()[0].observed_at.isoformat() == "2026-01-01T00:00:00+00:00"


def test_feed_from_quotes_json_file_extracts_mark_price(monkeypatch, tmp_path):
    response_path = tmp_path / "response.json"
    response_path.write_text(json.dumps({"results": [{"symbol": "BTCUSD", "mark_price": "67310.00"}]}))
    rc = _run(monkeypatch, tmp_path, ["feed", "--quotes-json", str(response_path), "--symbol", "BTC-USD"])
    assert rc == 0
    store = BtcPriceHistoryStore(tmp_path / "btc.json")
    assert store.load()[0].price == 67310.00


def test_feed_from_quotes_json_missing_symbol_fails_cleanly(monkeypatch, tmp_path, capsys):
    response_path = tmp_path / "response.json"
    response_path.write_text(json.dumps({"results": [{"symbol": "ETHUSD", "mark_price": "3000.0"}]}))
    rc = _run(monkeypatch, tmp_path, ["feed", "--quotes-json", str(response_path), "--symbol", "BTC-USD"])
    assert rc == 1
    assert "No mark price found" in capsys.readouterr().out
    assert BtcPriceHistoryStore(tmp_path / "btc.json").load() == []


def test_show_reports_closed_bars_from_fed_samples(monkeypatch, tmp_path, capsys):
    _run(monkeypatch, tmp_path, ["feed", "--price", "100.0", "--at", "2026-01-01T00:00:00+00:00"])
    _run(monkeypatch, tmp_path, ["feed", "--price", "110.0", "--at", "2026-01-01T00:05:00+00:00"])
    rc = _run(monkeypatch, tmp_path, ["show", "--interval-seconds", "3600"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 closed 3600s bar" in out


def test_show_with_no_samples_reports_zero_bars(monkeypatch, tmp_path, capsys):
    rc = _run(monkeypatch, tmp_path, ["show"])
    assert rc == 0
    assert "0 closed" in capsys.readouterr().out
