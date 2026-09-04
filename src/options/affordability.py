"""Phase 30, Part 5/17 — historical contract affordability calculations.

ANALYSIS ONLY (Part 5's explicit instruction): this module computes what
a ~$1,000 account could actually have afforded against real historical
bid/ask, and nothing here targets or assumes any dollar/day figure is
achievable. `DEFAULT_ACCOUNT_EQUITY_USD` is a configurable illustration
of the user's stated account size, not a strategy parameter.

Reuses `STANDARD_US_EQUITY_OPTION_MULTIPLIER` from Phase 26's
`phase26_dataset_builder` (the same explicit, flagged, market-convention
assumption used everywhere else in this codebase) rather than
re-declaring a second multiplier constant.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from src.options.phase26_dataset_builder import STANDARD_US_EQUITY_OPTION_MULTIPLIER
from src.options.research_dataset import ResearchObservation

DEFAULT_ACCOUNT_EQUITY_USD = 1_000.0
DEFAULT_TICK_SIZE_USD = 0.01  # illustrative; real US options tick regimes vary by premium tier (Part 5 does not require modeling that granularity)


@dataclass(frozen=True)
class AffordabilityAnalysis:
    option_id: str
    observation_timestamp: datetime
    account_equity_usd: float
    premium_cost_usd: float | None  # cost to buy ONE contract = execution price x multiplier; None if no real ask exists
    contracts_affordable: int | None
    max_capital_required_usd: float | None
    capital_pct: float | None  # max_capital_required_usd / account_equity_usd
    tick_impact_usd: float | None  # dollar P&L swing from one tick move against the full affordable position
    spread_cost_usd: float | None  # cost of paying the full bid/ask spread once, across the full affordable position
    data_limited: bool  # True if bid and/or ask was unavailable -- never fabricated, this flag says so explicitly


def analyze_affordability(
    row: ResearchObservation, *,
    account_equity_usd: float = DEFAULT_ACCOUNT_EQUITY_USD,
    tick_size_usd: float = DEFAULT_TICK_SIZE_USD,
) -> AffordabilityAnalysis:
    """Uses the real ASK as the entry execution price (Part 6's
    BUY_AT_ASK convention, never the close price -- see
    `execution_realism_pricing.py`). If no real ask exists for this row,
    every derived figure stays `None` and `data_limited=True` -- never
    substituted with mid/last/close."""
    if row.ask is None:
        return AffordabilityAnalysis(
            option_id=row.option_id, observation_timestamp=row.observation_timestamp,
            account_equity_usd=account_equity_usd, premium_cost_usd=None, contracts_affordable=None,
            max_capital_required_usd=None, capital_pct=None, tick_impact_usd=None, spread_cost_usd=None,
            data_limited=True,
        )

    premium_cost_usd = row.ask * STANDARD_US_EQUITY_OPTION_MULTIPLIER
    contracts_affordable = math.floor(account_equity_usd / premium_cost_usd) if premium_cost_usd > 0 else 0
    max_capital_required_usd = contracts_affordable * premium_cost_usd
    capital_pct = (max_capital_required_usd / account_equity_usd) if account_equity_usd > 0 else None
    tick_impact_usd = tick_size_usd * STANDARD_US_EQUITY_OPTION_MULTIPLIER * contracts_affordable

    spread_cost_usd = None
    data_limited = row.bid is None
    if row.bid is not None:
        spread_cost_usd = (row.ask - row.bid) * STANDARD_US_EQUITY_OPTION_MULTIPLIER * contracts_affordable

    return AffordabilityAnalysis(
        option_id=row.option_id, observation_timestamp=row.observation_timestamp,
        account_equity_usd=account_equity_usd, premium_cost_usd=premium_cost_usd,
        contracts_affordable=contracts_affordable, max_capital_required_usd=max_capital_required_usd,
        capital_pct=capital_pct, tick_impact_usd=tick_impact_usd, spread_cost_usd=spread_cost_usd,
        data_limited=data_limited,
    )


def analyze_affordability_batch(
    rows: list[ResearchObservation], *,
    account_equity_usd: float = DEFAULT_ACCOUNT_EQUITY_USD,
    tick_size_usd: float = DEFAULT_TICK_SIZE_USD,
) -> list[AffordabilityAnalysis]:
    return [analyze_affordability(r, account_equity_usd=account_equity_usd, tick_size_usd=tick_size_usd) for r in rows]
