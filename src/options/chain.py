"""Phase 18, Part 3 — the options chain observation model.

Confirmed real fields (get_option_quotes, real probe against a live
AAPL $230C 2026-09-18 contract): bid_price, ask_price, bid_size,
ask_size, mark_price, adjusted_mark_price, previous_close_price,
previous_close_date, volume, open_interest, implied_volatility, delta,
gamma, theta, vega, rho, break_even_price, chance_of_profit_long,
chance_of_profit_short, updated_at. ALL of these are LIVE-ONLY (a real
probe of get_option_quotes against an EXPIRED contract returned
results=[] -- confirmed empty, not an error).

Confirmed real fields for a HISTORICAL/expired contract
(get_option_historicals): open/high/low/close price bars only.
Confirmed via the tool's own guide text: "Option bars carry no volume"
-- historical volume is NEVER available, for any contract, any date,
via this connector. Historical bid/ask, open interest, IV, and Greeks
are likewise never present in this endpoint's response shape.

`OptionsFieldStatus` makes this explicit per-field rather than letting a
caller assume "if the dataclass has a value, it must be observed."
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime

from src.options.instrument import OptionContract


class OptionsFieldStatus(enum.Enum):
    OBSERVED = "observed"  # a real value came directly from the source
    DERIVED = "derived"  # computed deterministically from other OBSERVED fields (e.g. midpoint from bid/ask)
    ESTIMATED = "estimated"  # inferred by a model/algorithm (e.g. an IV solved from a price) -- always carries separate metadata, see implied_volatility.py/greeks.py
    UNAVAILABLE = "unavailable"  # the source does not supply this field for this observation -- never filled with a guess


@dataclass(frozen=True)
class OptionChainObservation:
    """One point-in-time (contract, quote) observation. Every optional
    numeric field defaults to None with UNAVAILABLE status -- nothing
    here is ever silently populated with an assumed value."""

    contract: OptionContract
    observation_timestamp: datetime  # when THIS observation was made (quote.updated_at for a live quote; a historical bar's begins_at for a historical bar)
    underlying_timestamp: datetime | None  # the underlying's own quote timestamp, if independently known (Part 5) -- None when not tracked separately
    source: str

    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    volume: int | None = None
    open_interest: int | None = None

    field_status: dict[str, OptionsFieldStatus] = field(default_factory=dict)

    def status_of(self, field_name: str) -> OptionsFieldStatus:
        return self.field_status.get(field_name, OptionsFieldStatus.UNAVAILABLE)

    @property
    def midpoint(self) -> float | None:
        """DERIVED, never OBSERVED -- computed only when both bid and ask
        are themselves OBSERVED (never derived from a lone `last`)."""
        if self.status_of("bid") != OptionsFieldStatus.OBSERVED or self.status_of("ask") != OptionsFieldStatus.OBSERVED:
            return None
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2

    @classmethod
    def from_live_quote(
        cls, contract: OptionContract, *, observation_timestamp: datetime, bid: float | None, ask: float | None,
        last: float | None, volume: int | None, open_interest: int | None, source: str = "mcp__HOOD__get_option_quotes",
        underlying_timestamp: datetime | None = None,
    ) -> "OptionChainObservation":
        """Every field passed here is OBSERVED (a real live-quote value);
        pass None for a field the caller genuinely doesn't have -- it is
        recorded UNAVAILABLE, never coerced to 0."""
        status = {}
        for name, value in (("bid", bid), ("ask", ask), ("last", last), ("volume", volume), ("open_interest", open_interest)):
            status[name] = OptionsFieldStatus.OBSERVED if value is not None else OptionsFieldStatus.UNAVAILABLE
        return cls(
            contract=contract, observation_timestamp=observation_timestamp, underlying_timestamp=underlying_timestamp,
            source=source, bid=bid, ask=ask, last=last, volume=volume, open_interest=open_interest, field_status=status,
        )

    @classmethod
    def from_historical_bar(
        cls, contract: OptionContract, *, observation_timestamp: datetime, close_price: float, source: str = "mcp__HOOD__get_option_historicals",
    ) -> "OptionChainObservation":
        """A historical OHLC bar's close, mapped onto `last` (the closest
        semantic fit) -- bid/ask/volume/open_interest are structurally
        UNAVAILABLE for this endpoint (confirmed: 'Option bars carry no
        volume', and bid/ask/OI are simply absent from the response
        shape), never guessed."""
        return cls(
            contract=contract, observation_timestamp=observation_timestamp, underlying_timestamp=None, source=source,
            last=close_price,
            field_status={
                "bid": OptionsFieldStatus.UNAVAILABLE, "ask": OptionsFieldStatus.UNAVAILABLE,
                "last": OptionsFieldStatus.OBSERVED, "volume": OptionsFieldStatus.UNAVAILABLE,
                "open_interest": OptionsFieldStatus.UNAVAILABLE,
            },
        )
