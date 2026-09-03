"""Phase 20, Part 8 — the research-inclusion pipeline: WHY an underlying
or a contract is included or excluded from the research panel, made
explicit and typed rather than an implicit filter buried in a script.

Extends the existing dynamic universe architecture (Phase 19's
`UnderlyingUniverse`/`OptionableUnderlying` and the Phase 19
`UnderlyingCandidate` from `opportunity_score.py`, both reused, not
duplicated):

    UnderlyingUniverse
        -> UnderlyingCandidate            (src.options.opportunity_score, reused)
        -> OptionChainCandidate           (this module)
        -> OptionContractCandidate        (this module)
        -> ResearchEligibleContract       (this module)

This is research infrastructure only (Part 8's explicit instruction) --
no live trading selection is built here, and no scoring/ranking of
opportunities happens in this module (that remains
`opportunity_score.py`'s explicitly-unimplemented job).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date

from src.options.contract_existence import ExistenceState
from src.options.instrument import OptionContract
from src.options.opportunity_score import UnderlyingCandidate


class InclusionReason(enum.Enum):
    UNDERLYING_INCLUDED_LIQUIDITY = "underlying_included_liquidity"
    UNDERLYING_INCLUDED_DATA_COVERAGE = "underlying_included_data_coverage"
    CONTRACT_INCLUDED_PRICE_HISTORY = "contract_included_price_history"


class ExclusionReason(enum.Enum):
    CONTRACT_EXCLUDED_INCOMPLETE_HISTORY = "contract_excluded_incomplete_history"
    CONTRACT_EXCLUDED_UNKNOWN_EXISTENCE = "contract_excluded_unknown_existence"
    CONTRACT_EXCLUDED_INVALID_DATA = "contract_excluded_invalid_data"
    UNDERLYING_EXCLUDED_NO_VERIFIED_HISTORICAL_OPTIONS = "underlying_excluded_no_verified_historical_options"


@dataclass(frozen=True)
class OptionChainCandidate:
    underlying_symbol: str
    expiration: date
    inclusion_reasons: tuple[InclusionReason, ...]
    exclusion_reasons: tuple[ExclusionReason, ...] = ()

    @property
    def is_included(self) -> bool:
        return len(self.exclusion_reasons) == 0 and len(self.inclusion_reasons) > 0


@dataclass(frozen=True)
class OptionContractCandidate:
    contract: OptionContract
    bar_count: int  # how many real daily bars this phase actually has for this contract
    min_expected_bar_count: int  # a data-completeness threshold, NOT an alpha judgment (e.g. "should span most of the trading days between first observation and expiration")
    existence_state: ExistenceState

    def evaluate(self) -> "ResearchEligibleContract":
        reasons_in: list[InclusionReason] = []
        reasons_out: list[ExclusionReason] = []

        if self.existence_state == ExistenceState.INSUFFICIENT_PIT_EVIDENCE:
            reasons_out.append(ExclusionReason.CONTRACT_EXCLUDED_INVALID_DATA)
        elif self.existence_state == ExistenceState.UNKNOWN_EXISTENCE:
            # Part 4: UNKNOWN_EXISTENCE does not automatically disqualify a contract (every real
            # contract this codebase has ever seen carries this state -- excluding all of them would
            # empty the panel) -- but it IS recorded so downstream disclosure can report how much of
            # the sample it affects. See summarize_existence_impact() below.
            reasons_in.append(InclusionReason.CONTRACT_INCLUDED_PRICE_HISTORY)
        elif self.existence_state == ExistenceState.KNOWN_EXPIRED:
            reasons_out.append(ExclusionReason.CONTRACT_EXCLUDED_INVALID_DATA)
        else:
            reasons_in.append(InclusionReason.CONTRACT_INCLUDED_PRICE_HISTORY)

        if self.bar_count < self.min_expected_bar_count:
            reasons_out.append(ExclusionReason.CONTRACT_EXCLUDED_INCOMPLETE_HISTORY)

        return ResearchEligibleContract(
            contract=self.contract, existence_state=self.existence_state, bar_count=self.bar_count,
            inclusion_reasons=tuple(reasons_in), exclusion_reasons=tuple(reasons_out),
        )


@dataclass(frozen=True)
class ResearchEligibleContract:
    contract: OptionContract
    existence_state: ExistenceState
    bar_count: int
    inclusion_reasons: tuple[InclusionReason, ...]
    exclusion_reasons: tuple[ExclusionReason, ...]

    @property
    def is_eligible(self) -> bool:
        return len(self.exclusion_reasons) == 0 and len(self.inclusion_reasons) > 0

    @property
    def has_unknown_existence(self) -> bool:
        return self.existence_state == ExistenceState.UNKNOWN_EXISTENCE


def evaluate_underlying_inclusion(candidate: UnderlyingCandidate, *, has_verified_historical_options: bool) -> tuple[InclusionReason | ExclusionReason, ...]:
    """Part 8's underlying-level WHY. `has_verified_historical_options`
    must come from a real `UnderlyingUniverse`/`OptionableUnderlying`
    lookup, never guessed."""
    if not has_verified_historical_options:
        return (ExclusionReason.UNDERLYING_EXCLUDED_NO_VERIFIED_HISTORICAL_OPTIONS,)
    # Both real bases for inclusion apply simultaneously for every underlying this phase used:
    # it was chosen because it is a highly liquid, actively-traded name (Part 1's target list, or a
    # name discovered dynamically per DynamicDiscoveryEvidence) AND because real historical option
    # data coverage was actually confirmed for it.
    return (InclusionReason.UNDERLYING_INCLUDED_LIQUIDITY, InclusionReason.UNDERLYING_INCLUDED_DATA_COVERAGE)


@dataclass(frozen=True)
class ExistenceImpactSummary:
    """Part 4's explicit disclosure requirement: 'Research results must
    clearly disclose how much of the sample is affected by
    UNKNOWN_EXISTENCE.'"""

    total_rows: int
    unknown_existence_rows: int

    @property
    def unknown_existence_fraction(self) -> float:
        return self.unknown_existence_rows / self.total_rows if self.total_rows else 0.0

    @property
    def is_materially_affected(self) -> bool:
        """Part 4: 'If a research result depends materially on uncertain
        contract existence, classify it accordingly.' A >50% threshold is
        the explicit, documented bar for 'material' here -- not a hidden
        magic number tuned to make a result look better."""
        return self.unknown_existence_fraction > 0.5


def summarize_existence_impact(existence_states: list[ExistenceState]) -> ExistenceImpactSummary:
    total = len(existence_states)
    unknown = sum(1 for s in existence_states if s == ExistenceState.UNKNOWN_EXISTENCE)
    return ExistenceImpactSummary(total_rows=total, unknown_existence_rows=unknown)
