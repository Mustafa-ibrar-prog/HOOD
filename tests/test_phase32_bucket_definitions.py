"""Phase 32, Part 1/21 — preregistered bucket definitions."""

from __future__ import annotations

from src.options.phase32_bucket_definitions import (
    COARSE_SCHEME,
    FINE_SCHEME,
    PREREGISTERED_SCHEMES,
)


def test_two_schemes_preregistered():
    assert len(PREREGISTERED_SCHEMES) == 2
    assert {s.name for s in PREREGISTERED_SCHEMES} == {"fine", "coarse"}


def test_fine_scheme_matches_existing_dte_and_moneyness_taxonomy():
    assert FINE_SCHEME.dte_values == ("0-7", "8-30", "31-60", "61-120", "120+")
    assert FINE_SCHEME.moneyness_values == ("deep_itm", "itm", "near_atm", "otm", "deep_otm")


def test_fine_scheme_passes_through_unchanged():
    assert FINE_SCHEME.coarsen_dte("8-30") == "8-30"
    assert FINE_SCHEME.coarsen_moneyness("deep_otm") == "deep_otm"


def test_fine_scheme_rejects_expired():
    assert FINE_SCHEME.coarsen_dte("expired") is None


def test_coarse_scheme_merges_correctly():
    assert COARSE_SCHEME.coarsen_dte("0-7") == "short"
    assert COARSE_SCHEME.coarsen_dte("8-30") == "short"
    assert COARSE_SCHEME.coarsen_dte("31-60") == "medium"
    assert COARSE_SCHEME.coarsen_dte("61-120") == "medium"
    assert COARSE_SCHEME.coarsen_dte("120+") == "long"
    assert COARSE_SCHEME.coarsen_moneyness("deep_itm") == "itm_side"
    assert COARSE_SCHEME.coarsen_moneyness("itm") == "itm_side"
    assert COARSE_SCHEME.coarsen_moneyness("near_atm") == "near_atm"
    assert COARSE_SCHEME.coarsen_moneyness("otm") == "otm_side"
    assert COARSE_SCHEME.coarsen_moneyness("deep_otm") == "otm_side"


def test_coarse_scheme_covers_every_fine_value():
    for v in FINE_SCHEME.dte_values:
        assert COARSE_SCHEME.coarsen_dte(v) is not None
    for v in FINE_SCHEME.moneyness_values:
        assert COARSE_SCHEME.coarsen_moneyness(v) is not None


def test_none_input_never_fabricates_a_bucket():
    assert FINE_SCHEME.coarsen_dte(None) is None
    assert COARSE_SCHEME.coarsen_dte(None) is None
    assert FINE_SCHEME.coarsen_moneyness(None) is None
    assert COARSE_SCHEME.coarsen_moneyness(None) is None
