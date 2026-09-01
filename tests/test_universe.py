"""Tests for the Universe abstraction (Phase 5, sections 1-3, 5)."""

from __future__ import annotations

from datetime import date

import pytest

from src.data.universe import (
    CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED,
    Universe,
    UniverseMember,
    test_universe as make_test_universe,
    us_diversified_universe,
    us_etf_benchmark_universe,
    us_small_cap_volatile_universe,
)


def test_universe_rejects_duplicate_symbols():
    with pytest.raises(ValueError, match="duplicate"):
        Universe(name="X", description="", members=(UniverseMember("AAPL", "equity", "tech"), UniverseMember("AAPL", "equity", "tech")), inclusion_rules=(), exclusion_rules=())


def test_universe_symbols_property():
    u = make_test_universe()
    assert u.symbols == ("AAPL", "JPM", "XOM")


def test_universe_by_sector():
    u = make_test_universe()
    sectors = u.by_sector()
    assert sectors["technology"] == ("AAPL",)
    assert sectors["financials"] == ("JPM",)


def test_universe_by_asset_type():
    u = us_diversified_universe()
    types = u.by_asset_type()
    assert "equity" in types
    assert "etf" in types
    assert set(types["etf"]) == {"SPY", "QQQ", "IWM"}


def test_sector_of_unknown_symbol_is_none():
    u = make_test_universe()
    assert u.sector_of("NOTREAL") is None


def test_member_is_effective_on_unbounded_window():
    m = UniverseMember("AAPL", "equity", "technology")
    assert m.is_effective_on(date(1990, 1, 1)) is True
    assert m.is_effective_on(date(2099, 1, 1)) is True


def test_member_is_effective_on_bounded_window():
    m = UniverseMember("AAPL", "equity", "technology", effective_start=date(2020, 1, 1), effective_end=date(2021, 1, 1))
    assert m.is_effective_on(date(2020, 6, 1)) is True
    assert m.is_effective_on(date(2019, 1, 1)) is False
    assert m.is_effective_on(date(2022, 1, 1)) is False


def test_symbols_as_of_matches_full_symbols_for_survivorship_biased_universe():
    """The honest limitation: with no historical constituent database,
    symbols_as_of() at ANY date returns the same set as .symbols — this
    IS the survivorship-bias limitation, made observable rather than
    hidden behind a method that looks point-in-time-aware but isn't."""
    u = us_diversified_universe()
    assert u.symbols_as_of(date(2015, 1, 1)) == u.symbols
    assert u.symbols_as_of(date(2026, 1, 1)) == u.symbols


def test_all_builtin_universes_are_labeled_survivorship_biased():
    for factory in (us_diversified_universe, us_small_cap_volatile_universe, us_etf_benchmark_universe, make_test_universe):
        assert factory().survivorship_bias_status == CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED


def test_diversified_universe_has_multiple_sectors():
    u = us_diversified_universe()
    sectors = u.by_sector()
    assert len(sectors) >= 6  # genuinely diversified, not concentrated in 1-2 sectors


def test_small_cap_universe_is_the_original_phase4_five():
    u = us_small_cap_volatile_universe()
    assert set(u.symbols) == {"NIO", "MARA", "SOFI", "SOUN", "PLUG"}
