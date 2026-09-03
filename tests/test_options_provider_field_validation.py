"""Phase 25, Part 4/25 — the ORATS field validation matrix: every row
uses exactly the 4 required classification values, is honestly tagged
with its real evidence tier, and no row silently claims
VERIFIED_AVAILABLE when only secondary evidence was gathered."""

from __future__ import annotations

from src.options.provider_field_validation import (
    ORATS_FIELD_VALIDATION_MATRIX,
    PAID_PROOF_REQUIRED_LOG,
    EvidenceTier,
    FieldClassification,
    rows_by_classification,
)


def test_matrix_has_a_meaningful_number_of_rows():
    assert len(ORATS_FIELD_VALIDATION_MATRIX) >= 15


def test_every_row_classification_is_one_of_the_four_required_values():
    allowed = {
        FieldClassification.VERIFIED_AVAILABLE,
        FieldClassification.VERIFIED_UNAVAILABLE,
        FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED,
        FieldClassification.UNKNOWN,
    }
    for row in ORATS_FIELD_VALIDATION_MATRIX:
        assert row.classification in allowed


def test_no_row_is_verified_available():
    """No live ORATS API call was ever made this phase (Part 2: no
    purchase, no payment credentials) -- nothing can honestly be
    VERIFIED_AVAILABLE."""
    for row in ORATS_FIELD_VALIDATION_MATRIX:
        assert row.classification != FieldClassification.VERIFIED_AVAILABLE, row.field_category


def test_no_row_is_verified_unavailable():
    """Nothing was ever confirmed absent via a real probe either."""
    for row in ORATS_FIELD_VALIDATION_MATRIX:
        assert row.classification != FieldClassification.VERIFIED_UNAVAILABLE, row.field_category


def test_claimed_available_rows_are_never_tagged_as_own_live_api_probe():
    """A CLAIMED_AVAILABLE_UNVERIFIED row must never claim the strongest
    evidence tier -- that combination would misrepresent secondary
    evidence as a live probe."""
    for row in ORATS_FIELD_VALIDATION_MATRIX:
        if row.classification == FieldClassification.CLAIMED_AVAILABLE_UNVERIFIED:
            assert row.evidence_tier != EvidenceTier.OWN_LIVE_API_PROBE, row.field_category


def test_unknown_rows_have_no_evidence_or_are_explicitly_weak():
    for row in ORATS_FIELD_VALIDATION_MATRIX:
        if row.classification == FieldClassification.UNKNOWN:
            assert row.evidence_tier != EvidenceTier.OWN_LIVE_API_PROBE, row.field_category


def test_pit_and_expired_contract_rows_are_present_and_unverified():
    """Part 5/7's specific tests must show up as real rows, not be
    skipped."""
    categories = {row.field_category.lower() for row in ORATS_FIELD_VALIDATION_MATRIX}
    assert any("historical date-scoped" in c or "point-in-time" in c for c in categories)
    assert any("expired-contract" in c for c in categories)


def test_contract_identity_gaps_are_marked_unknown_not_assumed():
    """multiplier/exercise_style/contract_status must not be silently
    presented as available -- Part 4's own instruction."""
    unknown_categories = {row.field_category.lower() for row in ORATS_FIELD_VALIDATION_MATRIX
                           if row.classification == FieldClassification.UNKNOWN}
    joined = " ".join(unknown_categories)
    assert "exercise_style" in joined
    assert "multiplier" in joined
    assert "first_listed_date" in joined or "last_trading_date" in joined


def test_rows_by_classification_covers_every_row_exactly_once():
    grouped = rows_by_classification()
    total = sum(len(v) for v in grouped.values())
    assert total == len(ORATS_FIELD_VALIDATION_MATRIX)


def test_no_field_category_is_duplicated():
    categories = [row.field_category for row in ORATS_FIELD_VALIDATION_MATRIX]
    assert len(categories) == len(set(categories))


def test_paid_proof_required_log_covers_orats():
    providers = {e.provider for e in PAID_PROOF_REQUIRED_LOG}
    assert "ORATS" in providers
    for entry in PAID_PROOF_REQUIRED_LOG:
        assert entry.classification == "PAID_PROOF_REQUIRED"
        assert len(entry.requirement_note) > 10


def test_every_row_cites_real_evidence_text():
    for row in ORATS_FIELD_VALIDATION_MATRIX:
        assert len(row.evidence_source) > 10
        assert len(row.notes) > 10
