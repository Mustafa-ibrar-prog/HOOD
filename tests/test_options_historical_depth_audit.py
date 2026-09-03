"""Phase 24, Parts 2/6/7/18 — the extended capability matrix and the
real historical-depth probes it's built from."""

from __future__ import annotations

from src.options.capability_audit import OPTIONS_CAPABILITY_MATRIX
from src.options.historical_depth_audit import (
    HISTORICAL_DEPTH_PROBES,
    POINT_IN_TIME_EXISTENCE_RECONCILIATION,
    extended_capability_matrix,
    historical_depth_lower_bound,
)


def test_extended_matrix_is_purely_additive_to_phase18s_matrix():
    """Every row Phase 18 already established must still be present,
    unmodified, in the extended matrix -- Phase 24 adds, never edits."""
    extended = extended_capability_matrix()
    assert len(extended) == len(OPTIONS_CAPABILITY_MATRIX) + 1
    for original_row in OPTIONS_CAPABILITY_MATRIX:
        assert original_row in extended


def test_extended_matrix_new_row_is_about_chain_enumeration_depth():
    extended = extended_capability_matrix()
    new_rows = [r for r in extended if r not in OPTIONS_CAPABILITY_MATRIX]
    assert len(new_rows) == 1
    assert "expired" in new_rows[0].data_field.lower()


def test_historical_depth_probes_include_at_least_one_empty_and_one_populated_result():
    """The boundary-finding methodology requires bracketing: at least
    one probe must have found nothing (proving the enumeration doesn't
    fabricate contracts for dates before real coverage) and at least one
    must have found real contracts."""
    found = [p for p in HISTORICAL_DEPTH_PROBES if p.contracts_found]
    empty = [p for p in HISTORICAL_DEPTH_PROBES if not p.contracts_found]
    assert found and empty


def test_historical_depth_lower_bound_is_the_earliest_populated_probe():
    found_dates = sorted(p.expiration_date_tested for p in HISTORICAL_DEPTH_PROBES if p.contracts_found)
    assert historical_depth_lower_bound() == found_dates[0]


def test_historical_depth_lower_bound_is_after_every_empty_probe():
    """The claimed lower bound must not precede an empty probe -- that
    would mean asserting coverage where a real probe found none."""
    lower_bound = historical_depth_lower_bound()
    empty_dates = [p.expiration_date_tested for p in HISTORICAL_DEPTH_PROBES if not p.contracts_found]
    for empty_date in empty_dates:
        assert empty_date <= lower_bound  # ISO date strings sort chronologically


def test_point_in_time_reconciliation_explicitly_distinguishes_existence_from_pit_listing():
    text = POINT_IN_TIME_EXISTENCE_RECONCILIATION.lower()
    assert "did this contract ever exist" in text
    assert "listed and tradable on date t" in text
    assert "historical_contract_existence_unknown" in text


def test_every_probe_has_a_note_explaining_its_evidence():
    for probe in HISTORICAL_DEPTH_PROBES:
        assert probe.note and len(probe.note) > 10
