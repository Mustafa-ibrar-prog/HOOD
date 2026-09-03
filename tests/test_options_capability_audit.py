"""Phase 18, Part 22/6 — capability audit structure tests."""

from __future__ import annotations

from src.options.capability_audit import OPTIONS_CAPABILITY_MATRIX, OptionsSourceCapability, summarize_capability


def test_matrix_nonempty_and_well_formed():
    assert len(OPTIONS_CAPABILITY_MATRIX) >= 5
    for row in OPTIONS_CAPABILITY_MATRIX:
        assert row.data_field
        assert row.evidence, f"{row.data_field} has no evidence documented"
        assert row.major_caveat, f"{row.data_field} has no major_caveat documented"


def test_contract_identity_is_historically_backfillable():
    row = next(r for r in OPTIONS_CAPABILITY_MATRIX if "Contract identity" in r.data_field)
    assert row.capability == OptionsSourceCapability.HISTORICALLY_BACKFILLABLE


def test_historical_volume_is_unavailable():
    row = next(r for r in OPTIONS_CAPABILITY_MATRIX if r.data_field == "Historical option volume")
    assert row.capability == OptionsSourceCapability.UNAVAILABLE


def test_historical_bid_ask_is_unavailable():
    row = next(r for r in OPTIONS_CAPABILITY_MATRIX if r.data_field == "Historical bid/ask")
    assert row.capability == OptionsSourceCapability.UNAVAILABLE


def test_no_row_claims_paid_required_without_a_source_needing_it():
    """This phase never purchased anything (Part 6 explicit prohibition)
    -- no row should claim a paid source was actually used."""
    for row in OPTIONS_CAPABILITY_MATRIX:
        assert row.capability != OptionsSourceCapability.PAID_REQUIRED


def test_summarize_capability_groups_by_classification():
    summary = summarize_capability()
    assert OptionsSourceCapability.UNAVAILABLE in summary
    assert len(summary[OptionsSourceCapability.UNAVAILABLE]) >= 4
