"""Phase 36, Part 14-16 — the live decision pipeline, connected end to
end but NOT activated.

    Market Data -> Strategy -> Opportunity -> Liquidity -> Risk ->
    Position Size -> Authorization -> Execution -> Order Monitor ->
    Position Manager -> Exit Engine

`run_live_decision_cycle` implements everything up through Authorization
(a READ-ONLY status check, reusing Phase 35's `EmergencyStopStore`/
`is_live_trading_authorized` completely unchanged) and stops there --
it NEVER imports `src.execution.gateway`, never constructs a
`LiveOrderPlacer`, and never calls `submit_order`/`place_option_order`.
The `OrderRequest` it can produce is handed back as data; wiring THAT
into a real gateway call is future work for a phase that actually
activates live trading, not this one (Phase 36 explicitly: "architecture
... without activating it").

Part 14's mandatory fail-closed rule is the FIRST thing this function
checks, unconditionally, before any strategy is even called:
`registry.production_eligible_strategies()` empty => NO_TRADE /
NO_VALIDATED_STRATEGY, regardless of `live_auto_execute`, risk
configuration, account balance, opportunity score, or market
conditions -- none of those are even looked at yet when this check
runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Sequence

from src.production import failure_modes as fm
from src.production.contract_validation import ContractValidationResult, validate_option_contract
from src.production.decision import DecisionType, StrategyDecision
from src.production.liquidity import LiquidityAssessment, assess_liquidity
from src.production.opportunity import Opportunity, build_opportunity
from src.production.ranking import RankedOpportunity, rank_or_no_validated_strategy
from src.production.registry import StrategyRegistry
from src.production.risk_handoff import RiskHandoffResult, evaluate_opportunity_against_risk
from src.production.snapshot import StrategySnapshot

if TYPE_CHECKING:
    from datetime import datetime

    from src.backtesting.sizing import PositionSizer
    from src.execution.emergency_stop import EmergencyStopStore
    from src.execution.orders import OrderRequest
    from src.execution.system_state import SystemStateAuditLog
    from src.production.strategy_interface import ProductionStrategy
    from src.risk.manager import RiskManager


@dataclass(frozen=True)
class PipelineResult:
    decision_type: DecisionType  # ENTER only when a concrete, risk-approved order is ready; NO_TRADE otherwise
    outcome_code: str  # one of src.production.failure_modes.ALL_OUTCOME_CODES
    detail: str
    ranked_opportunities: tuple[RankedOpportunity, ...] = ()
    contract_rejections: tuple[ContractValidationResult, ...] = ()
    risk_handoff: RiskHandoffResult | None = None
    order_request: "OrderRequest | None" = None  # inert data -- never submitted by this module


def run_live_decision_cycle(
    *,
    registry: StrategyRegistry,
    strategies_by_id: Mapping[str, "ProductionStrategy"],
    snapshots_by_underlying: Mapping[str, StrategySnapshot],
    risk_manager: "RiskManager",
    sizer: "PositionSizer",
    account_number: str,
    now: "datetime",
    emergency_stop_store: "EmergencyStopStore | None" = None,
    system_state_audit_log: "SystemStateAuditLog | None" = None,
    max_quote_age_seconds: float = 90.0,
    held_underlyings: frozenset[str] = frozenset(),
) -> PipelineResult:
    # --- Part 14: the mandatory, unconditional, FIRST check -------------
    eligible = registry.production_eligible_strategies()
    if not eligible:
        return PipelineResult(DecisionType.NO_TRADE, fm.NO_VALIDATED_STRATEGY, "No VALIDATED/LIVE_AUTHORIZED strategy in the registry.")

    eligible_ids = {m.strategy_id for m in eligible}

    # --- Part 20: account unavailable -----------------------------------
    for snapshot in snapshots_by_underlying.values():
        if snapshot.account.account_number is None or snapshot.account.buying_power_usd is None:
            return PipelineResult(DecisionType.NO_TRADE, fm.ACCOUNT_UNAVAILABLE, "AccountState is missing account_number/buying_power_usd.")
        account = snapshot.account
        break
    else:
        return PipelineResult(DecisionType.NO_TRADE, fm.NO_DECISIONS, "No snapshots provided.")

    # --- Strategy -> Decision --------------------------------------------
    decisions: list[StrategyDecision] = []
    for underlying, snapshot in snapshots_by_underlying.items():
        for strategy_id, strategy in strategies_by_id.items():
            if strategy_id not in eligible_ids:
                continue  # never call a strategy that isn't production-eligible, even if a caller mistakenly wired it in
            decision = strategy.decide(snapshot)
            if decision.decision == DecisionType.ENTER:
                decisions.append(decision)

    if not decisions:
        return PipelineResult(DecisionType.NO_TRADE, fm.NO_DECISIONS, "No ENTER decision from any eligible strategy this cycle.")

    # --- Contract validation, then Liquidity, then Opportunity ----------
    opportunities: list[Opportunity] = []
    rejections: list[ContractValidationResult] = []
    for decision in decisions:
        snapshot = snapshots_by_underlying[decision.underlying]  # type: ignore[index]
        live = snapshot.option_quotes.get(decision.option_id)  # type: ignore[arg-type]
        option = live.option if live is not None else None
        result = validate_option_contract(option, now=now, max_quote_age_seconds=max_quote_age_seconds)
        if not result.passed:
            rejections.append(result)
            continue
        liquidity = assess_liquidity(option, now=now, risk_limits=snapshot.risk_limits)  # type: ignore[arg-type]
        opportunities.append(build_opportunity(decision, option=option, liquidity=liquidity))  # type: ignore[arg-type]

    if not opportunities:
        return PipelineResult(
            DecisionType.NO_TRADE, fm.CONTRACT_REJECTED if rejections else fm.NO_OPPORTUNITIES,
            "Every candidate contract failed validation." if rejections else "No opportunities survived contract validation.",
            contract_rejections=tuple(rejections),
        )

    # --- Ranking (Part 13) ------------------------------------------------
    ranked = rank_or_no_validated_strategy(opportunities, has_validated_strategy=True, account=account, held_underlyings=held_underlyings)
    if ranked == fm.NO_VALIDATED_STRATEGY:  # unreachable given the Part-14 gate above, kept for defense-in-depth
        return PipelineResult(DecisionType.NO_TRADE, fm.NO_VALIDATED_STRATEGY, "Ranking layer reports no validated strategy.")
    if not ranked:
        return PipelineResult(DecisionType.NO_TRADE, fm.NO_OPPORTUNITIES, "Ranking produced no candidates.", contract_rejections=tuple(rejections))

    top = ranked[0].opportunity
    top_snapshot = snapshots_by_underlying[top.underlying]

    # --- Risk -> Position Size -> Order Validation (Part 12) ------------
    handoff = evaluate_opportunity_against_risk(
        top,
        risk_manager=risk_manager,
        sizer=sizer,
        account_number=account_number,
        trades_opened_today=top_snapshot.risk_state.trades_opened_today,
        daily_pnl_usd=top_snapshot.risk_state.daily_pnl_usd,
        open_positions=top_snapshot.positions,
        last_exit_time=top_snapshot.risk_state.last_exit_time,
        data_age_seconds=(now - top.option.timestamp).total_seconds() if top.option.timestamp else float("inf"),
        underlying_move_pct=0.0,  # Part 12 scope: computed upstream by whatever builds StrategySnapshot; not recomputed here
        now=now,
        last_position_size_usd=top_snapshot.risk_state.last_position_size_usd,
        last_trade_was_loss=top_snapshot.risk_state.last_trade_was_loss,
        available_cash=account.buying_power_usd,
        portfolio_equity=account.equity_usd or account.buying_power_usd,
    )
    if handoff.order_request is None:
        return PipelineResult(
            DecisionType.NO_TRADE, fm.RISK_REJECTED, handoff.rejection_reason or "Risk handoff produced no order.",
            ranked_opportunities=tuple(ranked), contract_rejections=tuple(rejections), risk_handoff=handoff,
        )

    # --- Authorization (Part 16, READ-ONLY -- never clears/authorizes anything) ---
    if emergency_stop_store is None or emergency_stop_store.is_stopped():
        return PipelineResult(
            DecisionType.NO_TRADE, fm.EMERGENCY_STOP_ACTIVE, "Emergency stop is active (or not configured).",
            ranked_opportunities=tuple(ranked), risk_handoff=handoff,
        )
    from src.execution.system_state import is_live_trading_authorized  # local import: keep this module's top-level imports free of anything execution-adjacent beyond the read-only checks used here

    if system_state_audit_log is None or not is_live_trading_authorized(system_state_audit_log):
        return PipelineResult(
            DecisionType.NO_TRADE, fm.NOT_AUTHORIZED, "System is not authorized for LIVE_AUTONOMOUS_TRADING.",
            ranked_opportunities=tuple(ranked), risk_handoff=handoff,
        )

    # --- Everything passed. Still not submitted -- see module docstring. ---
    return PipelineResult(
        DecisionType.ENTER, fm.READY_FOR_AUTHORIZATION,
        "Opportunity is risk-approved, sized, and the system is authorized -- ready for a caller to hand "
        "order_request to an execution gateway. This function itself never does so.",
        ranked_opportunities=tuple(ranked), risk_handoff=handoff, order_request=handoff.order_request,
    )
