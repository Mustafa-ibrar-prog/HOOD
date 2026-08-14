"""Abstract market-data interface.

Nothing in this codebase calls a HOOD MCP tool directly — those tools are
invoked by the orchestrating agent (Claude, via the MCP tool-call
interface), not imported and called from a standalone Python process. This
interface exists so the strategy scanner and position monitor can be
developed and unit-tested against a fake/stub implementation, and wired to
a real bridge via an injected client.

`HoodMarketDataProvider` (see hood_provider.py) is the real implementation,
backed by a `HoodToolClient` (hood_client.py) — inject whatever component
can actually invoke the HOOD MCP tools. It calls, per evaluation cycle:
  - mcp__HOOD__get_option_quotes            -> OptionQuote (critical)
  - mcp__HOOD__get_equity_quotes            -> EquityQuote (critical)
  - mcp__HOOD__get_option_historicals       -> option PriceBar series (supplementary)
  - mcp__HOOD__get_equity_historicals       -> underlying PriceBar series (supplementary)
and computes RSI/MACD/EMA/VWAP locally (market/indicators.py) from the
fetched underlying bars, rather than calling
mcp__HOOD__get_equity_technical_indicators — see hood_provider.py's module
docstring for why. "Critical" data failures raise (see market/errors.py);
"supplementary" data failures degrade to empty/None with a logged warning,
which flows into strategy/evidence.py as INSUFFICIENT_DATA — a safe HOLD.

For the scanner, HoodMarketDataProvider.get_option_chain_candidates() calls:
  - mcp__HOOD__get_option_chains            -> chain -> expirations
  - mcp__HOOD__get_option_instruments       -> contracts for a chain/expiration
(get_scanner_filter_specs / get_scans / run_scan remain future work for a
concrete Strategy, not this interface.)

No implementation calls mcp__HOOD__place_option_order,
mcp__HOOD__review_option_order, or mcp__HOOD__cancel_option_order — those
belong exclusively to the execution layer (src/execution), which itself
refuses to run outside paper mode. See src/execution/gateway.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from src.market.models import MarketSnapshot


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
    def get_option_chain_candidates(self, underlying_symbol: str, **filters: Any) -> list[dict[str, Any]]:
        """Return raw candidate contracts for a scanning strategy to
        evaluate. Shape is intentionally loose (dict) until a concrete
        strategy defines what it needs."""
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

    def get_option_chain_candidates(self, underlying_symbol: str, **filters: Any) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "No live market-data bridge is wired up yet. Implement a "
            "MarketDataProvider backed by the HOOD MCP tools before running "
            "real scans."
        )
