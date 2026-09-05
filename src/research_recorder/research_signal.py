"""Phase 37, Part 14 — MOMENTUM_BREAKOUT_EXISTING_V1 evaluated PURELY as
a research signal, via Phase 36's own
`MomentumBreakoutProductionAdapter` (unchanged, no new adapter built for
this phase). The strategy's real, frozen (Phase 35), unmodified logic
runs exactly as it does in `src.production`; only what this module does
with the result differs -- it is recorded, never executed.

Every record produced here is labeled `HYPOTHETICAL_RESEARCH_DECISION`,
never `TRADE`/`ORDER`/`POSITION`/`FILL` (Part 14's explicit instruction).
This module never touches `StrategyRegistry`/`ValidationArtifact` --
`MOMENTUM_BREAKOUT_EXISTING_V1` stays exactly as `NOT_READY` as it is
everywhere else in this project; nothing here registers or promotes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from src.production.decision import DecisionType
from src.production.momentum_breakout_adapter import MomentumBreakoutProductionAdapter
from src.production.snapshot import AccountState, RiskStateSnapshot, StrategySnapshot

if TYPE_CHECKING:
    from src.market.data_provider import MarketDataProvider


class ResultLabel(str, Enum):
    HYPOTHETICAL_RESEARCH_DECISION = "HYPOTHETICAL_RESEARCH_DECISION"


@dataclass(frozen=True)
class ResearchSignalRecord:
    observation_cycle_id: str
    strategy_id: str
    signal_timestamp: datetime
    produced_signal: bool
    underlying: str | None
    candidate_option_id: str | None
    decision: str  # DecisionType.value -- NEVER "TRADE"/"ORDER"/"POSITION"/"FILL"
    features: Mapping[str, Any]
    reason: str
    label: str = ResultLabel.HYPOTHETICAL_RESEARCH_DECISION.value
    evaluation_error: str | None = None


def _minimal_snapshot(now: datetime) -> StrategySnapshot:
    """The adapter's `decide()` only reads `snapshot.timestamp` -- it
    injects its own MarketDataProvider/universe via its constructor (see
    `src.production.momentum_breakout_adapter`). Every other field here
    is an intentionally minimal, unused placeholder, exactly mirroring
    Phase 36's own test fixture for this adapter."""
    return StrategySnapshot(
        timestamp=now,
        account=AccountState(account_number=None, buying_power_usd=None, equity_usd=None, as_of=now),
        underlying=None,  # type: ignore[arg-type]  -- unused by this adapter
        option_chain=(), option_quotes={}, positions=(),
        risk_state=RiskStateSnapshot(trades_opened_today=0, daily_pnl_usd=0.0, last_exit_time=None, last_position_size_usd=None, last_trade_was_loss=False),
        risk_limits=None, settings=None,  # type: ignore[arg-type]
    )


def evaluate_research_signal_for_cycle(
    *, market: "MarketDataProvider", universe: Sequence[str], observation_cycle_id: str, now: datetime,
) -> ResearchSignalRecord:
    adapter = MomentumBreakoutProductionAdapter(market, universe)
    try:
        decision = adapter.decide(_minimal_snapshot(now))
    except Exception as exc:  # noqa: BLE001 -- a scan failure must never crash the whole observation cycle
        return ResearchSignalRecord(
            observation_cycle_id=observation_cycle_id, strategy_id=adapter.strategy_id, signal_timestamp=now,
            produced_signal=False, underlying=None, candidate_option_id=None, decision=DecisionType.NO_TRADE.value,
            features={}, reason=f"Strategy evaluation failed: {exc}", evaluation_error=str(exc),
        )

    return ResearchSignalRecord(
        observation_cycle_id=observation_cycle_id, strategy_id=decision.strategy_id, signal_timestamp=decision.timestamp,
        produced_signal=decision.decision == DecisionType.ENTER, underlying=decision.underlying,
        candidate_option_id=decision.option_id, decision=decision.decision.value, features=dict(decision.features),
        reason=decision.reason,
    )
