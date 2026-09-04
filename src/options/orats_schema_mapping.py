"""Phase 29, Part 1 — raw ORATS `Strike`-row dict -> normalized types.

Pure, deterministic mapping functions -- no network call, no file I/O.
Field names match the real, verified ORATS schema
(`src/orats/constructs/api/data.py::Strike`, Phase 25's evidence,
corrected this phase -- see orats_field_provenance.py's module
docstring). A raw dict missing an expected key raises `KeyError`
(never silently substitutes 0/None and calls it "mapped") -- a caller
that only has a partial real API response must slice the dict itself
before calling these functions, not rely on them to paper over gaps.

Multiplier honesty note (same discipline as Phase 26's
`phase26_dataset_builder.py`): ORATS's schema states no multiplier
field anywhere -- `STANDARD_US_EQUITY_OPTION_MULTIPLIER = 100` is an
external, real-world market-convention ASSUMPTION, never source-
confirmed, and every contract built here carries
`MULTIPLIER_SOURCE_CONFIRMED = False`.
"""

from __future__ import annotations

from datetime import date, datetime

from src.data.source_profile import DataProvenance
from src.data.store_interfaces import ProvenancedObservation
from src.data.timestamp_model import EventTimestamps
from src.options.historical_data_interfaces import (
    ContractIdentity,
    ContractLifecycle,
    ContractLifecycleStatus,
    HistoricalOrLive,
    OptionDataProvenance,
)

ORATS_SOURCE = "orats"
STANDARD_US_EQUITY_OPTION_MULTIPLIER = 100
MULTIPLIER_SOURCE_CONFIRMED = False


def contract_id_for(ticker: str, right: str, strike: float, expiration: date) -> str:
    return f"{ticker}_{right}_{strike:.4f}_{expiration.isoformat()}"


def build_orats_provenance(*, retrieval_timestamp: datetime, publication_timestamp: datetime | None = None) -> OptionDataProvenance:
    return OptionDataProvenance(
        source=ORATS_SOURCE,
        retrieval_timestamp=retrieval_timestamp,
        publication_timestamp=publication_timestamp,
        historical_or_live=HistoricalOrLive.HISTORICAL,
        observation_kind=DataProvenance.OBSERVED,
        adjustment_status="unknown_no_adjustment_flag_in_schema",
        interpolation_flag=False,
        confidence_status="claimed_unverified_no_live_api_call_made",
    )


def _parse_date(raw: str) -> date:
    return datetime.strptime(raw[:10], "%Y-%m-%d").date()


def build_contract_identity_from_strike_row(row: dict, *, right: str, provenance: OptionDataProvenance) -> ContractIdentity:
    """`row` is one real ORATS `/strikes` response row (a dict with, at
    minimum, `ticker`, `strike`, `expirDate` keys -- see
    ORATS_RAW_FIELD_KEYS below for the exact real key names used by the
    live REST API, distinct from the Python client's snake_case
    attribute names)."""
    ticker = row["ticker"]
    strike = float(row["strike"])
    expiration = _parse_date(row["expirDate"])
    if right not in ("call", "put"):
        raise ValueError(f"right must be 'call' or 'put', got {right!r}")
    return ContractIdentity(
        option_id=contract_id_for(ticker, right, strike, expiration),
        underlying_symbol=ticker,
        call_put=right,
        strike=strike,
        expiration=expiration,
        multiplier=STANDARD_US_EQUITY_OPTION_MULTIPLIER,
        exercise_style=None,  # UNAVAILABLE -- see orats_field_provenance.py
        contract_status="unknown_no_state_field_in_schema",
        provenance=provenance,
    )


