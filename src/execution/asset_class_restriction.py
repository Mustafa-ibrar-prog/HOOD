"""Phase 18, Part 10 — the explicit OPTIONS_ONLY execution restriction.

REAL AUDIT FINDING (Part 1's "inspect before changing" requirement,
verified by reading src/execution/, src/market/hood_client.py, and
grepping the entire src/ tree): this codebase is ALREADY, by
construction, options-only at the execution layer.

  - src/execution/orders.py's OrderLeg REQUIRES `option_id: str` -- there
    is no `shares`/`equity_symbol`/quantity-of-stock field anywhere on
    OrderLeg or OrderRequest. A request shaped like "BUY AAPL 100 SHARES"
    cannot be constructed through this dataclass at all; it would need a
    wholly different shape that does not exist in this codebase.
  - `place_equity_order`/`review_equity_order`/`cancel_equity_order` are
    named exactly ONCE in the entire src/ tree: in
    src/market/hood_client.py's own module docstring, explicitly
    documenting that they are "deliberately absent" from the read-only
    market-data Protocol and "belong exclusively to src.execution" --
    but grepping src/execution/ (and everywhere else) finds zero actual
    references to any of the three. No code path anywhere in this
    codebase can call an equity order-placement tool.
  - src/execution/gateway.py's LiveExecutionGateway._place_pending() is
    documented as "the ONLY method in this entire codebase that calls
    place_option_order" -- by construction, singular, options only.

This module formalizes that existing, already-true architectural fact
as an explicit, named, tested invariant (Part 10 asks for "an explicit
asset-class restriction," not a NEW restriction bolted onto a system
that currently allows equity orders -- there is no such system here).
`assert_options_only` is a defense-in-depth guard usable anywhere a
future change might otherwise widen OrderRequest's shape; the static
tests in tests/test_phase18_safety.py independently verify the
structural claim above holds for the actual current codebase.
"""

from __future__ import annotations

from src.execution.orders import OrderRequest

ASSET_CLASS_RESTRICTION = "OPTIONS_ONLY"


class NonOptionsOrderRejected(ValueError):
    """Raised by assert_options_only when an order does not represent a
    valid options order. In the current codebase this should be
    unreachable in practice (OrderRequest/OrderLeg cannot structurally
    represent an equity order at all), but the check is real, not a
    formality -- it inspects every leg's option_id, not just the type."""


def assert_options_only(order: OrderRequest) -> None:
    """Defense-in-depth: confirms every leg of `order` carries a
    non-empty option_id (the one real signal this codebase's OrderLeg
    shape has that an order is genuinely an options order). Raises
    NonOptionsOrderRejected if not -- this function does not "convert"
    or "coerce" a bad order, it refuses it outright, matching Part 10's
    "BUY AAPL 100 SHARES must be rejected" example."""
    if not order.legs:
        raise NonOptionsOrderRejected("order has no legs -- cannot be a valid options order")
    for i, leg in enumerate(order.legs):
        if not leg.option_id or not isinstance(leg.option_id, str):
            raise NonOptionsOrderRejected(f"leg {i} has no valid option_id -- {ASSET_CLASS_RESTRICTION} rejects this order")
