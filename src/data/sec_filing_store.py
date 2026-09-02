"""Phase 16, Parts 2-4, 6 — a concrete SEC filing/fact store built on
Phase 15's architecture.

REAL RESPONSE SHAPES (Part 3) — verified via real, read-only
mcp__HOOD__get_sec_filing_index / get_sec_filing_facts calls made during
this phase's development, not inferred from tool names:

  get_sec_filing_index returns, per filing: filing_id (a connector-internal
  UUID — NOT the standard SEC EDGAR accession-number format
  nnnnnnnnnn-nn-nnnnnn; it IS stable and unique, so it serves the same
  join-key role, but should never be presented to a user as "the SEC
  accession number"), form_type, description, date_filed (a DATE, no
  time-of-day — confirmed across every filing probed). No accepted-
  timestamp, no amendment-status field (amendments show up as their own
  form_type string, e.g. "10-K/A", not a boolean flag on the original).

  get_sec_filing_facts returns, per fact: filing_id (joins back to the
  index), concept (a bare XBRL tag name, e.g. "NetIncomeLoss" —
  no separate "taxonomy" field is exposed; the us-gaap/dei/company-
  extension namespace is implicit in the tag, not surfaced), entity (the
  SEC CIK, e.g. "0000320193" for AAPL — a stable per-issuer id distinct
  from the ticker), period (a single date for an INSTANT fact, e.g.
  "2021-09-25", or a "start/end" string for a DURATION fact, e.g.
  "2021-09-26/2022-09-24" — start_date/end_date are also broken out as
  separate fields), value (string-formatted), unit (e.g. "iso4217:USD",
  "xbrli:shares", "iso4217:USD/xbrli:shares"), decimals (rounding
  precision), char_value (non-numeric text-block facts), and axises: a
  list of XBRL dimensional qualifiers. CONFIRMED BY REAL PROBE: the SAME
  concept+period appears many times with DIFFERENT axis breakdowns (by
  segment, by product, by fair-value hierarchy level, ...) — only the
  row with axises == [] is the consolidated headline total. A naive
  ingestion that doesn't filter on this would treat dozens of dimensional
  sub-components as "duplicate" observations of the same fact. See
  sec_fact_quality.py for how this is classified.

  CONFIRMED BY REAL PROBE: AAPL's FY2022 10-K does not tag revenue as
  "Revenues" at all (a request for that concept returned zero rows) — it
  uses "RevenueFromContractWithCustomerExcludingAssessedTax" instead
  (axises=[], FY2022 value 394,328,000,000 — matches Apple's real
  reported FY2022 revenue). This is exactly the concept-normalization
  risk Part 10 warns about; see sec_concepts.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from src.data.source_profile import DataProvenance
from src.data.store_interfaces import ProvenancedObservation
from src.data.timestamp_model import EventTimestamps


class SECFilingStoreError(RuntimeError):
    """Raised when a persisted SEC dataset is corrupted — same fail-closed
    convention as HistoricalDataStoreError."""


@dataclass(frozen=True)
class SECFilingRecord:
    """One filing-index entry (Part 3A). `filing_id` is the connector's
    UUID (see module docstring) — kept under that name, not renamed to
    "accession_number", so nothing downstream mistakes it for the real
    EDGAR accession format."""

    issuer_symbol: str
    filing_id: str
    form_type: str
    description: str
    date_filed: date
    source: str = "mcp__HOOD__get_sec_filing_index"

    @property
    def is_amendment(self) -> bool:
        return self.form_type.endswith("/A")

    def to_dict(self) -> dict:
        return {
            "issuer_symbol": self.issuer_symbol, "filing_id": self.filing_id, "form_type": self.form_type,
            "description": self.description, "date_filed": self.date_filed.isoformat(), "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SECFilingRecord":
        return cls(
            issuer_symbol=data["issuer_symbol"], filing_id=data["filing_id"], form_type=data["form_type"],
            description=data["description"], date_filed=date.fromisoformat(data["date_filed"]),
            source=data.get("source", "mcp__HOOD__get_sec_filing_index"),
        )


@dataclass(frozen=True)
class SECFactRecord:
    """One fact-index entry (Part 3B), joined back to its filing's
    `date_filed` at construction time (see SECFilingStore.add_fact) since
    the raw fact payload itself carries no filing-date field."""

    issuer_symbol: str
    filing_id: str
    concept: str
    entity_cik: str
    unit: str
    value: float
    period_end: date
    period_start: date | None  # None for an instant fact, set for a duration fact
    axises: tuple[str, ...]  # empty tuple == the consolidated/headline total; non-empty == a dimensional breakdown
    date_filed: date  # denormalized from the parent filing, for convenience and to keep this record self-contained
    retrieval_timestamp: datetime
    source: str = "mcp__HOOD__get_sec_filing_facts"

    @property
    def is_duration_fact(self) -> bool:
        return self.period_start is not None

    @property
    def is_consolidated_total(self) -> bool:
        """True only for the un-dimensioned (axises == ()) headline
        figure — the one safe to treat as "the" reported value for this
        concept/period. Any axis-qualified row is a real, legitimate SEC
        disclosure (a segment/product/fair-value breakdown), just not
        interchangeable with the total."""
        return len(self.axises) == 0

    def to_event_timestamps(self) -> EventTimestamps:
        """event_time = the fiscal period this fact describes;
        publication_time is deliberately left unset here — see
        sec_timestamp_policy.py, which computes causal availability from
        `date_filed` under the PUBLICATION_DATE_ONLY policy rather than
        forcing a fake time-of-day into EventTimestamps.publication_time
        (Part 5's explicit "do not invent a publication time" rule)."""
        return EventTimestamps(event_time=datetime(self.period_end.year, self.period_end.month, self.period_end.day))

    def to_provenanced_observation(self) -> ProvenancedObservation:
        return ProvenancedObservation(
            key=self.issuer_symbol, field=self.concept, value=self.value, timestamps=self.to_event_timestamps(),
            provenance=DataProvenance.OBSERVED, source=self.source,
        )

    def to_dict(self) -> dict:
        return {
            "issuer_symbol": self.issuer_symbol, "filing_id": self.filing_id, "concept": self.concept,
            "entity_cik": self.entity_cik, "unit": self.unit, "value": self.value,
            "period_end": self.period_end.isoformat(),
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "axises": list(self.axises), "date_filed": self.date_filed.isoformat(),
            "retrieval_timestamp": self.retrieval_timestamp.isoformat(), "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SECFactRecord":
        return cls(
            issuer_symbol=data["issuer_symbol"], filing_id=data["filing_id"], concept=data["concept"],
            entity_cik=data["entity_cik"], unit=data["unit"], value=float(data["value"]),
            period_end=date.fromisoformat(data["period_end"]),
            period_start=date.fromisoformat(data["period_start"]) if data.get("period_start") else None,
            axises=tuple(data.get("axises", [])), date_filed=date.fromisoformat(data["date_filed"]),
            retrieval_timestamp=datetime.fromisoformat(data["retrieval_timestamp"]),
            source=data.get("source", "mcp__HOOD__get_sec_filing_facts"),
        )


@dataclass(frozen=True)
class FilingFormProfile:
    """Part 6 — per-form-type classification. A small, explicit registry
    rather than a rule engine: every form this phase has actually
    observed (Part 3 probes covered 10-K, 10-Q, 8-K, and amendments) gets
    a row; anything unseen defaults to the conservative UNKNOWN_FORM
    profile (metadata-only, does not enter the fact store) rather than a
    guess."""

    form_type: str
    contains_structured_facts: bool
    reliable_publication_timing: bool  # a real date_filed is always present for any form; this flags whether that date is a reasonable causal proxy (true for periodic reports, murkier for some 8-K items)
    enters_historical_fact_store: bool
    is_amendment: bool
    notes: str


FORM_PROFILES: dict[str, FilingFormProfile] = {
    "10-K": FilingFormProfile(
        form_type="10-K", contains_structured_facts=True, reliable_publication_timing=True,
        enters_historical_fact_store=True, is_amendment=False,
        notes="Annual report. Confirmed real facts (Revenue/NetIncome/Assets/etc.) via probe.",
    ),
    "10-Q": FilingFormProfile(
        form_type="10-Q", contains_structured_facts=True, reliable_publication_timing=True,
        enters_historical_fact_store=True, is_amendment=False,
        notes="Quarterly report. Confirmed present for AAPL/MSFT/NVDA across 2021-2023; CONFIRMED ABSENT for JPM in the same window via real probe (see docs/sec_data_source.md) -- 10-Q coverage is NOT universal across issuers.",
    ),
    "10-K/A": FilingFormProfile(
        form_type="10-K/A", contains_structured_facts=True, reliable_publication_timing=True,
        enters_historical_fact_store=True, is_amendment=True,
        notes="Amended annual report -- a LATER information event, never overwrites the original 10-K (Part 5, rule 4).",
    ),
    "10-Q/A": FilingFormProfile(
        form_type="10-Q/A", contains_structured_facts=True, reliable_publication_timing=True,
        enters_historical_fact_store=True, is_amendment=True,
        notes="Amended quarterly report -- a LATER information event, never overwrites the original 10-Q (Part 5, rule 4).",
    ),
    "8-K": FilingFormProfile(
        form_type="8-K", contains_structured_facts=False, reliable_publication_timing=True,
        enters_historical_fact_store=False, is_amendment=False,
        notes="Material-event disclosure. Confirmed present (23 AAPL 8-Ks probed 2021-2023) but is event-narrative, not standardized financial-statement facts -- retained as METADATA_ONLY, never entered into the fact store this phase.",
    ),
}

UNKNOWN_FORM_PROFILE = FilingFormProfile(
    form_type="UNKNOWN", contains_structured_facts=False, reliable_publication_timing=False,
    enters_historical_fact_store=False, is_amendment=False,
    notes="Not one of the form types this phase verified via a real probe -- conservatively treated as metadata-only until independently checked.",
)


def classify_form(form_type: str) -> FilingFormProfile:
    return FORM_PROFILES.get(form_type, UNKNOWN_FORM_PROFILE)


class SECFilingStore:
    """JSONL-backed persistence for SECFilingRecord/SECFactRecord, mirroring
    src.data.store.HistoricalDataStore's exact convention (one file per
    symbol per record type, sorted, deduplicated, fail-closed on
    corruption) so the two stores feel like the same system."""

    def __init__(self, root_dir: Path):
        self._root = Path(root_dir)

    def _filings_path(self, symbol: str) -> Path:
        return self._root / symbol.upper() / "sec_filings.jsonl"

    def _facts_path(self, symbol: str) -> Path:
        return self._root / symbol.upper() / "sec_facts.jsonl"

    def save_filings(self, symbol: str, filings: Sequence[SECFilingRecord]) -> None:
        path = self._filings_path(symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        by_id = {f.filing_id: f for f in filings}
        ordered = sorted(by_id.values(), key=lambda f: (f.date_filed, f.filing_id))
        with path.open("w") as fh:
            for record in ordered:
                fh.write(json.dumps(record.to_dict(), sort_keys=True))
                fh.write("\n")

    def load_filings(self, symbol: str) -> list[SECFilingRecord]:
        path = self._filings_path(symbol)
        if not path.is_file():
            return []
        raw = path.read_text()
        if not raw.strip():
            return []
        try:
            return [SECFilingRecord.from_dict(json.loads(line)) for line in raw.splitlines() if line.strip()]
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise SECFilingStoreError(f"SEC filing index for {symbol} is corrupted or unreadable: {exc}") from exc

    def save_facts(self, symbol: str, facts: Sequence[SECFactRecord]) -> None:
        path = self._facts_path(symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Dedupe on the natural key: same filing + concept + period + unit + axises should
        # never appear twice; a genuine duplicate collapses (last write wins), which
        # sec_fact_quality.py's duplicate check independently re-verifies on load.
        by_key: dict[tuple, SECFactRecord] = {}
        for f in facts:
            key = (f.filing_id, f.concept, f.period_end, f.period_start, f.unit, f.axises)
            by_key[key] = f
        ordered = sorted(by_key.values(), key=lambda f: (f.date_filed, f.filing_id, f.concept, f.period_end))
        with path.open("w") as fh:
            for record in ordered:
                fh.write(json.dumps(record.to_dict(), sort_keys=True))
                fh.write("\n")

    def load_facts(self, symbol: str) -> list[SECFactRecord]:
        path = self._facts_path(symbol)
        if not path.is_file():
            return []
        raw = path.read_text()
        if not raw.strip():
            return []
        try:
            return [SECFactRecord.from_dict(json.loads(line)) for line in raw.splitlines() if line.strip()]
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise SECFilingStoreError(f"SEC facts for {symbol} are corrupted or unreadable: {exc}") from exc

    # --- FundamentalStore Protocol shape (Phase 15 interop) ------------------------------------

    def load(self, symbol: str) -> list[ProvenancedObservation]:
        return [f.to_provenanced_observation() for f in self.load_facts(symbol)]

    def save(self, symbol: str, observations: Sequence[ProvenancedObservation], *, source: str = "sec") -> None:
        raise NotImplementedError(
            "SECFilingStore.save() (the generic ProvenancedObservation-shaped save) is intentionally "
            "unimplemented -- SEC facts carry richer, SEC-specific provenance (filing_id, entity_cik, "
            "axises, date_filed) that a bare ProvenancedObservation cannot hold. Use save_facts() with "
            "SECFactRecord instead; this method exists only so SECFilingStore satisfies the "
            "FundamentalStore Protocol's shape for read interop via load()."
        )
