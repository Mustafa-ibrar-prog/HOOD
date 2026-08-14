"""Order shapes.

OrderRequest mirrors the parameters of mcp__HOOD__place_option_order /
mcp__HOOD__review_option_order (verified against their real, live tool
schemas: account_number, legs[option_id, side, position_effect,
ratio_quantity], quantity, type, price, stop_price, time_in_force,
market_hours, ref_id) so a real execution bridge is a thin pass-through of
this shape, not a redesign.

ORDER TYPES ACTUALLY AVAILABLE (verified against place_option_order's and
review_option_order's own schemas, not assumed):
  - "limit" (default) — requires `price`. The only type usable with 2+
    legs. This is the only type this codebase's orchestrator/monitor ever
    construct — every BUY-to-open and every sell-to-close order this
    system builds is a single-leg limit order, priced off the live quote
    (ask for a buy, bid for a sell).
  - "market" — no price. GFD only, regular_hours only, single-leg only.
    Not used anywhere in this codebase.
  - "stop_limit" — requires both `price` and `stop_price`. Single-leg only.
    Not used anywhere in this codebase.
  - "stop_market" — requires `stop_price`, no `price`. GFD only,
    regular_hours only, single-leg only, and (per the tool's own rule)
    sell-to-close only with stop_price below the current ask. Not used
    anywhere in this codebase.
Only limit/stop_limit's price and stop_limit/stop_market's stop_price
requirements are enforced below — the GFD-only/single-leg-only/
sell-to-close-only rules for market/stop_market are the live tool's own
constraints to enforce (it will reject a malformed order), not duplicated
here, since nothing in this codebase currently emits anything but a
single-leg limit order.

Nothing in this module calls place_option_order, review_option_order, or
cancel_option_order. See gateway.py for the enforcement boundary — in
particular, LiveExecutionGateway._place_pending() is the ONLY method in
this entire codebase permitted to reach place_option_order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "side": self.side,
            "position_effect": self.position_effect,
            "ratio_quantity": self.ratio_quantity,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OrderLeg":
        return cls(
            option_id=data["option_id"],
            side=data["side"],
            position_effect=data["position_effect"],
            ratio_quantity=int(data.get("ratio_quantity", 1)),
        )


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
    # Our own audit fields — not part of the upstream tool's schema.
    reason: str = ""
    chain_symbol: str | None = None  # passed to review_option_order for fee/collateral info
    underlying_type: str | None = None  # "equity" | "index" — same purpose

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError("OrderRequest requires at least one leg")
        if self.type in {"limit", "stop_limit"} and self.price is None:
            raise ValueError(f"price is required for order type '{self.type}'")
        if self.type in {"stop_limit", "stop_market"} and self.stop_price is None:
            raise ValueError(f"stop_price is required for order type '{self.type}'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_number": self.account_number,
            "legs": [leg.to_dict() for leg in self.legs],
            "quantity": self.quantity,
            "type": self.type,
            "price": self.price,
            "stop_price": self.stop_price,
            "time_in_force": self.time_in_force,
            "market_hours": self.market_hours,
            "ref_id": self.ref_id,
            "reason": self.reason,
            "chain_symbol": self.chain_symbol,
            "underlying_type": self.underlying_type,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OrderRequest":
        return cls(
            account_number=data["account_number"],
            legs=tuple(OrderLeg.from_dict(leg) for leg in data["legs"]),
            quantity=data["quantity"],
            type=data.get("type", "limit"),
            price=data.get("price"),
            stop_price=data.get("stop_price"),
            time_in_force=data.get("time_in_force", "gfd"),
            market_hours=data.get("market_hours", "regular_hours"),
            ref_id=data.get("ref_id"),
            reason=data.get("reason", ""),
            chain_symbol=data.get("chain_symbol"),
            underlying_type=data.get("underlying_type"),
        )


@dataclass(frozen=True)
class SimulatedFill:
    fill_price: float
    filled_at: datetime
    quote_bid: float
    quote_ask: float


@dataclass(frozen=True)
class LiveFill:
    """A REAL fill, from a REAL place_option_order response — distinct
    from SimulatedFill so the two can never be confused in a log or a
    position record. Field names are best-effort against the tool's
    documented behavior; the raw response is also kept in `raw` since the
    exact response shape (as opposed to the request shape) was not
    independently verified live for this tool, unlike the read-only market
    data tools elsewhere in this codebase."""

    order_id: str | None
    state: str | None
    filled_at: datetime
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderResult:
    # "simulated_fill"    — paper mode; always safe, never real.
    # "pending_approval"  — live mode; a PendingLiveOrder was created and
    #                       is awaiting a human's explicit approval. No
    #                       order has been placed.
    # "placed"            — live mode; a human approved this specific
    #                       pending order and it was actually submitted via
    #                       place_option_order. See `live_fill`.
    # "rejected"          — the order was not accepted (bad input, a human
    #                       rejected the pending order, etc.)
    status: str
    request: OrderRequest
    simulated_fill: SimulatedFill | None = None
    live_fill: LiveFill | None = None
    error: str | None = None
    extra: dict = field(default_factory=dict)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
