"""Market data shapes used throughout the system.

These are intentionally modeled after what the HOOD MCP tools will
eventually return (get_option_quotes, get_equity_quotes,
get_option_historicals, get_equity_historicals,
get_equity_technical_indicators) so that the future data_provider
implementation is a thin mapping layer rather than a redesign.

Field names here are our own normalized names, not a guarantee of the
exact upstream JSON keys — the future provider implementation is
responsible for mapping tool responses onto these dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class OptionQuote:
    """Mirrors mcp__HOOD__get_option_quotes: real-time bid/ask for one
    option contract (by instrument UUID), plus the prior-session close."""

    instrument_id: str
    bid_price: float
    ask_price: float
    last_trade_price: float | None
    previous_close: float | None
    volume: int | None
    open_interest: int | None
    as_of: datetime

    def __post_init__(self) -> None:
        if self.bid_price < 0 or self.ask_price < 0:
            raise ValueError("bid/ask prices must be >= 0")

    @property
    def mid_price(self) -> float:
        return (self.bid_price + self.ask_price) / 2

    @property
    def spread_pct(self) -> float:
        """Spread as a fraction of the mid price. Returns inf on a
        zero/invalid mid so callers never mistake "no data" for "tight
        spread."""
        mid = self.mid_price
        if mid <= 0 or self.ask_price < self.bid_price:
            return float("inf")
        return (self.ask_price - self.bid_price) / mid


@dataclass(frozen=True)
class EquityQuote:
    """Mirrors mcp__HOOD__get_equity_quotes for one underlying symbol."""

    symbol: str
    last_trade_price: float
    previous_close: float | None
    as_of: datetime


@dataclass(frozen=True)
class PriceBar:
    """One OHLCV bar, mirroring mcp__HOOD__get_option_historicals /
    mcp__HOOD__get_equity_historicals."""

    start_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    interpolated: bool = False

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError("bar high must be >= low")


@dataclass(frozen=True)
class MarketSnapshot:
    """Everything a single evaluation cycle needs, assembled from several
    HOOD MCP calls:
      - option:          get_option_quotes
      - underlying:      get_equity_quotes
      - option_bars:     get_option_historicals
      - underlying_bars: get_equity_historicals
      - rsi/macd/ema/vwap: get_equity_technical_indicators (type=rsi/macd/ema/vwap)

    fetched_at should be set to the time the *slowest* of these calls
    returned, so data_age_seconds is a conservative (not optimistic)
    staleness measure.
    """

    option: OptionQuote
    underlying: EquityQuote
    option_bars: tuple[PriceBar, ...]
    underlying_bars: tuple[PriceBar, ...]
    rsi: float | None
    rsi_prev: float | None
    macd_histogram: float | None
    macd_histogram_prev: float | None
    ema_fast: float | None
    ema_slow: float | None
    vwap: float | None
    volume_ratio: float | None
    fetched_at: datetime

    @property
    def data_age_seconds(self) -> float:
        now = datetime.now(timezone.utc)
        fetched = self.fetched_at
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return (now - fetched).total_seconds()


@dataclass(frozen=True)
class UnderlyingSnapshot:
    """Equity-only market data for scanning: a quote, recent bars, and
    locally computed indicators/structure for one underlying symbol — no
    option contract has been chosen yet. This is what a Strategy uses to
    judge "is this symbol showing a tradeable setup right now" before it
    ever picks a specific contract (see get_market_snapshot for that,
    contract-specific, step).
    """

    quote: EquityQuote
    bars: tuple[PriceBar, ...]
    rsi: float | None
    rsi_prev: float | None
    macd_histogram: float | None
    macd_histogram_prev: float | None
    ema_fast: float | None
    ema_slow: float | None
    vwap: float | None
    volume_ratio: float | None
    higher_highs: bool
    lower_highs: bool
    breakout_continuation: bool
    failed_breakout: bool
    fetched_at: datetime

    @property
    def data_age_seconds(self) -> float:
        now = datetime.now(timezone.utc)
        fetched = self.fetched_at
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return (now - fetched).total_seconds()
