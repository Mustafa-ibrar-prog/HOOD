"""Phase 28, Part 4/17 — evidence classification vocabulary."""

from __future__ import annotations

from src.options.phase28_evidence_classification import (
    ORATS_STATUS_UNCHANGED_THIS_PHASE,
    CapabilityEvidence,
    EvidenceClassification,
)


def test_exactly_five_required_values():
    assert {v.value for v in EvidenceClassification} == {
        "verified_by_actual_data", "verified_by_official_documentation",
        "claimed_unverified", "egress_blocked", "unknown",
    }


def test_orats_status_flagged_unchanged():
    assert ORATS_STATUS_UNCHANGED_THIS_PHASE is True


def test_capability_evidence_constructs_with_a_valid_classification():
    rec = CapabilityEvidence("ORATS", "historical_chain", EvidenceClassification.CLAIMED_UNVERIFIED, "real schema, no live call")
    assert rec.classification == EvidenceClassification.CLAIMED_UNVERIFIED


def test_orats_final_decision_from_phase25_is_unchanged():
    """No new actual ORATS API call was made this phase -- the Phase 25
    FinalDecision must still say so."""
    from src.options.provider_validation_decision import FINAL_DECISION, FinalDecision
    assert FINAL_DECISION == FinalDecision.ORATS_PROMISING_BUT_UNVERIFIED
