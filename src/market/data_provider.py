"""Abstract market-data interface.

Nothing in this codebase calls a HOOD MCP tool directly — those tools are
invoked by the orchestrating agent (Claude, via the MCP tool-call
interface), not imported and called from a standalone Python process. This
interface exists so the strategy scanner and position monitor can be
developed and unit-tested today against a fake/stub implementation, and
wired to a real bridge later.

The future concrete implementation's job is to call, per evaluation cycle:
  - mcp__HOOD__get_option_quotes            -> OptionQuote
  - mcp__HOOD__get_equity_quotes            -> EquityQuote
  - mcp__HOOD__get_option_historicals       -> option PriceBar series
  - mcp__HOOD__get_equity_historicals       -> underlying PriceBar series
  - mcp__HOOD__get_equity_technical_indicators (rsi/macd/ema/vwap)
  - mcp__HOOD__get_equity_price_book        -> underlying depth (liquidity checks)
and assemble the result into a MarketSnapshot.

For the scanner, the future implementation's job is to call:
  - mcp__HOOD__get_option_chains            -> chain -> expirations
  - mcp__HOOD__get_option_instruments       -> contracts for a chain/expiration
  - mcp__HOOD__get_scanner_filter_specs / get_scans / run_scan -> candidate universes
No implementation calls mcp__HOOD__place_option_order,
mcp__HOOD__review_option_order, or mcp__HOOD__cancel_option_order — those
belong exclusively to the execution layer (src/execution), which itself
refuses to run outside paper mode. See src/execution/gateway.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.market.models import MarketSnapshot


class MarketDataProvider(ABC):
    @abstractmethod
    def get_market_snapshot(self, option_id: str, underlying_symbol: str) -> MarketSnapshot:
        """Assemble a full MarketSnapshot for one option contract and its
        underlying, for one position-monitoring evaluation cycle."""
        raise NotImplementedError

    @abstractmethod
    def get_option_chain_candidates(self, underlying_symbol: str, **filters: Any) -> list[dict[str, Any]]:
        """Return raw candidate contracts for a scanning strategy to
        evaluate. Shape is intentionally loose (dict) until a concrete
        strategy defines what it needs."""
        raise NotImplementedError


class NotConfiguredMarketDataProvider(MarketDataProvider):
    """The only provider wired up today. Every method fails loudly and
    explicitly rather than returning fabricated data — silent fake data in
    a trading system is worse than a hard failure.
    """

    def get_market_snapshot(self, option_id: str, underlying_symbol: str) -> MarketSnapshot:
        raise NotImplementedError(
            "No live market-data bridge is wired up yet. Implement a "
            "MarketDataProvider backed by the HOOD MCP tools before running "
            "real scans or monitoring cycles."
        )

    def get_option_chain_candidates(self, underlying_symbol: str, **filters: Any) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "No live market-data bridge is wired up yet. Implement a "
            "MarketDataProvider backed by the HOOD MCP tools before running "
            "real scans."
        )
