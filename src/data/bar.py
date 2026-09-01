"""Normalized, broker-agnostic market-data shapes for the research/quant
layer.

Everything downstream of this module (storage, quality checks, features,
research datasets) depends on `Bar`/`Quote`, never on Robinhood-specific
shapes directly — src/market/models.py's PriceBar/EquityQuote/OptionQuote
stay exactly as they are (the live trading path's own models, unchanged)
and this module's `from_price_bar`/`from_equity_quote`/`from_option_quote`
adapters are the ONLY place that translates between the two. Nothing in
src/execution, src/risk, src/position_manager, or the live orchestrator
imports from this module, and nothing here imports from those — the
research layer is additive and separate from the live trading path.

FIELD SUPPORT — determined from what the existing HOOD integration
actually parses today (see src/market/hood_provider.py, src/market/
models.py), not invented:
  - OHLCV bars (PriceBar / get_*_historicals): open/high/low/close/volume
    only. No bid/ask/trade fields exist on a historical bar in this
    integration — Quote (below) is the separate shape for that.
  - Equity quotes (EquityQuote / get_equity_quotes): last_trade_price only.
    The raw HOOD payload's "quote" object does include bid_price/ask_price
    for equities (see hood_provider.py's own verified-shape comment near
    its equity-quote parser), but the existing EquityQuote model does not
    currently surface them — that is a real, narrow, additive extension
    point for a future change to hood_provider.py's equity-quote parser,
    not something invented here. Quote.bid/ask are therefore always None
    when built from an equity quote today.
  - Option quotes (OptionQuote / get_option_quotes): bid_price/ask_price
    are both present; last_trade_price is actually the option's *mark
    price* (options carry no true last-trade field at all — see
    hood_provider.py's own documentation of this).
  - bid_size/ask_size/trade_size: NOT present in any verified HOOD
    response shape anywhere in this codebase. Always None. Do not
    populate these with a guess — an absent field must read as "not
    supported by this data source," never as a silently fabricated 0.

Timestamps are always stored UTC, timezone-aware. Every existing parser in
hood_provider.py already produces UTC-aware datetimes, so these adapters
require that rather than silently coercing a naive input — a naive
timestamp reaching this layer means something upstream broke the existing
UTC convention, and that should be loud, not quietly "fixed" here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from src.market.models import EquityQuote, OptionQuote, PriceBar


@dataclass(frozen=True)
class Bar:
    """One normalized OHLCV bar for one symbol/timeframe/source."""

    timestamp: datetime  # UTC, timezone-aware
    symbol: str
    timeframe: str  # e.g. "5minute", "day" — mirrors the HOOD interval string
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str = "hood"

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("Bar.timestamp must be timezone-aware (UTC) — got a naive datetime")
        if self.timestamp.utcoffset().total_seconds() != 0:
            raise ValueError(
                f"Bar.timestamp must be UTC — got an offset of {self.timestamp.utcoffset()}; "
                "normalize to UTC before constructing a Bar"
            )
        if self.high < self.low:
            raise ValueError("Bar.high must be >= Bar.low")
        if self.volume < 0:
            raise ValueError("Bar.volume must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Bar":
        ts = datetime.fromisoformat(data["timestamp"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return cls(
            timestamp=ts,
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            open=float(data["open"]),
            high=float(data["high"]),
            low=float(data["low"]),
            close=float(data["close"]),
            volume=int(data["volume"]),
            source=data.get("source", "hood"),
        )

    @classmethod
    def from_price_bar(cls, price_bar: PriceBar, *, symbol: str, timeframe: str, source: str = "hood") -> "Bar":
        """Adapter from the EXISTING live-path model (src/market/models.py's
        PriceBar, mirroring get_equity_historicals/get_option_historicals)
        to the normalized research-layer Bar. PriceBar itself is untouched."""
        ts = price_bar.start_time
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return cls(
            timestamp=ts,
            symbol=symbol.upper(),
            timeframe=timeframe,
            open=price_bar.open,
            high=price_bar.high,
            low=price_bar.low,
            close=price_bar.close,
            volume=price_bar.volume,
            source=source,
        )


@dataclass(frozen=True)
class Quote:
    """A point-in-time bid/ask/trade snapshot — separate from Bar because
    the existing HOOD integration's historical bars carry no quote-side
    data at all (see module docstring). Every size field is present in the
    schema (per the requirement to support bid/ask/bid size/ask size/trade
    price/trade size where the connection supports them) but is always
    None with today's adapters — no verified HOOD response anywhere in
    this codebase includes a size field."""

    timestamp: datetime
    symbol: str
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None  # never populated today — see module docstring
    ask_size: float | None = None  # never populated today — see module docstring
    trade_price: float | None = None
    trade_size: float | None = None  # never populated today — see module docstring
    source: str = "hood"

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("Quote.timestamp must be timezone-aware (UTC) — got a naive datetime")

    @classmethod
    def from_option_quote(cls, quote: OptionQuote, *, symbol: str, source: str = "hood") -> "Quote":
        ts = quote.as_of if quote.as_of.tzinfo else quote.as_of.replace(tzinfo=timezone.utc)
        return cls(
            timestamp=ts,
            symbol=symbol.upper(),
            bid=quote.bid_price,
            ask=quote.ask_price,
            trade_price=quote.last_trade_price,  # mark price — see module docstring
            source=source,
        )

    @classmethod
    def from_equity_quote(cls, quote: EquityQuote, *, source: str = "hood") -> "Quote":
        ts = quote.as_of if quote.as_of.tzinfo else quote.as_of.replace(tzinfo=timezone.utc)
        # bid/ask intentionally None — see module docstring: EquityQuote does
        # not currently surface them even though the raw HOOD payload can.
        return cls(timestamp=ts, symbol=quote.symbol.upper(), trade_price=quote.last_trade_price, source=source)
