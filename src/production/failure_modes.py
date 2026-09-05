"""Phase 36, Part 20 — a single, canonical list of every fail-closed
reason this package's pipeline can stop for, plus the two exception
types this package adds that nothing else already covers.

Every other failure mode Part 20 lists already has a real, specific
representation elsewhere in this codebase, reused here rather than
duplicated:
  - stale quote            -> src.production.timestamps.StaleQuoteError
  - missing quote / invalid/expired/inactive contract / missing option ID
                            -> src.production.contract_validation.ContractRejectionCode
  - malformed decision      -> src.production.decision.MalformedDecisionError
  - risk rejection          -> src.risk.manager.RiskDecision(allowed=False)
  - emergency stop          -> src.execution.emergency_stop.EmergencyStopStore (Phase 35, unchanged)
  - unauthorized system state -> src.execution.system_state.is_live_trading_authorized (Phase 35, unchanged)
  - duplicate order/position -> src.risk.manager.RiskManager.check_duplicate_position +
                                 src.execution.pending.PendingOrderStore (Phase 34/35, unchanged)
"""

from __future__ import annotations


class AccountUnavailableError(RuntimeError):
    """Raised/reported when AccountState is missing the fields a decision
    cycle needs (no account_number, or no buying_power_usd) -- the
    live-analogue of a failed get_accounts/get_portfolio call. Never
    silently substitutes a default account number or a guessed buying
    power."""


class BrokerUnavailableError(RuntimeError):
    """Raised by a caller (not this package -- it never calls the broker)
    when a live data/tool call fails outright. Included here so
    pipeline-level tests have one place to assert this failure mode
    produces NO_TRADE, never an executable order."""


# Canonical PipelineResult.outcome_code values -- see pipeline.py.
NO_VALIDATED_STRATEGY = "NO_VALIDATED_STRATEGY"
ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"
NO_DECISIONS = "NO_DECISIONS"
NO_OPPORTUNITIES = "NO_OPPORTUNITIES"
CONTRACT_REJECTED = "CONTRACT_REJECTED"
RISK_REJECTED = "RISK_REJECTED"
EMERGENCY_STOP_ACTIVE = "EMERGENCY_STOP_ACTIVE"
NOT_AUTHORIZED = "NOT_AUTHORIZED"
READY_FOR_AUTHORIZATION = "READY_FOR_AUTHORIZATION"
EXIT_PROPOSED = "EXIT_PROPOSED"

ALL_OUTCOME_CODES = frozenset({
    NO_VALIDATED_STRATEGY, ACCOUNT_UNAVAILABLE, NO_DECISIONS, NO_OPPORTUNITIES, CONTRACT_REJECTED,
    RISK_REJECTED, EMERGENCY_STOP_ACTIVE, NOT_AUTHORIZED, READY_FOR_AUTHORIZATION, EXIT_PROPOSED,
})
