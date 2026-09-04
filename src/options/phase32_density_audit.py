"""Phase 32, Part 2/21 — the data-integrity / density audit, run BEFORE
any bucket feature or target is evaluated.

Operates on Phase 31's real contract-day panel
(`phase31_panel_builder.build_panel_rows`'s output) — the exact same
already-certified, already-causal rows Phase 31 built and tested, not a
re-ingestion of the raw store. This module adds density MEASUREMENT on
top, never a new data-quality check duplicating Phase 26's
`phase26_quality_rules.run_all_quality_checks` (already baked into every
row's `data_quality` field via Phase 30's `research_dataset.py`).

DATA TIER SEPARATION (Part 2's explicit A/B/C/D vocabulary): this
campaign uses tiers A (real observation), B (reconstructed feature —
e.g. a rolling-window return, still built ONLY from real prior
observations), and C (bucket aggregate — a median/mean/dispersion
computed from real per-contract values). Tier D (imputed/interpolated/
forward-filled) is NEVER produced anywhere in this phase — `IMPUTATION_
USED = False` is asserted by the phase-wide safety test, not just
claimed in prose.
"""

from __future__ import annotations

import enum
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Sequence

from src.options.phase32_bucket_definitions import COARSE_SCHEME, FINE_SCHEME, BucketScheme

IMPUTATION_USED = False  # this campaign never forward-fills, interpolates, or synthesizes a missing observation


class DataTier(enum.Enum):
    A_REAL_OBSERVATION = "real_observation"
    B_RECONSTRUCTED_FEATURE = "reconstructed_feature"
    C_BUCKET_AGGREGATE = "bucket_aggregate"
    D_IMPUTED = "imputed"  # never produced this phase -- see IMPUTATION_USED


@dataclass(frozen=True)
class UnderlyingDateDensity:
    underlying: str
    date: date
    n_contracts: int
    n_expirations: int
    n_calls: int
    n_puts: int
    dte_bucket_counts: dict[str, int]
    moneyness_bucket_counts: dict[str, int]
    n_flagged_critical: int
    n_flagged_warning: int
    n_flagged_clean: int


def build_density_report(panel_rows: Sequence[dict]) -> tuple[UnderlyingDateDensity, ...]:
    """One row per (underlying, real date) actually present in the
    panel — Part 2's per-underlying-per-date audit fields."""
    groups: dict[tuple[str, date], list[dict]] = defaultdict(list)
    for r in panel_rows:
        groups[(r["underlying_symbol"], r["timestamp"].date())].append(r)

    out = []
    for (underlying, d), rows in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        expirations = {r["expiration"] for r in rows}
        calls = sum(1 for r in rows if r["call_put"] == "call")
        puts = sum(1 for r in rows if r["call_put"] == "put")
        dte_counts = Counter(r.get("dte_bucket") for r in rows)
        moneyness_counts = Counter(r.get("moneyness_bucket") for r in rows)
        quality_counts = Counter(r.get("data_quality") for r in rows)
        out.append(UnderlyingDateDensity(
            underlying=underlying, date=d, n_contracts=len(rows), n_expirations=len(expirations),
            n_calls=calls, n_puts=puts, dte_bucket_counts=dict(dte_counts), moneyness_bucket_counts=dict(moneyness_counts),
            n_flagged_critical=quality_counts.get("flagged_critical", 0),
            n_flagged_warning=quality_counts.get("flagged_warning", 0),
            n_flagged_clean=quality_counts.get("clean", 0),
        ))
    return tuple(out)


@dataclass(frozen=True)
class BucketDensityCell:
    underlying: str
    call_put: str
    dte_bucket: str
    moneyness_bucket: str
    n_dates: int
    n_observations: int
    median_observations_per_date: float


