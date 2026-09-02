"""Deterministic content-hash identifiers for datasets, feature sets, and
experiments — the mechanism that makes research reproducible per Phase 2's
requirement: "A backtest performed today should be identifiable from a
backtest performed next month."

Every hash here is a pure function of its inputs: same inputs, same
output, every time, on any machine — never a random UUID (those are used
elsewhere, e.g. ExperimentRecord.experiment_id, purely for uniqueness, not
for identifying content).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:
    from src.data.universe import Universe


def content_hash(payload: Mapping[str, Any], *, length: int = 16) -> str:
    """Deterministic, key-order-independent hash of a JSON-serializable
    mapping. `length` truncates the hex digest for readability — 16 hex
    chars (64 bits) is more than enough collision resistance for a
    human-facing dataset/feature version tag."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:length]


def compute_data_version(
    *,
    source: str,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    record_count: int | None = None,
) -> str:
    """Identifies exactly which historical dataset a research result was
    built from. `start`/`end` should be ISO-formatted timestamps (or dates)
    — pass whatever the dataset's own start/end actually is, not a
    requested range that may not have been fully covered."""
    payload: dict[str, Any] = {
        "source": source,
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "start": start,
        "end": end,
    }
    if record_count is not None:
        payload["record_count"] = record_count
    return content_hash(payload)


def compute_feature_version(feature_manifest: Sequence[Mapping[str, Any]]) -> str:
    """`feature_manifest` is FeatureEngine.manifest()'s output: a list of
    {name, version, params, ...} dicts. Order-independent (sorted by name)
    so registering the same features in a different order never produces a
    spuriously different version — only an actual change to which features
    or which parameters are used does."""
    canonical = sorted(
        (
            {"name": f["name"], "version": f["version"], "params": f.get("params", {})}
            for f in feature_manifest
        ),
        key=lambda d: d["name"],
    )
    return content_hash({"features": canonical})


def compute_universe_version(universe: "Universe") -> str:
    """Identifies exactly which universe (name + membership) a research
    result was built from — a future data source's universe_version field
    (Phase 15, Part 14) should be this, not a hand-typed string. Order-
    independent over membership (sorted symbols) so re-registering the
    same Universe with members listed in a different order never produces
    a spuriously different version."""
    return content_hash({"name": universe.name, "symbols": sorted(universe.symbols)})


@dataclass(frozen=True)
class DatasetVersionRecord:
    """Phase 15, Part 14 — what a future research dataset must record to
    be reproducible from a known version, generalizing compute_data_version
    (which only identifies one symbol/timeframe/source/date-range) to the
    full set of facts Part 14 asks for: source, retrieval time, source
    version, schema version, adjustment status, universe version, and
    feature version. `fingerprint()` composes them into one deterministic
    id the same way compute_data_version/compute_feature_version already
    do — reused via content_hash, not reimplemented."""

    source: str
    retrieval_timestamp: datetime
    source_version: str | None
    schema_version: str
    adjustment_status: str
    universe_version: str
    feature_version: str | None = None

    def fingerprint(self) -> str:
        return content_hash({
            "source": self.source,
            "retrieval_timestamp": self.retrieval_timestamp.isoformat(),
            "source_version": self.source_version,
            "schema_version": self.schema_version,
            "adjustment_status": self.adjustment_status,
            "universe_version": self.universe_version,
            "feature_version": self.feature_version,
        })
