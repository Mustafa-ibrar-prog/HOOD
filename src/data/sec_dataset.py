"""Phase 16, Parts 9, 11, 13 — the SEC_FUNDAMENTALS_ASOF dataset generator.

Produces historically-correct point-in-time fundamental observations for
a universe over a date range — nothing else. Per Part 9's explicit
instruction ("must not perform alpha testing") and Part 16 ("This
requirement is absolute"), there is no return, IC, Sharpe, or any
predictive computation anywhere in this module — every function here
only reads what was KNOWN, never what happened AFTER.

The neutral concept names (Part 11: latest_known_revenue,
latest_known_net_income, ...) are exactly the normalized_concept values
from sec_concepts.CONCEPT_MAP — no valuation ratio, growth rate, or
signal is derived from them here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from src.data.sec_filing_store import SECFilingStore
from src.data.sec_snapshot import get_available_facts, latest_known_value
from src.data.sec_timestamp_policy import SECCausalPolicy
from src.data.versioning import DatasetVersionRecord, content_hash

DATASET_NAME = "SEC_FUNDAMENTALS_ASOF"

# Part 11's neutral representations -- only concepts with an unambiguous accounting meaning.
DEFAULT_FACT_WHITELIST: tuple[str, ...] = (
    "revenue", "operating_income", "net_income", "diluted_eps", "cash_and_equivalents",
    "total_assets", "total_liabilities", "stockholders_equity", "operating_cash_flow",
)


@dataclass(frozen=True)
class SECDatasetSpec:
    universe_name: str
    symbols: tuple[str, ...]
    start_date: date
    end_date: date
    observation_frequency: str  # "monthly" | "quarterly" -- the cadence of as_of snapshot instants generated
    timestamp_policy: SECCausalPolicy
    filing_forms: tuple[str, ...]
    fact_whitelist: tuple[str, ...] = DEFAULT_FACT_WHITELIST


@dataclass(frozen=True)
class SECFundamentalObservation:
    """latest_known_<normalized_concept> for one symbol at one as_of
    instant. `value is None` when nothing was knowable yet — never
    silently defaulted to 0 or interpolated."""

    symbol: str
    as_of: datetime
    normalized_concept: str
    value: float | None
    fact_period_end: date | None  # the fiscal period the value describes, for transparency (never used as the causal timestamp -- see sec_timestamp_policy.py's rule 1)
    fact_date_filed: date | None


def generate_asof_instants(spec: SECDatasetSpec) -> list[datetime]:
    """A simple, deterministic monthly/quarterly schedule -- Part 9 asks
    for "a specified observation frequency," not a specific calendar
    convention, so this picks the first-of-month (or first-of-quarter)
    UTC midnight on or after start_date, stepping forward until
    end_date."""
    if spec.observation_frequency not in ("monthly", "quarterly"):
        raise ValueError(f"unsupported observation_frequency: {spec.observation_frequency!r}")
    step_months = 1 if spec.observation_frequency == "monthly" else 3
    out: list[datetime] = []
    year, month = spec.start_date.year, spec.start_date.month
    while True:
        instant = datetime(year, month, 1, tzinfo=timezone.utc)
        if instant.date() > spec.end_date:
            break
        out.append(instant)
        month += step_months
        while month > 12:
            month -= 12
            year += 1
    return out


def generate_sec_fundamentals_asof(
    store: SECFilingStore, spec: SECDatasetSpec, *, retrieval_timestamp: datetime | None = None
) -> tuple[list[SECFundamentalObservation], DatasetVersionRecord]:
    """The Part 9 generator. Returns the raw point-in-time observations
    plus the DatasetVersionRecord that makes this exact run reproducible
    (Part 13) -- no alpha computation of any kind."""
    retrieval_timestamp = retrieval_timestamp or datetime.now(timezone.utc)
    instants = generate_asof_instants(spec)
    observations: list[SECFundamentalObservation] = []
    for symbol in spec.symbols:
        form_by_filing_id = {f.filing_id: f.form_type for f in store.load_filings(symbol)}
        eligible_facts = [f for f in store.load_facts(symbol) if form_by_filing_id.get(f.filing_id) in spec.filing_forms]
        for as_of in instants:
            available = get_available_facts(eligible_facts, as_of=as_of, policy=spec.timestamp_policy)
            for concept in spec.fact_whitelist:
                fact = latest_known_value(available, normalized_concept=concept)
                observations.append(SECFundamentalObservation(
                    symbol=symbol, as_of=as_of, normalized_concept=concept,
                    value=fact.value if fact else None,
                    fact_period_end=fact.period_end if fact else None,
                    fact_date_filed=fact.date_filed if fact else None,
                ))

    version = DatasetVersionRecord(
        source="mcp__HOOD__get_sec_filing_index+get_sec_filing_facts (via SECFilingStore)",
        retrieval_timestamp=retrieval_timestamp,
        source_version=None,  # unknown/unversioned upstream -- see docs/sec_data_source.md
        schema_version="sec-v1",
        adjustment_status="as-filed, amendments preserved separately, no restatement collapsing",
        universe_version=content_hash({"universe_name": spec.universe_name, "symbols": sorted(spec.symbols)}),
        fact_selection_version=content_hash({"fact_whitelist": sorted(spec.fact_whitelist), "filing_forms": sorted(spec.filing_forms)}),
        timestamp_policy_version=content_hash({"policy": spec.timestamp_policy.value}),
    )
    return observations, version
