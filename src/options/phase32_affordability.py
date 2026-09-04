"""Phase 32, Parts 12, 13 & 14/21 — economic significance, extended
$1,000 account affordability, and the tradeability annotation.

Reuses Phase 31's `phase31_affordability_liquidity.{affordability_filter_report,
liquidity_report,cost_sensitivity_report}` UNCHANGED for the baseline
premium/liquidity/cost stats — bucket rows carry `bid`/`ask`/`volume`/
`open_interest`/`spread_pct` (the bucket's MEDIAN of each), the exact
columns those functions already expect. This module adds Part 13's two
extra requirements those functions don't cover (25th/75th percentile
premium, cheapest REAL qualifying contracts), which need the
pre-aggregation CONTRACT-DAY panel, not the bucket row's single median.

TRADEABILITY (Part 14's explicit extra labels: TRADEABLE_SIGNAL_FRAGILE,
DATA_LIMITED) is deliberately a SEPARATE annotation from
`phase31_classification.DiscoveryClassification` — the same
"STATISTICAL_VALIDITY vs ACCOUNT_FEASIBILITY" separation Phase 31's
`classify_account_feasibility` already established, extended with two
more labels because Part 14 asks for them explicitly. It is never fed
back into the statistical classification or the Promising Finding Gate.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Sequence

from src.options.phase26_dataset_builder import STANDARD_US_EQUITY_OPTION_MULTIPLIER
from src.options.phase31_classification import DiscoveryClassification

DEFAULT_ACCOUNT_EQUITY_USD = 1_000.0


@dataclass(frozen=True)
class QualifyingContract:
    option_id: str
    underlying: str
    premium_usd: float
    ask: float


@dataclass(frozen=True)
class BucketAffordabilityReport:
    n_contract_days: int
    n_priced: int
    median_premium_usd: float | None
    p25_premium_usd: float | None
    p75_premium_usd: float | None
    pct_affordable: float | None
    pct_requiring_over_account: float | None
    cheapest_contracts: tuple[QualifyingContract, ...]
    capital_concentration_cheapest_usd: float | None


def build_bucket_affordability_report(
    contract_day_rows: Sequence[dict], *, account_equity_usd: float = DEFAULT_ACCOUNT_EQUITY_USD, n_cheapest: int = 5,
) -> BucketAffordabilityReport:
    """`contract_day_rows` is the ORIGINAL Phase 31 per-contract panel
    (or any real subset of it) — never the bucket-aggregate rows, which
    only carry a single median price."""
    priced = [(r, r["ask"] * STANDARD_US_EQUITY_OPTION_MULTIPLIER) for r in contract_day_rows if r.get("ask") is not None]
    if not priced:
        return BucketAffordabilityReport(len(contract_day_rows), 0, None, None, None, None, None, (), None)

    premiums = sorted(p for _r, p in priced)
    n = len(premiums)
    median = premiums[n // 2]
    p25 = premiums[int(n * 0.25)]
    p75 = premiums[min(n - 1, int(n * 0.75))]
    affordable = sum(1 for p in premiums if p <= account_equity_usd)
    over = sum(1 for p in premiums if p > account_equity_usd)

    ranked = sorted(priced, key=lambda rp: rp[1])[:n_cheapest]
    cheapest = tuple(
        QualifyingContract(option_id=r.get("option_id", ""), underlying=r.get("underlying_symbol", ""), premium_usd=p, ask=r["ask"])
        for r, p in ranked
    )
    concentration = cheapest[0].premium_usd / account_equity_usd if cheapest else None

    return BucketAffordabilityReport(
        n_contract_days=len(contract_day_rows), n_priced=len(priced), median_premium_usd=median,
        p25_premium_usd=p25, p75_premium_usd=p75, pct_affordable=affordable / n, pct_requiring_over_account=over / n,
        cheapest_contracts=cheapest, capital_concentration_cheapest_usd=concentration,
    )


class TradeabilityClassification(enum.Enum):
    TRADEABLE = "tradeable"
    TRADEABLE_SIGNAL_FRAGILE = "tradeable_signal_fragile"
    NOT_TRADEABLE_TOO_EXPENSIVE = "not_tradeable_too_expensive"
    NOT_APPLICABLE_NO_STATISTICAL_SIGNAL = "not_applicable_no_statistical_signal"
    DATA_LIMITED = "data_limited"


def classify_tradeability(
    affordability: BucketAffordabilityReport, statistical_classification: DiscoveryClassification, *, min_pct_affordable: float = 0.5,
) -> TradeabilityClassification:
    if affordability.n_priced == 0:
        return TradeabilityClassification.DATA_LIMITED
    if statistical_classification not in (DiscoveryClassification.DISCOVERY_SUPPORTED, DiscoveryClassification.PROMISING):
        return TradeabilityClassification.NOT_APPLICABLE_NO_STATISTICAL_SIGNAL
    if affordability.pct_affordable is not None and affordability.pct_affordable >= min_pct_affordable:
        return TradeabilityClassification.TRADEABLE
    if affordability.pct_affordable is not None and affordability.pct_affordable > 0:
        return TradeabilityClassification.TRADEABLE_SIGNAL_FRAGILE
    return TradeabilityClassification.NOT_TRADEABLE_TOO_EXPENSIVE
