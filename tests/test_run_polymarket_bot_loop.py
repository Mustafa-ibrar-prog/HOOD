"""Control-flow tests for scripts/run_polymarket_bot.py's own unattended
loop -- specifically the BTC feed-refresh wiring a live incident
revealed had NO visibility: BtcFeedRefresher.maybe_refresh() swallowed
every provider failure with zero logging, so a persistent Coinbase
outage looked identical, from the log, to "nothing is wrong yet."

These tests exercise the REAL loop body in main() (via --max-cycles),
with run_cycle() itself stubbed out (that path is already covered by
test_polymarket_engine.py) so this file stays focused on exactly what
regressed: is maybe_refresh() actually called every loop iteration,
and does every ATTEMPTED refresh (success or failure) get logged with
enough detail to diagnose it live -- request time, newest candle
timestamp, candle age, fresh/stale, and the provider error if any.

Fakes throughout; never a real network call, never a real Polymarket
client.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.run_polymarket_bot as bot  # noqa: E402
from src.market.models import PriceBar  # noqa: E402
from src.polymarket.engine import CycleReport  # noqa: E402
from src.polymarket.logger import PolymarketDecisionLogger  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402

_BASE = datetime(2026, 10, 9, 18, 0, 0, tzinfo=timezone.utc)


class _FakeCoinbaseSource:
    """Replaces CoinbaseBtcQuoteSource entirely -- deterministic,
    controllable success/failure, no real network dependency."""

    name = "fake-coinbase"

    def __init__(self, *, candles: list[PriceBar] | None = None, raise_exc: Exception | None = None):
        self._candles = list(candles or [])
        self.raise_exc = raise_exc
        self.call_count = 0

    def get_recent_candles(self, *, limit: int) -> list[PriceBar]:
        self.call_count += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return self._candles[-limit:] if limit and limit < len(self._candles) else list(self._candles)


def _candles(n: int, *, start: datetime = _BASE) -> list[PriceBar]:
    bars = []
    for i in range(n):
        price = 65000.0 + i
        bars.append(PriceBar(
            start_time=start + timedelta(seconds=i * 60), open=price, high=price + 5, low=price - 5,
            close=price + 1, volume=1.5,
        ))
    return bars


def _isolated_settings(tmp_path: Path, **overrides) -> PolymarketSettings:
    env = {
        "POLYMARKET_BTC_PRICE_HISTORY_FILE": str(tmp_path / "btc.json"),
        "POLYMARKET_DECISION_LOG_FILE": str(tmp_path / "decisions.jsonl"),
        "POLYMARKET_PENDING_ORDERS_FILE": str(tmp_path / "pending.json"),
        "POLYMARKET_EMERGENCY_STOP_FILE": str(tmp_path / "estop.json"),
        "POLYMARKET_DAILY_PNL_FILE": str(tmp_path / "pnl.json"),
        "POLYMARKET_POSITIONS_FILE": str(tmp_path / "positions.json"),
        "POLYMARKET_POLL_INTERVAL_SECONDS": "1",
        **overrides,
    }
    return PolymarketSettings.from_env(env=env)


def _run_bot(
    monkeypatch, tmp_path: Path, *, max_cycles: int, source: _FakeCoinbaseSource,
) -> PolymarketDecisionLogger:
    """Runs the real scripts/run_polymarket_bot.main() loop for exactly
    `max_cycles` iterations, with run_cycle()/the Polymarket client/the
    Coinbase source replaced by fakes -- isolates this test to the BTC
    feed-refresh wiring alone."""
    settings = _isolated_settings(tmp_path)
    monkeypatch.setattr(bot.PolymarketSettings, "from_env", staticmethod(lambda env=None: settings))
    monkeypatch.setattr(bot, "get_polymarket_client", lambda settings: object())
    monkeypatch.setattr(bot, "CoinbaseBtcQuoteSource", lambda: source)
    monkeypatch.setattr(bot, "run_cycle", lambda **kwargs: CycleReport(ran=True))
    monkeypatch.setattr(bot.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(sys, "argv", ["run_polymarket_bot.py", "--max-cycles", str(max_cycles)])

    bot.main()
    return PolymarketDecisionLogger(Path(settings.decision_log_file), also_console=False)


def test_maybe_refresh_is_called_once_per_loop_iteration(tmp_path, monkeypatch):
    """Requirement 1: BtcFeedRefresher.maybe_refresh() must actually be
    called every loop iteration -- a spy on the real method (not a
    replacement) proves the wiring in main(), not just that SOMETHING
    was called."""
    import src.polymarket.btc_market_data as btc_market_data

    call_count = {"n": 0}
    original = btc_market_data.BtcFeedRefresher.maybe_refresh

    def _spy(self, *, now=None):
        call_count["n"] += 1
        return original(self, now=now)

    monkeypatch.setattr(btc_market_data.BtcFeedRefresher, "maybe_refresh", _spy)
    source = _FakeCoinbaseSource(candles=_candles(10))

    _run_bot(monkeypatch, tmp_path, max_cycles=5, source=source)

    assert call_count["n"] == 5  # exactly once per cycle, never skipped, never double-called


def test_a_new_coinbase_request_is_made_on_a_new_minute_boundary(tmp_path, monkeypatch):
    """Requirement 2: within the loop's real cadence, a new provider
    request happens once a new 1-minute boundary is reached -- proven
    here by advancing the wall clock maybe_refresh() actually reads
    between cycles, exactly as a real multi-minute bot run would."""
    import src.polymarket.btc_market_data as btc_market_data

    times = iter([
        _BASE, _BASE + timedelta(seconds=20),              # same minute -- 1 attempt total so far
        _BASE + timedelta(minutes=1, seconds=5),            # new minute -- 2nd attempt
        _BASE + timedelta(minutes=1, seconds=40),           # same minute as above -- still 2
        _BASE + timedelta(minutes=2, seconds=0),             # new minute -- 3rd attempt
    ])
    real_now = datetime.now

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(times)

    monkeypatch.setattr(btc_market_data, "datetime", _FakeDatetime)
    source = _FakeCoinbaseSource(candles=_candles(10))

    _run_bot(monkeypatch, tmp_path, max_cycles=5, source=source)

    # 1 call from the startup bootstrap (unconditional, before the loop
    # starts) + exactly 1 per new minute boundary reached during the
    # loop's 5 iterations above (3 of them) -- never more than that.
    assert source.call_count == 1 + 3


def test_successful_refresh_is_logged_with_request_time_candle_age_and_freshness(tmp_path, monkeypatch):
    """Requirement 3: every refresh attempt/result is logged -- request
    time, newest candle timestamp, candle age, and fresh/stale."""
    source = _FakeCoinbaseSource(candles=_candles(10))
    logger = _run_bot(monkeypatch, tmp_path, max_cycles=1, source=source)

    entries = [e for e in logger.read_all() if e.get("kind") == "btc_feed_refresh"]
    assert len(entries) == 1
    evidence = entries[0]["evidence"]
    assert evidence["request_time"] is not None
    assert evidence["newest_candle_time"] is not None
    assert evidence["candle_age_seconds"] is not None
    assert evidence["feed_label"] in ("FRESH", "STALE")
    assert evidence["provider_error"] is None
    assert evidence["candles_recorded"] == 5  # maybe_refresh()'s own small catch-up window (limit=5)
    assert evidence["provider"] == "fake-coinbase"
    # The startup bootstrap already persisted candles before the loop's
    # first maybe_refresh() call, so both reflect that -- not None.
    assert evidence["newest_persisted_before"] is not None
    assert evidence["newest_persisted_after"] is not None


def test_provider_failure_is_logged_with_the_real_error_and_never_crashes_the_bot(tmp_path, monkeypatch):
    """Requirements 3 and 5: a provider error must be captured verbatim
    in the log (never silently swallowed), and the bot must keep
    running normal cycles regardless -- the BTC feed is isolated from
    Polymarket trading."""
    source = _FakeCoinbaseSource(raise_exc=RuntimeError("Coinbase candles request failed: timed out"))
    logger = _run_bot(monkeypatch, tmp_path, max_cycles=3, source=source)

    entries = [e for e in logger.read_all() if e.get("kind") == "btc_feed_refresh"]
    assert len(entries) == 1  # only one new-minute attempt across these fast, same-minute cycles
    evidence = entries[0]["evidence"]
    assert evidence["provider_error"] == "RuntimeError: Coinbase candles request failed: timed out"
    assert evidence["candle_age_seconds"] is None
    assert evidence["newest_candle_time"] is None
    # Requirement 5: a provider outage never crashes the bot or blocks
    # normal cycles -- main() ran all 3 cycles despite every refresh
    # attempt failing (asserted implicitly: _run_bot returning normally
    # means main() completed --max-cycles 3 without raising).
