"""Phase 31, Parts 8 & 9/18 — the affordability ECONOMIC FILTER (never a
target) and liquidity/execution-cost reporting.

Part 8 is explicit: "Include the $1,000 account constraint as an
ECONOMIC FILTER, not a target... Separate STATISTICAL_VALIDITY from
ACCOUNT_FEASIBILITY. Do NOT eliminate a statistically valid signal
solely because it is expensive." `classify_account_feasibility` below
returns its own, separate label — it is never consulted by
`phase31_classification.py`'s statistical DiscoveryClassification.

Reuses `src.options.phase26_dataset_builder.STANDARD_US_EQUITY_OPTION_
MULTIPLIER` (the same explicit, flagged market-convention constant every
other module in this codebase uses) rather than a new one. Does not
reuse Phase 30's `affordability.analyze_affordability` per-row function
directly, since it expects a `ResearchObservation` dataclass, not a
panel-row dict — the arithmetic is identical, restated here for the flat
dict shape rather than requiring a wasteful dict->dataclass round-trip
for every row of a large panel.

Cost-sensitivity multipliers (1x/2x/3x) match the EXACT convention
Phase 19-23's options-alpha campaigns already established (see
`docs/options_alpha_research_foundation.md`'s "Cost sensitivity: Q5-Q1
spread survives only 1x cost assumption, net-negative at 2x/3x") — reused
here as a project-standard cost-stress convention, not invented fresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.options.phase26_dataset_builder import STANDARD_US_EQUITY_OPTION_MULTIPLIER
from src.research.analysis import mean

DEFAULT_ACCOUNT_EQUITY_USD = 1_000.0
DEFAULT_COST_MULTIPLIERS: tuple[float, ...] = (1.0, 2.0, 3.0)


@dataclass(frozen=True)
class AffordabilityFilterReport:
    n_rows: int
    n_priced_rows: int  # rows with a real ask
    average_premium_usd: float | None
    median_premium_usd: float | None
    min_premium_usd: float | None
    max_premium_usd: float | None
    pct_affordable_with_account: float | None
    account_equity_usd: float
    average_spread_cost_usd: float | None  # per single contract
    average_capital_required_usd: float | None  # per single contract == average_premium_usd, restated per Part 8's field list


def affordability_filter_report(panel_rows: Sequence[dict], *, account_equity_usd: float = DEFAULT_ACCOUNT_EQUITY_USD) -> AffordabilityFilterReport:
    premiums = [r["ask"] * STANDARD_US_EQUITY_OPTION_MULTIPLIER for r in panel_rows if r.get("ask") is not None]
    if not premiums:
        return AffordabilityFilterReport(
            n_rows=len(panel_rows), n_priced_rows=0, average_premium_usd=None, median_premium_usd=None,
            min_premium_usd=None, max_premium_usd=None, pct_affordable_with_account=None,
            account_equity_usd=account_equity_usd, average_spread_cost_usd=None, average_capital_required_usd=None,
        )
    affordable = [p for p in premiums if p <= account_equity_usd]
    spreads = [
        (r["ask"] - r["bid"]) * STANDARD_US_EQUITY_OPTION_MULTIPLIER
        for r in panel_rows if r.get("ask") is not None and r.get("bid") is not None
    ]
    sorted_premiums = sorted(premiums)
    return AffordabilityFilterReport(
        n_rows=len(panel_rows), n_priced_rows=len(premiums), average_premium_usd=mean(premiums),
        median_premium_usd=sorted_premiums[len(sorted_premiums) // 2], min_premium_usd=min(premiums),
        max_premium_usd=max(premiums), pct_affordable_with_account=len(affordable) / len(premiums),
        account_equity_usd=account_equity_usd, average_spread_cost_usd=mean(spreads) if spreads else None,
        average_capital_required_usd=mean(premiums),
    )


def classify_account_feasibility(report: AffordabilityFilterReport, *, min_pct_affordable: float = 0.5) -> str:
    """A SEPARATE dimension from statistical validity (Part 8's explicit
    instruction) — never fed into `phase31_classification.py`."""
    if report.pct_affordable_with_account is None:
        return "ACCOUNT_FEASIBILITY_UNKNOWN_NO_PRICED_ROWS"
    if report.pct_affordable_with_account >= min_pct_affordable:
        return "ACCOUNT_FEASIBLE"
    return "ACCOUNT_INFEASIBLE_EXPENSIVE_CONTRACTS"


@dataclass(frozen=True)
class LiquidityReport:
    n_rows: int
    pct_quote_available: float | None
    average_spread_pct: float | None
    average_volume: float | None
    average_open_interest: float | None
    execution_data_limited: bool


def liquidity_report(panel_rows: Sequence[dict], *, min_quote_availability: float = 0.5) -> LiquidityReport:
    quote_available = [1.0 if r.get("bid") is not None and r.get("ask") is not None else 0.0 for r in panel_rows]
    spread_pcts = [r["spread_pct"] for r in panel_rows if r.get("spread_pct") is not None]
    volumes = [r["volume"] for r in panel_rows if r.get("volume") is not None]
    open_interests = [r["open_interest"] for r in panel_rows if r.get("open_interest") is not None]
    pct_avail = mean(quote_available) if quote_available else None
    return LiquidityReport(
        n_rows=len(panel_rows), pct_quote_available=pct_avail,
        average_spread_pct=mean(spread_pcts) if spread_pcts else None,
        average_volume=mean(volumes) if volumes else None,
        average_open_interest=mean(open_interests) if open_interests else None,
        execution_data_limited=(pct_avail is None or pct_avail < min_quote_availability),
    )


@dataclass(frozen=True)
class CostSensitivityResult:
    multiplier: float
    gross_effect: float | None
    average_round_trip_cost_pct: float | None
    net_effect: float | None
    survives: bool | None


def cost_sensitivity_report(
    gross_effect: float | None, liquidity: LiquidityReport, *, multipliers: tuple[float, ...] = DEFAULT_COST_MULTIPLIERS,
) -> tuple[CostSensitivityResult, ...]:
    """`gross_effect` is the raw quantile-spread (or other economic-
    significance figure) BEFORE costs; `average_round_trip_cost_pct`
    approximates a round-trip cost as `average_spread_pct * multiplier`
    (crossing the spread once to enter, once to exit, scaled by the
    stress multiplier -- the SAME 1x/2x/3x convention Phase 19-23
    established, see module docstring). `EXECUTION_DATA_LIMITED`
    portfolios (see `LiquidityReport.execution_data_limited`) still get a
    result here, but the caller must treat it as unreliable — this
    function itself never fabricates a spread where none was observed."""
    out = []
    for m in multipliers:
        cost = liquidity.average_spread_pct * m if liquidity.average_spread_pct is not None else None
        net = (gross_effect - cost) if (gross_effect is not None and cost is not None) else None
        survives = (net > 0) if net is not None else None
        out.append(CostSensitivityResult(multiplier=m, gross_effect=gross_effect, average_round_trip_cost_pct=cost, net_effect=net, survives=survives))
    return tuple(out)
