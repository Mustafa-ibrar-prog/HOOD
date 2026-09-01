"""Phase 6, section 20: a formal research→deployment gate.

    RESEARCHED
        v
    HOLDOUT_VALIDATED
        v
    PAPER_TRADING_ELIGIBLE
        v
    HUMAN_APPROVAL
        v
    PAPER_TRADING

This module can only ever compute up to `PAPER_TRADING_ELIGIBLE` — nothing
in this codebase, in this phase or any other, is permitted to grant
HUMAN_APPROVAL or flip a strategy into PAPER_TRADING; those stages are
external to the research code by design and require a real person's
decision outside of what any script here does. `determine_gate_stage` is a
pure function with no side effects (it does not submit orders, does not
write to any live-trading configuration, and does not import
src.execution/src.orchestrator) — it only classifies evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.research.classification import ClassificationResult, StrategyClassification
from src.research.pass_criteria import PassCriteriaEvaluation


class ResearchGateStage(str, Enum):
    RESEARCHED = "RESEARCHED"
    HOLDOUT_VALIDATED = "HOLDOUT_VALIDATED"
    PAPER_TRADING_ELIGIBLE = "PAPER_TRADING_ELIGIBLE"
    NOT_READY = "NOT_READY"  # explicit terminal state for a holdout that did not clear the bar


@dataclass(frozen=True)
class GateDecision:
    strategy_id: str
    strategy_version: str
    stage: ResearchGateStage
    eligible_for_paper_trading_review: bool
    reasons: tuple[str, ...]

    def render(self) -> str:
        lines = [
            f"PAPER-TRADING GATE — {self.strategy_id} {self.strategy_version}",
            f"  Stage: {self.stage.value}",
            f"  Eligible for paper-trading REVIEW: {self.eligible_for_paper_trading_review}",
            "  (NOTE: 'eligible for review' is NOT approval and NOT activation. HUMAN_APPROVAL and PAPER_TRADING "
            "are stages this codebase does not and will not perform automatically.)",
        ]
        for r in self.reasons:
            lines.append(f"    - {r}")
        return "\n".join(lines)


def determine_gate_stage(
    *,
    strategy_id: str,
    strategy_version: str,
    classification: ClassificationResult,
    pass_criteria_evaluation: PassCriteriaEvaluation,
    holdout_trade_count: int,
    min_trade_count_for_a_verdict: int,
) -> GateDecision:
    reasons: list[str] = []

    if holdout_trade_count < min_trade_count_for_a_verdict:
        reasons.append(f"holdout trade count ({holdout_trade_count}) is below the minimum for any verdict ({min_trade_count_for_a_verdict}) — sample is too small to judge")
        return GateDecision(strategy_id, strategy_version, ResearchGateStage.NOT_READY, False, tuple(reasons))

    reasons.append(f"holdout ran with an adequate sample ({holdout_trade_count} >= {min_trade_count_for_a_verdict} trades) — HOLDOUT_VALIDATED reached")

    if classification.classification != StrategyClassification.PROMISING:
        reasons.append(f"classification is {classification.classification.value}, not PROMISING — does not clear the bar for paper-trading eligibility")
        reasons.extend(classification.reasons)
        return GateDecision(strategy_id, strategy_version, ResearchGateStage.HOLDOUT_VALIDATED, False, tuple(reasons))

    if not pass_criteria_evaluation.all_passed:
        failed = [r.name for r in pass_criteria_evaluation.results if r.passed is False]
        reasons.append(f"classification is PROMISING but {len(failed)} pre-registered pass criterion/criteria failed: {', '.join(failed)}")
        return GateDecision(strategy_id, strategy_version, ResearchGateStage.HOLDOUT_VALIDATED, False, tuple(reasons))

    reasons.append("classification is PROMISING and every pre-registered pass criterion passed")
    reasons.append("PAPER_TRADING_ELIGIBLE means eligible for human review of a paper-trading trial — it does NOT mean paper trading has started")
    return GateDecision(strategy_id, strategy_version, ResearchGateStage.PAPER_TRADING_ELIGIBLE, True, tuple(reasons))
