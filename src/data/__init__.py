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
    us_diversified_secondary_universe,
    us_diversified_universe,
    us_etf_benchmark_universe,
    us_small_cap_volatile_universe,
)
from src.data.universe_quality import SymbolQualitySummary, render_universe_quality_report, run_universe_quality_report, usable_symbols
from src.data.versioning import DatasetVersionRecord, compute_data_version, compute_feature_version, compute_universe_version, content_hash
from src.data.timestamp_model import CausalTimestampPolicy, EventTimestamps, PointInTimeViolation, assert_no_lookahead, is_knowable_at
from src.data.source_profile import DATA_SOURCE_MATRIX, AvailabilityClass, CostClass, DataProvenance, DataSourceProfile, ResearchSuitability
from src.data.generic_quality import find_duplicate_timestamps, find_out_of_order_indices, find_publication_time_violations, find_timezone_naive_indices
from src.data.store_interfaces import (
    EarningsStore,
    FundamentalStore,
    HistoricalBarStore,
    MacroStore,
    OptionsStore,
    ProvenancedObservation,
    QuoteStore,
    TradeStore,
)
from src.data.sec_filing_store import (
    FORM_PROFILES,
    UNKNOWN_FORM_PROFILE,
    FilingFormProfile,
    SECFactRecord,
    SECFilingRecord,
    SECFilingStore,
    SECFilingStoreError,
    classify_form,
)
from src.data.sec_timestamp_policy import SECCausalPolicy, sec_is_available_asof
from src.data.sec_fact_quality import (
    FactQualityClass,
    SECQualityReport,
    classify_fact,
    find_duplicate_facts,
    find_impossible_period_ordering,
    find_unit_inconsistencies,
)
from src.data.sec_concepts import CONCEPT_MAP, CONCEPT_MAP_BY_SOURCE, ConceptMapping, is_known_reliable_concept, normalized_concept_for
from src.data.sec_snapshot import get_available_facts, get_available_facts_for_symbol, latest_known_value
from src.data.sec_dataset import (
    DATASET_NAME,
    DEFAULT_FACT_WHITELIST,
    SECDatasetSpec,
    SECFundamentalObservation,
    generate_asof_instants,
    generate_sec_fundamentals_asof,
)

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
    "us_diversified_secondary_universe",
    "us_small_cap_volatile_universe",
    "us_etf_benchmark_universe",
    "test_universe",
    "SymbolQualitySummary",
    "run_universe_quality_report",
    "usable_symbols",
    "render_universe_quality_report",
    "DatasetVersionRecord",
    "compute_universe_version",
    "CausalTimestampPolicy",
    "EventTimestamps",
    "PointInTimeViolation",
    "assert_no_lookahead",
    "is_knowable_at",
    "DATA_SOURCE_MATRIX",
    "AvailabilityClass",
    "CostClass",
    "DataProvenance",
    "DataSourceProfile",
    "ResearchSuitability",
    "find_duplicate_timestamps",
    "find_out_of_order_indices",
    "find_publication_time_violations",
    "find_timezone_naive_indices",
    "EarningsStore",
    "FundamentalStore",
    "HistoricalBarStore",
    "MacroStore",
    "OptionsStore",
    "ProvenancedObservation",
    "QuoteStore",
    "TradeStore",
    "FORM_PROFILES",
    "UNKNOWN_FORM_PROFILE",
    "FilingFormProfile",
    "SECFactRecord",
    "SECFilingRecord",
    "SECFilingStore",
    "SECFilingStoreError",
    "classify_form",
    "SECCausalPolicy",
    "sec_is_available_asof",
    "FactQualityClass",
    "SECQualityReport",
    "classify_fact",
    "find_duplicate_facts",
    "find_impossible_period_ordering",
    "find_unit_inconsistencies",
    "CONCEPT_MAP",
    "CONCEPT_MAP_BY_SOURCE",
    "ConceptMapping",
    "is_known_reliable_concept",
    "normalized_concept_for",
    "get_available_facts",
    "get_available_facts_for_symbol",
    "latest_known_value",
    "DATASET_NAME",
    "DEFAULT_FACT_WHITELIST",
    "SECDatasetSpec",
    "SECFundamentalObservation",
    "generate_asof_instants",
    "generate_sec_fundamentals_asof",
]
