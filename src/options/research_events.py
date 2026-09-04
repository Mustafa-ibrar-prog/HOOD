"""Phase 30, Part 9/17 — the options-research event model, integrating
cleanly with the existing Phase 3 event-driven backtesting framework
(`src/backtesting/events.py`) rather than duplicating it.

MARKET_EVENT is `src.backtesting.events.MarketEvent`, reused directly and
unmodified -- an options-research replay still starts from the same
underlying-bar tick the equity backtester already uses. The other six
categories Part 9 names (OPTION_CHAIN_EVENT, CONTRACT_EVENT, SIGNAL_EVENT,
ORDER_SIMULATION_EVENT, POSITION_EVENT, EXIT_EVENT) have no equity-shaped
equivalent in `events.py` (its `SignalEvent`/`OrderEvent`/`FillEvent` all
carry equity-specific fields -- `direction: "LONG"|"FLAT"`, share
`quantity`, no `option_id`/strike/expiration concept at all), so each is
a new, purpose-built dataclass here, following the exact same shape
conventions (`timestamp` drives queue ordering; `__post_init__`
validates enumerated fields; frozen).

`ResearchEventQueue` is a thin subclass of the base `EventQueue` --
`push()` is the ONLY method it overrides (to recognize this module's
seven event types in addition to `MarketEvent`, via its own priority
table rather than mutating `events.py`'s private `_EVENT_PRIORITY` dict);
`pop()`/`__len__`/`__bool__` and the strict chronological/no-lookahead
guarantee (`LookAheadViolationError`) are inherited unchanged from the
base class, so a research replay gets the exact same "cannot push an
event before the last-popped timestamp" safety Phase 3 already built and
tested.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from datetime import datetime

from src.backtesting.events import EventQueue, LookAheadViolationError, MarketEvent


@dataclass(frozen=True)
class OptionChainEvent:
    """A snapshot of which contracts were REALLY knowable for an
    underlying as of `timestamp` -- never a full future chain; typically
    built from `research_dataset`'s per-contract rows filtered by a PIT
    "as of" cutoff."""

    timestamp: datetime
    underlying_symbol: str
    contract_ids: tuple[str, ...]


@dataclass(frozen=True)
class OptionContractEvent:
    """One real field observation for one contract becoming knowable --
    mirrors `ProvenancedObservation`'s (key/field/value) shape, scoped to
    a single contract."""

    timestamp: datetime
    option_id: str
    field: str
    value: float | None


@dataclass(frozen=True)
class OptionSignalEvent:
    timestamp: datetime
    option_id: str
    underlying_symbol: str
    signal_strength: float
    strategy_name: str
    reason: str = ""


@dataclass(frozen=True)
class OrderSimulationEvent:
    """A SIMULATED order intent and its simulated outcome -- reuses Part
    6's `ExecutionPriceModel` vocabulary as a plain string for
    `execution_model` (e.g. "buy_at_ask") rather than importing the enum
    directly, to avoid a hard dependency loop between the event model and
    the pricing module; a caller constructs this FROM an
    `ExecutionPriceResult`, never the reverse. Never touches a real order
    -- see Part 15's paper-trading interfaces and the phase-wide safety
    test for the structural guarantee that nothing here calls a live
    order-placement path."""

    timestamp: datetime
    option_id: str
    side: str  # "buy" | "sell"
    quantity: int
    execution_model: str
    simulated_price: float | None
    status: str  # "simulated_fill" | "simulated_reject" | "execution_data_limited"
    reason: str = ""

    def __post_init__(self) -> None:
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if self.status not in ("simulated_fill", "simulated_reject", "execution_data_limited"):
            raise ValueError("status must be 'simulated_fill', 'simulated_reject', or 'execution_data_limited'")
        if self.status == "simulated_fill" and self.simulated_price is None:
            raise ValueError("a simulated_fill must carry a simulated_price -- never a fill with no price")


@dataclass(frozen=True)
class OptionPositionEvent:
    """A position state update -- typically built from a Part 7
    `PositionSnapshot`."""

    timestamp: datetime
    option_id: str
    structure: str
    market_value: float | None
    unrealized_pnl: float | None


@dataclass(frozen=True)
class OptionExitEvent:
    timestamp: datetime
    option_id: str
    exit_reason: str
    realized_pnl: float | None


_RESEARCH_EVENT_PRIORITY: dict[type, int] = {
    MarketEvent: 0,
    OptionChainEvent: 1,
    OptionContractEvent: 2,
    OptionSignalEvent: 3,
    OrderSimulationEvent: 4,
    OptionPositionEvent: 5,
    OptionExitEvent: 6,
}


class ResearchEventQueue(EventQueue):
    """See module docstring -- overrides only `push()`."""

    def push(self, event: object) -> None:
        priority = _RESEARCH_EVENT_PRIORITY.get(type(event))
        if priority is None:
            raise TypeError(f"Unknown event type: {type(event).__name__}")
        ts = event.timestamp
        if self._last_popped_timestamp is not None and ts < self._last_popped_timestamp:
            raise LookAheadViolationError(
                f"Attempted to push a {type(event).__name__} timestamped {ts.isoformat()}, which is "
                f"BEFORE the last-processed timestamp {self._last_popped_timestamp.isoformat()} — this "
                "would let a later moment's information influence an earlier one."
            )
        heapq.heappush(self._heap, (ts, priority, next(self._counter), event))
