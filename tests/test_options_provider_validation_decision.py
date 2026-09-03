"""Phase 25, Parts 26/27 — the final decision and purchase
recommendation: the decision is exactly one of the 5 allowed values, and
the recommendation structurally cannot be marked as acted-upon."""

from __future__ import annotations

import pytest

from src.options.provider_validation_decision import (
    FINAL_DECISION,
    FINAL_DECISION_RATIONALE,
    PURCHASE_RECOMMENDATION,
    FinalDecision,
    PurchaseRecommendation,
)


def test_final_decision_enum_has_exactly_the_five_required_values():
    assert {v.value for v in FinalDecision} == {
        "orats_verified_research_ready",
        "orats_promising_but_unverified",
        "alternative_provider_verified",
        "no_provider_verified",
        "historical_options_data_still_insufficient",
    }


def test_final_decision_is_one_of_the_allowed_values():
    assert FINAL_DECISION in set(FinalDecision)


def test_final_decision_is_not_verified_research_ready():
    """No live ORATS probe was ever made -- the strongest honest decision
    available this phase cannot be the VERIFIED variant."""
    assert FINAL_DECISION != FinalDecision.ORATS_VERIFIED_RESEARCH_READY


def test_final_decision_rationale_is_substantive():
    assert len(FINAL_DECISION_RATIONALE) > 100
    assert "PAID_PROOF_REQUIRED" in FINAL_DECISION_RATIONALE


def test_purchase_recommendation_always_awaits_human_approval():
    assert PURCHASE_RECOMMENDATION.awaiting_human_approval is True


def test_purchase_recommendation_cannot_be_constructed_as_acted_upon():
    with pytest.raises(ValueError):
        PurchaseRecommendation(
            recommended_provider="X", exact_product="X", why="X", fields_available="X",
            historical_depth="X", approximate_cost="X", trial_availability="X", licensing="X",
            expected_research_gain="X", awaiting_human_approval=False,
        )


def test_purchase_recommendation_has_every_required_field_populated():
    r = PURCHASE_RECOMMENDATION
    for field_name in (
        "recommended_provider", "exact_product", "why", "fields_available", "historical_depth",
        "approximate_cost", "trial_availability", "licensing", "expected_research_gain",
    ):
        value = getattr(r, field_name)
        assert isinstance(value, str) and len(value) > 0, field_name


def test_purchase_recommendation_trial_availability_says_paid_proof_required():
    assert "PAID_PROOF_REQUIRED" in PURCHASE_RECOMMENDATION.trial_availability
