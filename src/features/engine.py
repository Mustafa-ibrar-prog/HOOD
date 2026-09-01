"""FeatureEngine: runs a registered set of Feature implementations over one
symbol's bar series and aligns the results into a FeatureFrame.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from src.data.bar import Bar
from src.features.base import Feature


@dataclass(frozen=True)
class FeatureFrame:
    symbol: str
    timestamps: tuple[datetime, ...]
    feature_names: tuple[str, ...]
    feature_versions: dict[str, str]
    columns: dict[str, tuple[float | None, ...]]  # feature name -> aligned values

    def to_rows(self) -> list[dict]:
        rows = []
        for i, ts in enumerate(self.timestamps):
            row: dict = {"timestamp": ts, "symbol": self.symbol}
            for name in self.feature_names:
                row[name] = self.columns[name][i]
            rows.append(row)
        return rows


class FeatureEngine:
    """Add a feature by constructing it and passing it in — nothing here
    needs to change to support a new feature. Each feature is computed
    once over the whole series (independently of every other feature),
    matching the requirement that a feature be addable and testable
    independently of the rest of the engine."""

    def __init__(self, features: Sequence[Feature]):
        names = [f.spec.name for f in features]
        if len(set(names)) != len(names):
            raise ValueError(f"FeatureEngine requires unique feature names, got duplicates in: {names}")
        self._features = list(features)

    def manifest(self) -> list[dict]:
        """Reproducibility record for every registered feature — feeds
        src.data.versioning.compute_feature_version()."""
        return [
            {
                "name": f.spec.name,
                "version": f.spec.version,
                "params": dict(f.spec.params),
                "required_columns": list(f.spec.required_columns),
                "lookback": f.spec.lookback,
                "description": f.spec.description,
            }
            for f in self._features
        ]

    def compute(self, bars: Sequence[Bar]) -> FeatureFrame:
        if not bars:
            raise ValueError("FeatureEngine.compute() requires at least one bar")
        symbols = {b.symbol for b in bars}
        if len(symbols) > 1:
            raise ValueError(f"FeatureEngine.compute() expects a single symbol's series, got {sorted(symbols)}")
        timestamps = tuple(b.timestamp for b in bars)
        for i in range(1, len(timestamps)):
            if timestamps[i] <= timestamps[i - 1]:
                raise ValueError("bars must be strictly ascending by timestamp for feature computation")

        columns: dict[str, tuple[float | None, ...]] = {}
        for feat in self._features:
            values = feat.compute(bars)
            if len(values) != len(bars):
                raise ValueError(f"feature {feat.spec.name!r} returned {len(values)} values for {len(bars)} bars")
            columns[feat.spec.name] = tuple(values)

        return FeatureFrame(
            symbol=next(iter(symbols)),
            timestamps=timestamps,
            feature_names=tuple(f.spec.name for f in self._features),
            feature_versions={f.spec.name: f.spec.version for f in self._features},
            columns=columns,
        )
