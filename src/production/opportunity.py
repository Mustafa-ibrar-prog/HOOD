"""Phase 36, Part 11 — the canonical Opportunity object between strategy
and risk.

Only an ENTER `StrategyDecision` produces an Opportunity -- EXIT is
never risk-gated (RiskManager.evaluate_exit_conditions is advisory-only,
closing risk is always allowed) and routes directly to that existing
check, not through this object; HOLD/NO_TRADE produce nothing to route
at all. No opportunity may bypass risk (Part 11) -- there is no
constructor path from `StrategyDecision` straight to an `OrderRequest`
anywhere in this module or any other in this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.production.decision import DecisionType, StrategyDecision
from src.production.liquidity import LiquidityAssessment
from src.production.live_snapshot import OptionLiveState


class NotAnEntryDecisionError(ValueError):
    """Raised by build_opportunity when given a decision that is not ENTER
    -- an Opportunity only ever represents a candidate NEW position."""


@dataclass(frozen=True)
class Opportunity:
    strategy_id: str
    timestamp: datetime
    underlying: str
    option: OptionLiveState
    decision: StrategyDecision
    liquidity: LiquidityAssessment
    estimated_entry_price: float | None
    estimated_maximum_loss_usd: float | None
    proposed_holding_period_minutes: float | None
    reason: str
    confidence: float | None


def build_opportunity(
    decision: StrategyDecision, *, option: OptionLiveState, liquidity: LiquidityAssessment,
) -> Opportunity:
    if decision.decision != DecisionType.ENTER:
        raise NotAnEntryDecisionError(f"build_opportunity requires an ENTER decision, got {decision.decision.value}")

    # Entry price estimate: the live ask (a marketable buy-to-open limit),
    # the same convention MOMENTUM_BREAKOUT_EXISTING_V1's own
    # entry_price_rule uses (src/options/phase35_frozen_strategy_spec.py)
    # -- never fabricated when the ask itself is missing.
    estimated_entry_price = option.ask
    estimated_maximum_loss_usd = None
    if estimated_entry_price is not None and decision.quantity_recommendation is not None:
        # Long options: maximum loss is the full premium paid (100% of
        # entry cost), never more -- CONTRACT_MULTIPLIER reused from
        # src.config.constants, not redefined.
        from src.config.constants import CONTRACT_MULTIPLIER

        estimated_maximum_loss_usd = estimated_entry_price * decision.quantity_recommendation * CONTRACT_MULTIPLIER

    return Opportunity(
        strategy_id=decision.strategy_id,
        timestamp=decision.timestamp,
        underlying=decision.underlying,  # type: ignore[arg-type]  -- guaranteed non-None by ENTER validation in StrategyDecision.__post_init__
        option=option,
        decision=decision,
        liquidity=liquidity,
        estimated_entry_price=estimated_entry_price,
        estimated_maximum_loss_usd=estimated_maximum_loss_usd,
        proposed_holding_period_minutes=decision.expected_holding_period_minutes,
        reason=decision.reason,
        confidence=decision.confidence,
    )
