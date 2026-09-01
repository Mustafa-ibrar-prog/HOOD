"""Phase 7, Part 17 & 19: the 12-stage research gate state machine."""

from __future__ import annotations

import pytest

from src.research.research_gate import (
    CODE_COMPUTABLE_STAGES,
    FORWARD_ORDER,
    IllegalStageTransitionError,
    ResearchGateStore,
    ResearchLifecycleStage,
    StageRequiresHumanActionError,
    assert_code_may_set_stage,
    can_transition,
)

S = ResearchLifecycleStage


def test_forward_order_matches_the_prompt_exact_chain():
    assert FORWARD_ORDER == (
        S.IDEA, S.PREREGISTERED, S.DISCOVERY_TESTED, S.DEVELOPMENT_VALIDATED, S.STATISTICALLY_SUPPORTED,
        S.INDEPENDENT_HOLDOUT, S.HOLDOUT_VALIDATED, S.PAPER_TRADING_ELIGIBLE, S.HUMAN_APPROVAL,
        S.PAPER_TRADING, S.LIVE_ELIGIBLE, S.LIVE_TRADING,
    )


def test_can_transition_allows_the_immediate_next_stage():
    for a, b in zip(FORWARD_ORDER, FORWARD_ORDER[1:]):
        assert can_transition(a, b) is True


def test_can_transition_rejects_skipping_a_stage():
    assert can_transition(S.IDEA, S.DISCOVERY_TESTED) is False  # skips PREREGISTERED
    assert can_transition(S.PREREGISTERED, S.STATISTICALLY_SUPPORTED) is False


def test_can_transition_rejects_moving_backward():
    assert can_transition(S.HOLDOUT_VALIDATED, S.IDEA) is False


def test_not_ready_reachable_from_any_forward_stage():
    for stage in FORWARD_ORDER:
        assert can_transition(stage, S.NOT_READY) is True


def test_not_ready_is_terminal_no_forward_transition_out_of_it():
    for stage in FORWARD_ORDER:
        assert can_transition(S.NOT_READY, stage) is False


def test_code_computable_stages_stop_at_paper_trading_eligible():
    assert S.PAPER_TRADING_ELIGIBLE in CODE_COMPUTABLE_STAGES
    assert S.HUMAN_APPROVAL not in CODE_COMPUTABLE_STAGES
    assert S.PAPER_TRADING not in CODE_COMPUTABLE_STAGES
    assert S.LIVE_ELIGIBLE not in CODE_COMPUTABLE_STAGES
    assert S.LIVE_TRADING not in CODE_COMPUTABLE_STAGES


def test_assert_code_may_set_stage_raises_beyond_the_boundary():
    assert_code_may_set_stage(S.PAPER_TRADING_ELIGIBLE)  # no raise
    with pytest.raises(StageRequiresHumanActionError):
        assert_code_may_set_stage(S.HUMAN_APPROVAL)
    with pytest.raises(StageRequiresHumanActionError):
        assert_code_may_set_stage(S.PAPER_TRADING)
    with pytest.raises(StageRequiresHumanActionError):
        assert_code_may_set_stage(S.LIVE_TRADING)


# --- ResearchGateStore -----------------------------------------------------------------


def test_store_first_transition_must_be_idea(tmp_path):
    store = ResearchGateStore(tmp_path / "gate.jsonl")
    with pytest.raises(IllegalStageTransitionError):
        store.transition(hypothesis_id="H1", to_stage=S.DISCOVERY_TESTED, reason="x", evidence_summary="x")


def test_store_walks_the_full_chain_up_to_paper_trading_eligible(tmp_path):
    store = ResearchGateStore(tmp_path / "gate.jsonl")
    store.transition(hypothesis_id="H1", to_stage=S.IDEA, reason="new idea", evidence_summary="")
    for stage in FORWARD_ORDER[1:FORWARD_ORDER.index(S.PAPER_TRADING_ELIGIBLE) + 1]:
        store.transition(hypothesis_id="H1", to_stage=stage, reason="advanced", evidence_summary="evidence")
    assert store.current_stage("H1") == S.PAPER_TRADING_ELIGIBLE


