"""Phase 30, Part 4/17 — the research OpportunityScore architecture.

ARCHITECTURE ONLY (Part 4's explicit instruction, echoed by Part 10:
"do not create any new alpha family or trading hypothesis this phase").
No weight, threshold, or formula below is tuned for profitability --
`NullScoringMethod` is the only concrete `ScoringMethod` this phase
ships, and it deliberately produces `NOT_COMPUTED_THIS_PHASE` for every
row. It exists only to prove the architecture's wiring end-to-end (a
`ScoringMethod` really can consume a `ResearchObservation` + `FeatureRow`
+ `SelectionResult` and emit a well-formed `ResearchOpportunityScore`),
not to make any claim about what's actually a good opportunity. A real
scoring method is future work for a phase that explicitly registers a
research hypothesis (Phase 23's `HypothesisRegistry` pattern), not this
one.

Relationship to `src/options/opportunity_score.py` (Phase 19) -- a NEW
module, not a modification: Phase 19's `ContractCandidate`/`ChainCandidate`/
`OpportunityScore` pipeline is built against the LIVE-pipeline types
(`OptionContract`, `MoneynessBucket`, `OptionsFieldStatus` from
`src/options/chain.py`/`instrument.py`/`moneyness.py`) that the live
Robinhood-backed scanner produces. This phase's research pipeline
produces a structurally different row shape (`ResearchObservation`/
`FeatureRow` from Parts 1-2, `SelectionResult` from Part 3) over the free
historical dataset -- forcing either shape through the other's
constructor would mean fabricating fields neither pipeline actually has.
The two modules share the same DESIGN PATTERN deliberately (an
architecture-only score object with `composite`/`method` fields guarded
by a `__post_init__` that refuses a computed score paired with the
"not computed" method label) rather than the same class, because the
project's established discipline is "reuse the pattern, not force a fit"
(see Phase 25-29's per-phase certification-dimension enums for the same
precedent).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from src.options.contract_selection import SelectionResult
from src.options.research_dataset import DataQualityStatus, PITStatus, ResearchObservation
from src.options.research_features import FeatureRow

NOT_COMPUTED_THIS_PHASE = "NOT_COMPUTED_THIS_PHASE"


@dataclass(frozen=True)
class ResearchOpportunityScore:
    """The terminal record. Every score-like field stays `None` unless a
    real `scoring_method` (never the placeholder) computed it -- mirrors
    Phase 19's `OpportunityScore.__post_init__` guard exactly."""

    option_id: str
    observation_timestamp: datetime
    opportunity_score: float | None = None
    confidence: float | None = None
    expected_return: float | None = None
    expected_risk: float | None = None
    liquidity_score: float | None = None
    execution_score: float | None = None
    data_quality_score: float | None = None
    reason_codes: tuple[str, ...] = ()
    scoring_method: str = NOT_COMPUTED_THIS_PHASE

    def __post_init__(self) -> None:
        computed_fields = (
            self.opportunity_score, self.confidence, self.expected_return, self.expected_risk,
            self.liquidity_score, self.execution_score, self.data_quality_score,
        )
        if any(v is not None for v in computed_fields) and self.scoring_method == NOT_COMPUTED_THIS_PHASE:
            raise ValueError(
                "a score-like field was set without a real scoring_method -- never pair a computed "
                "value with the NOT_COMPUTED_THIS_PHASE placeholder label"
            )


class ScoringMethod(ABC):
    """The abstract contract a future, explicitly-registered research
    hypothesis would implement. `name` becomes the resulting score's
    `scoring_method` label -- never `NOT_COMPUTED_THIS_PHASE` for a real
    implementation."""

    name: str

    @abstractmethod
    def score(
        self, *, observation: ResearchObservation, features: FeatureRow, selection: SelectionResult,
    ) -> ResearchOpportunityScore:
        raise NotImplementedError


class NullScoringMethod(ScoringMethod):
    """The only concrete method this phase ships -- proves the pipeline
    wires together without asserting any opportunity judgment. Always
    returns an all-`None`, `NOT_COMPUTED_THIS_PHASE` score, and always
    carries a `REJECTED_BY_SELECTION` or `NO_SCORING_METHOD_IMPLEMENTED`
    reason code so a caller can see WHY nothing was scored, never a
    silent empty result."""

    name = NOT_COMPUTED_THIS_PHASE

    def score(
        self, *, observation: ResearchObservation, features: FeatureRow, selection: SelectionResult,
    ) -> ResearchOpportunityScore:
        reason_codes = ["NO_SCORING_METHOD_IMPLEMENTED_THIS_PHASE"]
        if not selection.is_eligible():
            reason_codes.append("REJECTED_BY_SELECTION")
        if observation.data_quality == DataQualityStatus.FLAGGED_CRITICAL:
            reason_codes.append("DATA_QUALITY_FLAGGED_CRITICAL")
        if observation.pit_status != PITStatus.PIT_SAFE:
            reason_codes.append("PIT_STATUS_NOT_SAFE")
        return ResearchOpportunityScore(
            option_id=observation.option_id, observation_timestamp=observation.observation_timestamp,
            reason_codes=tuple(reason_codes),
        )


def score_rows(
    observations: list[ResearchObservation], features: list[FeatureRow], selections: list[SelectionResult],
    *, method: ScoringMethod = NullScoringMethod(),
) -> list[ResearchOpportunityScore]:
    """Aligns the three parallel-but-independently-produced row lists by
    `(option_id, observation_timestamp)` -- never assumes they share
    index order, since Parts 1-3 each iterate/group independently."""
    features_by_key = {(f.option_id, f.observation_timestamp): f for f in features}
    selections_by_key = {(s.option_id, s.observation_timestamp): s for s in selections}

    out: list[ResearchOpportunityScore] = []
    for obs in observations:
        key = (obs.option_id, obs.observation_timestamp)
        feature_row = features_by_key.get(key)
        selection = selections_by_key.get(key)
        if feature_row is None or selection is None:
            continue  # cannot score a row this pipeline never produced features/a selection decision for
        out.append(method.score(observation=obs, features=feature_row, selection=selection))
    return out
