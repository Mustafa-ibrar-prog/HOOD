"""Phase 37, Part 6/23 — market-hours gating (behaviorally identical to
`is_within_monitoring_window` without importing it, since that module
transitively imports `src.execution.gateway`) and credential redaction.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.config.settings import Settings
from src.research_recorder.market_hours import is_market_open_for_recording
from src.research_recorder.recorder import MARKET_CLOSED
from src.research_recorder.security import assert_no_credential_shaped_content, redact


def _settings():
    return Settings.from_env(env={"TRADING_MODE": "paper"})


def test_matches_is_within_monitoring_window_semantics():
    """Deliberately reimplements is_within_monitoring_window's logic --
    this test proves the two stay behaviorally identical without this
    package ever importing position_manager.monitor (see market_hours.py's
    module docstring)."""
    from src.position_manager.monitor import is_within_monitoring_window

    settings = _settings()
    cases = [
        datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc),  # Tuesday, within hours
        datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc),  # Saturday
        datetime(2026, 8, 18, 3, 0, tzinfo=timezone.utc),  # Tuesday, before hours (UTC 3am = ET 11pm prior day)
        datetime(2026, 8, 18, 12, 0),  # naive, within local hours
    ]
    for now in cases:
        assert is_market_open_for_recording(now, settings) == is_within_monitoring_window(now, settings)


def test_market_closed_on_weekend_returns_the_literal_sentinel_from_recorder():
    from src.market.data_provider import MarketDataProvider
    from src.research_recorder.recorder import RecorderConfig, RecorderStores, run_observation_cycle
    from src.research_recorder.storage import CycleLogStore, NormalizedOptionStore, NormalizedUnderlyingStore, RawObservationStore, ResearchSignalStore
    import tempfile
    from pathlib import Path

    class _UnusedClient:
        def get_equity_quotes(self, symbols):
            raise AssertionError("must never be called when the market is closed")

        def get_option_quotes(self, instrument_ids):
            raise AssertionError("must never be called when the market is closed")

    class _UnusedMarket(MarketDataProvider):
        def get_market_snapshot(self, option_id, underlying_symbol, now=None):
            raise AssertionError

        def get_underlying_snapshot(self, symbol, now=None):
            raise AssertionError

        def get_option_expirations(self, underlying_symbol):
            raise AssertionError

        def get_option_chain_candidates(self, underlying_symbol, **filters):
            raise AssertionError("must never be called when the market is closed")

    saturday = datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as d:
        stores = RecorderStores(
            raw=RawObservationStore(Path(d) / "raw.jsonl"), underlying=NormalizedUnderlyingStore(Path(d) / "u.jsonl"),
            option=NormalizedOptionStore(Path(d) / "o.jsonl"), signal=ResearchSignalStore(Path(d) / "s.jsonl"),
            cycle_log=CycleLogStore(Path(d) / "c.jsonl"),
        )
        result = run_observation_cycle(
            client=_UnusedClient(), market=_UnusedMarket(), settings=_settings(), stores=stores, now=saturday,
            universe=["AAPL"],
        )
    assert result == MARKET_CLOSED


# --- Security / redaction ------------------------------------------------------------------------


def test_redact_replaces_api_key_shaped_text():
    text = "Failed to connect: api_key=sk-live-abc123xyz"
    redacted = redact(text)
    assert "sk-live-abc123xyz" not in redacted
    assert "REDACTED" in redacted


def test_redact_replaces_bearer_token():
    text = "Authorization: Bearer abcdef123456"
    redacted = redact(text)
    assert "abcdef123456" not in redacted


def test_redact_leaves_ordinary_text_unchanged():
    text = "get_option_quotes failed for opt-1: connection timeout"
    assert redact(text) == text


def test_assert_no_credential_shaped_content_raises_on_secret_like_text():
    import pytest
    with pytest.raises(ValueError):
        assert_no_credential_shaped_content("password: hunter2")


def test_assert_no_credential_shaped_content_passes_on_clean_text():
    assert_no_credential_shaped_content("get_equity_quotes failed for AAPL: timeout")  # must not raise
