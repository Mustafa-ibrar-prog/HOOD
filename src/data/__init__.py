"""Normalized, broker-agnostic market-data layer for the research/quant
platform — the foundation Phase 1's audit identified as missing.

Nothing in this package depends on Robinhood-specific shapes; the
adapters in bar.py are the only translation point from the existing
src/market/ models. Nothing in src/execution, src/risk,
src/position_manager, or src/orchestrator.py imports from this package,
and this package never imports from those — it is purely additive.
"""

from __future__ import annotations

from src.data.bar import Bar, Quote
from src.data.quality import DataQualityIssue, DataQualityReport, validate_bars
from src.data.store import DatasetMetadata, HistoricalDataStore, HistoricalDataStoreError
from src.data.versioning import compute_data_version, compute_feature_version, content_hash

__all__ = [
    "Bar",
    "Quote",
    "DataQualityIssue",
    "DataQualityReport",
    "validate_bars",
    "DatasetMetadata",
    "HistoricalDataStore",
    "HistoricalDataStoreError",
    "compute_data_version",
    "compute_feature_version",
    "content_hash",
]