def test_store_cannot_programmatically_reach_human_approval(tmp_path):
    store = ResearchGateStore(tmp_path / "gate.jsonl")
    store.transition(hypothesis_id="H1", to_stage=S.IDEA, reason="x", evidence_summary="")
    store.transition(hypothesis_id="H1", to_stage=S.PREREGISTERED, evidence_summary="x", reason="x")
    with pytest.raises(StageRequiresHumanActionError):
        store.transition(hypothesis_id="H1", to_stage=S.HUMAN_APPROVAL, reason="x", evidence_summary="x")


def test_store_rejects_skipping_a_stage(tmp_path):
    store = ResearchGateStore(tmp_path / "gate.jsonl")
    store.transition(hypothesis_id="H1", to_stage=S.IDEA, reason="x", evidence_summary="")
    with pytest.raises(IllegalStageTransitionError):
        store.transition(hypothesis_id="H1", to_stage=S.DISCOVERY_TESTED, reason="x", evidence_summary="")  # skips PREREGISTERED


def test_store_can_mark_not_ready_from_any_stage(tmp_path):
    store = ResearchGateStore(tmp_path / "gate.jsonl")
    store.transition(hypothesis_id="H1", to_stage=S.IDEA, reason="x", evidence_summary="")
    store.transition(hypothesis_id="H1", to_stage=S.PREREGISTERED, reason="x", evidence_summary="")
    store.transition(hypothesis_id="H1", to_stage=S.NOT_READY, reason="failed discovery screen", evidence_summary="IC not significant")
    assert store.current_stage("H1") == S.NOT_READY


def test_store_records_full_history_never_deletes(tmp_path):
    store = ResearchGateStore(tmp_path / "gate.jsonl")
    store.transition(hypothesis_id="H1", to_stage=S.IDEA, reason="x", evidence_summary="")
    store.transition(hypothesis_id="H1", to_stage=S.PREREGISTERED, reason="x", evidence_summary="")
    history = store.history("H1")
    assert len(history) == 2
    assert history[0].to_stage == S.IDEA
    assert history[1].to_stage == S.PREREGISTERED


def test_different_hypothesis_versions_track_independently(tmp_path):
    store = ResearchGateStore(tmp_path / "gate.jsonl")
    store.transition(hypothesis_id="H1", hypothesis_version="1.0", to_stage=S.IDEA, reason="x", evidence_summary="")
    store.transition(hypothesis_id="H1", hypothesis_version="2.0", to_stage=S.IDEA, reason="x", evidence_summary="")
    assert store.current_stage("H1", "1.0") == S.IDEA
    assert store.current_stage("H1", "2.0") == S.IDEA
    assert len(store.history("H1", "1.0")) == 1


def test_paper_trading_cannot_be_reached_from_discovery_in_one_hop(tmp_path):
    """Direct proof of the section-19 requirement: 'paper trading cannot
    be reached from discovery' — no sequence of ONE call gets there, and
    the boundary function refuses it outright regardless of prior state."""
    store = ResearchGateStore(tmp_path / "gate.jsonl")
    store.transition(hypothesis_id="H1", to_stage=S.IDEA, reason="x", evidence_summary="")
    store.transition(hypothesis_id="H1", to_stage=S.PREREGISTERED, reason="x", evidence_summary="")
    store.transition(hypothesis_id="H1", to_stage=S.DISCOVERY_TESTED, reason="x", evidence_summary="")
    with pytest.raises((IllegalStageTransitionError, StageRequiresHumanActionError)):
        store.transition(hypothesis_id="H1", to_stage=S.PAPER_TRADING, reason="x", evidence_summary="")
