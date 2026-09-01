"""Phase 7, Part 1: an explicit research-data lifecycle.

Phase 6 already built a 2-way DEVELOPMENT/HOLDOUT split
(src.research.holdout) for one specific strategy (MR-002). This module
generalizes that idea into a 4-stage lifecycle for the whole research
program, reusable by any future hypothesis:

    DISCOVERY_DATA    -> where hypotheses are generated and first
                          screened (cross-sectional IC, not backtesting)
    DEVELOPMENT_DATA   -> where a strategy is actually built/backtested
                          and where parameter selection is allowed
    VALIDATION_DATA    -> an intermediate check, still visible to
                          research but NOT to parameter selection
    FINAL_HOLDOUT_DATA -> touched by nothing until a strategy's
                          parameters are already frozen

The four ranges are computed from the ACTUAL available data range (never
invented), in the same spirit as src.research.holdout.determine_holdout_split:
a deterministic function of (start, end, stage_fractions), not a
hand-picked date chosen to flatter a result.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence


class PartitionLifecycleStage(str, Enum):
    DISCOVERY = "DISCOVERY_DATA"
    DEVELOPMENT = "DEVELOPMENT_DATA"
    VALIDATION = "VALIDATION_DATA"
    FINAL_HOLDOUT = "FINAL_HOLDOUT_DATA"


# Stages allowed to influence parameter/strategy selection. VALIDATION is
# visible for reporting (e.g. computing an out-of-sample-looking metric to
# READ) but is not where a sweep/walk-forward is allowed to pick a
# parameter from — see assert_stage_allows_parameter_selection below.
STAGES_ALLOWING_PARAMETER_SELECTION = frozenset({PartitionLifecycleStage.DISCOVERY, PartitionLifecycleStage.DEVELOPMENT})


class PartitionAccessError(RuntimeError):
    """Raised when code attempts to use a partition in a way its stage
    does not permit — e.g. selecting parameters from FINAL_HOLDOUT_DATA."""


@dataclass(frozen=True)
class ResearchDatasetPartition:
    dataset_id: str
    universe_name: str
    start_date: date
    end_date: date
    partition_type: PartitionLifecycleStage
    created_at: datetime
    source_version: str
    data_version: str
    feature_version: str
    status: str  # "ACTIVE" | "SUPERSEDED"
    immutable: bool  # True for every stage except a not-yet-finalized DISCOVERY partition, in principle

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError(f"partition {self.dataset_id!r}: start_date must be <= end_date")

    def contains(self, d: date) -> bool:
        return self.start_date <= d <= self.end_date

    def overlaps(self, start: date, end: date) -> bool:
        return start <= self.end_date and end >= self.start_date

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["start_date"] = self.start_date.isoformat()
        d["end_date"] = self.end_date.isoformat()
        d["created_at"] = self.created_at.isoformat()
        d["partition_type"] = self.partition_type.value
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResearchDatasetPartition":
        return cls(
            dataset_id=data["dataset_id"], universe_name=data["universe_name"],
            start_date=date.fromisoformat(data["start_date"]), end_date=date.fromisoformat(data["end_date"]),
            partition_type=PartitionLifecycleStage(data["partition_type"]), created_at=datetime.fromisoformat(data["created_at"]),
            source_version=data["source_version"], data_version=data["data_version"], feature_version=data["feature_version"],
            status=data.get("status", "ACTIVE"), immutable=bool(data.get("immutable", True)),
        )


class PartitionStore:
    """Append-only, same convention as every other *Store in this
    codebase. A partition once written is never edited — a corrected
    partition set gets new dataset_ids and the old ones are marked
    SUPERSEDED via a fresh record, never rewritten in place."""

    def __init__(self, path: Path):
        self._path = path

    def record(self, partition: ResearchDatasetPartition) -> ResearchDatasetPartition:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(partition.to_dict(), sort_keys=True, default=str))
            f.write("\n")
            f.flush()
        return partition

    def load_all(self) -> list[ResearchDatasetPartition]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        return [ResearchDatasetPartition.from_dict(json.loads(line)) for line in raw.splitlines() if line.strip()]

    def get(self, dataset_id: str) -> ResearchDatasetPartition | None:
        for p in self.load_all():
            if p.dataset_id == dataset_id:
                return p
        return None

    def active_by_stage(self, stage: PartitionLifecycleStage) -> list[ResearchDatasetPartition]:
        return [p for p in self.load_all() if p.partition_type == stage and p.status == "ACTIVE"]


def determine_lifecycle_partitions(
    *,
    universe_name: str,
    full_start: date,
    full_end: date,
    source_version: str,
    data_version: str,
    feature_version: str,
    discovery_fraction: float = 0.40,
    development_fraction: float = 0.30,
    validation_fraction: float = 0.15,
    now: datetime | None = None,
) -> tuple[ResearchDatasetPartition, ResearchDatasetPartition, ResearchDatasetPartition, ResearchDatasetPartition]:
    """Splits [full_start, full_end] into 4 CHRONOLOGICAL, non-overlapping
    ranges by fraction of total days — a deterministic function of the
    actual available range, never a hand-picked date. The remaining
    fraction (1 - discovery - development - validation) becomes
    FINAL_HOLDOUT_DATA, always the most RECENT slice (mirroring
    src.research.holdout's "reserve the most recent period" principle —
    the only genuinely untouched data is what came last)."""
    if not (0 < discovery_fraction < 1 and 0 < development_fraction < 1 and 0 <= validation_fraction < 1):
        raise ValueError("fractions must be in (0, 1)")
    total = discovery_fraction + development_fraction + validation_fraction
    if total >= 1.0:
        raise ValueError(f"discovery + development + validation fractions must leave room for a holdout (sum={total} must be < 1.0)")

    total_days = (full_end - full_start).days + 1
    if total_days < 10:
        raise ValueError("full_start..full_end is too short to partition into 4 stages meaningfully")

    discovery_days = max(1, round(total_days * discovery_fraction))
    development_days = max(1, round(total_days * development_fraction))
    validation_days = max(1, round(total_days * validation_fraction))

    discovery_start = full_start
    discovery_end = discovery_start + _days(discovery_days - 1)
    development_start = discovery_end + _days(1)
    development_end = development_start + _days(development_days - 1)
    validation_start = development_end + _days(1)
    validation_end = validation_start + _days(validation_days - 1)
    holdout_start = validation_end + _days(1)
    holdout_end = full_end

    if holdout_start > holdout_end:
        raise ValueError(
            f"the requested fractions leave no room for FINAL_HOLDOUT_DATA within {full_start}..{full_end} "
            f"({total_days} days) — reduce discovery/development/validation fractions"
        )

    now = now or datetime.now(timezone.utc)
    make = lambda suffix, stage, s, e: ResearchDatasetPartition(  # noqa: E731
        dataset_id=f"{universe_name}-{suffix}-{source_version}", universe_name=universe_name, start_date=s, end_date=e,
        partition_type=stage, created_at=now, source_version=source_version, data_version=data_version,
        feature_version=feature_version, status="ACTIVE", immutable=True,
    )
    return (
        make("discovery", PartitionLifecycleStage.DISCOVERY, discovery_start, discovery_end),
        make("development", PartitionLifecycleStage.DEVELOPMENT, development_start, development_end),
        make("validation", PartitionLifecycleStage.VALIDATION, validation_start, validation_end),
        make("holdout", PartitionLifecycleStage.FINAL_HOLDOUT, holdout_start, holdout_end),
    )


def _days(n: int):
    from datetime import timedelta

    return timedelta(days=n)


def assert_stage_allows_parameter_selection(partition: ResearchDatasetPartition, *, context: str) -> None:
    """The core structural protection Part 1 asks for: any code path that
    is about to use a partition's data to CHOOSE a parameter, threshold,
    or strategy variant must call this first. Raises PartitionAccessError
    for VALIDATION_DATA and FINAL_HOLDOUT_DATA."""
    if partition.partition_type not in STAGES_ALLOWING_PARAMETER_SELECTION:
        raise PartitionAccessError(
            f"{context}: {partition.dataset_id} is {partition.partition_type.value} — parameter/strategy selection "
            f"is only allowed from {sorted(s.value for s in STAGES_ALLOWING_PARAMETER_SELECTION)}."
        )


def assert_no_partition_overlap(partitions: Sequence[ResearchDatasetPartition]) -> None:
    """Defensive check: no two of the given partitions may cover
    overlapping date ranges — a stale/miscomputed partition set is exactly
    the kind of silent contamination this whole module exists to prevent."""
    ordered = sorted(partitions, key=lambda p: p.start_date)
    for a, b in zip(ordered, ordered[1:]):
        if a.overlaps(b.start_date, b.end_date):
            raise PartitionAccessError(f"partitions {a.dataset_id} and {b.dataset_id} overlap ({a.start_date}..{a.end_date} vs {b.start_date}..{b.end_date})")


def filter_rows_by_partition(rows: Sequence[Mapping[str, Any]], partition: ResearchDatasetPartition) -> list[dict]:
    """Restricts a panel of rows (dicts with a `timestamp` key, same shape
    used throughout src.research.ic/quantile) to one partition's date
    range — the data-side complement to assert_stage_allows_parameter_selection."""
    return [dict(r) for r in rows if partition.contains(r["timestamp"].date())]
