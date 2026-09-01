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
from typing import Any, Mapping, Sequence


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
