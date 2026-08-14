"""The execution layer's safety boundary.

THIS IS THE ONLY MODULE THAT SHOULD EVER BE EXTENDED TO CALL A HOOD ORDER
TOOL. As of this codebase, nothing does — LiveExecutionGateway is an
explicit, permanent refusal, not a stub waiting to be filled in casually.

Two independent guarantees are enforced here, on purpose overlapping so a
bug in one doesn't silently remove the other:

  1. get_execution_gateway() only ever returns a *working* gateway when
     TRADING_MODE=paper. When TRADING_MODE=live, it raises immediately —
     it does not hand back something that could place a real order,
     because that "something" does not exist yet.

  2. Even if a caller directly constructs LiveExecutionGateway and calls
     it, submit_order()/cancel_order() unconditionally raise. There is no
     code path in this class that reaches place_option_order or
     cancel_option_order.

Turning on real trading later requires a human to deliberately implement
LiveExecutionGateway (wiring it to review_option_order + place_option_order
with explicit user confirmation, per the HOOD tool's own instructions) —
not just flip TRADING_MODE. See README.md "Before live trading" section.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.execution.orders import OrderRequest, OrderResult, SimulatedFill

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.logging.decision_logger import DecisionLogger


class LiveTradingDisabledError(RuntimeError):
    """Raised whenever anything attempts to route a real order while the
    system is not both configured AND implemented for live trading."""


def assert_paper_mode(settings: "Settings") -> None:
    """Belt-and-braces guard. Call this at the top of any function that is
    about to do something order-related, even if the caller believes it
    already checked."""
    if not settings.is_paper:
        raise LiveTradingDisabledError(
            f"TRADING_MODE={settings.trading_mode!r} — refusing to proceed. "
            "This build only operates in paper mode."
        )


class ExecutionGateway(ABC):
    @abstractmethod
    def submit_order(self, order: OrderRequest) -> OrderResult:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, account_number: str, order_id: str) -> OrderResult:
        raise NotImplementedError


class PaperExecutionGateway(ExecutionGateway):
    """The only gateway wired up today. Never calls place_option_order,
    review_option_order, or cancel_option_order. Simulates a fill at the
    quoted mid price and writes it to the decision/audit log."""

    def __init__(self, settings: "Settings", decision_logger: "DecisionLogger"):
        self._settings = settings
        self._decision_logger = decision_logger

    def submit_order(self, order: OrderRequest) -> OrderResult:
        assert_paper_mode(self._settings)

        # Paper fills use the caller-supplied limit price when given
        # (matching what a limit order would target); otherwise there's no
        # quote to simulate against here, so the caller must supply price.
        if order.price is None:
            result = OrderResult(status="rejected", request=order, error="No price to simulate a fill against")
            self._decision_logger.log_simulated_order(order, result)
            return result

        fill = SimulatedFill(
            fill_price=float(order.price),
            filled_at=datetime.now(timezone.utc),
            quote_bid=float(order.price),
            quote_ask=float(order.price),
        )
        result = OrderResult(status="simulated_fill", request=order, simulated_fill=fill)
        self._decision_logger.log_simulated_order(order, result)
        return result

    def cancel_order(self, account_number: str, order_id: str) -> OrderResult:
        assert_paper_mode(self._settings)
        self._decision_logger.log_simulated_cancel(account_number=account_number, order_id=order_id)
        return OrderResult(
            status="simulated_fill",
            request=OrderRequest(
                account_number=account_number,
                legs=(_placeholder_leg(),),
                quantity="0",
                price="0",
                reason=f"paper-cancel {order_id}",
            ),
            extra={"cancelled_order_id": order_id},
        )


def _placeholder_leg():
    from src.execution.orders import OrderLeg

    # OrderRequest requires >=1 leg; a cancel has no real leg, so this is a
    # clearly-marked placeholder purely to satisfy the audit-log shape.
    return OrderLeg(option_id="n/a", side="sell", position_effect="close")


class LiveExecutionGateway(ExecutionGateway):
    """Not implemented, by design. This class exists so the interface is
    visible and typed, not as a partially-built path to real orders.
    Every method refuses unconditionally, regardless of settings."""

    def submit_order(self, order: OrderRequest) -> OrderResult:
        raise LiveTradingDisabledError(
            "Live order execution is not implemented in this codebase. "
            "place_option_order must never be called until a human "
            "explicitly builds this path (with review_option_order + "
            "confirmation, per that tool's own workflow) and approves live "
            "trading."
        )

    def cancel_order(self, account_number: str, order_id: str) -> OrderResult:
        raise LiveTradingDisabledError(
            "Live order cancellation is not implemented in this codebase. "
            "cancel_option_order must never be called until live trading "
            "is explicitly approved and this path is deliberately built."
        )


def get_execution_gateway(settings: "Settings", decision_logger: "DecisionLogger") -> ExecutionGateway:
    """The only supported way to obtain a gateway. Deliberately does not
    branch to LiveExecutionGateway even when TRADING_MODE=live — returning
    a live-capable gateway is a decision for a future, explicit change, not
    something this function does automatically based on a config value."""
    if settings.is_paper:
        return PaperExecutionGateway(settings, decision_logger)
    raise LiveTradingDisabledError(
        f"TRADING_MODE={settings.trading_mode!r} — live execution is not "
        "implemented yet. Refusing to build or return a live execution "
        "path. Set TRADING_MODE=paper to run this system."
    )


def new_ref_id() -> str:
    return str(uuid.uuid4())
