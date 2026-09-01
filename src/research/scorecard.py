"""Phase 7, Part 16: a standardized research scorecard.

Explicitly NOT one collapsed score — 12 separate dimensions, each with its
own verdict and evidence note, because collapsing "positive out-of-sample
Sharpe" and "economically plausible mechanism" and "survived a shuffled-
signal placebo" into one number is exactly the kind of false precision
this whole phase exists to avoid. classify_with_scorecard is a
DOCUMENTED, rule-based function, not a weighted formula tuned to produce
a particular answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence


class DimensionVerdict(str, Enum):
    SUPPORTS = "SUPPORTS"
    NEUTRAL = "NEUTRAL"
    AGAINST = "AGAINST"
    NOT_APPLICABLE = "NOT_APPLICABLE"


SCORECARD_DIMENSIONS: tuple[str, ...] = (
    "statistical_evidence", "economic_significance", "out_of_sample_stability", "parameter_stability",
    "regime_stability", "universe_stability", "cost_robustness", "execution_robustness", "data_quality",
    "multiple_testing_penalty", "research_contamination_risk", "economic_rationale",
)


@dataclass(frozen=True)
class ScorecardDimension:
    name: str
    verdict: DimensionVerdict
    detail: str

    def __post_init__(self) -> None:
        if self.name not in SCORECARD_DIMENSIONS:
            raise ValueError(f"unknown scorecard dimension {self.name!r} — must be one of {SCORECARD_DIMENSIONS}")


@dataclass(frozen=True)
class ResearchScorecard:
    hypothesis_id: str
    dimensions: tuple[ScorecardDimension, ...]
    classification: str  # "PROMISING" | "INCONCLUSIVE" | "FRAGILE" | "REJECTED" | "NOT_READY"
    classification_reason: str

    def render(self) -> str:
        lines = [f"RESEARCH SCORECARD — {self.hypothesis_id}", ""]
        by_name = {d.name: d for d in self.dimensions}
        for name in SCORECARD_DIMENSIONS:
            d = by_name.get(name)
            if d is None:
                lines.append(f"  {name}: (not reported)")
            else:
                lines.append(f"  [{d.verdict.value:14s}] {name}: {d.detail}")
        lines.append("")
        lines.append(f"CLASSIFICATION: {self.classification}  ({self.classification_reason})")
        return "\n".join(lines)


def build_scorecard(hypothesis_id: str, dimensions: Sequence[ScorecardDimension]) -> ResearchScorecard:
    """Fills in any dimension the caller didn't supply as NOT_APPLICABLE
    ("this research stage was never reached") rather than silently
    omitting it — every one of the 12 dimensions always appears."""
    supplied = {d.name for d in dimensions}
    complete = list(dimensions) + [
        ScorecardDimension(name, DimensionVerdict.NOT_APPLICABLE, "this research stage has not been reached yet")
        for name in SCORECARD_DIMENSIONS if name not in supplied
    ]
    classification, reason = classify_with_scorecard(complete)
    return ResearchScorecard(hypothesis_id=hypothesis_id, dimensions=tuple(complete), classification=classification, classification_reason=reason)


def classify_with_scorecard(dimensions: Sequence[ScorecardDimension]) -> tuple[str, str]:
    """Rule-based, documented classification:

    1. If >= 8 of 12 dimensions are NOT_APPLICABLE, the research process
       simply hasn't progressed far enough to judge -> NOT_READY. (A
       discovery-only screen with no backtest, no holdout, no cost/
       execution robustness will always land here — correctly, since a
       cross-sectional IC alone was never meant to be a final verdict.)
    2. If economic_significance itself is NOT_APPLICABLE (this hypothesis
       has never been backtested, so "is this actually tradable after
       costs" has no answer yet) -> NOT_READY. This is the direct,
       targeted enforcement of Part 6's point ("a statistically
       significant effect is not automatically tradable") — a hypothesis
       cannot be called PROMISING on IC evidence alone, no matter how
       many OTHER dimensions happen to be evaluable at the discovery
       stage; economic significance specifically must have been checked.
    3. Otherwise, if statistical_evidence OR economic_significance is
       AGAINST (evaluable AND clearly negative), -> REJECTED — a
       hypothesis with no measurable edge or no economic viability
       doesn't get a softer landing just because other dimensions look OK.
    4. Otherwise, among the EVALUABLE (non-NOT_APPLICABLE) dimensions,
       compute the fraction with verdict SUPPORTS:
         >= 0.70 -> PROMISING
         >= 0.40 -> INCONCLUSIVE
         <  0.40 -> FRAGILE
    """
    by_name = {d.name: d for d in dimensions}
    n_not_applicable = sum(1 for d in dimensions if d.verdict == DimensionVerdict.NOT_APPLICABLE)
    if n_not_applicable >= 8:
        return "NOT_READY", f"{n_not_applicable}/{len(dimensions)} dimensions are NOT_APPLICABLE — this hypothesis has not progressed past a discovery-only screen"

    econ = by_name.get("economic_significance")
    if econ is None or econ.verdict == DimensionVerdict.NOT_APPLICABLE:
        return "NOT_READY", "economic_significance has not been evaluated (no backtest has run) — statistical evidence alone is never sufficient for a PROMISING/REJECTED/FRAGILE verdict (Part 6)"

    stat = by_name.get("statistical_evidence")
    if (stat and stat.verdict == DimensionVerdict.AGAINST) or econ.verdict == DimensionVerdict.AGAINST:
        return "REJECTED", "statistical evidence or economic significance is directly AGAINST the hypothesis"

    evaluable = [d for d in dimensions if d.verdict != DimensionVerdict.NOT_APPLICABLE]
    if not evaluable:
        return "NOT_READY", "no dimension has been evaluated yet"
    supports_fraction = sum(1 for d in evaluable if d.verdict == DimensionVerdict.SUPPORTS) / len(evaluable)
    if supports_fraction >= 0.70:
        return "PROMISING", f"{supports_fraction:.0%} of evaluable dimensions SUPPORT the hypothesis"
    if supports_fraction >= 0.40:
        return "INCONCLUSIVE", f"only {supports_fraction:.0%} of evaluable dimensions SUPPORT the hypothesis — mixed evidence"
    return "FRAGILE", f"only {supports_fraction:.0%} of evaluable dimensions SUPPORT the hypothesis — evidence is weak or contradictory"
