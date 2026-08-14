"""Typed interface for the subset of HOOD MCP tools this codebase uses:
market data (for HoodMarketDataProvider) and read-only position sync (for
position_manager/hood_sync.py).

IMPORTANT — read before wiring this to production: nothing in this
codebase calls a HOOD MCP tool directly. Those tools (mcp__HOOD__...) are
invoked through the orchestrating agent's own tool-call interface; there is
no Python SDK binding for them inside a plain Python process running in
this repository. HoodToolClient is the seam: whatever component actually
has the ability to invoke the HOOD MCP tools (or to relay a call to the
agent that does) implements this Protocol and gets injected into
HoodMarketDataProvider / the position-sync functions. Tests inject a fake
implementation built from mocked responses shaped like the real tools'
documented output — see tests/test_hood_provider.py. No implementation of
this Protocol, real or fake, is ever expected to define an order-placement
method — review_option_order / place_option_order / cancel_option_order /
review_equity_order / place_equity_order / cancel_equity_order are
deliberately absent here; they belong exclusively to src/execution.

Method signatures mirror the real tools' request parameters as inspected
from their MCP schemas:
  - get_equity_quotes            <- mcp__HOOD__get_equity_quotes
  - get_option_quotes            <- mcp__HOOD__get_option_quotes
  - get_equity_historicals       <- mcp__HOOD__get_equity_historicals
  - get_option_historicals       <- mcp__HOOD__get_option_historicals
  - get_option_chains            <- mcp__HOOD__get_option_chains
  - get_option_instruments       <- mcp__HOOD__get_option_instruments
  - get_option_positions         <- mcp__HOOD__get_option_positions

Response *shapes* (the JSON field names each tool returns) have been
VERIFIED against live, read-only calls for all seven methods above — SPY as
the underlying, a SPY $780 call expiring 2026-08-21 as the option contract,
and the session's own (real) brokerage account for get_option_positions —
not guessed. hood_provider.py / hood_sync.py document the verified shape
at each call site and raise a clear error if a real response doesn't match
it, rather than guessing at a value. If Robinhood changes a response
shape, re-verify with the same kind of live read-only call and update the
parser + its regression test together.
"""

from __future__ import annotations

from typing import Any, Protocol


class HoodToolClient(Protocol):
    def get_equity_quotes(self, symbols: list[str]) -> dict[str, Any]: ...

    def get_option_quotes(self, instrument_ids: list[str]) -> dict[str, Any]: ...

    def get_equity_historicals(
        self,
        symbols: list[str],
        start_time: str,
        end_time: str | None = None,
        interval: str | None = None,
        bounds: str | None = None,
        adjustment_type: str | None = None,
    ) -> dict[str, Any]: ...

    def get_option_historicals(
        self,
        instrument_ids: list[str],
        start_time: str,
        end_time: str | None = None,
        interval: str | None = None,
        bounds: str | None = None,
    ) -> dict[str, Any]: ...

    def get_option_chains(self, underlying_symbol: str | None = None, ids: str | None = None) -> dict[str, Any]: ...

    def get_option_instruments(
        self,
        chain_symbol: str | None = None,
        chain_id: str | None = None,
        ids: str | None = None,
        expiration_dates: str | None = None,
        strike_price: str | None = None,
        type: str | None = None,
        state: str | None = None,
        tradability: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]: ...

    def get_option_positions(
        self,
        account_number: str,
        nonzero: bool | None = None,
        chain_ids: str | None = None,
        expiration_date: str | None = None,
        expiration_date_gte: str | None = None,
        expiration_date_lte: str | None = None,
        option_ids: str | None = None,
        option_type: str | None = None,
        type: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]: ...
