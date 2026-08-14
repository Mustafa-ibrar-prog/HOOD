"""Order shapes.

OrderRequest mirrors the parameters of mcp__HOOD__place_option_order
(account_number, legs[option_id, side, position_effect, ratio_quantity],
quantity, type, price, stop_price, time_in_force, market_hours, ref_id) so
that whenever a real execution bridge is eventually built, it's a thin
pass-through of this shape rather than a redesign.

Nothing in this module calls place_option_order, review_option_order, or
cancel_option_order. See gateway.py for the enforcement boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class OrderLeg:
    option_id: str
    side: str  # "buy" | "sell"
    position_effect: str  # "open" | "close"
    ratio_quantity: int = 1

    def __post_init__(self) -> None:
        if self.side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if self.position_effect not in {"open", "close"}:
            raise ValueError("position_effect must be 'open' or 'close'")


@dataclass(frozen=True)
class OrderRequest:
    account_number: str
    legs: tuple[OrderLeg, ...]
    quantity: str
    type: str = "limit"  # "limit" | "market" | "stop_limit" | "stop_market"
    price: str | None = None
    stop_price: str | None = None
    time_in_force: str = "gfd"
    market_hours: str = "regular_hours"
    ref_id: str | None = None
    # Our own audit field — which Decision produced this order. Not part of
    # the upstream tool's schema.
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError("OrderRequest requires at least one leg")
        if self.type in {"limit", "stop_limit"} and self.price is None:
            raise ValueError(f"price is required for order type '{self.type}'")
        if self.type in {"stop_limit", "stop_market"} and self.stop_price is None:
            raise ValueError(f"stop_price is required for order type '{self.type}'")


@dataclass(frozen=True)
class SimulatedFill:
    fill_price: float
    filled_at: datetime
    quote_bid: float
    quote_ask: float


@dataclass(frozen=True)
class OrderResult:
    status: str  # "simulated_fill" | "rejected"
    request: OrderRequest
    simulated_fill: SimulatedFill | None = None
    error: str | None = None
    extra: dict = field(default_factory=dict)
