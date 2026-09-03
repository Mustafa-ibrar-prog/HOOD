"""Phase 20, Part 1/3/21/24 — the expanded 12-underlying universe and
the real dynamic-discovery evidence record."""

from __future__ import annotations

from src.options.universe import PHASE20_DYNAMIC_DISCOVERY_EVIDENCE, phase20_verified_underlying_universe

TARGET_SYMBOLS = {"NVDA", "TSLA", "SPY", "QQQ", "AAPL", "MSFT", "AMD", "AMZN", "META", "GOOGL", "NFLX", "IWM"}


def test_phase20_universe_covers_every_target_symbol():
    universe = phase20_verified_underlying_universe()
    assert set(universe.symbols) == TARGET_SYMBOLS


def test_phase20_universe_every_member_verified():
    universe = phase20_verified_underlying_universe()
    for m in universe.members:
        assert m.has_verified_historical_options is True
        assert m.evidence_note
        assert len(m.verified_expirations) >= 1


def test_phase20_universe_original_four_have_three_expirations():
    universe = phase20_verified_underlying_universe()
    for sym in ("AAPL", "NVDA", "SPY", "TSLA"):
        member = universe.member(sym)
        assert member is not None
        assert len(member.verified_expirations) == 3


def test_phase20_universe_new_symbols_have_at_least_one_expiration():
    universe = phase20_verified_underlying_universe()
    for sym in ("QQQ", "MSFT", "AMD", "AMZN", "META", "GOOGL", "NFLX", "IWM"):
        member = universe.member(sym)
        assert member is not None
        assert len(member.verified_expirations) >= 1


def test_googl_avoids_the_pre_split_confound():
    """GOOGL's 20:1 split (2022-07) means the only expiration this phase
    uses for it is 2023-06-16 (safely post-split) -- never 2022-06-17."""
    universe = phase20_verified_underlying_universe()
    googl = universe.member("GOOGL")
    assert googl is not None
    assert "2022-06-17" not in googl.verified_expirations
    assert "2023-06-16" in googl.verified_expirations


def test_dynamic_discovery_evidence_is_real_and_nonempty():
    ev = PHASE20_DYNAMIC_DISCOVERY_EVIDENCE
    assert ev.scan_id
    assert ev.total_matching_instruments > 0
    assert len(ev.sample_discovered_symbols) > 0


def test_dynamic_discovery_evidence_overlaps_curated_universe():
    ev = PHASE20_DYNAMIC_DISCOVERY_EVIDENCE
    universe_symbols = set(phase20_verified_underlying_universe().symbols)
    assert set(ev.overlap_with_curated_universe).issubset(universe_symbols)
    assert len(ev.overlap_with_curated_universe) > 0
