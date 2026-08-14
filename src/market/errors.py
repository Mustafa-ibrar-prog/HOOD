"""Errors the real MarketDataProvider implementation can raise.

Distinguishing these from a bare NotImplementedError (which
NotConfiguredMarketDataProvider still raises for "no provider wired up at
all") lets callers eventually tell "nothing is implemented" apart from "a
real fetch was attempted and failed" — useful for logging/alerting even
though both currently make PositionMonitor fall back to a safe HOLD (see
position_manager/monitor.py).
"""

from __future__ import annotations


class MarketDataError(RuntimeError):
    """Base class for every error HoodMarketDataProvider can raise."""


class HoodToolError(MarketDataError):
    """A HOOD MCP tool call failed, or its response could not be parsed
    into the shape this provider expects. Wraps whatever the underlying
    client raised, or a parsing failure, with context about which call."""


class QuoteUnavailableError(MarketDataError):
    """No usable quote was returned for the requested symbol/contract."""


class InvalidQuoteError(MarketDataError):
    """A quote was returned but fails basic sanity checks (e.g. a
    negative price, or another shape violation the model itself rejects)."""


class OptionContractNotFoundError(MarketDataError):
    """The requested option contract/instrument could not be resolved —
    e.g. an invalid, delisted, or mistyped instrument UUID."""
