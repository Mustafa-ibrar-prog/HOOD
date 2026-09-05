"""Phase 38, Part 11 — $1,000 account affordability, reusing Phase 31's
existing `affordability_filter_report`/`classify_account_feasibility`
UNCHANGED (they already operate on a flat dict-shaped "panel row" with
`bid`/`ask` keys -- exactly what a `ForwardOutcome` maps to). No fixed
daily-return requirement is imposed anywhere in this module (Part 11's
explicit instruction) -- affordability is evaluated purely as capital
required vs. capital available.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.options.phase31_affordability_liquidity import (
    DEFAULT_ACCOUNT_EQUITY_USD,
    AffordabilityFilterReport,
    affordability_filter_report,
    classify_account_feasibility,
)
from src.options.phase38_targets import ForwardOutcome


@dataclass(frozen=True)
class ThousandDollarAffordabilityResult:
    report: AffordabilityFilterReport
    classification: str
    max_simultaneous_positions_at_equity: int | None  # how many of this strategy's typical positions $1,000 could hold at once
    max_loss_single_position_usd: float | None  # full premium -- a long option's max loss
    max_loss_all_simultaneous_positions_usd: float | None


def evaluate_thousand_dollar_affordability(
    outcomes: Sequence[ForwardOutcome], *, account_equity_usd: float = DEFAULT_ACCOUNT_EQUITY_USD,
) -> ThousandDollarAffordabilityResult:
    panel_rows = [{"bid": o.entry_bid, "ask": o.entry_ask} for o in outcomes]
    report = affordability_filter_report(panel_rows, account_equity_usd=account_equity_usd)
    classification = classify_account_feasibility(report)

    max_simultaneous = None
    max_loss_single = None
    max_loss_all = None
    if report.average_premium_usd is not None and report.average_premium_usd > 0:
        max_loss_single = report.average_premium_usd  # long options: max loss = full premium paid
        max_simultaneous = int(account_equity_usd // report.average_premium_usd)
        max_loss_all = max_simultaneous * max_loss_single

    return ThousandDollarAffordabilityResult(report, classification, max_simultaneous, max_loss_single, max_loss_all)
