"""Phase 26, Part 1/12 — the first CONCRETE implementation of Phase 24's
provider-agnostic Protocols (`src.options.historical_data_interfaces`),
built from real, actually-downloaded data
(`scripts/phase26_step0_fetch_actual_sample.py` ->
`logs/research_data/phase26_raw/`).

Phase 24/25 were explicit that no concrete provider implementation
existed yet ("design only"). Phase 26's Part 12 explicitly asks for one
now that actual data has been obtained -- this module is that
implementation, scoped to exactly one real, verified source (the
QuantConnect/Lean open-source sample), not a generic multi-vendor
adapter. It reuses every existing type it can rather than duplicating:
`ContractIdentity`/`ContractLifecycle`/`OptionDataProvenance`/
`HistoricalOrLive`/`ContractLifecycleStatus` (Phase 24),
`ProvenancedObservation` (Phase 15), and `EventTimestamps`/
`CausalTimestampPolicy`/`is_knowable_at`/`assert_no_lookahead` (Phase 15,
Part 9's PIT machinery -- built once, reused here rather than
reinvented).

Multiplier honesty note (Part 3): this data source's CSV rows and file
names carry no multiplier field at all. `STANDARD_US_EQUITY_OPTION_
MULTIPLIER = 100` is a well-known, external, real-world market
convention (not a value this data source itself states) -- used here
only because `ContractIdentity.multiplier` is a required `int`, and
every contract this module actually builds is explicitly flagged via
`MULTIPLIER_SOURCE_CONFIRMED = False` so no downstream code can mistake
this convention for a source-confirmed field. See
docs/phase26_historical_options_dataset_certification.md Part 3 for the
classification this maps to (NOT_AVAILABLE from the source, not
VERIFIED_BY_ACTUAL_DATA).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from src.data.source_profile import DataProvenance
from src.data.store_interfaces import ProvenancedObservation
from src.data.timestamp_model import CausalTimestampPolicy, EventTimestamps
from src.options.historical_data_interfaces import (
    ContractIdentity,
    ContractLifecycle,
    ContractLifecycleStatus,
    HistoricalOrLive,
    OptionDataProvenance,
)
from src.options.phase26_lean_sample_parser import (
    LeanContractFileMeta,
    LeanEquityBar,
    LeanOpenInterestRow,
    LeanQuoteRow,
    LeanTradeRow,
)

LEAN_SAMPLE_SOURCE = "quantconnect_lean_open_source_sample"

# A real, external, industry-standard convention -- NOT stated anywhere
# in this data source itself. See module docstring.
STANDARD_US_EQUITY_OPTION_MULTIPLIER = 100
MULTIPLIER_SOURCE_CONFIRMED = False

MARKET_DATA_TIMESTAMP_POLICY = CausalTimestampPolicy.EVENT_TIME


def contract_id_for(meta: LeanContractFileMeta) -> str:
    """A stable, deterministic, human-readable identifier built purely
    from the real file-name-encoded identity -- no invented ID scheme."""
    return f"{meta.underlying_symbol}_{meta.right}_{meta.strike:.4f}_{meta.expiration.isoformat()}"


def build_provenance(*, retrieval_timestamp: datetime, adjustment_status: str) -> OptionDataProvenance:
    return OptionDataProvenance(
        source=LEAN_SAMPLE_SOURCE,
        retrieval_timestamp=retrieval_timestamp,
        publication_timestamp=None,  # the repo does not state when AlgoSeek/QuantConnect published this file
        historical_or_live=HistoricalOrLive.HISTORICAL,
        observation_kind=DataProvenance.OBSERVED,  # real recorded market quotes/trades, not a derived value
        adjustment_status=adjustment_status,
        interpolation_flag=False,  # nothing in this pipeline gap-fills or interpolates
        confidence_status="verified_by_actual_data_this_phase",
    )


def build_contract_identity(meta: LeanContractFileMeta, provenance: OptionDataProvenance) -> ContractIdentity:
    return ContractIdentity(
        option_id=contract_id_for(meta),
        underlying_symbol=meta.underlying_symbol,
        call_put=meta.right,
        strike=meta.strike,
        expiration=meta.expiration,
        multiplier=STANDARD_US_EQUITY_OPTION_MULTIPLIER,
        exercise_style=meta.option_style,  # this field IS source-confirmed (the filename literally states american/european)
        contract_status="unknown_no_state_field_in_source",
        provenance=provenance,
    )


def build_contract_lifecycle(
    meta: LeanContractFileMeta,
    observed_dates: list[date],
    provenance: OptionDataProvenance,
    *,
    today: date,
) -> ContractLifecycle:
    """`first_listed_date` stays None -- this source has no listing-date
    field; `first_observable_date`/`last_trade_date` are the real min/max
    of dates this codebase actually saw a row for (never approximated
    beyond what was actually observed). `status` is EXPIRED only when
    today is unambiguously past the contract's real expiration date --
    a fact independent of this data source, not an assumption about it."""
    if not observed_dates:
        raise ValueError("cannot build a lifecycle with zero observed dates")
    status = ContractLifecycleStatus.EXPIRED if today > meta.expiration else ContractLifecycleStatus.UNKNOWN
    return ContractLifecycle(
        option_id=contract_id_for(meta),
        first_observable_date=min(observed_dates),
        first_listed_date=None,
        last_trade_date=max(observed_dates),
        expiration_date=meta.expiration,
        status=status,
        provenance=provenance,
    )


def _event_timestamps(ts: datetime, *, ingestion_time: datetime) -> EventTimestamps:
    return EventTimestamps(event_time=ts, observation_time=ts, publication_time=None, ingestion_time=ingestion_time)


def quote_observations(contract_id: str, row: LeanQuoteRow, *, ingestion_time: datetime) -> list[ProvenancedObservation]:
    ts = _event_timestamps(row.timestamp, ingestion_time=ingestion_time)
    fields = {
        "bid": row.bid_close, "ask": row.ask_close,
        "bid_open": row.bid_open, "bid_high": row.bid_high, "bid_low": row.bid_low,
        "ask_open": row.ask_open, "ask_high": row.ask_high, "ask_low": row.ask_low,
        "last_bid_size": float(row.last_bid_size), "last_ask_size": float(row.last_ask_size),
    }
    return [
        ProvenancedObservation(key=contract_id, field=name, value=value, timestamps=ts,
                                provenance=DataProvenance.OBSERVED, source=LEAN_SAMPLE_SOURCE)
        for name, value in fields.items()
    ]


def trade_observations(contract_id: str, row: LeanTradeRow, *, ingestion_time: datetime) -> list[ProvenancedObservation]:
    ts = _event_timestamps(row.timestamp, ingestion_time=ingestion_time)
    fields = {"price": row.close, "open": row.open, "high": row.high, "low": row.low, "volume": float(row.volume)}
    return [
        ProvenancedObservation(key=contract_id, field=name, value=value, timestamps=ts,
                                provenance=DataProvenance.OBSERVED, source=LEAN_SAMPLE_SOURCE)
        for name, value in fields.items()
    ]


def open_interest_observation(contract_id: str, row: LeanOpenInterestRow, *, ingestion_time: datetime) -> ProvenancedObservation:
    ts = _event_timestamps(row.timestamp, ingestion_time=ingestion_time)
    return ProvenancedObservation(key=contract_id, field="open_interest", value=float(row.open_interest),
                                   timestamps=ts, provenance=DataProvenance.OBSERVED, source=LEAN_SAMPLE_SOURCE)


def underlying_observations(symbol: str, bar: LeanEquityBar, *, ingestion_time: datetime) -> list[ProvenancedObservation]:
    ts = _event_timestamps(datetime(bar.date.year, bar.date.month, bar.date.day, tzinfo=timezone.utc), ingestion_time=ingestion_time)
    fields = {"open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close, "volume": float(bar.volume)}
    return [
        ProvenancedObservation(key=symbol, field=name, value=value, timestamps=ts,
                                provenance=DataProvenance.OBSERVED, source=LEAN_SAMPLE_SOURCE)
        for name, value in fields.items()
    ]


@dataclass(frozen=True)
class InMemoryLeanSampleStore:
    """Concrete implementation of the Phase 24 store Protocols'
    read surface, backed entirely by real parsed data passed in at
    construction time -- no lazy fetch, no network call, no fabricated
    fallback for a missing key (`get_contract`/`load` return None/[]
    exactly like the Protocols specify)."""

    contracts: dict[str, ContractIdentity]
    lifecycles: dict[str, ContractLifecycle]
    quotes: dict[str, list[ProvenancedObservation]]
    trades: dict[str, list[ProvenancedObservation]]
    open_interest: dict[str, list[ProvenancedObservation]]
    underlying: dict[str, list[ProvenancedObservation]]

    def get_contract(self, option_id: str) -> ContractIdentity | None:
        return self.contracts.get(option_id)

    def list_contracts_for_expiration(self, underlying_symbol: str, expiration: date) -> list[ContractIdentity]:
        return [c for c in self.contracts.values() if c.underlying_symbol == underlying_symbol and c.expiration == expiration]

    def get_lifecycle(self, option_id: str) -> ContractLifecycle | None:
        return self.lifecycles.get(option_id)

    def load_quotes(self, contract_id: str) -> list[ProvenancedObservation]:
        return list(self.quotes.get(contract_id, []))

    def load_trades(self, contract_id: str) -> list[ProvenancedObservation]:
        return list(self.trades.get(contract_id, []))

    def load_open_interest(self, contract_id: str) -> list[ProvenancedObservation]:
        return list(self.open_interest.get(contract_id, []))

    def load_underlying(self, symbol: str) -> list[ProvenancedObservation]:
        return list(self.underlying.get(symbol, []))
