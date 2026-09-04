"""Phase 30, Part 3/17 — the contract-selection engine.

Reuses Part 1's `ResearchObservation` (DATA_QUALITY/PIT_STATUS/bid/ask/
volume/open_interest/moneyness/dte) directly as its input row shape --
no parallel row type. Every threshold lives in `SelectionCriteria`, a
plain, fully caller-configurable dataclass with conservative-but-not-
profitability-tuned defaults (Part 3's explicit instruction: "these
parameters should be configurable, not hard-coded for a specific
profitability target"). This module never ranks or scores a contract --
that is Part 4's `OpportunityScore`'s job; this module only answers
"is this contract even eligible for further consideration," with an
explicit, auditable reason whenever the answer is no.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from src.options.research_dataset import DataQualityStatus, PITStatus, ResearchObservation


class SelectionDecision(enum.Enum):
    ELIGIBLE = "eligible"
    REJECTED = "rejected"


class RejectionReason(enum.Enum):
    NO_BID = "no_bid"
    NO_ASK = "no_ask"
    WIDE_SPREAD = "wide_spread"
    INSUFFICIENT_VOLUME = "insufficient_volume"
    INSUFFICIENT_OI = "insufficient_oi"
    INVALID_DTE = "invalid_dte"
    INVALID_MONEYNESS = "invalid_moneyness"
    INSUFFICIENT_DATA = "insufficient_data"
    PIT_FAILURE = "pit_failure"
    PRICE_TOO_HIGH = "price_too_high"
    DATA_QUALITY_FAILURE = "data_quality_failure"


@dataclass(frozen=True)
class SelectionCriteria:
    """Every field below is a real, adjustable parameter -- none is
    presented as a research-derived optimum. Defaults are deliberately
    permissive (wide DTE/moneyness bands, no volume/OI floor, a high
    premium cap) so an unconfigured call does not silently reject
    everything; a real research run is expected to pass its own
    criteria explicitly."""

    min_dte: int = 0
    max_dte: int = 3650
    min_moneyness: float = 0.01
    max_moneyness: float = 100.0
    max_spread_pct: float = 5.0
    min_volume: float = 0.0
    min_open_interest: float = 0.0
    max_premium_per_contract_usd: float = 1_000_000.0
    reject_on_flagged_critical_quality: bool = True
    require_pit_safe: bool = True


@dataclass(frozen=True)
class SelectionResult:
    option_id: str
    observation_timestamp: object  # datetime; kept loosely typed to avoid a redundant import cycle in this docstring-heavy module
    decision: SelectionDecision
    reasons: tuple[RejectionReason, ...]

    def is_eligible(self) -> bool:
        return self.decision == SelectionDecision.ELIGIBLE


def evaluate_contract(row: ResearchObservation, criteria: SelectionCriteria = SelectionCriteria()) -> SelectionResult:
    reasons: list[RejectionReason] = []

    if row.bid is None:
        reasons.append(RejectionReason.NO_BID)
    if row.ask is None:
        reasons.append(RejectionReason.NO_ASK)
    if row.bid is not None and row.ask is not None:
        mid = (row.bid + row.ask) / 2
        if mid > 0:
            spread_pct = (row.ask - row.bid) / mid
            if spread_pct > criteria.max_spread_pct:
                reasons.append(RejectionReason.WIDE_SPREAD)

    if row.volume is None:
        reasons.append(RejectionReason.INSUFFICIENT_DATA)
    elif row.volume < criteria.min_volume:
        reasons.append(RejectionReason.INSUFFICIENT_VOLUME)

    if row.open_interest is None:
        reasons.append(RejectionReason.INSUFFICIENT_DATA)
    elif row.open_interest < criteria.min_open_interest:
        reasons.append(RejectionReason.INSUFFICIENT_OI)

    if row.dte is None:
        reasons.append(RejectionReason.INSUFFICIENT_DATA)
    elif not (criteria.min_dte <= row.dte <= criteria.max_dte):
        reasons.append(RejectionReason.INVALID_DTE)

    if row.moneyness is None:
        reasons.append(RejectionReason.INSUFFICIENT_DATA)
    elif not (criteria.min_moneyness <= row.moneyness <= criteria.max_moneyness):
        reasons.append(RejectionReason.INVALID_MONEYNESS)

    if criteria.require_pit_safe and row.pit_status != PITStatus.PIT_SAFE:
        reasons.append(RejectionReason.PIT_FAILURE)

    reference_price = row.ask if row.ask is not None else row.option_close
    if reference_price is not None and reference_price * 100 > criteria.max_premium_per_contract_usd:
        reasons.append(RejectionReason.PRICE_TOO_HIGH)

    if criteria.reject_on_flagged_critical_quality and row.data_quality == DataQualityStatus.FLAGGED_CRITICAL:
        reasons.append(RejectionReason.DATA_QUALITY_FAILURE)

    decision = SelectionDecision.REJECTED if reasons else SelectionDecision.ELIGIBLE
    return SelectionResult(
        option_id=row.option_id, observation_timestamp=row.observation_timestamp,
        decision=decision, reasons=tuple(reasons),
    )


def evaluate_contracts(rows: list[ResearchObservation], criteria: SelectionCriteria = SelectionCriteria()) -> list[SelectionResult]:
    return [evaluate_contract(r, criteria) for r in rows]


def eligible_rows(rows: list[ResearchObservation], criteria: SelectionCriteria = SelectionCriteria()) -> list[ResearchObservation]:
    """Convenience: the subset of `rows` whose evaluate_contract() result
    is ELIGIBLE -- for a caller that just wants the surviving rows, not
    the full audit trail."""
    results = evaluate_contracts(rows, criteria)
    eligible_keys = {(r.option_id, r.observation_timestamp) for r in results if r.is_eligible()}
    return [row for row in rows if (row.option_id, row.observation_timestamp) in eligible_keys]
