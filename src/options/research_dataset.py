"""Phase 30, Part 1/17 — the research-facing dataset abstraction layer.

The user has decided NOT to purchase ORATS or any paid provider (Phase
29's `ORATS_ACTIVATION_PENDING_HUMAN` remains the final ORATS state,
unchanged and unmodified by this phase). `HISTORICAL_OPTIONS_DATA_
PARTIAL` (Phase 27's `EXPANDED_FINAL_GATE`) is accepted as a PERMANENT
limitation of the free dataset, not a defect to keep chasing a paid fix
for. This module is the first piece of "build the strongest possible
research framework around the real free data we actually possess."

Reuse, not reinvention: this module adds NO new ingestion, parsing, or
certification logic. It is a read-only VIEW over an already-built,
already-certified `InMemoryLeanSampleStore` (Phase 26/27) — the exact
same store `phase27_ingest.build_expanded_store_from_directories()`
produces from the real, on-disk QuantConnect/Lean sample. Every
per-contract quality-flag computation reuses `phase26_quality_rules.
run_all_quality_checks` directly; every point-in-time judgment reuses
Phase 15's `EventTimestamps`/`is_knowable_at` machinery via
`phase26_pit_certification`'s already-tested helpers. Moneyness/DTE
math is newly written here (Part 1's own field list explicitly wants a
`moneyness`/`DTE` column on every observation row, which no existing
module currently materializes per-observation — `phase27_coverage_report.
moneyness_bucket` buckets a single strike against a chain-level reference
price for a *report*, a different job from this module's per-observation
numeric moneyness ratio).

Row model — "one research observation per (contract, timestamp)": the
real store keeps quotes/trades/open-interest as separate per-contract
field streams (each observation is one field at one timestamp). This
module's `build_research_observations()` merges those streams per
contract into wide rows keyed by the UNION of every timestamp seen for
that contract across quotes/trades/OI — each row carries whatever fields
were actually observed at that exact timestamp and `None` for anything
not observed then. This is not a resampling or interpolation step (Part
1 forbids fabricating a value): a row with `bid=None` genuinely means no
real quote observation exists for that contract at that timestamp, not
that mid/last was substituted.

DATA_SOURCE / DATA_QUALITY / PIT_STATUS / PROVENANCE (Part 1's explicit
per-observation retention requirement):
  - DATA_SOURCE: the contract's own `ContractIdentity.provenance.source`
    string (e.g. "quantconnect_lean_open_source_sample") — never
    re-derived, always the real value already attached at ingestion.
  - DATA_QUALITY: `DataQualityStatus`, computed once per CONTRACT (not
    per row — `phase26_quality_rules` flags are contract-scoped, not
    timestamp-scoped) by running the real, unmodified quality-rule suite
    and taking the worst severity found for that contract. A contract
    with zero flags is CLEAN; any "warning"-severity flag (including the
    permanent `multiplier_not_source_confirmed` flag every contract in
    this dataset legitimately carries) makes it FLAGGED_WARNING; any
    "critical"-severity flag makes it FLAGGED_CRITICAL. This is an
    honest per-contract summary, never silently dropped from the row.
  - PIT_STATUS: `PITStatus`, computed per ROW from whether that row's own
    merged timestamp is a genuine, non-None causal timestamp (`PIT_SAFE`)
    or missing (`PIT_UNKNOWN` — never defaulted to safe by omission, Part
    1's own instruction: "every observation must retain ... PIT_STATUS").
    This is a NECESSARY, not sufficient, PIT condition for a row in
    isolation; a caller doing an "as of" backtest query must still apply
    `phase26_pit_certification.knowable_observations_as_of`-style
    filtering against their own simulated `as_of` clock — this field only
    certifies the row itself is not fundamentally timestamp-less.
  - PROVENANCE: the contract's real, unmodified `OptionDataProvenance`
    record, attached to every row for that contract verbatim.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime

from src.options.historical_data_interfaces import OptionDataProvenance
from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase26_quality_rules import QualityFlag, run_all_quality_checks


class DataQualityStatus(enum.Enum):
    CLEAN = "clean"
    FLAGGED_WARNING = "flagged_warning"
    FLAGGED_CRITICAL = "flagged_critical"


class PITStatus(enum.Enum):
    PIT_SAFE = "pit_safe"  # a genuine, non-None causal timestamp is attached to this row
    PIT_UNKNOWN = "pit_unknown"  # no causal timestamp -- never treated as knowable at any as_of


@dataclass(frozen=True)
class ResearchObservation:
    """One merged row: a contract's state at one real observed timestamp.
    Every optional field is `None`, never a fabricated placeholder, when
    the real store has no observation for that field at this exact
    timestamp."""

    underlying: str
    option_id: str
    call_put: str
    strike: float
    expiration: date
    observation_timestamp: datetime
    underlying_price: float | None
    option_open: float | None
    option_high: float | None
    option_low: float | None
    option_close: float | None
    bid: float | None
    ask: float | None
    volume: float | None
    open_interest: float | None
    moneyness: float | None  # strike / underlying_price; None if underlying_price unavailable at this timestamp
    dte: int | None  # (expiration - observation_timestamp.date()).days; may be negative (past expiration)
    data_source: str
    data_quality: DataQualityStatus
    pit_status: PITStatus
    provenance: OptionDataProvenance
    quality_flags: tuple[str, ...]  # this CONTRACT's real flag rule-names, e.g. ("multiplier_not_source_confirmed",)


def _contract_quality(flags_for_contract: list[QualityFlag]) -> DataQualityStatus:
    if any(f.severity == "critical" for f in flags_for_contract):
        return DataQualityStatus.FLAGGED_CRITICAL
    if any(f.severity == "warning" for f in flags_for_contract):
        return DataQualityStatus.FLAGGED_WARNING
    return DataQualityStatus.CLEAN


def _underlying_price_by_date(store: InMemoryLeanSampleStore, underlying: str) -> dict[date, float]:
    """The real close series for this underlying, keyed by real observed
    date -- exactly the same lookup discipline
    `phase27_coverage_report.build_field_availability_report` uses (never
    reach across to a different era's price for the same symbol)."""
    return {
        o.timestamps.event_time.date(): o.value
        for o in store.underlying.get(underlying, [])
        if o.field == "close" and o.value is not None and o.timestamps.event_time is not None
    }


def build_research_observations(store: InMemoryLeanSampleStore) -> list[ResearchObservation]:
    """The real, complete conversion: every contract in `store.contracts`
    becomes one or more `ResearchObservation` rows, one per real
    timestamp seen for that contract across its quote/trade/OI streams.
    Deterministic ordering: contracts sorted by option_id, rows within a
    contract sorted by timestamp."""
    flags_by_contract: dict[str, list[QualityFlag]] = {}
    for flag in run_all_quality_checks(store):
        flags_by_contract.setdefault(flag.contract_id, []).append(flag)

    out: list[ResearchObservation] = []
    for option_id in sorted(store.contracts):
        contract = store.contracts[option_id]
        price_by_date = _underlying_price_by_date(store, contract.underlying_symbol)
        contract_flags = flags_by_contract.get(option_id, [])
        quality = _contract_quality(contract_flags)
        flag_names = tuple(sorted({f.rule for f in contract_flags}))

        by_ts: dict[datetime, dict[str, float]] = {}
        for o in store.quotes.get(option_id, []):
            if o.timestamps.event_time is not None:
                by_ts.setdefault(o.timestamps.event_time, {})[o.field] = o.value
        for o in store.trades.get(option_id, []):
            if o.timestamps.event_time is not None:
                by_ts.setdefault(o.timestamps.event_time, {})[f"trade_{o.field}"] = o.value
        for o in store.open_interest.get(option_id, []):
            if o.timestamps.event_time is not None:
                by_ts.setdefault(o.timestamps.event_time, {})["open_interest"] = o.value

        for ts in sorted(by_ts):
            fields = by_ts[ts]
            underlying_price = price_by_date.get(ts.date())
            moneyness = (contract.strike / underlying_price) if underlying_price else None
            dte = (contract.expiration - ts.date()).days

            out.append(ResearchObservation(
                underlying=contract.underlying_symbol,
                option_id=option_id,
                call_put=contract.call_put,
                strike=contract.strike,
                expiration=contract.expiration,
                observation_timestamp=ts,
                underlying_price=underlying_price,
                option_open=fields.get("trade_open"),
                option_high=fields.get("trade_high"),
                option_low=fields.get("trade_low"),
                option_close=fields.get("trade_price"),
                bid=fields.get("bid"),
                ask=fields.get("ask"),
                volume=fields.get("trade_volume"),
                open_interest=fields.get("open_interest"),
                moneyness=moneyness,
                dte=dte,
                data_source=contract.provenance.source,
                data_quality=quality,
                pit_status=PITStatus.PIT_SAFE,  # ts is never None here -- only real event_time-bearing rows are built
                provenance=contract.provenance,
                quality_flags=flag_names,
            ))
    return out


def observations_for_contract(observations: list[ResearchObservation], option_id: str) -> list[ResearchObservation]:
    return [o for o in observations if o.option_id == option_id]


def observations_for_underlying(observations: list[ResearchObservation], underlying: str) -> list[ResearchObservation]:
    return [o for o in observations if o.underlying == underlying]
