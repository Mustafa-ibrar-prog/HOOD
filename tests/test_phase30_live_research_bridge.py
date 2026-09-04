"""Phase 30, Part 12/17 — the live/research data-bridge design."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.options.live_research_bridge import (
    DataOrigin,
    MixedOriginError,
    SymbolResearchAvailability,
    label_live,
    label_research,
    live_universe_status,
    research_availability_for_symbol,
)
from src.options.phase27_coverage_report import TARGET_UNDERLYINGS
from src.options.live_research_bridge import assert_single_origin

NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)


def test_all_twelve_target_symbols_are_live_visible():
    statuses = live_universe_status()
    assert len(statuses) == 12
    assert set(s.symbol for s in statuses) == set(TARGET_UNDERLYINGS)
    assert all(s.live_visible for s in statuses)


def test_only_aapl_and_spy_have_historical_research():
    statuses = {s.symbol: s.research_availability for s in live_universe_status()}
    assert statuses["AAPL"] == SymbolResearchAvailability.HAS_HISTORICAL_RESEARCH
    assert statuses["SPY"] == SymbolResearchAvailability.HAS_HISTORICAL_RESEARCH
    for sym in ("NVDA", "TSLA", "QQQ", "MSFT", "AMD", "AMZN", "META", "GOOGL", "NFLX", "IWM"):
        assert statuses[sym] == SymbolResearchAvailability.LIVE_ONLY_NO_HISTORICAL_RESEARCH


def test_research_availability_helper_matches_registry():
    assert research_availability_for_symbol("NVDA") == SymbolResearchAvailability.LIVE_ONLY_NO_HISTORICAL_RESEARCH
    assert research_availability_for_symbol("AAPL") == SymbolResearchAvailability.HAS_HISTORICAL_RESEARCH


def test_single_origin_batch_passes():
    points = [label_live("AAPL", {"bid": 1.0}, retrieved_at=NOW), label_live("AAPL", {"bid": 1.1}, retrieved_at=NOW)]
    assert assert_single_origin(points) == DataOrigin.LIVE


def test_mixed_origin_batch_raises():
    points = [label_live("AAPL", {}, retrieved_at=NOW), label_research("AAPL", {}, retrieved_at=NOW)]
    with pytest.raises(MixedOriginError):
        assert_single_origin(points)


def test_empty_batch_raises_value_error_not_a_default_origin():
    with pytest.raises(ValueError):
        assert_single_origin([])


def test_labeled_points_carry_correct_origin():
    live_pt = label_live("NVDA", {"px": 1.0}, retrieved_at=NOW)
    research_pt = label_research("AAPL", {"px": 1.0}, retrieved_at=NOW)
    assert live_pt.origin == DataOrigin.LIVE
    assert research_pt.origin == DataOrigin.RESEARCH
