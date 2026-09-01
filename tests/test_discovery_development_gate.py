"""Phase 9, Part 20 & 21: the 14-stage discovery/development research
gate — mirrors tests/test_research_gate.py's proof structure for Phase
7's gate, applied to this separate Part-20 vocabulary."""

from __future__ import annotations

import pytest

from src.research.discovery_development_gate import (
    CODE_COMPUTABLE_STAGES,
    FORWARD_ORDER,
    DiscoveryDevelopmentGateStore,
    DiscoveryDevelopmentStage,
    IllegalStageTransitionError,
    StageRequiresHumanActionError,
    assert_code_may_set_stage,
    can_transition,
)

S = DiscoveryDevelopmentStage


def test_forward_order_matches_the_prompt_exact_chain():
    assert FORWARD_ORDER == (
        S.IDEA, S.PREREGISTERED, S.DISCOVERY_TESTED, S.DISCOVERY_SUPPORTED, S.DEVELOPMENT_PREREGISTERED,
        S.DEVELOPMENT_TESTED, S.DEVELOPMENT_SUPPORTED, S.VALIDATION, S.HOLDOUT, S.PAPER_TRADING_ELIGIBLE,
        S.HUMAN_APPROVAL, S.PAPER_TRADING, S.LIVE_ELIGIBLE, S.LIVE_TRADING,
    )


def test_can_transition_allows_only_the_immediate_next_stage():
    for a, b in zip(FORWARD_ORDER, FORWARD_ORDER[1:]):
        assert can_transition(a, b) is True
    assert can_transition(S.IDEA, S.DISCOVERY_TESTED) is False  # skips PREREGISTERED
    assert can_transition(S.DISCOVERY_TESTED, S.DEVELOPMENT_TESTED) is False  # skips DISCOVERY_SUPPORTED, DEVELOPMENT_PREREGISTERED


def test_not_ready_reachable_from_anywhere_and_terminal():
    for stage in FORWARD_ORDER:
        assert can_transition(stage, S.NOT_READY) is True
    for stage in FORWARD_ORDER:
        assert can_transition(S.NOT_READY, stage) is False


def test_code_computable_stages_stop_at_paper_trading_eligible():
    assert S.PAPER_TRADING_ELIGIBLE in CODE_COMPUTABLE_STAGES
    assert S.HUMAN_APPROVAL not in CODE_COMPUTABLE_STAGES
    assert S.PAPER_TRADING not in CODE_COMPUTABLE_STAGES
    assert S.LIVE_TRADING not in CODE_COMPUTABLE_STAGES
    with pytest.raises(StageRequiresHumanActionError):
        assert_code_may_set_stage(S.HUMAN_APPROVAL)


def test_store_walks_discovery_stages_then_stops(tmp_path):
    store = DiscoveryDevelopmentGateStore(tmp_path / "gate.jsonl")
    store.transition(hypothesis_id="P9-VOLCLUST-A", to_stage=S.IDEA, reason="x", evidence_summary="")
    store.transition(hypothesis_id="P9-VOLCLUST-A", to_stage=S.PREREGISTERED, reason="x", evidence_summary="")
    store.transition(hypothesis_id="P9-VOLCLUST-A", to_stage=S.DISCOVERY_TESTED, reason="x", evidence_summary="")
    assert store.current_stage("P9-VOLCLUST-A") == S.DISCOVERY_TESTED


def test_store_rejects_skipping_discovery_supported(tmp_path):
    store = DiscoveryDevelopmentGateStore(tmp_path / "gate.jsonl")
    store.transition(hypothesis_id="H", to_stage=S.IDEA, reason="x", evidence_summary="")
    store.transition(hypothesis_id="H", to_stage=S.PREREGISTERED, reason="x", evidence_summary="")
    store.transition(hypothesis_id="H", to_stage=S.DISCOVERY_TESTED, reason="x", evidence_summary="")
    with pytest.raises(IllegalStageTransitionError):
        store.transition(hypothesis_id="H", to_stage=S.DEVELOPMENT_PREREGISTERED, reason="x", evidence_summary="")  # skips DISCOVERY_SUPPORTED


def test_store_can_mark_not_ready_after_discovery_tested(tmp_path):
    store = DiscoveryDevelopmentGateStore(tmp_path / "gate.jsonl")
    store.transition(hypothesis_id="H", to_stage=S.IDEA, reason="x", evidence_summary="")
    store.transition(hypothesis_id="H", to_stage=S.PREREGISTERED, reason="x", evidence_summary="")
    store.transition(hypothesis_id="H", to_stage=S.DISCOVERY_TESTED, reason="x", evidence_summary="")
    store.transition(hypothesis_id="H", to_stage=S.NOT_READY, reason="discovery evidence too weak", evidence_summary="IC not significant")
    assert store.current_stage("H") == S.NOT_READY


def test_cannot_reach_paper_trading_eligible_from_discovery_in_one_hop(tmp_path):
    store = DiscoveryDevelopmentGateStore(tmp_path / "gate.jsonl")
    store.transition(hypothesis_id="H", to_stage=S.IDEA, reason="x", evidence_summary="")
    store.transition(hypothesis_id="H", to_stage=S.PREREGISTERED, reason="x", evidence_summary="")
    store.transition(hypothesis_id="H", to_stage=S.DISCOVERY_TESTED, reason="x", evidence_summary="")
    with pytest.raises((IllegalStageTransitionError, StageRequiresHumanActionError)):
        store.transition(hypothesis_id="H", to_stage=S.PAPER_TRADING_ELIGIBLE, reason="x", evidence_summary="")


def test_store_cannot_programmatically_reach_human_approval_even_from_the_top_of_code_computable(tmp_path):
    store = DiscoveryDevelopmentGateStore(tmp_path / "gate.jsonl")
    for stage in FORWARD_ORDER[: FORWARD_ORDER.index(S.PAPER_TRADING_ELIGIBLE) + 1]:
        store.transition(hypothesis_id="H", to_stage=stage, reason="x", evidence_summary="")
    assert store.current_stage("H") == S.PAPER_TRADING_ELIGIBLE
    with pytest.raises(StageRequiresHumanActionError):
        store.transition(hypothesis_id="H", to_stage=S.HUMAN_APPROVAL, reason="x", evidence_summary="")


def test_history_never_deletes_prior_records(tmp_path):
    store = DiscoveryDevelopmentGateStore(tmp_path / "gate.jsonl")
    store.transition(hypothesis_id="H", to_stage=S.IDEA, reason="x", evidence_summary="")
    store.transition(hypothesis_id="H", to_stage=S.PREREGISTERED, reason="x", evidence_summary="")
    history = store.history("H")
    assert len(history) == 2
    assert history[0].to_stage == S.IDEA
