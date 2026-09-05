"""Phase 37, Part 19 — the automated data-quality report.

Reads ONLY from the four stores (never re-fetches anything live).
Every count here is a data-QUALITY statistic, never an alpha signal --
`DataQualityReport` has no field named anything like "score"/"edge"/
"expectancy", and this module never computes one (see
`tests/test_phase37_quality_report.py::test_report_is_never_treated_as_alpha_evidence`).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from src.research_recorder.quote_quality import DEFAULT_STALE_QUOTE_SECONDS

if TYPE_CHECKING:
    from src.research_recorder.storage import RecorderStores as _RecorderStoresType  # noqa: F401 -- type-checking only, avoids a circular import at runtime


@dataclass(frozen=True)
class DataQualityReport:
    cycles_attempted: int
    cycles_successful: int  # a cycle with at least one successful symbol
    cycles_failed: int  # a cycle with zero successful symbols
    symbols_attempted: int
    symbols_successful: int
    option_contracts_observed: int
    unique_option_contracts: int
    unique_expirations: int
    calls: int
    puts: int
    dte_distribution: dict[str, int]  # DTE bucket label -> count, coarse (never raw per-observation dump)
    moneyness_distribution: dict[str, int]
    quote_completeness_pct: float | None  # fraction of option rows with both bid and ask present
    stale_quote_count: int
    duplicate_count: int
    invalid_quote_count: int  # missing/non-positive bid or ask, or crossed market
    api_failures: int
    parser_failures: int


def build_data_quality_report(stores) -> DataQualityReport:  # stores: RecorderStores -- untyped here to avoid a circular import with recorder.py
    cycle_rows = stores.cycle_log.load_all_raw_dicts()
    cycles_attempted = len(cycle_rows)
    cycles_successful = sum(1 for r in cycle_rows if r.get("symbols_succeeded"))
    cycles_failed = cycles_attempted - cycles_successful

    symbols_attempted = sum(len(r.get("symbols_attempted", [])) for r in cycle_rows)
    symbols_successful = sum(len(r.get("symbols_succeeded", [])) for r in cycle_rows)

    option_rows = stores.option.load_all_raw_dicts()
    unique_contracts = {row["option_id"] for row in option_rows}
    unique_expirations = {row["expiration"] for row in option_rows if row.get("expiration")}
    calls = sum(1 for row in option_rows if row.get("option_type") == "call")
    puts = sum(1 for row in option_rows if row.get("option_type") == "put")

    dte_counter: Counter[str] = Counter()
    moneyness_counter: Counter[str] = Counter()
    for row in option_rows:
        dte_counter[_dte_bucket_label(row.get("dte"))] += 1
        moneyness_counter[_moneyness_bucket_label(row.get("moneyness"))] += 1

    priced = sum(1 for row in option_rows if row.get("bid") is not None and row.get("ask") is not None)
    completeness = (priced / len(option_rows)) if option_rows else None

    invalid_count = sum(
        1 for row in option_rows
        if row.get("bid") is None or row.get("ask") is None
        or (row.get("bid") is not None and row["bid"] <= 0)
        or (row.get("ask") is not None and row["ask"] <= 0)
        or (row.get("bid") is not None and row.get("ask") is not None and row["ask"] < row["bid"])
    )

    api_failures = sum(
        1 for r in cycle_rows for f in r.get("symbols_failed", [])
        if f.get("reason") and ("failed:" in f["reason"] or "API" in f["reason"])
    )
    duplicate_count = sum(r.get("duplicates_detected", 0) for r in cycle_rows)

    stale_quote_count = 0
    for row in option_rows:
        market_ts = row.get("market_timestamp")
        obs_ts = row.get("observation_timestamp")
        if market_ts and obs_ts:
            age = (datetime.fromisoformat(obs_ts) - datetime.fromisoformat(market_ts)).total_seconds()
            if age > DEFAULT_STALE_QUOTE_SECONDS:
                stale_quote_count += 1

    raw_observations = stores.raw.load_all()
    parser_failures = sum(1 for obs in raw_observations if obs.raw_payload.get("_unparseable"))

    return DataQualityReport(
        cycles_attempted=cycles_attempted, cycles_successful=cycles_successful, cycles_failed=cycles_failed,
        symbols_attempted=symbols_attempted, symbols_successful=symbols_successful,
        option_contracts_observed=len(option_rows), unique_option_contracts=len(unique_contracts),
        unique_expirations=len(unique_expirations), calls=calls, puts=puts,
        dte_distribution=dict(dte_counter), moneyness_distribution=dict(moneyness_counter),
        quote_completeness_pct=completeness, stale_quote_count=stale_quote_count, duplicate_count=duplicate_count,
        invalid_quote_count=invalid_count, api_failures=api_failures, parser_failures=parser_failures,
    )


def _dte_bucket_label(dte) -> str:
    if dte is None:
        return "UNKNOWN"
    if dte < 0:
        return "EXPIRED"
    if dte <= 15:
        return "SHORT_0_15"
    if dte <= 45:
        return "MEDIUM_16_45"
    return "LONG_46_PLUS"


def _moneyness_bucket_label(moneyness) -> str:
    if moneyness is None:
        return "UNKNOWN"
    if moneyness > 0.03:
        return "ITM"
    if moneyness < -0.03:
        return "OTM"
    return "NEAR_ATM"
