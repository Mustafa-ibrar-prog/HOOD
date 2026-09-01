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
from src.data.universe import (
    CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED,
    POINT_IN_TIME_AVAILABLE,
    Universe,
    UniverseMember,
    test_universe,
    us_diversified_universe,
    us_etf_benchmark_universe,
    us_small_cap_volatile_universe,
)
from src.data.universe_quality import SymbolQualitySummary, render_universe_quality_report, run_universe_quality_report, usable_symbols
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
    "Universe",
    "UniverseMember",
    "CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED",
    "POINT_IN_TIME_AVAILABLE",
    "us_diversified_universe",
    "us_small_cap_volatile_universe",
    "us_etf_benchmark_universe",
    "test_universe",
    "SymbolQualitySummary",
    "run_universe_quality_report",
    "usable_symbols",
    "render_universe_quality_report",
]
