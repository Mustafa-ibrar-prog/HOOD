"""Phase 28, Part 9/10/18/17 — provider ranking, human-approval gate
state, and the final phase decision."""

from __future__ import annotations

import pytest

from src.options.phase28_provider_decision import (
    FINAL_DECISION_RATIONALE,
    HUMAN_APPROVAL_GATE_STATE,
    ORATS_STRONGEST_DIMENSIONS,
    PHASE28_FINAL_DECISION,
    PROVIDER_RECOMMENDATION,
    RANKING,
    SELECTED_PRODUCT,
    SELECTED_PROVIDER,
    HumanApprovalGateState,
    Phase28FinalDecision,
    orats_beats_every_other_finalist_on,
)
from src.options.provider_validation_decision import PurchaseRecommendation


def test_ranking_covers_all_five_required_categories():
    assert RANKING.best_overall
    assert RANKING.best_value
    assert RANKING.best_data_quality
    assert RANKING.best_execution_realism
    assert RANKING.best_for_this_project


def test_selected_provider_is_orats():
    assert SELECTED_PROVIDER == "ORATS"
    assert SELECTED_PRODUCT == "Delayed Data API"


def test_human_approval_gate_state_matches_part_10_exactly():
    assert HUMAN_APPROVAL_GATE_STATE == HumanApprovalGateState.PAID_PROVIDER_RECOMMENDATION_PENDING_HUMAN_APPROVAL
    assert HUMAN_APPROVAL_GATE_STATE.value == "paid_provider_recommendation_pending_human_approval"


def test_final_decision_is_one_of_the_four_required_values():
    assert {v.value for v in Phase28FinalDecision} == {
        "no_paid_provider_justified", "paid_provider_recommended_pending_human_approval",
        "multiple_paid_providers_require_human_review", "paid_provider_data_unverified",
    }
    assert PHASE28_FINAL_DECISION in set(Phase28FinalDecision)


def test_final_decision_is_the_recommended_pending_approval_value():
    assert PHASE28_FINAL_DECISION == Phase28FinalDecision.PAID_PROVIDER_RECOMMENDED_PENDING_HUMAN_APPROVAL


def test_rationale_is_substantive_and_names_the_universal_licensing_gap():
    assert len(FINAL_DECISION_RATIONALE) > 200
    assert "LICENSING_CLARITY" in FINAL_DECISION_RATIONALE
    assert "ORATS_PROMISING_BUT_UNVERIFIED" in FINAL_DECISION_RATIONALE


def test_provider_recommendation_always_awaits_human_approval():
    assert PROVIDER_RECOMMENDATION.awaiting_human_approval is True
    with pytest.raises(ValueError):
        PurchaseRecommendation(
            recommended_provider="X", exact_product="X", why="X", fields_available="X",
            historical_depth="X", approximate_cost="X", trial_availability="X", licensing="X",
            expected_research_gain="X", awaiting_human_approval=False,
        )


def test_provider_recommendation_names_orats_and_the_delayed_data_api():
    assert PROVIDER_RECOMMENDATION.recommended_provider == "ORATS"
    assert PROVIDER_RECOMMENDATION.exact_product == "Delayed Data API"


def test_provider_recommendation_licensing_field_says_unverified():
    assert "LICENSING_UNVERIFIED" in PROVIDER_RECOMMENDATION.licensing


def test_orats_genuinely_beats_every_other_finalist_on_its_claimed_strongest_dimensions():
    for dim in ORATS_STRONGEST_DIMENSIONS:
        assert orats_beats_every_other_finalist_on(dim), dim