def build_contract_lifecycle(contract_id: str, expiration: date, observed_dates: list[date], provenance: OptionDataProvenance, *, today: date) -> ContractLifecycle:
    if not observed_dates:
        raise ValueError("cannot build a lifecycle with zero observed dates")
    status = ContractLifecycleStatus.EXPIRED if today > expiration else ContractLifecycleStatus.UNKNOWN
    return ContractLifecycle(
        option_id=contract_id,
        first_observable_date=min(observed_dates),
        first_listed_date=None,  # UNAVAILABLE -- see PIT_CONTRACT_EXISTENCE_LIMITED, orats_lifecycle_pit.py
        last_trade_date=max(observed_dates),
        expiration_date=expiration,
        status=status,
        provenance=provenance,
    )


# The REAL ORATS `/strikes` endpoint's own raw JSON key names, per side
# (call/put), as used by the actual REST API (distinct from the Python
# client's snake_case attribute names used elsewhere in this project's
# evidence) -- both are real, verified names from the same schema
# inspection; this map is what `map_strike_row_to_observations` below
# actually reads.
_QUOTE_FIELD_KEYS = {
    "call": {"bid": "callBidPrice", "ask": "callAskPrice", "bid_size": "callBidSize", "ask_size": "callAskSize"},
    "put": {"bid": "putBidPrice", "ask": "putAskPrice", "bid_size": "putBidSize", "ask_size": "putAskSize"},
}
_VOLUME_OI_KEYS = {"call": {"volume": "callVolume", "open_interest": "callOpenInterest"},
                    "put": {"volume": "putVolume", "open_interest": "putOpenInterest"}}
_GREEKS_KEYS = {"delta": "delta", "gamma": "gamma", "theta": "theta", "vega": "vega", "rho": "rho"}


def map_strike_row_to_observations(
    row: dict, *, right: str, contract_id: str, event_time: datetime, ingestion_time: datetime,
) -> tuple[list[ProvenancedObservation], list[ProvenancedObservation], list[ProvenancedObservation], ProvenancedObservation | None]:
    """Returns (quote_observations, trade_observations [volume only --
    ORATS has no per-trade price/size, only an aggregate daily volume
    figure], open_interest_observations, underlying_price_observation).
    Every value comes directly from `row` -- nothing here computes,
    estimates, or defaults a missing key; a missing key is simply
    absent from the returned lists (never a fabricated 0/None entry)."""
    ts = EventTimestamps(event_time=event_time, observation_time=event_time, publication_time=None, ingestion_time=ingestion_time)

    def _obs(field: str, value) -> ProvenancedObservation:
        return ProvenancedObservation(key=contract_id, field=field, value=value, timestamps=ts,
                                       provenance=DataProvenance.OBSERVED, source=ORATS_SOURCE)

    quote_obs = []
    for norm_field, raw_key in _QUOTE_FIELD_KEYS[right].items():
        if raw_key in row and row[raw_key] is not None:
            quote_obs.append(_obs(norm_field, float(row[raw_key])))
    for norm_field, raw_key in _GREEKS_KEYS.items():
        if raw_key in row and row[raw_key] is not None:
            quote_obs.append(_obs(norm_field, float(row[raw_key])))
    if "iv" in row and row["iv"] is not None:
        quote_obs.append(_obs("iv", float(row["iv"])))

    trade_obs = []
    volume_key = _VOLUME_OI_KEYS[right]["volume"]
    if volume_key in row and row[volume_key] is not None:
        trade_obs.append(_obs("volume", float(row[volume_key])))

    oi_obs = []
    oi_key = _VOLUME_OI_KEYS[right]["open_interest"]
    if oi_key in row and row[oi_key] is not None:
        oi_obs.append(_obs("open_interest", float(row[oi_key])))

    underlying_obs = None
    for key in ("underlyingPrice", "spotPrice"):
        if key in row and row[key] is not None:
            underlying_obs = ProvenancedObservation(key=row["ticker"], field="close", value=float(row[key]), timestamps=ts,
                                                       provenance=DataProvenance.OBSERVED, source=ORATS_SOURCE)
            break

    return quote_obs, trade_obs, oi_obs, underlying_obs
