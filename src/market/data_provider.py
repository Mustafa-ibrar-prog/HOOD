"""Abstract market-data interface.

Nothing in this codebase calls a HOOD MCP tool directly — those tools are
invoked by the orchestrating agent (Claude, via the MCP tool-call
interface), not imported and called from a standalone Python process. This
interface exists so the strategy scanner and position monitor can be
developed and unit-tested against a fake/stub implementation, and wired to
a real bridge via an injected client.

`HoodMarketDataProvider` (see hood_provider.py) is the real implementation,
backed by a `HoodToolClient` (hood_client.py) — inject whatever component
can actually invoke the HOOD MCP tools. It calls, per position-monitoring
cycle:
  - mcp__HOOD__get_option_quotes            -> OptionQuote (critical)
  - mcp__HOOD__get_equity_quotes            -> EquityQuote (critical)
  - mcp__HOOD__get_option_historicals       -> option PriceBar series (supplementary)
  - mcp__HOOD__get_equity_historicals       -> underlying PriceBar series (supplementary)
and, per scan cycle (get_underlying_snapshot):
  - mcp__HOOD__get_equity_quotes            -> EquityQuote (critical)
  - mcp__HOOD__get_equity_historicals       -> underlying PriceBar series (supplementary)
computing RSI/MACD/EMA/VWAP/structure locally (market/indicators.py) from
the fetched underlying bars, rather than calling
mcp__HOOD__get_equity_technical_indicators — see hood_provider.py's module
docstring for why. "Critical" data failures raise (see market/errors.py);
"supplementary" data failures degrade to empty/None with a logged warning,
which flows into strategy/evidence.py as INSUFFICIENT_DATA — a safe HOLD.

For the scanner:
  - get_option_expirations() calls mcp__HOOD__get_option_chains only —
    cheap, returns every listed expiration date so a Strategy can narrow
    to a DTE window BEFORE asking for contracts. Skipping this and asking
    get_option_chain_candidates() for every expiration of a liquid
    underlying (SPY has 35+) would mean paginating through thousands of
    contracts to find a handful near-the-money ones.
  - get_option_chain_candidates() calls mcp__HOOD__get_option_chains then
    mcp__HOOD__get_option_instruments (ideally scoped to specific
    expiration_dates via **filters, following the pattern above).
(get_scanner_filter_specs / get_scans / run_scan remain future work for a
concrete Strategy, not this interface.)

No implementation calls mcp__HOOD__place_option_order,
mcp__HOOD__review_option_order, or mcp__HOOD__cancel_option_order — those
belong exclusively to the execution layer (src/execution), which itself
refuses to run outside paper mode. See src/execution/gateway.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any

from src.market.models import MarketSnapshot, UnderlyingSnapshot


class MarketDataProvider(ABC):
    @abstractmethod
    def get_market_snapshot(
        self, option_id: str, underlying_symbol: str, now: datetime | None = None
    ) -> MarketSnapshot:
        """Assemble a full MarketSnapshot for one option contract and its
        underlying, for one position-monitoring evaluation cycle.

        `now` is an optional override (defaults to the real current time)
        used for deterministic testing of time-dependent behavior (market
        hours, historicals window) — production callers should omit it."""
        raise NotImplementedError

    @abstractmethod
    def get_underlying_snapshot(self, symbol: str, now: datetime | None = None) -> UnderlyingSnapshot:
        """Assemble an equity-only UnderlyingSnapshot for one symbol — used
        by a scanning Strategy to judge whether a symbol looks tradeable
        before picking a specific option contract.

        `now` is an optional override, same convention as
        get_market_snapshot."""
        raise NotImplementedError

    @abstractmethod
    def get_option_expirations(self, underlying_symbol: str) -> list[date]:
        """Return every listed expiration date across all option chains
        for this underlying, sorted ascending, deduplicated. Cheap (one
        get_option_chains call) — meant to be called before
        get_option_chain_candidates so a Strategy can narrow to a specific
        expiration (or a small DTE-window set of them) instead of pulling
        an underlying's entire, potentially huge, option chain."""
        raise NotImplementedError

    @abstractmethod
    def get_option_chain_candidates(self, underlying_symbol: str, **filters: Any) -> list[dict[str, Any]]:
        """Return raw candidate contracts for a scanning strategy to
        evaluate. Shape is intentionally loose (dict) until a concrete
        strategy defines what it needs. Pass `expiration_dates=...` (see
        get_option_expirations) to avoid pulling an underlying's entire
        chain."""
        raise NotImplementedError


class NotConfiguredMarketDataProvider(MarketDataProvider):
    """The safe default when no HoodToolClient has been wired up. Every
    method fails loudly and explicitly rather than returning fabricated
    data — silent fake data in a trading system is worse than a hard
    failure. Use HoodMarketDataProvider (hood_provider.py) for the real
    implementation.
    """

    def get_market_snapshot(
        self, option_id: str, underlying_symbol: str, now: datetime | None = None
    ) -> MarketSnapshot:
        raise NotImplementedError(
            "No live market-data bridge is wired up yet. Construct a "
            "HoodMarketDataProvider with a HoodToolClient before running "
            "real scans or monitoring cycles."
        )

    def get_underlying_snapshot(self, symbol: str, now: datetime | None = None) -> UnderlyingSnapshot:
        raise NotImplementedError(
            "No live market-data bridge is wired up yet. Construct a "
            "HoodMarketDataProvider with a HoodToolClient before running "
            "real scans."
        )

    def get_option_expirations(self, underlying_symbol: str) -> list[date]:
        raise NotImplementedError(
            "No live market-data bridge is wired up yet. Construct a "
            "HoodMarketDataProvider with a HoodToolClient before running "
            "real scans."
        )

    def get_option_chain_candidates(self, underlying_symbol: str, **filters: Any) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "No live market-data bridge is wired up yet. Implement a "
            "MarketDataProvider backed by the HOOD MCP tools before running "
            "real scans."
        )
