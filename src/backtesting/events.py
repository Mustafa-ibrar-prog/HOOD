"""The event types and chronological event queue the backtesting engine
is built around (Phase 3, section 1).

MECHANICAL look-ahead enforcement, not just a design intention: EventQueue
tracks the timestamp of the last event it handed out and refuses to accept
a new event timestamped strictly before that. Every place the engine
creates a new event (a signal from a bar, an order from a signal, a fill
from an order) goes through this queue — so a bug that tried to make an
earlier moment depend on a later one would raise LookAheadViolationError
immediately, not silently produce a wrong backtest.
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.data.bar import Bar


class LookAheadViolationError(RuntimeError):
    """Raised by EventQueue.push() when an event would be processed out of
    chronological order — the one invariant this module refuses to bend."""


@dataclass(frozen=True)
class MarketEvent:
    timestamp: datetime
    symbol: str
    bar: Bar


@dataclass(frozen=True)
class SignalEvent:
    timestamp: datetime  # the timestamp of the bar the signal was computed from — NOT when it executes
    symbol: str
    direction: str  # "LONG" | "FLAT" — see src/backtesting/strategy.py; SHORT is reserved, not implemented
    strength: float
    strategy_name: str
    reason: str = ""


@dataclass(frozen=True)
class OrderEvent:
    """`.timestamp` is when this order is ELIGIBLE TO FILL (what the
    EventQueue sorts by — the queue processes every event by `.timestamp`,
    generically) — NOT when the underlying signal was generated. That's
    `generated_at_timestamp`, kept for audit only. For the default
    look-ahead-safe execution model, `.timestamp` is always strictly later
    than `generated_at_timestamp` (see ExecutionModel.delay_bars())."""

    order_id: str
    timestamp: datetime  # == fill-eligible timestamp; used for chronological queue ordering
    generated_at_timestamp: datetime  # the signal's own bar timestamp — audit only, never used for ordering
    symbol: str
    side: str  # "buy" | "sell"
    quantity: int
    order_type: str  # "market" | "limit"
    limit_price: float | None
    strategy_name: str
    reason: str
    risk_decision: str  # "APPROVED" | "MODIFIED" | "REJECTED"
    risk_reason: str

    def __post_init__(self) -> None:
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if self.quantity <= 0:
            raise ValueError("quantity must be > 0")
        if self.order_type not in ("market", "limit"):
            raise ValueError("order_type must be 'market' or 'limit'")
        if self.timestamp < self.generated_at_timestamp:
            raise ValueError("an order's fill-eligible timestamp cannot be before the signal that generated it")


@dataclass(frozen=True)
class FillEvent:
    order_id: str
    fill_id: str
    timestamp: datetime  # actual execution timestamp
    symbol: str
    side: str
    quantity: int
    order_type: str
    requested_price: float  # the reference price before slippage/spread
    execution_price: float  # the actual simulated fill price
    slippage_amount: float  # execution_price - requested_price, signed
    fees: float
    spread_source: str  # "modeled_spread" | "real_bid_ask" — see src/backtesting/execution_models.py
    status: str  # "filled" | "rejected"
    reason: str = ""


@dataclass(frozen=True)
class PortfolioUpdateEvent:
    timestamp: datetime
    cash: float
    equity: float
    positions_value: float
    drawdown_pct: float


@dataclass(frozen=True)
class EndOfPeriodEvent:
    timestamp: datetime


_EVENT_PRIORITY: dict[type, int] = {
    MarketEvent: 0,
    SignalEvent: 1,
    OrderEvent: 2,
    FillEvent: 3,
    PortfolioUpdateEvent: 4,
    EndOfPeriodEvent: 5,
}


class EventQueue:
    """A strict chronological priority queue. Ties at the same timestamp
    break by event-type priority (a market event must be visible before a
    signal at the same instant can react to it, etc.), then by insertion
    order — so replaying the identical inputs always yields the identical
    processing order (Phase 3's determinism requirement)."""

    def __init__(self) -> None:
        self._heap: list[tuple[datetime, int, int, Any]] = []
        self._counter = itertools.count()
        self._last_popped_timestamp: datetime | None = None

    def push(self, event: Any) -> None:
        priority = _EVENT_PRIORITY.get(type(event))
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

    def pop(self) -> Any:
        ts, _priority, _seq, event = heapq.heappop(self._heap)
        self._last_popped_timestamp = ts
        return event

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)
