"""Phase 36, Part 18 — an adapter proving the production Strategy
interface CAN represent the existing, unmodified `MomentumBreakoutStrategy`.

This module changes NO logic in `src/strategy/momentum_breakout.py`.
`decide()` constructs the REAL `MomentumBreakoutStrategy` and calls its
REAL, unmodified `scan()` method, then maps whatever `SetupCandidate` it
returns (if any) into a `StrategyDecision` -- pure translation, no new
signal, no parameter change, no optimization.

`MomentumBreakoutProductionAdapter` is registered in the default registry
at `StrategyStatus.NOT_READY` (registry.py's `build_default_registry`)
and stays there -- this module does not, and structurally cannot (there
is no `mark_validated` call anywhere in it), make it production-eligible.
No live trade path exists for it: this adapter is exercised only by
`tests/test_phase36_momentum_breakout_adapter.py`, never by
`orchestrator.py`'s real cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from src.options.phase35_frozen_strategy_spec import STRATEGY_ID
from src.production.decision import DecisionType, StrategyDecision
from src.production.strategy_interface import ProductionStrategy
from src.strategy.momentum_breakout import MomentumBreakoutStrategy

if TYPE_CHECKING:
    from src.market.data_provider import MarketDataProvider
    from src.production.snapshot import StrategySnapshot


class MomentumBreakoutProductionAdapter(ProductionStrategy):
    strategy_id = STRATEGY_ID  # "MOMENTUM_BREAKOUT_EXISTING_V1" -- must remain NOT_READY in the registry

    def __init__(self, market: "MarketDataProvider", universe: Sequence[str]):
        self._market = market
        self._universe = tuple(universe)

    def decide(self, snapshot: "StrategySnapshot") -> StrategyDecision:
        # The REAL, unmodified strategy -- no parameter override, no
        # config change, exactly what the live orchestrator constructs.
        inner = MomentumBreakoutStrategy(now=snapshot.timestamp)
        candidates = inner.scan(self._market, self._universe)  # REAL, unmodified scan()

        if not candidates:
            return StrategyDecision(
                strategy_id=self.strategy_id, timestamp=snapshot.timestamp, decision=DecisionType.NO_TRADE,
                reason="MomentumBreakoutStrategy.scan() found no qualifying setup this cycle.",
            )

        top = max(candidates, key=lambda c: c.score)
        return StrategyDecision(
            strategy_id=self.strategy_id,
            timestamp=snapshot.timestamp,
            decision=DecisionType.ENTER,
            underlying=top.underlying_symbol,
            option_id=top.option_id,
            option_type="call" if top.side == "long_call" else "put",
            strike=None,  # not exposed on SetupCandidate -- never parsed out of option_description here, never fabricated
            expiration=top.expiration,
            side=top.side,
            quantity_recommendation=top.suggested_quantity,
            signal_score=top.score,
            expected_holding_period_minutes=None,  # MomentumBreakoutStrategy has no fixed holding period -- see FrozenStrategySpec.ExitSpec.maximum_holding_period_rule
            reason="; ".join(top.signals) if top.signals else "MomentumBreakoutStrategy setup",
            features={"signals": top.signals, "thesis_catalyst": top.thesis.catalyst},
            confidence=None,  # MomentumBreakoutStrategy does not supply a confidence score
        )
