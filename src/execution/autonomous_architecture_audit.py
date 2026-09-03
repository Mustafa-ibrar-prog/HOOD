"""Phase 28, Part 12/13/14 — architecture-readiness audit for the future
autonomous execution loop. Design/audit only (Part 12: "Do NOT implement
live trading in this phase") -- every entry below is a REAL, already-
existing module this phase found by inspection, not a new implementation.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class ReadinessStatus(enum.Enum):
    READY = "ready"  # a real, existing module already implements this stage
    PARTIAL = "partial"  # a real module exists but only partially covers the stage
    MISSING = "missing"  # no real module implements this stage yet


@dataclass(frozen=True)
class PipelineStageAudit:
    stage: str
    real_module: str
    status: ReadinessStatus
    note: str


# Part 12's exact 15-stage pipeline, audited against this codebase's real,
# already-existing modules (every one of these was inspected directly this
# phase, not assumed from a module name).
PIPELINE_READINESS: tuple[PipelineStageAudit, ...] = (
    PipelineStageAudit("MARKET DATA", "src/market/hood_provider.py (HoodMarketDataProvider)", ReadinessStatus.READY,
                        "Real, already wired into src/orchestrator.py."),
    PipelineStageAudit("UNIVERSE SCANNER", "src/strategy/scanner.py (StrategyScanner) + Settings.scan_universe", ReadinessStatus.READY,
                        "Real; scan universe is a configured symbol list."),
    PipelineStageAudit("OPTION CHAIN SCANNER", "src/market/hood_provider.py + src/strategy/momentum_breakout.py's chain-fetching logic", ReadinessStatus.READY,
                        "Real, but folded into the strategy module rather than a separately named component -- functionally present, not architecturally separated."),
    PipelineStageAudit("FEATURE ENGINE", "src/features/ (multiple real modules)", ReadinessStatus.READY,
                        "Real, substantial existing feature library from Phases 1-21."),
    PipelineStageAudit("SIGNAL ENGINE", "src/strategy/base.py (Strategy) + src/strategy/momentum_breakout.py (MomentumBreakoutStrategy)", ReadinessStatus.READY,
                        "Real; exactly one concrete strategy exists today (MomentumBreakoutStrategy) -- 'signal engine' currently means one strategy, not a pluggable registry of many."),
    PipelineStageAudit("OPPORTUNITY RANKER", "src/options/opportunity_score.py (OpportunityScore, ContractCandidate, ChainCandidate)", ReadinessStatus.READY,
                        "Real scoring/ranking types exist."),
    PipelineStageAudit("LIQUIDITY FILTER", "src/risk/manager.py (RiskManager) + Settings.min_option_volume/min_option_open_interest/max_spread_pct", ReadinessStatus.READY,
                        "Real, enforced as explicit RiskManager checks, not a separately named module -- functionally present."),
    PipelineStageAudit("RISK ENGINE", "src/risk/manager.py (RiskManager, RiskDecision, RiskCheckResult)", ReadinessStatus.READY,
                        "Real, the most mature single component in this list -- already the deterministic gate every proposed trade must clear."),
    PipelineStageAudit("POSITION SIZER", "src/risk/manager.py's RiskManager.check_position_size + Settings.max_position_size_usd", ReadinessStatus.PARTIAL,
                        "Real, but folded into RiskManager rather than a dedicated module -- no volatility/Kelly/liquidity-aware sizing logic exists yet, only a flat USD cap check."),
    PipelineStageAudit("EXECUTION ENGINE", "src/execution/gateway.py (ExecutionGateway/PaperExecutionGateway/LiveExecutionGateway)", ReadinessStatus.READY,
                        "Real, and ALREADY SUPPORTS a no-human-in-the-loop path: LiveExecutionGateway.submit_order() with settings.live_auto_execute=True calls _place_pending(..., approved_by='system:auto_execute') directly -- see this module's own audit finding below."),
    PipelineStageAudit("ROBINHOOD", "mcp__HOOD__* tools (external, agent-mediated -- see Part 14 below)", ReadinessStatus.READY,
                        "Real and already the sole real order-placement/account/live-data path this entire project has ever used."),
    PipelineStageAudit("ORDER MONITOR", "src/position_manager/monitor.py (PositionMonitor)", ReadinessStatus.READY,
                        "Real, already wired into src/orchestrator.py's cycle."),
    PipelineStageAudit("POSITION MANAGER", "src/position_manager/ (store.py, models.py, hood_sync.py, peak_tracker.py)", ReadinessStatus.READY,
                        "Real, substantial existing package."),
    PipelineStageAudit("EXIT ENGINE", "src/position_manager/evaluator.py (PositionEvaluator)", ReadinessStatus.READY,
                        "Real; HOLD/EARLY_EXIT/TARGET_EXIT/STOP_EXIT/trailing-exit logic all already implemented and tested."),
    PipelineStageAudit("TRADE JOURNAL", "src/logging/trade_journal.py (TradeJournal, TradeJournalEntry)", ReadinessStatus.READY,
                        "Real, already wired into src/orchestrator.py's cycle."),
)


# The single most important real finding of this audit (Part 12): the
# execution engine's no-per-trade-approval path is NOT missing infrastructure
# -- it already exists (settings.live_auto_execute=True), already tested
# (tests/test_execution_gateway.py from an earlier phase), and is gated by
# THREE independent, already-real switches (trading_mode=="live" AND
# live_trading_confirmed AND live_auto_execute). What is genuinely missing
# is the SYSTEM-LEVEL, auditable authorization LAYER this phase adds in
# system_state.py -- a formal record of WHO/WHEN/WHY those switches were
# ever turned on, plus a PAUSED/EMERGENCY_STOP concept neither switch has.
#
# A second, real, honestly-reported finding: src/orchestrator.py's own
# module docstring is now STALE -- it says "In TRADING_MODE=live, this
# module still never places a real order itself... every submit_order()
# call... only ever creates a PendingLiveOrder awaiting explicit human
# approval," without mentioning that gateway.py's live_auto_execute=True
# path already bypasses that pending-approval step entirely. This is a
# documentation gap, not a code bug -- flagged here, NOT edited this phase
# (Part 12: do not implement/modify live trading this phase; a docstring
# in the live execution path is left untouched out of the same caution).
ORCHESTRATOR_DOCSTRING_STALENESS_FINDING = (
    "src/orchestrator.py's module docstring describes every live submit_order() call as always stopping at "
    "a PendingLiveOrder awaiting human approval. This was accurate when written but is no longer the whole "
    "picture: src/execution/gateway.py's LiveExecutionGateway.submit_order() has since gained a "
    "live_auto_execute=True path that places the order immediately with no pending-approval step, gated only "
    "by RiskManager/PositionEvaluator's deterministic checks. Reported here as a real finding; not edited "
    "this phase."
)


class OptionStructure(enum.Enum):
    """Part 13's explicit allow-list. Only structures the risk engine can
    accurately model may ever be enabled -- today that is exactly one."""

    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    DEFINED_RISK_SPREAD = "defined_risk_spread"  # NOT YET risk-modeled by RiskManager -- see note below


CURRENTLY_RISK_MODELED_STRUCTURES: frozenset[OptionStructure] = frozenset({OptionStructure.LONG_CALL, OptionStructure.LONG_PUT})

OPTIONS_ONLY_ENFORCEMENT_FINDING = (
    "Confirmed by direct inspection this phase: src/execution/gateway.py's OrderRequest/PendingLiveOrder "
    "types and every real order-placement path in this codebase are option-leg-shaped (contract identity, "
    "strike, expiration, right) -- there is no equity/ETF-share order type or code path anywhere in "
    "src/execution/ or src/orchestrator.py. Rejection of stock/ETF-share orders (Part 13) is therefore "
    "structural (no such order can even be CONSTRUCTED, let alone submitted), not merely a runtime check "
    "that could be bypassed. MomentumBreakoutStrategy (the only real strategy today) only ever proposes "
    "single-leg long call/put option trades -- defined-risk spreads are listed in Part 13's allow-list but "
    "are NOT YET risk-modeled by RiskManager (no multi-leg net-debit/max-loss check exists yet) and must "
    "stay disabled until a future phase builds that risk model, per Part 13's own instruction: "
    "'Only structures that the risk engine can accurately model may eventually be enabled.'"
)


class SystemRole(enum.Enum):
    LIVE_DATA_ACCOUNT_POSITIONS_ORDERS_EXECUTION = "live_data_account_positions_orders_execution"
    RESEARCH_BACKTESTING_HISTORICAL_LIQUIDITY_IV_GREEKS = "research_backtesting_historical_liquidity_iv_greeks"


@dataclass(frozen=True)
class RoleAssignment:
    system: str
    role: SystemRole
    note: str


# Part 14's exact role separation, confirmed unchanged by this phase --
# Phase 25/26/27 already established and preserved this boundary; this
# phase re-confirms it, never blurs it.
ROLE_ASSIGNMENTS: tuple[RoleAssignment, ...] = (
    RoleAssignment("Robinhood (mcp__HOOD__* tools)", SystemRole.LIVE_DATA_ACCOUNT_POSITIONS_ORDERS_EXECUTION,
                    "Unchanged since Phase 15/24/25/26/27 -- the sole live/account/execution source, never a historical-research source."),
    RoleAssignment("QuantConnect/Lean free sample (Phase 26/27) + any future paid provider (Part 9's ORATS recommendation)", SystemRole.RESEARCH_BACKTESTING_HISTORICAL_LIQUIDITY_IV_GREEKS,
                    "Research/backtest-only; never a live execution or live-quote source. This phase adds no new mixing of the two roles."),
)
