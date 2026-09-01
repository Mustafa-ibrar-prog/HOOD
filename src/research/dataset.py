"""Research dataset generator: combines market data + features + future
targets into one dataset, with features and targets kept in clearly
separated, prefix-tagged columns (Phase 2, section 7's explicit
requirement) so a target can never be mistaken for a feature downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.data.bar import Bar
from src.features.engine import FeatureEngine
from src.research.targets import future_return

FEATURE_PREFIX = "feature_"
TARGET_PREFIX = "target_"


@dataclass(frozen=True)
class ResearchDataset:
    symbol: str
    rows: tuple[dict, ...]
    feature_columns: tuple[str, ...]
    target_columns: tuple[str, ...]
    data_version: str
    feature_version: str


class ResearchDatasetGenerator:
    def __init__(self, feature_engine: FeatureEngine, horizons: Sequence[int] = (1, 5, 20), *, log_returns: bool = False):
        if not horizons:
            raise ValueError("at least one horizon is required")
        self._engine = feature_engine
        self._horizons = tuple(horizons)
        self._log_returns = log_returns

    def generate(self, bars: Sequence[Bar], *, data_version: str) -> ResearchDataset:
        if not bars:
            raise ValueError("generate() requires at least one bar")

        frame = self._engine.compute(bars)
        feature_columns = tuple(f"{FEATURE_PREFIX}{name}" for name in frame.feature_names)

        target_series = {h: future_return(bars, h, log=self._log_returns) for h in self._horizons}
        target_columns = tuple(f"{TARGET_PREFIX}future_return_{h}bar" for h in self._horizons)

        rows = []
        for i, ts in enumerate(frame.timestamps):
            row: dict = {"timestamp": ts, "symbol": frame.symbol}
            for name, col in zip(frame.feature_names, feature_columns):
                row[col] = frame.columns[name][i]
            for h, col in zip(self._horizons, target_columns):
                row[col] = target_series[h][i]
            rows.append(row)

        feature_version = "|".join(f"{n}:{v}" for n, v in sorted(frame.feature_versions.items()))
        return ResearchDataset(
            symbol=frame.symbol,
            rows=tuple(rows),
            feature_columns=feature_columns,
            target_columns=target_columns,
            data_version=data_version,
            feature_version=feature_version,
        )
