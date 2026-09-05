"""Phase 36, Part 10 — a structured liquidity assessment.

Reuses whatever thresholds are ALREADY validated and operating in this
codebase's real risk configuration (`RiskLimits.max_spread_pct`/
`min_option_volume`/`min_option_open_interest`/`stale_data_max_seconds`
-- the exact numbers `RiskManager.check_spread`/`check_liquidity`/
`check_data_freshness` already gate real trades on today) rather than
inventing new production thresholds. Two real fields this codebase's
`OptionQuote` doesn't carry at all yet -- bid_size/ask_size -- have NO
existing validated threshold anywhere in this project; per Part 10's
explicit instruction, those are marked `CONFIGURATION_REQUIRED`, never
given an arbitrary made-up number, and never used to REJECT a contract
(only to report that the check could not be performed).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from src.production.live_snapshot import OptionLiveState

if TYPE_CHECKING:
    from src.risk.models import RiskLimits

CONFIGURATION_REQUIRED = "CONFIGURATION_REQUIRED"


class LiquidityClassification(str, Enum):
    LIQUID = "LIQUID"
    MARGINAL = "MARGINAL"  # fails one soft check but not disqualifying
    ILLIQUID = "ILLIQUID"
    UNKNOWN = "UNKNOWN"  # required data is missing -- never assumed liquid


@dataclass(frozen=True)
class LiquidityAssessment:
    option_id: str
    spread: float | None
    spread_pct: float | None
    bid_size: int | None
    ask_size: int | None
    volume: int | None
    open_interest: int | None
    quote_age_seconds: float | None
    classification: LiquidityClassification
    rejection_reason: str | None
    configuration_required: tuple[str, ...]  # which inputs had no validated production threshold to check against


def assess_liquidity(option: OptionLiveState, *, now: datetime, risk_limits: "RiskLimits") -> LiquidityAssessment:
    # bid_size/ask_size have no validated production threshold anywhere in
    # this codebase today, regardless of whether a value is even present on
    # `option` -- always reported, never used to reject.
    configuration_required: list[str] = ["min_bid_size", "min_ask_size"]

    quote_age = (now - option.timestamp).total_seconds() if option.timestamp is not None else None

    if option.bid is None or option.ask is None:
        return LiquidityAssessment(
            option.option_id, None, None, option.bid_size, option.ask_size, option.volume, option.open_interest,
            quote_age, LiquidityClassification.UNKNOWN, "Missing bid/ask", tuple(configuration_required),
        )
    spread = option.ask - option.bid
    mid = (option.bid + option.ask) / 2
    spread_pct = (spread / mid) if mid > 0 else None

    if option.volume is None or option.open_interest is None:
        return LiquidityAssessment(
            option.option_id, spread, spread_pct, option.bid_size, option.ask_size, option.volume,
            option.open_interest, quote_age, LiquidityClassification.UNKNOWN,
            "Missing volume/open interest", tuple(configuration_required),
        )

    reasons: list[str] = []
    if spread_pct is None or spread_pct > risk_limits.max_spread_pct:
        reasons.append(f"spread {spread_pct} exceeds max_spread_pct={risk_limits.max_spread_pct}")
    if option.volume < risk_limits.min_option_volume:
        reasons.append(f"volume {option.volume} below min_option_volume={risk_limits.min_option_volume}")
    if option.open_interest < risk_limits.min_option_open_interest:
        reasons.append(f"open_interest {option.open_interest} below min_option_open_interest={risk_limits.min_option_open_interest}")
    if quote_age is not None and quote_age > risk_limits.stale_data_max_seconds:
        reasons.append(f"quote age {quote_age:.0f}s exceeds stale_data_max_seconds={risk_limits.stale_data_max_seconds}")

    if not reasons:
        classification = LiquidityClassification.LIQUID
    elif len(reasons) == 1:
        classification = LiquidityClassification.MARGINAL
    else:
        classification = LiquidityClassification.ILLIQUID

    return LiquidityAssessment(
        option.option_id, spread, spread_pct, option.bid_size, option.ask_size, option.volume,
        option.open_interest, quote_age, classification,
        "; ".join(reasons) if reasons else None, tuple(configuration_required),
    )
