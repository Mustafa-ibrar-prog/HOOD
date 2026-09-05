"""Phase 37, Part 7/9/13 — the canonical, normalized observation layer
(layer B — never mixed with layer A raw payloads or layer C research
signals, per Part 16's explicit separation).

Reuses the EXISTING Robinhood integration's real, live-verified response
shape (the SAME `{"data": {"results": [...]}}` wrapper and per-row
`{"quote": {...}, "close": {...}}` structure `src/market/hood_provider.py`
already parses into `OptionQuote`/`EquityQuote` — see that module's
docstring for the live probe this shape was verified against) — but
reads the RAW dict directly, rather than going through `OptionQuote`,
because Part 7 asks this recorder to capture several real, live-confirmed
fields (`bid_size`, `ask_size`, `implied_volatility`, all five Greeks,
`break_even_price`, `chance_of_profit_long/short`) that `OptionQuote`
does not carry at all (the "unclaimed extension point" documented in
`docs/options_architecture.md` and `docs/phase34_readiness_audit.md`'s
live-data-audit table — exact real key names confirmed there, not
guessed). No NEW market-data provider or tool call is added — this
module only reads more of what the SAME tool call already returns.

Every field is populated ONLY if the corresponding raw key is present
and parseable; otherwise it stays `None` with provenance `MISSING` — this
module never reconstructs, fills, or carries forward a value (Part 7's
explicit instruction).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping

from src.research_recorder.dte import DTE_VERSION, compute_dte
from src.research_recorder.moneyness import MONEYNESS_VERSION, compute_moneyness
from src.research_recorder.provenance import LiveObservationProvenance


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class NormalizedUnderlyingObservation:
    symbol: str
    observation_cycle_id: str
    observation_timestamp: datetime  # when this observation was recorded into the cycle
    market_timestamp: datetime | None  # the tool's own as-of timestamp (e.g. venue_last_trade_time), if any
    bid: float | None
    ask: float | None
    last: float | None
    midpoint: float | None
    volume: int | None
    field_provenance: Mapping[str, str] = field(default_factory=dict)


def build_normalized_underlying_observation(
    *, symbol: str, observation_cycle_id: str, observation_timestamp: datetime, quote_row: Mapping[str, Any] | None,
) -> NormalizedUnderlyingObservation:
    """`quote_row` is one row's real `"quote"` dict from a live
    `get_equity_quotes` response (already matched to `symbol` by the
    caller -- see recorder.py -- never a first-row fallback, matching
    `hood_provider.py`'s own established discipline)."""
    provenance: dict[str, str] = {}
    if quote_row is None:
        return NormalizedUnderlyingObservation(
            symbol=symbol, observation_cycle_id=observation_cycle_id, observation_timestamp=observation_timestamp,
            market_timestamp=None, bid=None, ask=None, last=None, midpoint=None, volume=None,
            field_provenance={k: LiveObservationProvenance.MISSING.value for k in ("bid", "ask", "last", "midpoint", "volume")},
        )

    bid = _to_float(quote_row.get("bid_price"))
    ask = _to_float(quote_row.get("ask_price"))
    last = _to_float(quote_row.get("last_trade_price"))
    market_timestamp = _parse_datetime(quote_row.get("venue_last_trade_time"))
    volume = _to_int(quote_row.get("volume"))

    for name, value in (("bid", bid), ("ask", ask), ("last", last), ("volume", volume)):
        provenance[name] = LiveObservationProvenance.LIVE.value if value is not None else LiveObservationProvenance.MISSING.value

    midpoint = (bid + ask) / 2 if bid is not None and ask is not None else None
    provenance["midpoint"] = LiveObservationProvenance.DERIVED_FROM_LIVE.value if midpoint is not None else LiveObservationProvenance.MISSING.value

    return NormalizedUnderlyingObservation(
        symbol=symbol, observation_cycle_id=observation_cycle_id, observation_timestamp=observation_timestamp,
        market_timestamp=market_timestamp, bid=bid, ask=ask, last=last, midpoint=midpoint, volume=volume,
        field_provenance=provenance,
    )


@dataclass(frozen=True)
class NormalizedOptionObservation:
    option_id: str
    underlying: str
    observation_cycle_id: str
    observation_timestamp: datetime
    market_timestamp: datetime | None

    option_type: str | None
    strike: float | None
    expiration: date | None
    dte: int | None
    contract_state: str | None  # e.g. "active"
    contract_tradability: str | None  # e.g. "tradable"

    bid: float | None
    ask: float | None
    bid_size: int | None
    ask_size: int | None
    mark: float | None
    adjusted_mark: float | None
    last_trade: float | None  # options have no true last-trade field (hood_provider.py's own finding) -- always None, documented not omitted
    midpoint: float | None
    volume: int | None
    open_interest: int | None
    implied_volatility: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    rho: float | None
    break_even: float | None
    chance_of_profit_long: float | None
    chance_of_profit_short: float | None

    moneyness: float | None
    moneyness_underlying_price_used: float | None
    moneyness_version: str

    field_provenance: Mapping[str, str] = field(default_factory=dict)


_OPTION_RAW_FIELDS = (
    "bid", "ask", "bid_size", "ask_size", "mark", "adjusted_mark", "volume", "open_interest",
    "implied_volatility", "delta", "gamma", "theta", "vega", "rho", "break_even",
    "chance_of_profit_long", "chance_of_profit_short",
)


def build_normalized_option_observation(
    *,
    option_id: str,
    underlying: str,
    observation_cycle_id: str,
    observation_timestamp: datetime,
    market_timezone: str,
    quote_row: Mapping[str, Any] | None,  # one row's real "quote" dict from get_option_quotes, already matched by instrument_id
    chain_row: Mapping[str, Any] | None,  # the chain-candidate row that identified this contract (strike/expiration/type/state/tradability)
    underlying_price: float | None,  # the SAME-cycle underlying price -- never a later one
) -> NormalizedOptionObservation:
    provenance: dict[str, str] = {}

    option_type = None
    strike = None
    expiration = None
    contract_state = None
    contract_tradability = None
    if chain_row is not None:
        option_type = chain_row.get("type") or chain_row.get("option_type")
        strike = _to_float(chain_row.get("strike_price") or chain_row.get("strike"))
        raw_expiration = chain_row.get("expiration_date") or chain_row.get("expiration")
        if raw_expiration:
            try:
                expiration = date.fromisoformat(str(raw_expiration))
            except ValueError:
                expiration = None
        contract_state = chain_row.get("state")
        contract_tradability = chain_row.get("tradability")
    for name, value in (
        ("option_type", option_type), ("strike", strike), ("expiration", expiration),
        ("contract_state", contract_state), ("contract_tradability", contract_tradability),
    ):
        provenance[name] = LiveObservationProvenance.LIVE.value if value is not None else LiveObservationProvenance.MISSING.value

    dte = None
    if expiration is not None:
        dte = compute_dte(expiration=expiration, observation_timestamp=observation_timestamp, market_timezone=market_timezone)
        provenance["dte"] = LiveObservationProvenance.DERIVED_FROM_LIVE.value
    else:
        provenance["dte"] = LiveObservationProvenance.MISSING.value

    values: dict[str, float | int | None] = {k: None for k in _OPTION_RAW_FIELDS}
    market_timestamp = None
    if quote_row is not None:
        values["bid"] = _to_float(quote_row.get("bid_price"))
        values["ask"] = _to_float(quote_row.get("ask_price"))
        values["bid_size"] = _to_int(quote_row.get("bid_size"))
        values["ask_size"] = _to_int(quote_row.get("ask_size"))
        values["mark"] = _to_float(quote_row.get("mark_price"))
        values["adjusted_mark"] = _to_float(quote_row.get("adjusted_mark_price"))
        values["volume"] = _to_int(quote_row.get("volume"))
        values["open_interest"] = _to_int(quote_row.get("open_interest"))
        values["implied_volatility"] = _to_float(quote_row.get("implied_volatility"))
        values["delta"] = _to_float(quote_row.get("delta"))
        values["gamma"] = _to_float(quote_row.get("gamma"))
        values["theta"] = _to_float(quote_row.get("theta"))
        values["vega"] = _to_float(quote_row.get("vega"))
        values["rho"] = _to_float(quote_row.get("rho"))
        values["break_even"] = _to_float(quote_row.get("break_even_price"))
        values["chance_of_profit_long"] = _to_float(quote_row.get("chance_of_profit_long"))
        values["chance_of_profit_short"] = _to_float(quote_row.get("chance_of_profit_short"))
        market_timestamp = _parse_datetime(quote_row.get("updated_at"))

    for name in _OPTION_RAW_FIELDS:
        provenance[name] = LiveObservationProvenance.LIVE.value if values[name] is not None else LiveObservationProvenance.MISSING.value

    # Options have no true last-trade field (mark_price is the tool's own
    # documented "current price" instead) -- always None, and explicitly
    # documented as such rather than silently omitted from the record.
    last_trade = None
    provenance["last_trade"] = LiveObservationProvenance.MISSING.value

    midpoint = (values["bid"] + values["ask"]) / 2 if values["bid"] is not None and values["ask"] is not None else None
    provenance["midpoint"] = LiveObservationProvenance.DERIVED_FROM_LIVE.value if midpoint is not None else LiveObservationProvenance.MISSING.value

    moneyness_result = compute_moneyness(underlying_price=underlying_price, strike=strike, option_type=option_type)
    provenance["moneyness"] = LiveObservationProvenance.DERIVED_FROM_LIVE.value if moneyness_result.moneyness is not None else LiveObservationProvenance.MISSING.value

    return NormalizedOptionObservation(
        option_id=option_id, underlying=underlying, observation_cycle_id=observation_cycle_id,
        observation_timestamp=observation_timestamp, market_timestamp=market_timestamp,
        option_type=option_type, strike=strike, expiration=expiration, dte=dte,
        contract_state=contract_state, contract_tradability=contract_tradability,
        bid=values["bid"], ask=values["ask"], bid_size=values["bid_size"], ask_size=values["ask_size"],
        mark=values["mark"], adjusted_mark=values["adjusted_mark"], last_trade=last_trade, midpoint=midpoint,
        volume=values["volume"], open_interest=values["open_interest"], implied_volatility=values["implied_volatility"],
        delta=values["delta"], gamma=values["gamma"], theta=values["theta"], vega=values["vega"], rho=values["rho"],
        break_even=values["break_even"], chance_of_profit_long=values["chance_of_profit_long"],
        chance_of_profit_short=values["chance_of_profit_short"],
        moneyness=moneyness_result.moneyness, moneyness_underlying_price_used=moneyness_result.underlying_price_used,
        moneyness_version=MONEYNESS_VERSION, field_provenance=provenance,
    )
