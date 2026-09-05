"""Phase 39, Part 11 — observation coverage report.

Composes Phase 37's existing `DataQualityReport` (never recomputes its
fields) with the additional per-date/per-symbol/per-contract
distributional statistics Part 11 asks for. The purpose (Part 11's own
words) is "to determine when we have enough information to return to
Phase 38" — this module reports DATA QUALITY / COVERAGE statistics only,
never an alpha signal or a trading recommendation (matching Phase 37's
own `build_data_quality_report` discipline).
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.research_recorder.quality_report import (
    DataQualityReport,
    _dte_bucket_label,
    _moneyness_bucket_label,
    build_data_quality_report,
)

if TYPE_CHECKING:
    from src.research_recorder.storage import RecorderStores as _RecorderStoresType  # noqa: F401


@dataclass(frozen=True)
class CoverageReport:
    data_quality: DataQualityReport  # composed, not duplicated
    total_cycles: int
    cycles_by_date: dict[str, int]
    cycles_by_symbol: dict[str, int]
    contracts_observed_by_symbol: dict[str, int]
    unique_expirations_by_symbol: dict[str, int]
    dte_bucket_counts: dict[str, int]
    moneyness_bucket_counts: dict[str, int]
    observations_per_contract_mean: float | None
    observations_per_contract_median: float | None
    observations_per_contract_max: int | None
    implied_volatility_availability_pct: float | None
    greeks_availability_pct: float | None  # fraction of option rows with ALL FIVE greeks present
    volume_availability_pct: float | None
    open_interest_availability_pct: float | None


def build_coverage_report(stores) -> CoverageReport:  # stores: RecorderStores -- untyped to avoid a circular import with recorder.py
    quality = build_data_quality_report(stores)

    cycle_rows = stores.cycle_log.load_all_raw_dicts()
    option_rows = stores.option.load_all_raw_dicts()

    cycles_by_date: Counter[str] = Counter()
    cycles_by_symbol: Counter[str] = Counter()
    for row in cycle_rows:
        started_at = row.get("started_at")
        if started_at:
            cycles_by_date[str(started_at)[:10]] += 1
        for symbol in row.get("symbols_succeeded", []) or []:
            cycles_by_symbol[symbol] += 1

    contracts_by_symbol: Counter[str] = Counter()
    expirations_by_symbol: dict[str, set] = {}
    dte_counts: Counter[str] = Counter()
    moneyness_counts: Counter[str] = Counter()
    per_contract_obs: Counter[str] = Counter()
    n_option_rows = len(option_rows)
    iv_present = 0
    greeks_present = 0
    volume_present = 0
    oi_present = 0

    for row in option_rows:
        symbol = row.get("underlying")
        option_id = row.get("option_id")
        if symbol:
            contracts_by_symbol[symbol] += 1
            expirations_by_symbol.setdefault(symbol, set())
            if row.get("expiration"):
                expirations_by_symbol[symbol].add(row["expiration"])
        if option_id:
            per_contract_obs[option_id] += 1
        dte_counts[_dte_bucket_label(row.get("dte"))] += 1
        moneyness_counts[_moneyness_bucket_label(row.get("moneyness"))] += 1
        if row.get("implied_volatility") is not None:
            iv_present += 1
        if all(row.get(g) is not None for g in ("delta", "gamma", "theta", "vega", "rho")):
            greeks_present += 1
        if row.get("volume") is not None:
            volume_present += 1
        if row.get("open_interest") is not None:
            oi_present += 1

    per_contract_counts = list(per_contract_obs.values())

    return CoverageReport(
        data_quality=quality,
        total_cycles=len(cycle_rows),
        cycles_by_date=dict(cycles_by_date),
        cycles_by_symbol=dict(cycles_by_symbol),
        contracts_observed_by_symbol=dict(contracts_by_symbol),
        unique_expirations_by_symbol={k: len(v) for k, v in expirations_by_symbol.items()},
        dte_bucket_counts=dict(dte_counts),
        moneyness_bucket_counts=dict(moneyness_counts),
        observations_per_contract_mean=(statistics.mean(per_contract_counts) if per_contract_counts else None),
        observations_per_contract_median=(statistics.median(per_contract_counts) if per_contract_counts else None),
        observations_per_contract_max=(max(per_contract_counts) if per_contract_counts else None),
        implied_volatility_availability_pct=(iv_present / n_option_rows if n_option_rows else None),
        greeks_availability_pct=(greeks_present / n_option_rows if n_option_rows else None),
        volume_availability_pct=(volume_present / n_option_rows if n_option_rows else None),
        open_interest_availability_pct=(oi_present / n_option_rows if n_option_rows else None),
    )
