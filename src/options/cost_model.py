"""Phase 19, Part 10 — mark-to-market vs execution-realistic research
labeling, and explicitly-assumption-only cost sensitivity.

Because historical bid/ask is confirmed UNAVAILABLE for every past date
(Phase 18, reaffirmed Phase 19), ANY option-return research built on
`get_option_historicals` closes is, structurally, MARK-TO-MARKET
HISTORICAL RESEARCH -- it prices entry/exit at a bar's close, not at a
real fillable bid/ask. `EXECUTION_REALISTIC_RESEARCH` names the OTHER
kind (priced against real historical bid/ask) that this phase's data
CANNOT produce -- it exists as a label so no result is ever miscaptioned
as the more rigorous kind it is not, not because this phase computes one.

A cost SENSITIVITY figure (spread/slippage/commission) can still be
useful context -- but only if presented as what it is: an ASSUMPTION
applied on top of mark-to-market research, never as an observed cost.
`CostAssumption.label` is structurally required to say so.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class ResearchRealismLabel(enum.Enum):
    MARK_TO_MARKET_HISTORICAL_RESEARCH = "mark_to_market_historical_research"  # priced off get_option_historicals closes -- the ONLY kind this phase can produce
    EXECUTION_REALISTIC_RESEARCH = "execution_realistic_research"  # priced off real historical bid/ask -- UNAVAILABLE this phase, never actually produced


@dataclass(frozen=True)
class CostAssumption:
    """An explicitly-labeled ASSUMPTION, never an observed cost. Applying
    one to a mark-to-market return produces a SENSITIVITY figure, not a
    more accurate return -- the true fill-level cost for any historical
    date is simply not knowable from this data source."""

    label: str
    spread_pct_of_mid: float  # e.g. 0.10 = assume the effective round-trip spread cost is 10% of the option's mid/close price
    slippage_pct: float
    commission_per_contract: float
    rationale: str

    def __post_init__(self) -> None:
        if "ASSUMPTION" not in self.label.upper():
            raise ValueError(f"CostAssumption.label must say so explicitly (contain 'ASSUMPTION'), got {self.label!r}")
        if self.spread_pct_of_mid < 0 or self.slippage_pct < 0 or self.commission_per_contract < 0:
            raise ValueError("CostAssumption's cost components must all be >= 0")


def apply_cost_assumption(mark_to_market_return: float, entry_price: float, assumption: CostAssumption, *, contract_multiplier: int = 100) -> float:
    """Returns a cost-ADJUSTED return under `assumption` -- a sensitivity
    figure, explicitly not a claim about the true realized cost. The
    round-trip cost is applied as: (spread + slippage) x 2 (entry AND
    exit legs each cross the assumed spread/slippage) plus a flat
    commission per contract, all expressed as a fraction of the entry
    notional (entry_price x contract_multiplier)."""
    if entry_price <= 0:
        raise ValueError(f"entry_price must be > 0, got {entry_price}")
    notional = entry_price * contract_multiplier
    round_trip_cost_fraction = (assumption.spread_pct_of_mid + assumption.slippage_pct) * 2
    commission_fraction = (assumption.commission_per_contract * 2) / notional  # entry + exit commission
    return mark_to_market_return - round_trip_cost_fraction - commission_fraction


# Preregistered sensitivity assumptions (Part 10's "1x/2x/3x" convention,
# mirrored from the equity-research cost-stress pattern) -- fixed before
# any Phase 19 discovery result was computed, never tuned to make a
# result look better or worse.
COST_SENSITIVITY_ASSUMPTIONS: tuple[CostAssumption, ...] = (
    CostAssumption("1x ASSUMPTION (tight, liquid contract)", spread_pct_of_mid=0.03, slippage_pct=0.01, commission_per_contract=0.65, rationale="ASSUMPTION: a near-the-money, liquid single-underlying option might realistically trade near a 3% effective spread"),
    CostAssumption("2x ASSUMPTION (typical)", spread_pct_of_mid=0.06, slippage_pct=0.02, commission_per_contract=0.65, rationale="ASSUMPTION: a typical single-stock option away from the most liquid strikes"),
    CostAssumption("3x ASSUMPTION (wide/thin contract)", spread_pct_of_mid=0.10, slippage_pct=0.04, commission_per_contract=0.65, rationale="ASSUMPTION: a thin, wide-spread contract (e.g. far OTM, far-dated) -- no real historical spread data exists to calibrate this, it is a stress case only"),
)

# Phase 21/22's extreme/illiquid stress case, added additively (Phase 19's
# COST_SENSITIVITY_ASSUMPTIONS tuple above is left untouched -- some
# callers explicitly want the 1x/2x/3x ladder without this 4th, more
# extreme tier). Never calibrated to any observed spread (none exist
# historically) -- a stress case only, same as the 3x tier's own rationale.
FIVE_X_ASSUMPTION = CostAssumption(
    "5x ASSUMPTION (extreme/illiquid stress case)", spread_pct_of_mid=0.18, slippage_pct=0.07, commission_per_contract=0.65,
    rationale="ASSUMPTION: an extreme stress case (e.g. a far-dated, far-OTM, thinly-quoted contract) -- not calibrated to any observed spread (none exist historically)",
)
