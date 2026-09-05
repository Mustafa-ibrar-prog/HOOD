"""Phase 36, Part 12 — the exact handoff:

    Opportunity -> RiskEngine -> PositionSizer -> ExecutionOrder

Risk can reject an Opportunity outright (`RiskDecision.allowed=False`);
when it does, no `OrderRequest` is ever constructed. A strategy's own
`quantity_recommendation`/`signal_score` are only ever a HINT fed into
the position sizer's `signal_strength` parameter -- the actual order
quantity always comes from `PositionSizer.target_quantity()`, never
copied from the strategy's decision directly (Part 12: "Strategy cannot
override risk").

This module constructs an `OrderRequest` (Part 12's "ExecutionOrder")
but NEVER calls `submit_order`/`place_option_order` -- it has no
reference to `src.execution.gateway` or any `LiveOrderPlacer` at all
(verified by `tests/test_phase36_strategy_isolation.py`). "Only the
execution gateway can submit orders" remains true: constructing the
inert `OrderRequest` dataclass is not submitting it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Iterable

from src.config.constants import CONTRACT_MULTIPLIER
from src.execution.asset_class_restriction import NonOptionsOrderRejected, assert_options_only
from src.execution.orders import OrderLeg, OrderRequest
from src.production.opportunity import Opportunity

if TYPE_CHECKING:
    from src.backtesting.sizing import PositionSizer
    from src.risk.manager import RiskDecision, RiskManager
    from src.risk.models import HeldPosition


@dataclass(frozen=True)
class RiskHandoffResult:
    opportunity: Opportunity
    risk_decision: "RiskDecision | None"
    sized_quantity: int | None
    order_request: OrderRequest | None
    rejection_reason: str | None


def evaluate_opportunity_against_risk(
    opportunity: Opportunity,
    *,
    risk_manager: "RiskManager",
    sizer: "PositionSizer",
    account_number: str,
    trades_opened_today: int,
    daily_pnl_usd: float,
    open_positions: Iterable["HeldPosition"],
    last_exit_time: datetime | None,
    data_age_seconds: float,
    underlying_move_pct: float,
    now: datetime,
    last_position_size_usd: float | None,
    last_trade_was_loss: bool,
    available_cash: float,
    portfolio_equity: float,
) -> RiskHandoffResult:
    if opportunity.estimated_entry_price is None:
        return RiskHandoffResult(opportunity, None, None, None, "No estimated entry price -- cannot evaluate risk")

    hinted_quantity = opportunity.decision.quantity_recommendation or 1
    proposed_size_usd = opportunity.estimated_entry_price * hinted_quantity * CONTRACT_MULTIPLIER

    risk_decision = risk_manager.evaluate_new_trade(
        candidate_symbol=opportunity.underlying,
        candidate_option_id=opportunity.option.option_id,
        proposed_size_usd=proposed_size_usd,
        trades_opened_today=trades_opened_today,
        daily_pnl_usd=daily_pnl_usd,
        open_positions=open_positions,
        last_exit_time=last_exit_time,
        data_age_seconds=data_age_seconds,
        bid=opportunity.option.bid or 0.0,
        ask=opportunity.option.ask or 0.0,
        volume=opportunity.option.volume,
        open_interest=opportunity.option.open_interest,
        underlying_move_pct=underlying_move_pct,
        now=now,
        last_position_size_usd=last_position_size_usd,
        last_trade_was_loss=last_trade_was_loss,
    )
    if not risk_decision.allowed:
        return RiskHandoffResult(opportunity, risk_decision, None, None, "; ".join(risk_decision.blocking_reasons))

    # The strategy's own quantity_recommendation/signal_score are only a
    # HINT here (signal_strength) -- the real quantity is whatever the
    # sizer computes, never copied straight from the decision.
    sized_quantity = sizer.target_quantity(
        signal_strength=opportunity.decision.signal_score or 0.0,
        reference_price=opportunity.estimated_entry_price,
        available_cash=available_cash,
        portfolio_equity=portfolio_equity,
    )
    if sized_quantity <= 0:
        return RiskHandoffResult(opportunity, risk_decision, 0, None, "Position sizer returned zero quantity")

    order_request = OrderRequest(
        account_number=account_number,
        legs=(OrderLeg(option_id=opportunity.option.option_id, side="buy", position_effect="open"),),
        quantity=str(sized_quantity),
        type="limit",
        price=f"{opportunity.estimated_entry_price:.2f}",
        reason=f"{opportunity.strategy_id}: {opportunity.reason}",
    )
    # Order Validation stage (Part 3's pipeline): defense-in-depth reuse of
    # Phase 18/35's own boundary check -- structurally redundant given
    # OrderLeg always requires option_id, but explicit, not assumed.
    try:
        assert_options_only(order_request)
    except NonOptionsOrderRejected as exc:
        return RiskHandoffResult(opportunity, risk_decision, sized_quantity, None, f"Order validation failed: {exc}")

    return RiskHandoffResult(opportunity, risk_decision, sized_quantity, order_request, None)
