"""Phase 19, Part 19 — dynamic options-underlying universe tests."""

from __future__ import annotations

import pytest

from src.options.universe import (
    OptionableUnderlying,
    UnderlyingFilterConfig,
    UnderlyingUniverse,
    phase19_verified_underlying_universe,
)


def test_verified_flag_requires_evidence_note():
    with pytest.raises(ValueError):
        OptionableUnderlying("AAPL", "equity", "technology", has_verified_historical_options=True, evidence_note="")


def test_verified_flag_with_evidence_note_ok():
    m = OptionableUnderlying("AAPL", "equity", "technology", has_verified_historical_options=True, evidence_note="real probe")
    assert m.has_verified_historical_options is True


def test_unverified_member_needs_no_evidence_note():
    m = OptionableUnderlying("XYZ", "equity", None, has_verified_historical_options=False)
    assert m.evidence_note == ""


def test_duplicate_symbols_rejected():
    members = (
        OptionableUnderlying("AAPL", "equity", "technology", has_verified_historical_options=False),
        OptionableUnderlying("AAPL", "equity", "technology", has_verified_historical_options=False),
    )
    with pytest.raises(ValueError):
        UnderlyingUniverse(name="X", description="", members=members, source_equity_universe_name="US_DIVERSIFIED")


def test_phase19_verified_universe_has_real_evidence_for_every_member():
    universe = phase19_verified_underlying_universe()
    assert universe.symbols == ("AAPL", "NVDA", "SPY", "TSLA")
    for m in universe.members:
        assert m.has_verified_historical_options is True
        assert m.evidence_note
        assert "2022-03-18" in m.verified_expirations


def test_live_flag_not_set_by_phase19():
    universe = phase19_verified_underlying_universe()
    for m in universe.members:
        assert m.has_verified_live_options is False


def test_filter_by_historical_verification():
    universe = phase19_verified_underlying_universe()
    config = UnderlyingFilterConfig(require_verified_historical_options=True)
    filtered = universe.filtered(config)
    assert filtered.symbols == universe.symbols


def test_filter_by_live_verification_excludes_everyone():
    """No member has verified LIVE options this phase -- filtering on it must yield an empty universe, not a guess."""
    universe = phase19_verified_underlying_universe()
    config = UnderlyingFilterConfig(require_verified_live_options=True)
    filtered = universe.filtered(config)
    assert filtered.symbols == ()


def test_filter_by_asset_type():
    universe = phase19_verified_underlying_universe()
    config = UnderlyingFilterConfig(asset_types=("etf",))
    filtered = universe.filtered(config)
    assert filtered.symbols == ("SPY",)


def test_member_lookup():
    universe = phase19_verified_underlying_universe()
    assert universe.member("NVDA") is not None
    assert universe.member("MISSING") is None
