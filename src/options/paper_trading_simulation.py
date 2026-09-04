"""Phase 30, Part 15/17 — paper-trading preparation interfaces.

BUILT BUT NOT STARTED (Part 15's explicit instruction: "do NOT auto-start
or wire this to live order submission"). Nothing in this module imports
`src.execution.gateway`/`src.execution.live_client`/`src.orchestrator`,
calls any live/paper order-placement tool, or reads/writes
`SystemState` -- it is a pure, in-memory simulation library a future
phase's paper-trading RUNNER would call, not a runner itself. See the
phase-wide safety test for the structural (AST-based) guarantee.

Reuses Part 6's `execution_realism_pricing` functions directly for every
simulated fill price (never a fabricated price) and Part 9's
`OrderSimulationEvent` as the event this module's fills/rejections
naturally produce.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from datetime import datetime

from src.options.execution_realism_pricing import (
    ExecutionPriceModel,
    buy_at_ask,
    sell_at_bid,
    slippage_assumption,
)
from src.options.phase26_dataset_builder import STANDARD_US_EQUITY_OPTION_MULTIPLIER
from src.options.research_dataset import ResearchObservation
from src.options.research_events import OrderSimulationEvent


class PaperOrderStatus(enum.Enum):
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CommissionSchedule:
    """Fully configurable -- $0/$0 defaults reflect Robinhood's real,
    documented options-commission structure, not an assumption that all
    brokers are free; a caller researching a different broker's fee
    schedule supplies real numbers here."""

    per_contract_usd: float = 0.0
    per_order_usd: float = 0.0

    def total(self, filled_quantity: int) -> float:
        return self.per_order_usd + self.per_contract_usd * filled_quantity


@dataclass(frozen=True)
class PaperOrderRequest:
    option_id: str
    side: str  # "buy" | "sell"
    quantity: int

    def __post_init__(self) -> None:
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if self.quantity <= 0:
            raise ValueError("quantity must be > 0")


@dataclass(frozen=True)
class PaperFillResult:
    option_id: str
    status: PaperOrderStatus
    requested_quantity: int
    filled_quantity: int
    execution_price: float | None
    commission_usd: float
    slippage_assumption_usd: float | None
    reason: str
    order_simulation_event: OrderSimulationEvent


def simulate_paper_order(
    request: PaperOrderRequest, row: ResearchObservation, *,
    commission: CommissionSchedule = CommissionSchedule(),
    slippage_usd: float = 0.0,
    max_fill_fraction_of_volume: float | None = None,
) -> PaperFillResult:
    """Simulates ONE order submission against a real observed row. Never
    fabricates a fill price -- `slippage_usd` (if non-zero) routes
    through Part 6's `slippage_assumption`, which itself refuses to
    produce a price when no real bid/ask exists.

    `max_fill_fraction_of_volume`: an OPTIONAL, configurable liquidity
    constraint (e.g. 0.1 = "never simulate filling more than 10% of the
    real observed volume in one order") -- `None` (the default) applies
    no such constraint, so a caller must opt in rather than have an
    arbitrary conservative fraction imposed."""
    price_result = (
        slippage_assumption(row, side=request.side, slippage_usd=slippage_usd) if slippage_usd
        else (buy_at_ask(row) if request.side == "buy" else sell_at_bid(row))
    )

    if price_result.execution_price is None:
        event = OrderSimulationEvent(
            timestamp=row.observation_timestamp, option_id=row.option_id, side=request.side,
            quantity=request.quantity, execution_model=price_result.model.value, simulated_price=None,
            status="execution_data_limited", reason=price_result.note,
        )
        return PaperFillResult(
            option_id=row.option_id, status=PaperOrderStatus.REJECTED, requested_quantity=request.quantity,
            filled_quantity=0, execution_price=None, commission_usd=0.0, slippage_assumption_usd=None,
            reason=price_result.note, order_simulation_event=event,
        )

    filled_qty = request.quantity
    status = PaperOrderStatus.FILLED
    reason = "simulated fill at a real observed price"
    if max_fill_fraction_of_volume is not None:
        max_fillable = math.floor((row.volume or 0) * max_fill_fraction_of_volume)
        if max_fillable < request.quantity:
            filled_qty = max(0, max_fillable)
            status = PaperOrderStatus.PARTIALLY_FILLED if filled_qty > 0 else PaperOrderStatus.REJECTED
            reason = (
                f"liquidity-limited fill: {filled_qty}/{request.quantity} contracts "
                f"(real observed volume={row.volume}, max_fraction={max_fill_fraction_of_volume})"
                if filled_qty > 0 else
                f"rejected: real observed volume={row.volume} supports 0 contracts at max_fraction={max_fill_fraction_of_volume}"
            )

    commission_usd = commission.total(filled_qty) if filled_qty > 0 else 0.0
    event = OrderSimulationEvent(
        timestamp=row.observation_timestamp, option_id=row.option_id, side=request.side,
        quantity=filled_qty if filled_qty > 0 else request.quantity, execution_model=price_result.model.value,
        simulated_price=price_result.execution_price if filled_qty > 0 else None,
        status="simulated_fill" if filled_qty > 0 else "simulated_reject", reason=reason,
    )
    return PaperFillResult(
        option_id=row.option_id, status=status, requested_quantity=request.quantity, filled_quantity=filled_qty,
        execution_price=price_result.execution_price if filled_qty > 0 else None, commission_usd=commission_usd,
        slippage_assumption_usd=price_result.slippage_assumption_usd, reason=reason, order_simulation_event=event,
    )


def reevaluate_pending_order(
    request: PaperOrderRequest, updated_row: ResearchObservation, *,
    commission: CommissionSchedule = CommissionSchedule(),
    slippage_usd: float = 0.0,
    max_fill_fraction_of_volume: float | None = None,
) -> PaperFillResult:
    """The "market changed" abstraction: a caller re-simulates the SAME
    request against a NEWER real observation row (a later real
    timestamp's bid/ask/volume) -- modeling a pending order encountering
    updated market conditions on the next real tick, never a fabricated
    price movement."""
    return simulate_paper_order(
        request, updated_row, commission=commission, slippage_usd=slippage_usd,
        max_fill_fraction_of_volume=max_fill_fraction_of_volume,
    )


@dataclass(frozen=True)
class PaperExitResult:
    option_id: str
    exit_quantity: int
    execution_price: float | None
    realized_pnl: float | None
    commission_usd: float
    status: PaperOrderStatus
    reason: str


def simulate_paper_exit(
    *, option_id: str, side_to_close: str, quantity: int, entry_price: float, row: ResearchObservation,
    commission: CommissionSchedule = CommissionSchedule(), slippage_usd: float = 0.0,
    multiplier: int = STANDARD_US_EQUITY_OPTION_MULTIPLIER,
) -> PaperExitResult:
    """`side_to_close`: "sell" closes a long position (sell-to-close,
    priced at the real bid); "buy" closes a short position (buy-to-close,
    priced at the real ask)."""
    if side_to_close not in ("buy", "sell"):
        raise ValueError("side_to_close must be 'buy' or 'sell'")
    price_result = (
        slippage_assumption(row, side=side_to_close, slippage_usd=slippage_usd) if slippage_usd
        else (sell_at_bid(row) if side_to_close == "sell" else buy_at_ask(row))
    )
    if price_result.execution_price is None:
        return PaperExitResult(
            option_id=option_id, exit_quantity=0, execution_price=None, realized_pnl=None,
            commission_usd=0.0, status=PaperOrderStatus.REJECTED, reason=price_result.note,
        )
    commission_usd = commission.total(quantity)
    sign = 1 if side_to_close == "sell" else -1  # closing a long realizes (exit-entry); closing a short realizes (entry-exit)
    realized_pnl = sign * (price_result.execution_price - entry_price) * quantity * multiplier - commission_usd
    return PaperExitResult(
        option_id=option_id, exit_quantity=quantity, execution_price=price_result.execution_price,
        realized_pnl=realized_pnl, commission_usd=commission_usd, status=PaperOrderStatus.FILLED,
        reason="simulated exit fill at a real observed price",
    )


@dataclass
class PaperPositionState:
    option_id: str
    open_quantity: int = 0
    total_commission_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    fill_count: int = 0
    exit_count: int = 0


class PaperTradingLedger:
    """An in-memory-only position-update ledger — never persisted to a
    live broker, never touches `SystemState`. A future paper-trading
    RUNNER (out of scope this phase) would drive this via
    `simulate_paper_order`/`simulate_paper_exit`, not the reverse."""

    def __init__(self) -> None:
        self._positions: dict[str, PaperPositionState] = {}

    def _state_for(self, option_id: str) -> PaperPositionState:
        return self._positions.setdefault(option_id, PaperPositionState(option_id=option_id))

    def apply_fill(self, fill: PaperFillResult) -> PaperPositionState:
        state = self._state_for(fill.option_id)
        if fill.status in (PaperOrderStatus.FILLED, PaperOrderStatus.PARTIALLY_FILLED):
            delta = fill.filled_quantity if fill.order_simulation_event.side == "buy" else -fill.filled_quantity
            state.open_quantity += delta
            state.total_commission_usd += fill.commission_usd
            state.fill_count += 1
        return state

    def apply_exit(self, exit_result: PaperExitResult) -> PaperPositionState:
        state = self._state_for(exit_result.option_id)
        if exit_result.status == PaperOrderStatus.FILLED:
            state.open_quantity -= exit_result.exit_quantity
            state.total_commission_usd += exit_result.commission_usd
            state.realized_pnl_usd += exit_result.realized_pnl or 0.0
            state.exit_count += 1
        return state

    def position(self, option_id: str) -> PaperPositionState:
        return self._positions.get(option_id, PaperPositionState(option_id=option_id))

    def all_positions(self) -> tuple[PaperPositionState, ...]:
        return tuple(self._positions.values())
