"""Phase 40, Part 11-13 — bid/ask-only execution pricing, explicit
slippage assumptions, and fees.

Never fills at an arbitrary midpoint (Part 11): `entry_execution_price`
and `exit_execution_price` below start from a REAL observed ask/bid and
return `None` (NO_EXECUTABLE_QUOTE, no fill) if it is missing — the same
"a missing quote is EXECUTION_DATA_LIMITED, never approximated"
discipline `src.options.execution_realism_pricing` already established,
applied here to Phase 40's own real-time (not historical) quote shape.

Slippage/fee NUMBERS are not invented here (Part 13's explicit warning
against "new favorable fees") — `BASELINE`/`STRESSED` map onto
`src.options.cost_model.COST_SENSITIVITY_ASSUMPTIONS`' existing,
already-reviewed, explicitly-labeled-as-ASSUMPTION 1x/3x tiers, reused
verbatim. The REAL, zero-slippage simulated fill from
`src.execution.gateway.PaperExecutionGateway` (Part 9's actual
PAPER_FILL) is never replaced by a slippage-adjusted number — this
module's output is an ADDITIONAL, separately-labeled net-of-cost
figure layered on top of it (Part 12: "Record the exact assumption used
for every fill"), exactly the sensitivity-not-observation framing
`cost_model.py`'s own docstring requires.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.options.cost_model import COST_SENSITIVITY_ASSUMPTIONS, CostAssumption

NO_EXECUTABLE_QUOTE = "NO_EXECUTABLE_QUOTE"


class SlippageAssumptionTier(str, Enum):
    BASELINE = "BASELINE"  # COST_SENSITIVITY_ASSUMPTIONS[0]: "1x ASSUMPTION (tight, liquid contract)"
    STRESSED = "STRESSED"  # COST_SENSITIVITY_ASSUMPTIONS[2]: "3x ASSUMPTION (wide/thin contract)"


_TIER_TO_ASSUMPTION: dict[SlippageAssumptionTier, CostAssumption] = {
    SlippageAssumptionTier.BASELINE: COST_SENSITIVITY_ASSUMPTIONS[0],
    SlippageAssumptionTier.STRESSED: COST_SENSITIVITY_ASSUMPTIONS[2],
}


def cost_assumption_for(tier: SlippageAssumptionTier) -> CostAssumption:
    return _TIER_TO_ASSUMPTION[tier]


@dataclass(frozen=True)
class ExecutionPriceBreakdown:
    side: str  # "entry" | "exit"
    real_bid: float | None
    real_ask: float | None
    quoted_spread: float | None  # real_ask - real_bid, informational
    base_executable_price: float | None  # the REAL fill: ask for entry, bid for exit -- never a midpoint
    slippage_tier: SlippageAssumptionTier
    slippage_usd_per_share: float  # ADDITIONAL assumption, from CostAssumption.slippage_pct * base price
    fee_usd_per_contract: float  # ADDITIONAL assumption, from CostAssumption.commission_per_contract
    note: str


def entry_execution_price(*, bid: float | None, ask: float | None, tier: SlippageAssumptionTier) -> ExecutionPriceBreakdown | str:
    """Buy-to-open: fills at the real ask (Part 11). Returns the literal
    NO_EXECUTABLE_QUOTE string (never a fabricated price) if the ask is
    missing."""
    if ask is None:
        return NO_EXECUTABLE_QUOTE
    assumption = cost_assumption_for(tier)
    spread = (ask - bid) if bid is not None else None
    return ExecutionPriceBreakdown(
        side="entry", real_bid=bid, real_ask=ask, quoted_spread=spread, base_executable_price=ask,
        slippage_tier=tier, slippage_usd_per_share=ask * assumption.slippage_pct,
        fee_usd_per_contract=assumption.commission_per_contract,
        note=f"real ask (buy-to-open); {tier.value} slippage/fee assumption from src.options.cost_model",
    )


def exit_execution_price(*, bid: float | None, ask: float | None, tier: SlippageAssumptionTier) -> ExecutionPriceBreakdown | str:
    """Sell-to-close: fills at the real bid (Part 11). Returns the literal
    NO_EXECUTABLE_QUOTE string (never a fabricated price) if the bid is
    missing."""
    if bid is None:
        return NO_EXECUTABLE_QUOTE
    assumption = cost_assumption_for(tier)
    spread = (ask - bid) if ask is not None else None
    return ExecutionPriceBreakdown(
        side="exit", real_bid=bid, real_ask=ask, quoted_spread=spread, base_executable_price=bid,
        slippage_tier=tier, slippage_usd_per_share=bid * assumption.slippage_pct,
        fee_usd_per_contract=assumption.commission_per_contract,
        note=f"real bid (sell-to-close); {tier.value} slippage/fee assumption from src.options.cost_model",
    )


@dataclass(frozen=True)
class CostBreakdown:
    gross_pnl_usd: float  # (exit_base_price - entry_base_price) * quantity * multiplier -- the REAL simulated fill's own P&L
    spread_cost_usd: float  # informational: what the round-trip quoted spread alone would have cost, at 1x, on this trade's quantity
    slippage_usd: float  # entry + exit slippage assumption, quantity/multiplier-scaled
    fees_usd: float  # entry + exit commission assumption, quantity-scaled
    net_pnl_usd: float  # gross - slippage - fees (spread is already embedded in the real ask/bid fill prices, never double-subtracted)


def compute_cost_breakdown(
    *, entry: ExecutionPriceBreakdown, exit: ExecutionPriceBreakdown, quantity: int, contract_multiplier: int = 100,
) -> CostBreakdown:
    gross = (exit.base_executable_price - entry.base_executable_price) * quantity * contract_multiplier
    slippage = (entry.slippage_usd_per_share + exit.slippage_usd_per_share) * quantity * contract_multiplier
    fees = (entry.fee_usd_per_contract + exit.fee_usd_per_contract) * quantity
    spread_cost = 0.0
    if entry.quoted_spread is not None:
        spread_cost += entry.quoted_spread * quantity * contract_multiplier
    if exit.quoted_spread is not None:
        spread_cost += exit.quoted_spread * quantity * contract_multiplier
    net = gross - slippage - fees
    return CostBreakdown(
        gross_pnl_usd=round(gross, 2), spread_cost_usd=round(spread_cost, 2), slippage_usd=round(slippage, 2),
        fees_usd=round(fees, 2), net_pnl_usd=round(net, 2),
    )
