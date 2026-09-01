"""Tests for Phase 6, section 20's research->paper-trading gate. The gate
must never reach HUMAN_APPROVAL or PAPER_TRADING from code — those aren't
even states this enum can express."""

from __future__ import annotations

from src.research.classification import ClassificationResult, StrategyClassification
from src.research.paper_trading_gate import ResearchGateStage, determine_gate_stage
from src.research.pass_criteria import PassCriteriaEvaluation, PassCriterionResult


def _evaluation(all_pass: bool) -> PassCriteriaEvaluation:
    return PassCriteriaEvaluation(results=(
        PassCriterionResult("minimum trade count", True, "ok"),
        PassCriterionResult("positive expectancy", all_pass, "ok" if all_pass else "failed"),
    ))


def test_small_sample_is_not_ready_regardless_of_classification():
    classification = ClassificationResult(StrategyClassification.PROMISING, ("looks great",))
    gate = determine_gate_stage(
        strategy_id="MR-002", strategy_version="1.0", classification=classification,
        pass_criteria_evaluation=_evaluation(True), holdout_trade_count=3, min_trade_count_for_a_verdict=20,
    )
    assert gate.stage == ResearchGateStage.NOT_READY
    assert gate.eligible_for_paper_trading_review is False


def test_inconclusive_classification_stops_at_holdout_validated():
    classification = ClassificationResult(StrategyClassification.INCONCLUSIVE, ("insufficient evidence",))
    gate = determine_gate_stage(
        strategy_id="MR-002", strategy_version="1.0", classification=classification,
        pass_criteria_evaluation=_evaluation(True), holdout_trade_count=50, min_trade_count_for_a_verdict=20,
    )
    assert gate.stage == ResearchGateStage.HOLDOUT_VALIDATED
    assert gate.eligible_for_paper_trading_review is False


def test_promising_but_failed_pass_criteria_stops_at_holdout_validated():
    classification = ClassificationResult(StrategyClassification.PROMISING, ("positive expectancy",))
    gate = determine_gate_stage(
        strategy_id="MR-002", strategy_version="1.0", classification=classification,
        pass_criteria_evaluation=_evaluation(False), holdout_trade_count=500, min_trade_count_for_a_verdict=20,
    )
    assert gate.stage == ResearchGateStage.HOLDOUT_VALIDATED
    assert gate.eligible_for_paper_trading_review is False


def test_promising_and_all_criteria_passed_reaches_paper_trading_eligible():
    classification = ClassificationResult(StrategyClassification.PROMISING, ("positive expectancy",))
    gate = determine_gate_stage(
        strategy_id="MR-002", strategy_version="1.0", classification=classification,
        pass_criteria_evaluation=_evaluation(True), holdout_trade_count=500, min_trade_count_for_a_verdict=20,
    )
    assert gate.stage == ResearchGateStage.PAPER_TRADING_ELIGIBLE
    assert gate.eligible_for_paper_trading_review is True


def test_the_gate_enum_has_no_human_approval_or_paper_trading_state():
    """The gate can only ever compute up to PAPER_TRADING_ELIGIBLE — this
    codebase never grants the stages after it."""
    stage_values = {s.value for s in ResearchGateStage}
    assert "HUMAN_APPROVAL" not in stage_values
    assert "PAPER_TRADING" not in stage_values


def test_rejected_classification_stops_at_holdout_validated():
    classification = ClassificationResult(StrategyClassification.REJECTED, ("negative expectancy",))
    gate = determine_gate_stage(
        strategy_id="MR-002", strategy_version="1.0", classification=classification,
        pass_criteria_evaluation=_evaluation(True), holdout_trade_count=500, min_trade_count_for_a_verdict=20,
    )
    assert gate.stage == ResearchGateStage.HOLDOUT_VALIDATED
    assert gate.eligible_for_paper_trading_review is False
