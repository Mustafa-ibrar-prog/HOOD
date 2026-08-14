"""Typed interface for the HOOD MCP order-placement/account tools.

Deliberately separate from src/market/hood_client.py's HoodToolClient — that
Protocol's own docstring says order-placement methods are "deliberately
absent" there and "belong exclusively to src/execution". This is that
exclusive home.

Same seam pattern as HoodToolClient: nothing in this Python process can call
an MCP tool directly. Whatever component actually has the ability to invoke
the HOOD MCP tools (the orchestrating agent, or something relaying to it)
implements this Protocol and gets injected into LiveExecutionGateway.
confirm_and_place() — see gateway.py. Tests inject a fake implementation.

Method signatures mirror the real tools' request parameters, inspected from
their live MCP schemas (mcp__HOOD__place_option_order,
mcp__HOOD__review_option_order, mcp__HOOD__cancel_option_order,
mcp__HOOD__get_accounts, mcp__HOOD__get_portfolio):

  - place_option_order   <- mcp__HOOD__place_option_order
                             "Place a real options order with real money."
                             Requires account_number to be agentic_allowed=
                             true AND option_level_2/option_level_3 (see
                             preflight.py). By design this codebase only
                             ever calls this from
                             LiveExecutionGateway.confirm_and_place(), and
                             only after a human has explicitly approved the
                             specific PendingLiveOrder.
  - review_option_order  <- mcp__HOOD__review_option_order
                             Simulates without placing; returns a quote plus
                             pre-trade alerts, and (with chain_symbol +
                             underlying_type) fees/collateral. Used to give
                             the human real numbers to approve/reject
                             against — never skipped in this codebase's flow.
  - cancel_option_order   <- mcp__HOOD__cancel_option_order
                             Not wired to anything yet — see gateway.py's
                             LiveExecutionGateway.cancel_order(), which still
                             refuses unconditionally. Present here so the
                             seam exists when that is deliberately built.
  - get_accounts          <- mcp__HOOD__get_accounts
                             Used by preflight.py to verify agentic_allowed /
                             option_level before any order is even proposed.
                             Does NOT return reliable buying power (per that
                             tool's own description) — see get_portfolio.
  - get_portfolio         <- mcp__HOOD__get_portfolio
                             Used by preflight.py for buying-power /
                             portfolio-value checks.

None of these response *shapes* (as opposed to request shapes, which are
directly copied from the tool schemas above) have been independently
verified against a real live call in this codebase, unlike the read-only
market-data tools in hood_client.py. preflight.py and gateway.py treat
fields defensively (missing/None-safe) and keep the raw response alongside
any parsed value, rather than assuming an exact shape.
"""

from __future__ import annotations

from typing import Any, Protocol


class LiveOrderPlacer(Protocol):
    def get_accounts(self) -> dict[str, Any]: ...

    def get_portfolio(self, account_number: str) -> dict[str, Any]: ...

    def review_option_order(
        self,
        account_number: str,
        legs: list[dict[str, Any]],
        quantity: str,
        type: str = "limit",
        price: str | None = None,
        stop_price: str | None = None,
        time_in_force: str = "gfd",
        market_hours: str = "regular_hours",
        direction: str | None = None,
        chain_symbol: str | None = None,
        underlying_type: str | None = None,
    ) -> dict[str, Any]: ...

    def place_option_order(
        self,
        account_number: str,
        legs: list[dict[str, Any]],
        quantity: str,
        type: str = "limit",
        price: str | None = None,
        stop_price: str | None = None,
        time_in_force: str = "gfd",
        market_hours: str = "regular_hours",
        direction: str | None = None,
        ref_id: str | None = None,
    ) -> dict[str, Any]: ...

    def cancel_option_order(self, account_number: str, order_id: str) -> dict[str, Any]: ...
