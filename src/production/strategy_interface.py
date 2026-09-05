"""Phase 36, Part 2-3 — the strict production Strategy interface.

`ProductionStrategy` is the ONLY shape a strategy may implement to
participate in the live decision pipeline. Its single method receives a
`StrategySnapshot` and returns a `StrategyDecision` -- both pure data
(see snapshot.py / decision.py). This module, and every concrete
`ProductionStrategy` implementation, must have NO access to:

  - Robinhood order placement (src.execution.gateway, src.execution.live_client)
  - broker credentials (src.market.hood_client)
  - the live-authorization store (src.execution.system_state)
  - the emergency-stop store (src.execution.emergency_stop)

`tests/test_phase36_strategy_isolation.py` verifies this by AST-scanning
this module and every concrete adapter for a forbidden import -- an
architectural test, not a convention someone has to remember.

Strategy -> Decision -> Risk -> Position Sizing -> Order Validation ->
Authorization -> Execution (Part 3) is enforced by every downstream
module in this package calling the one before it; nothing in this
module, or any `ProductionStrategy` implementation, is capable of
skipping ahead to Execution -- there is no execution-shaped object
reachable from here at all.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.production.decision import StrategyDecision
    from src.production.snapshot import StrategySnapshot


class ProductionStrategy(ABC):
    strategy_id: str = "unnamed-production-strategy"

    @abstractmethod
    def decide(self, snapshot: "StrategySnapshot") -> "StrategyDecision":
        """Pure function of `snapshot` -- no side effects, no order
        placement, no broker access. Must not raise for "nothing to do";
        return a NO_TRADE/HOLD decision instead (mirrors
        `Strategy.scan`'s "must not raise for no setups found"
        convention in src/strategy/base.py)."""
        raise NotImplementedError
