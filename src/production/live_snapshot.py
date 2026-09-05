"""Phase 36, Part 6 — the canonical LiveMarketSnapshot.

Contains only information actually available at decision time. Every
field is Optional; a missing field stays `None`, never a fabricated or
guessed value (the same discipline `src/market/models.py`'s
`OptionQuote`/`EquityQuote` already use). See
`docs/phase36_production_strategy_contract.md` section 18 for the
field-by-field audit of which of these this codebase's actual
Robinhood integration (`src/market/hood_provider.py`) can currently
populate live, versus which are confirmed available by the underlying
tool but not yet parsed/surfaced by this codebase's models.

This is a NEW shape, not a rename of `src/market/models.py::MarketSnapshot`
-- that dataclass was built for the position-monitoring cycle
(one option + its underlying, plus locally-computed indicators) and is
reused unchanged elsewhere; this one is the strategy-facing contract
Part 6 asks for, with fields (bid/ask size, IV, Greeks, DTE, strike,
expiration, option type) `MarketSnapshot` never carried at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.production.provenance import DataProvenance


@dataclass(frozen=True)
class UnderlyingLiveState:
    symbol: str
    timestamp: datetime
    bid: float | None
    ask: float | None
    last: float | None
    volume: int | None
    provenance: DataProvenance = DataProvenance.LIVE


@dataclass(frozen=True)
class OptionLiveState:
    option_id: str
    underlying: str
    option_type: str | None  # "call" | "put"
    strike: float | None
    expiration: date | None
    dte_days: int | None
    bid: float | None
    ask: float | None
    bid_size: int | None
    ask_size: int | None
    mark: float | None
    volume: int | None
    open_interest: int | None
    implied_volatility: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    rho: float | None
    state: str | None  # e.g. "active" -- chain-listing status, distinct from a quote
    tradability: str | None  # e.g. "tradable"
    timestamp: datetime | None
    provenance: DataProvenance = DataProvenance.LIVE

    def __post_init__(self) -> None:
        if self.option_type is not None and self.option_type not in {"call", "put"}:
            raise ValueError(f"option_type must be 'call' or 'put', got {self.option_type!r}")


@dataclass(frozen=True)
class LiveMarketSnapshot:
    as_of: datetime
    underlying: UnderlyingLiveState
    option: OptionLiveState | None  # None when no specific contract is in view yet (e.g. an underlying-only scan)


def build_live_market_snapshot(
    *,
    equity_quote,  # src.market.models.EquityQuote
    option_quote=None,  # src.market.models.OptionQuote | None
    underlying_symbol: str,
    option_id: str | None = None,
    option_type: str | None = None,
    strike: float | None = None,
    expiration: date | None = None,
    dte_days: int | None = None,
    state: str | None = None,
    tradability: str | None = None,
    as_of: datetime | None = None,
) -> LiveMarketSnapshot:
    """Maps the EXISTING `EquityQuote`/`OptionQuote` (src/market/models.py,
    unchanged) into the canonical shape. Fields those dataclasses never
    carry at all (bid/ask size, IV, Greeks, strike, expiration, DTE,
    option type, chain state/tradability) are accepted as separate,
    optional parameters -- sourced, in a real caller, from whatever
    selected the contract (a chain-candidate row), never invented here.
    Omitting any of them leaves the corresponding LiveMarketSnapshot
    field `None` -- never a fabricated value.
    """
    underlying = UnderlyingLiveState(
        symbol=underlying_symbol,
        timestamp=equity_quote.as_of,
        bid=None,  # EquityQuote carries no bid/ask today -- see the Robinhood compatibility audit
        ask=None,
        last=equity_quote.last_trade_price,
        volume=None,
    )
    option = None
    if option_quote is not None:
        option = OptionLiveState(
            option_id=option_quote.instrument_id,
            underlying=underlying_symbol,
            option_type=option_type,
            strike=strike,
            expiration=expiration,
            dte_days=dte_days,
            bid=option_quote.bid_price,
            ask=option_quote.ask_price,
            bid_size=None,  # not surfaced by OptionQuote today -- see audit
            ask_size=None,
            mark=option_quote.last_trade_price,  # OptionQuote stores mark_price here -- see hood_provider.py
            volume=option_quote.volume,
            open_interest=option_quote.open_interest,
            implied_volatility=None,  # not surfaced by OptionQuote today -- see audit
            delta=None, gamma=None, theta=None, vega=None, rho=None,
            state=state,
            tradability=tradability,
            timestamp=option_quote.as_of,
        )
    elif option_id is not None:
        # A contract is identified but no live quote could be fetched --
        # never silently omit it, carry it forward with every priced
        # field explicitly None so contract_validation.py can reject it
        # by rejection code rather than a caller mistaking "no option"
        # for "an option with no data".
        option = OptionLiveState(
            option_id=option_id, underlying=underlying_symbol, option_type=option_type, strike=strike,
            expiration=expiration, dte_days=dte_days, bid=None, ask=None, bid_size=None, ask_size=None,
            mark=None, volume=None, open_interest=None, implied_volatility=None, delta=None, gamma=None,
            theta=None, vega=None, rho=None, state=state, tradability=tradability, timestamp=None,
        )
    return LiveMarketSnapshot(as_of=as_of or equity_quote.as_of, underlying=underlying, option=option)
