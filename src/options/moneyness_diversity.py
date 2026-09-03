"""Phase 20, Part 6 — moneyness diversity measurement across a research
panel: per-bucket contract count, observation count, average DTE, share
of sample, and incomplete-history percentage. Reporting only -- this
module never chooses which bucket "matters more"; it exists so a reader
can see whether the panel over-represents one moneyness region (Part 6's
explicit instruction: 'Do not over-represent one moneyness region simply
because it has more available historical data.').
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

from src.options.moneyness import MoneynessBucket

ALL_BUCKETS: tuple[MoneynessBucket, ...] = (
    MoneynessBucket.DEEP_ITM, MoneynessBucket.ITM, MoneynessBucket.NEAR_ATM, MoneynessBucket.OTM, MoneynessBucket.DEEP_OTM,
)


@dataclass(frozen=True)
class MoneynessBucketStats:
    bucket: MoneynessBucket
    contract_count: int
    observation_count: int
    average_dte: float | None
    share_of_sample: float  # observation_count / total observation_count across all buckets
    incomplete_history_fraction: float  # fraction of this bucket's contracts flagged incomplete


@dataclass(frozen=True)
class MoneynessDiversityReport:
    underlying_symbol: str
    buckets: tuple[MoneynessBucketStats, ...]

    @property
    def most_represented_bucket(self) -> MoneynessBucket | None:
        if not self.buckets:
            return None
        return max(self.buckets, key=lambda b: b.observation_count).bucket

    @property
    def is_concentrated(self) -> bool:
        """True when a single bucket holds more than half the sample --
        an explicit, documented threshold, not a hidden judgment call."""
        if not self.buckets:
            return False
        return max(b.share_of_sample for b in self.buckets) > 0.5


def build_moneyness_diversity_report(underlying_symbol: str, rows: Sequence[dict], *, incomplete_contract_ids: frozenset[str] = frozenset()) -> MoneynessDiversityReport:
    """`rows` are research-panel rows carrying at minimum
    `moneyness_bucket` (str, matching a MoneynessBucket.value), `dte`
    (int), and `option_id` (str)."""
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        b = r.get("moneyness_bucket")
        if b is not None:
            by_bucket[b].append(r)

    total_obs = sum(len(v) for v in by_bucket.values())
    stats = []
    for bucket in ALL_BUCKETS:
        bucket_rows = by_bucket.get(bucket.value, [])
        if not bucket_rows:
            continue
        contract_ids = {r["option_id"] for r in bucket_rows}
        dtes = [r["dte"] for r in bucket_rows if r.get("dte") is not None]
        incomplete_count = sum(1 for cid in contract_ids if cid in incomplete_contract_ids)
        stats.append(MoneynessBucketStats(
            bucket=bucket, contract_count=len(contract_ids), observation_count=len(bucket_rows),
            average_dte=(sum(dtes) / len(dtes)) if dtes else None,
            share_of_sample=(len(bucket_rows) / total_obs) if total_obs else 0.0,
            incomplete_history_fraction=(incomplete_count / len(contract_ids)) if contract_ids else 0.0,
        ))
    return MoneynessDiversityReport(underlying_symbol=underlying_symbol, buckets=tuple(stats))
