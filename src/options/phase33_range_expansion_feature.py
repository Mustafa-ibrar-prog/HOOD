"""Phase 33, Part C/24 — the coarse-grained P22-OPT-013 replication
FEATURE: bucket-day aggregates of each contract's own range-expansion
ratio.

P22-OPT-013's original feature (Phase 22; already replicated once,
unmodified, at the individual-contract level as Phase 31's P31-OPT-003)
is `option_range_expansion`: today's own (H-L)/close ratio divided by
the mean of that SAME ratio over the 5 trading days STRICTLY BEFORE
today (`src.options.price_volatility_proxy.range_expansion_ratio`,
wrapped by `src.options.momentum_features.option_range_expansion`) — a
value of 1.0 means "a perfectly typical day"; the baseline never uses
today or any later observation, so the feature is causal by
construction.

Phase 33 does NOT recompute this feature or re-derive a new baseline
window. `src.options.phase31_panel_builder.build_panel_rows` already
computes it, unchanged, on every real contract-day row (column
`option_range_expansion`) — this module's ONLY job is to aggregate
those already-causal per-contract values within each Phase 32 bucket-day
(median/mean/log-mean/cross-sectional dispersion), exactly Part C's
instruction: "Construct the range-expansion feature... Aggregate within
Phase 32 buckets." No contract-day row is ever assigned to a bucket
based on information from a later date — bucket membership here is
IDENTICAL to `phase32_bucket_panel.build_bucket_day_table`'s (same
`scheme.coarsen_dte`/`coarsen_moneyness` calls, same grouping key), so
this module inherits Phase 32's already-verified no-survivorship-leakage
guarantee for free rather than re-deriving it.

If a bucket-day's aggregate statistic cannot be honestly computed (e.g.
every contract's `option_range_expansion` is `None` that day, or fewer
than 2 real values exist for a dispersion estimate), the corresponding
field is `None` — Part C's explicit instruction: "If a statistic can't
be reconstructed, mark DATA_LIMITED -- never invent a substitute." A
`None` here always means real data was insufficient, never a fabricated
0 or 1.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

from src.options.phase32_bucket_definitions import BucketScheme
from src.options.phase32_bucket_panel import BucketKey

RANGE_EXPANSION_COL = "option_range_expansion"  # the exact Phase 31 contract-day column, never redefined here


@dataclass(frozen=True)
class RangeExpansionBucketStats:
    key: BucketKey
    n_contracts_total: int  # every real contract-day row in this bucket-day, regardless of feature availability
    n_contracts_with_value: int  # how many actually had a real (non-None) option_range_expansion value
    median_range_expansion: float | None
    mean_range_expansion: float | None
    log_mean_range_expansion: float | None  # mean of ln(ratio); undefined (None) unless every included ratio is > 0
    range_expansion_dispersion: float | None  # cross-sectional stdev of the ratio within this bucket-day; needs >= 2 real values
    n_excluded_nonpositive_for_log: int  # ratios <= 0 excluded from the log-mean, reported so the exclusion is never silent


def _bucket_key_for_row(row: dict, scheme: BucketScheme) -> BucketKey | None:
    """Reproduces `phase32_bucket_panel.build_bucket_day_table`'s exact
    grouping key construction (Part 3's causal aggregation), so a
    contract-day row lands in the SAME bucket-day here as it does in
    the Phase 32 bucket panel -- never a parallel, potentially
    inconsistent definition of "which bucket a contract belongs to.\""""
    dte_b = scheme.coarsen_dte(row.get("dte_bucket"))
    money_b = scheme.coarsen_moneyness(row.get("moneyness_bucket"))
    if dte_b is None or money_b is None:
        return None
    return (row["underlying_symbol"], row["call_put"], dte_b, money_b, row["timestamp"].date())


def compute_range_expansion_bucket_stats(key: BucketKey, rows: Sequence[dict]) -> RangeExpansionBucketStats:
    values = [r[RANGE_EXPANSION_COL] for r in rows if r.get(RANGE_EXPANSION_COL) is not None]
    positive_values = [v for v in values if v > 0]
    log_values = [math.log(v) for v in positive_values]

    return RangeExpansionBucketStats(
        key=key, n_contracts_total=len(rows), n_contracts_with_value=len(values),
        median_range_expansion=(statistics.median(values) if values else None),
        mean_range_expansion=(statistics.mean(values) if values else None),
        log_mean_range_expansion=(statistics.mean(log_values) if log_values else None),
        range_expansion_dispersion=(statistics.stdev(values) if len(values) >= 2 else None),
        n_excluded_nonpositive_for_log=(len(values) - len(positive_values)),
    )


def build_range_expansion_bucket_table(panel_rows: Sequence[dict], scheme: BucketScheme) -> dict[BucketKey, RangeExpansionBucketStats]:
    """The causal aggregation step: groups real contract-day rows into
    the SAME bucket-day keys Phase 32's bucket panel uses, then reduces
    each group to `RangeExpansionBucketStats`."""
    grouped: dict[BucketKey, list[dict]] = defaultdict(list)
    for r in panel_rows:
        key = _bucket_key_for_row(r, scheme)
        if key is not None:
            grouped[key].append(r)
    return {key: compute_range_expansion_bucket_stats(key, rows) for key, rows in grouped.items()}


def attach_range_expansion_features(bucket_rows: list[dict], panel_rows: Sequence[dict], scheme: BucketScheme) -> list[dict]:
    """Merges the range-expansion aggregates onto Phase 32's already-
    built bucket-day rows (`phase32_bucket_panel.build_bucket_panel`'s
    output — same schema, same `option_id`/`timestamp`/`underlying_symbol`/
    `call_put`/`dte_bucket`/`moneyness_bucket` fields), matched on the
    identical bucket key. A bucket-day row that exists in Phase 32's
    panel but has no range-expansion value (e.g. every contract-day
    lacked the 5-day trailing baseline needed to compute the ratio) gets
    `None` fields here, never a dropped row and never a fabricated
    value -- Part C's explicit instruction honored row by row."""
    table = build_range_expansion_bucket_table(panel_rows, scheme)
    out = []
    for row in bucket_rows:
        key: BucketKey = (row["underlying_symbol"], row["call_put"], row["dte_bucket"], row["moneyness_bucket"], row["timestamp"].date())
        stats = table.get(key)
        new_row = dict(row)
        new_row["bucket_range_expansion_median"] = stats.median_range_expansion if stats else None
        new_row["bucket_range_expansion_mean"] = stats.mean_range_expansion if stats else None
        new_row["bucket_range_expansion_log_mean"] = stats.log_mean_range_expansion if stats else None
        new_row["bucket_range_expansion_dispersion"] = stats.range_expansion_dispersion if stats else None
        new_row["bucket_range_expansion_n_with_value"] = stats.n_contracts_with_value if stats else 0
        out.append(new_row)
    return out
