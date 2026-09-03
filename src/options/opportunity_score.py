"""Phase 19, Part 11 — the OpportunityScore PIPELINE SCHEMA.

Architecture only, per this phase's explicit scope: `UnderlyingCandidate`
-> `ChainCandidate` -> `ContractCandidate` -> `SignalEvaluation` ->
`OpportunityScore` are dataclasses describing what a FUTURE options-
opportunity ranking pipeline would carry at each stage. No scoring
FUNCTION is implemented here (choosing a weighting/composite-score
formula is a strategy decision, out of scope this phase -- see
docs/options_alpha_research_foundation.md), and no instance of
`OpportunityScore` produced by this phase's code claims a real composite
score: `composite_score` stays `None` with `scoring_method="NOT_COMPUTED_THIS_PHASE"`
unless a caller explicitly supplies both.

`UNAVAILABLE_HISTORICALLY` (Part 11's required exact sentinel string) is
what `ContractCandidate.render_field()` returns for any field this
phase's data source cannot supply for a historical (non-live) contract --
never a silent None, never a fabricated placeholder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from src.options.chain import OptionsFieldStatus
from src.options.instrument import OptionContract
from src.options.moneyness import MoneynessBucket

UNAVAILABLE_HISTORICALLY = "UNAVAILABLE_HISTORICALLY"


@dataclass(frozen=True)
class ContractCandidate:
    contract: OptionContract
    as_of: date
    close_price: float | None = None
    bid: float | None = None
    ask: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    implied_volatility: float | None = None
    delta: float | None = None
    moneyness_bucket: MoneynessBucket | None = None
    dte: int | None = None
    field_status: dict[str, OptionsFieldStatus] = field(default_factory=dict)

    def render_field(self, name: str) -> str:
        """Returns the field's value as a string if it is OBSERVED or
        DERIVED; otherwise (UNAVAILABLE, ESTIMATED-without-a-value, or
        simply never populated) returns the exact sentinel string
        UNAVAILABLE_HISTORICALLY -- Part 11's explicit requirement, so a
        report can never silently omit a field a reader would otherwise
        assume was just zero or absent."""
        status = self.field_status.get(name, OptionsFieldStatus.UNAVAILABLE)
        if status not in (OptionsFieldStatus.OBSERVED, OptionsFieldStatus.DERIVED):
            return UNAVAILABLE_HISTORICALLY
        value = getattr(self, name, None)
        return UNAVAILABLE_HISTORICALLY if value is None else str(value)


@dataclass(frozen=True)
class ChainCandidate:
    underlying_symbol: str
    expiration: date
    contracts: tuple[ContractCandidate, ...]


@dataclass(frozen=True)
class SignalEvaluation:
    """Schema only -- what a future signal's output on one contract
    would look like. No signal is implemented or run this phase."""

    signal_name: str
    contract_option_id: str
    raw_value: float | None
    computed_at: date
    notes: str = ""


@dataclass(frozen=True)
class UnderlyingCandidate:
    underlying_symbol: str
    chains: tuple[ChainCandidate, ...]


@dataclass(frozen=True)
class OpportunityScore:
    """The pipeline's terminal stage. `composite_score`/`scoring_method`
    are left unset by every Phase 19 code path -- populating them with a
    real number requires a strategy-level weighting decision this phase
    explicitly does not make (see module docstring)."""

    contract_option_id: str
    signal_evaluations: tuple[SignalEvaluation, ...]
    composite_score: float | None = None
    scoring_method: str = "NOT_COMPUTED_THIS_PHASE"

    def __post_init__(self) -> None:
        if self.composite_score is not None and self.scoring_method == "NOT_COMPUTED_THIS_PHASE":
            raise ValueError("composite_score was set without a real scoring_method -- never pair a computed score with the placeholder method label")