def compute_bucket_density(panel_rows: Sequence[dict], scheme: BucketScheme) -> tuple[BucketDensityCell, ...]:
    by_key_date: dict[tuple[str, str, str, str], dict[date, int]] = defaultdict(lambda: defaultdict(int))
    for r in panel_rows:
        dte_b = scheme.coarsen_dte(r.get("dte_bucket"))
        money_b = scheme.coarsen_moneyness(r.get("moneyness_bucket"))
        if dte_b is None or money_b is None:
            continue
        key = (r["underlying_symbol"], r["call_put"], dte_b, money_b)
        by_key_date[key][r["timestamp"].date()] += 1

    out = []
    for (underlying, call_put, dte_b, money_b), by_date in by_key_date.items():
        counts = sorted(by_date.values())
        median = counts[len(counts) // 2]
        out.append(BucketDensityCell(
            underlying=underlying, call_put=call_put, dte_bucket=dte_b, moneyness_bucket=money_b,
            n_dates=len(by_date), n_observations=sum(counts), median_observations_per_date=median,
        ))
    return tuple(sorted(out, key=lambda c: (c.underlying, c.call_put, c.dte_bucket, c.moneyness_bucket)))


@dataclass(frozen=True)
class SchemeSelectionResult:
    chosen_scheme: BucketScheme
    fine_cells_meeting_threshold: int
    coarse_cells_meeting_threshold: int
    min_median_observations_per_date: int
    min_dates: int
    min_usable_cells: int
    reason: str


def select_scheme_by_density(
    panel_rows: Sequence[dict], *, min_median_obs_per_date: int = 3, min_dates: int = 10, min_usable_cells: int = 5,
) -> SchemeSelectionResult:
    """Part 1's explicit instruction: measure density BEFORE deciding
    which preregistered scheme to use, and document exclusions. A cell
    "meets the threshold" if it has real observations on >= `min_dates`
    distinct real dates with a median of >= `min_median_obs_per_date`
    contracts per date -- both fixed BEFORE this function ever saw real
    numbers."""
    fine_cells = compute_bucket_density(panel_rows, FINE_SCHEME)
    coarse_cells = compute_bucket_density(panel_rows, COARSE_SCHEME)
    fine_ok = sum(1 for c in fine_cells if c.median_observations_per_date >= min_median_obs_per_date and c.n_dates >= min_dates)
    coarse_ok = sum(1 for c in coarse_cells if c.median_observations_per_date >= min_median_obs_per_date and c.n_dates >= min_dates)

    if fine_ok >= min_usable_cells:
        chosen, reason = FINE_SCHEME, (
            f"{fine_ok} FINE bucket cells meet the density threshold "
            f"(>= {min_median_obs_per_date} median obs/date across >= {min_dates} dates)."
        )
    elif coarse_ok >= min_usable_cells:
        chosen, reason = COARSE_SCHEME, (
            f"FINE scheme had only {fine_ok} usable cells (need >= {min_usable_cells}); "
            f"COARSE scheme has {coarse_ok} meeting the same threshold."
        )
    else:
        chosen, reason = COARSE_SCHEME, (
            f"Neither scheme reaches {min_usable_cells} usable cells (FINE={fine_ok}, COARSE={coarse_ok}); "
            "defaulting to COARSE as the less-restrictive option -- expect NOT_READY/data-limited results downstream, "
            "not a claim that aggregation solved the density problem."
        )
    return SchemeSelectionResult(
        chosen_scheme=chosen, fine_cells_meeting_threshold=fine_ok, coarse_cells_meeting_threshold=coarse_ok,
        min_median_observations_per_date=min_median_obs_per_date, min_dates=min_dates, min_usable_cells=min_usable_cells,
        reason=reason,
    )


def find_missing_dates(panel_rows: Sequence[dict], underlying_trading_dates: dict[str, Sequence[date]]) -> dict[str, list[date]]:
    """`underlying_trading_dates` -- real dates the UNDERLYING itself has
    an equity close for (e.g. from `phase31_panel_builder.
    build_underlying_series`). A date present there but with zero panel
    rows is a real 'no options coverage that day' gap, reported
    honestly, never filled."""
    covered: dict[str, set[date]] = defaultdict(set)
    for r in panel_rows:
        covered[r["underlying_symbol"]].add(r["timestamp"].date())
    return {
        underlying: [d for d in dates if d not in covered.get(underlying, set())]
        for underlying, dates in underlying_trading_dates.items()
    }


def count_duplicate_observations(panel_rows: Sequence[dict]) -> int:
    seen: set[tuple[str, object]] = set()
    duplicates = 0
    for r in panel_rows:
        key = (r["option_id"], r["timestamp"])
        if key in seen:
            duplicates += 1
        seen.add(key)
    return duplicates


def count_impossible_prices(panel_rows: Sequence[dict]) -> dict[str, int]:
    """Zero/negative option prices and crossed (bid>ask) quotes — a
    thin, disclosure-only re-tabulation of what `data_quality` already
    encodes (Phase 26's `check_negative_or_zero_prices`/`check_bid_gt_ask`),
    reported at the panel level for this phase's density report."""
    zero_or_negative = sum(
        1 for r in panel_rows
        if any(v is not None and v <= 0 for v in (r.get("option_close"), r.get("bid"), r.get("ask")))
    )
    crossed = sum(1 for r in panel_rows if r.get("bid") is not None and r.get("ask") is not None and r["bid"] > r["ask"])
    return {"zero_or_negative_price_rows": zero_or_negative, "crossed_quote_rows": crossed}
