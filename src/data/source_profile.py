"""Phase 15, Parts 3-5, 9, 10 — the data-source provenance matrix.

`AvailabilityClass` encodes Part 3's A-G distinction exactly (never treat
B/E as equivalent to D — a live tool is not a historical archive).
`DataProvenance` encodes Part 4/12/20's OBSERVED/DERIVED/MODELED/ESTIMATED
distinction. `CostClass`/`ResearchSuitability` encode Parts 10/21's
classification vocabularies.

`DATA_SOURCE_MATRIX` is the actual audit result: one `DataSourceProfile`
row per field/category investigated in Part 4 (A-G), populated from
direct inspection of this repository's code (src/data/*, src/market/*)
and, where noted, real read-only calls made against the connected HOOD
tools during this phase's development (see scripts/
phase15_data_architecture_audit.py for the full evidence narrative per
row — this module holds the structured conclusions, not the evidence
trail itself).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class AvailabilityClass(enum.Enum):
    """Part 3's A-G distinction. Never conflate AVAILABLE_VIA_API or
    LIVE_ONLY with HISTORICALLY_BACKFILLABLE — a tool that can be CALLED
    today is not the same as a tool that can answer a question about
    2021-2023."""

    AVAILABLE_NOW = "available_now"  # already persisted in this repository
    AVAILABLE_VIA_API = "available_via_api"  # the connected tools can retrieve it today
    HISTORICALLY_ARCHIVABLE = "historically_archivable"  # can be collected/stored going FORWARD from today
    HISTORICALLY_BACKFILLABLE = "historically_backfillable"  # the source can supply real observations for the PAST research window
    LIVE_ONLY = "live_only"  # only the current instant is ever retrievable; no historical archive exists anywhere
    MODELED_DERIVED = "modeled_derived"  # computed from other observations, not itself an observation
    ESTIMATED = "estimated"  # inferred by an algorithm/classifier rather than directly observed


class DataProvenance(enum.Enum):
    OBSERVED = "observed"
    DERIVED = "derived"
    MODELED = "modeled"
    ESTIMATED = "estimated"


class CostClass(enum.Enum):
    FREE = "free"
    LOW_COST = "low_cost"
    MODERATE_COST = "moderate_cost"
    HIGH_COST = "high_cost"
    UNKNOWN = "unknown"


class ResearchSuitability(enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class DataSourceProfile:
    """One row of the Part 5 data-provenance matrix."""

    data_source: str
    field: str
    frequency: str
    historical_coverage: str
    symbol_coverage: str
    point_in_time: bool | None  # None = genuinely unverified/ambiguous, not a silent False
    release_timestamp_available: bool
    adjustment: str
    provenance: DataProvenance
    availability: AvailabilityClass
    api_or_source: str
    cost: CostClass
    rate_limits: str
    storage_estimate: str
    research_suitability: ResearchSuitability
    major_caveat: str


# ---------------------------------------------------------------------------
# The actual audit result. Every row below is backed by direct repository
# inspection and/or a real read-only probe call made during this phase's
# development (documented in scripts/phase15_data_architecture_audit.py).
# Nothing here is guessed.
# ---------------------------------------------------------------------------
DATA_SOURCE_MATRIX: tuple[DataSourceProfile, ...] = (
    DataSourceProfile(
        data_source="src/data/store.py (HistoricalDataStore, current baseline)",
        field="open/high/low/close/volume",
        frequency="daily",
        historical_coverage="2021-09-01..2026-08-31 (persisted)",
        symbol_coverage="20/20 US_DIVERSIFIED (45 total symbols across all prior phases)",
        point_in_time=True,  # a closed daily bar IS its own causal timestamp
        release_timestamp_available=True,
        adjustment="split-adjusted, dividend-unadjusted",
        provenance=DataProvenance.OBSERVED,
        availability=AvailabilityClass.AVAILABLE_NOW,
        api_or_source="mcp__HOOD__get_equity_historicals (already ingested)",
        cost=CostClass.FREE,
        rate_limits="n/a (already stored locally)",
        storage_estimate="~1254 bars/symbol, trivially small (JSONL)",
        research_suitability=ResearchSuitability.HIGH,
        major_caveat="Current, unchanged baseline (Part 2) — do not alter.",
    ),
    DataSourceProfile(
        data_source="mcp__HOOD__get_equity_historicals, intraday intervals",
        field="open/high/low/close/volume, 1-minute .. hourly",
        frequency="1minute/5minute/15minute/30minute/hour",
        historical_coverage="real data confirmed as recent as 4 days before this audit; probe at ~2 years back (2024-08-28) returned ONLY interpolated=true, volume=0 placeholder bars, not real observations",
        symbol_coverage="same equities as daily (tool accepts any symbol)",
        point_in_time=True,
        release_timestamp_available=True,
        adjustment="adjustment_type parameter available (none/split/all)",
        provenance=DataProvenance.OBSERVED,
        availability=AvailabilityClass.LIVE_ONLY,  # for the 2021-2023 discovery window specifically — see caveat
        api_or_source="mcp__HOOD__get_equity_historicals(interval=minute|5minute|...)",
        cost=CostClass.FREE,
        rate_limits="server auto-selects interval to bound ~2500 bars/call; explicit fine intervals over wide ranges are rejected",
        storage_estimate="~390 bars/session/symbol at 1-minute -> ~98,000 bars/symbol/year; multi-year intraday for 20 symbols would be tens of millions of rows",
        research_suitability=ResearchSuitability.UNAVAILABLE,
        major_caveat="CANNOT backfill the 2021-09-01..2023-08-31 discovery window: a real probe 2 years back returned only flat, zero-volume, interpolated=true gap-fill bars, not observations. Do NOT mistake these for real data — this is exactly the AVAILABLE_VIA_API != HISTORICALLY_BACKFILLABLE trap Part 3 warns against. Usable only for a FUTURE research window collected forward from today.",
    ),
    DataSourceProfile(
        data_source="mcp__HOOD__get_equity_quotes",
        field="last trade price, previous close (bid/ask NOT surfaced by the existing EquityQuote model)",
        frequency="point-in-time snapshot only",
        historical_coverage="none — current instant only, no start/end time parameter exists on this tool",
        symbol_coverage="any equity symbol",
        point_in_time=False,
        release_timestamp_available=False,
        adjustment="n/a",
        provenance=DataProvenance.OBSERVED,
        availability=AvailabilityClass.LIVE_ONLY,
        api_or_source="mcp__HOOD__get_equity_quotes",
        cost=CostClass.FREE,
        rate_limits="n/a (live snapshot)",
        storage_estimate="n/a — cannot be backdated",
        research_suitability=ResearchSuitability.UNAVAILABLE,
        major_caveat="Confirms Phase 14's finding: no historical quote archive exists or is retrievable through this tool.",
    ),
    DataSourceProfile(
        data_source="mcp__HOOD__get_equity_price_book",
        field="Level 2 order book (bid/ask ladder, resting size per level)",
        frequency="point-in-time snapshot only",
        historical_coverage="none — tool schema has no time-range parameter at all",
        symbol_coverage="up to 4 symbols/call",
        point_in_time=False,
        release_timestamp_available=False,
        adjustment="n/a",
        provenance=DataProvenance.OBSERVED,
        availability=AvailabilityClass.LIVE_ONLY,
        api_or_source="mcp__HOOD__get_equity_price_book",
        cost=CostClass.FREE,
        rate_limits="max 4 symbols/call",
        storage_estimate="n/a — cannot be backdated",
        research_suitability=ResearchSuitability.UNAVAILABLE,
        major_caveat="Reconfirms Phase 14: this tool is never integrated into src/ or scripts/, and is structurally live-only (no historical archive is possible even if integrated).",
    ),
    DataSourceProfile(
        data_source="mcp__HOOD__get_equity_fundamentals",
        field="valuation ratios, market cap, shares outstanding, 52-week range, dividend schedule",
        frequency="today's snapshot only",
        historical_coverage="none — tool description is explicit: \"today's fundamentals\"",
        symbol_coverage="up to 10 symbols/call",
        point_in_time=False,
        release_timestamp_available=False,
        adjustment="n/a",
        provenance=DataProvenance.OBSERVED,
        availability=AvailabilityClass.LIVE_ONLY,
        api_or_source="mcp__HOOD__get_equity_fundamentals",
        cost=CostClass.FREE,
        rate_limits="max 10 symbols/call",
        storage_estimate="n/a — cannot be backdated",
        research_suitability=ResearchSuitability.UNAVAILABLE,
        major_caveat="Current-snapshot fundamentals (PE, market cap) — not a substitute for the historical reported-financials series below.",
    ),
    DataSourceProfile(
        data_source="mcp__HOOD__get_financials",
        field="revenue, gross profit, net income, net margin (quarterly/annual)",
        frequency="quarterly or annual, up to 40 periods/call",
        historical_coverage="confirmed real data back to 2019 Q2 (fiscal quarters), fully covering the 2021-09-01..2023-08-31 discovery window",
        symbol_coverage="up to 20 symbols/call",
        point_in_time=False,  # see caveat: no publication/filing date field at all
        release_timestamp_available=False,
        adjustment="as-reported (no restatement-vs-original distinction surfaced)",
        provenance=DataProvenance.OBSERVED,
        availability=AvailabilityClass.HISTORICALLY_BACKFILLABLE,
        api_or_source="mcp__HOOD__get_financials",
        cost=CostClass.FREE,
        rate_limits="limit capped at 40 periods/call",
        storage_estimate="~7 years x 4 quarters x a handful of fields x 20 symbols -- trivially small",
        research_suitability=ResearchSuitability.MEDIUM,
        major_caveat="POINT_IN_TIME_UNSAFE AS RETURNED: only carries `period_end_date` (fiscal quarter end), never a filing/report date. Confirmed materially different from public-availability date: AAPL's quarter ending 2021-09-25 was not public until its 10-K filed 2021-10-29 (over a month later). Using period_end_date as the causal timestamp would be a real lookahead bug. Becomes usable ONLY if joined against a real filing/report date from get_sec_filing_index or get_earnings_results.",
    ),
    DataSourceProfile(
        data_source="mcp__HOOD__get_earnings_results / get_earnings_calendar",
        field="report date, EPS estimate, EPS actual",
        frequency="per-quarter events",
        historical_coverage="get_earnings_results returns only the trailing ~8 quarters from TODAY (~2 years) — does NOT reach back to the 2021-2023 discovery window at all",
        symbol_coverage="get_earnings_results: 1 symbol/call; get_earnings_calendar: market-wide, date-windowed (max 31 days/call)",
        point_in_time=None,  # report.date itself is real and causal; whether eps.estimate is the ORIGINAL pre-print consensus or a later-revised value was not verified this phase
        release_timestamp_available=True,
        adjustment="n/a",
        provenance=DataProvenance.OBSERVED,
        availability=AvailabilityClass.LIVE_ONLY,  # for THIS repo's discovery window; see caveat
        api_or_source="mcp__HOOD__get_earnings_results, mcp__HOOD__get_earnings_calendar",
        cost=CostClass.FREE,
        rate_limits="8 trailing quarters per symbol; 31-day window per calendar call",
        storage_estimate="n/a until historical depth is confirmed sufficient",
        research_suitability=ResearchSuitability.LOW,
        major_caveat="report.date is a genuine, real, causally-safe timestamp when it IS in range — but the trailing-8-quarters window means this tool literally cannot answer any question about 2021-2023 today. Whether eps.estimate reflects the original pre-earnings consensus (point-in-time-safe) or a currently-revised value was not independently verified this phase — treat as unverified, not assumed-safe.",
    ),
    DataSourceProfile(
        data_source="mcp__HOOD__get_sec_filing_index / get_sec_filing_facts",
        field="10-K/10-Q/8-K filing dates, and tagged GAAP facts within a filing",
        frequency="per-filing events (10-K annual, 10-Q quarterly, 8-K as-needed)",
        historical_coverage="confirmed real filing dates back to 2020-10-30 for AAPL 10-Ks, fully covering and preceding the 2021-09-01..2023-08-31 discovery window",
        symbol_coverage="per-symbol, exact ticker",
        point_in_time=True,  # date_filed IS a genuine SEC public-record timestamp
        release_timestamp_available=True,
        adjustment="as-filed (no restatement ambiguity — each filing_id is immutable)",
        provenance=DataProvenance.OBSERVED,
        availability=AvailabilityClass.HISTORICALLY_BACKFILLABLE,
        api_or_source="mcp__HOOD__get_sec_filing_index, mcp__HOOD__get_sec_filing_facts, mcp__HOOD__get_sec_filing_facts_catalog",
        cost=CostClass.FREE,
        rate_limits="get_sec_filing_facts: up to 3 filing_ids and 10 concepts per call",
        storage_estimate="a handful of filings/year/symbol, each with a bounded set of tagged facts -- small",
        research_suitability=ResearchSuitability.HIGH,
        major_caveat="The strongest point-in-time-safe fundamental-adjacent source found this phase: date_filed is a real, public SEC record date. Only probed for 10-K (annual); 10-Q (quarterly) coverage/depth was not independently verified this phase and should be re-checked before full adoption.",
    ),
    DataSourceProfile(
        data_source="mcp__HOOD__get_option_chains / get_option_instruments / get_option_historicals",
        field="contract chains, strikes/expirations, OHLC option price bars",
        frequency="per-contract; option_historicals supports 15second..50year intervals",
        historical_coverage="get_option_chains returns only the CURRENTLY LISTED chain (expirations from today forward through 2028) — no evidence of a historical chain snapshot for 2021-2023; option_historicals requires an instrument_id already known, and 2021-2023 contract IDs are not discoverable through any tool probed this phase",
        symbol_coverage="per-underlying",
        point_in_time=None,
        release_timestamp_available=False,
        adjustment="n/a (options are not split/dividend adjusted the way equities are)",
        provenance=DataProvenance.OBSERVED,
        availability=AvailabilityClass.LIVE_ONLY,  # chain discovery specifically; see caveat
        api_or_source="mcp__HOOD__get_option_chains, get_option_instruments, get_option_historicals",
        cost=CostClass.FREE,
        rate_limits="get_option_historicals: up to 10 instrument_ids/call",
        storage_estimate="not estimated — historical contract universe is not enumerable",
        research_suitability=ResearchSuitability.UNAVAILABLE,
        major_caveat="Systematic historical options backfill for 2021-2023 is infeasible through this API: there is no tool that lists what contracts existed on a past date, so their instrument_ids (required by get_option_historicals) cannot be recovered. This is a real, structural gap, not a coverage-depth question.",
    ),
    DataSourceProfile(
        data_source="Macroeconomic data (Treasury yields, CPI, VIX, credit spreads, etc.)",
        field="various",
        frequency="various",
        historical_coverage="no macro-specific tool exists anywhere among the connected read-only HOOD tools",
        symbol_coverage="n/a",
        point_in_time=None,
        release_timestamp_available=False,
        adjustment="n/a",
        provenance=DataProvenance.OBSERVED,
        availability=AvailabilityClass.LIVE_ONLY,
        api_or_source="mcp__HOOD__get_index_historicals/get_index_quotes cover market INDEXES (e.g. SPX), not macro releases (CPI, unemployment, GDP, Treasury yields) — no tool for the latter exists in this connection",
        cost=CostClass.UNKNOWN,
        rate_limits="n/a",
        storage_estimate="n/a",
        research_suitability=ResearchSuitability.UNAVAILABLE,
        major_caveat="No macro data source is connected at all. A future integration would need an external, point-in-time-safe macro vendor (e.g. one that preserves ALFRED-style vintage/revision history) — not something this environment currently provides.",
    ),
)
