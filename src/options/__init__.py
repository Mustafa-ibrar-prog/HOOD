"""Phase 18 — options-only instrument/chain/position/store architecture.

This package is the research-layer options data model, parallel to
src/data/'s equity/SEC architecture and separate from src/market/'s
live-trading-oriented OptionQuote/PriceBar and src/position_manager/'s
live single-leg OpenPosition. Nothing here calls a HOOD MCP tool
directly (same boundary as everywhere else in this codebase) and nothing
here computes alpha, IC, or any predictive statistic.

PROJECT DIRECTION (Phase 18): the live trading system's final tradable
instrument is OPTIONS CONTRACTS ONLY. Equities, OHLCV, SEC fundamentals,
and volatility/regime data may be used as INPUT DATA for options
decisions, but nothing in this codebase's execution layer is permitted
to place an equity/share order as the final instrument. See
src/execution/asset_class_restriction.py for the enforced guard and
docs/options_architecture.md for the full documentation.
"""

from __future__ import annotations

from src.options.instrument import OptionContract
from src.options.chain import OptionChainObservation, OptionsFieldStatus
from src.options.greeks import DerivedGreeksMetadata, Greeks, GreeksProvenance
from src.options.implied_volatility import DerivedIVMetadata, IVObservation, IVProvenance
from src.options.liquidity import LiquidityMetrics, compute_liquidity_metrics
from src.options.point_in_time import ContractExistenceEvidence, assert_no_survivorship_bias_in_contract_universe, contract_existed_at
from src.options.quality import (
    OptionsQualityIssue,
    find_duplicate_contract_timestamp,
    find_inconsistent_contract_metadata,
    find_timestamp_ordering_issues,
    validate_greeks,
    validate_iv,
    validate_observation,
)
from src.options.store import HistoricalOptionsDataUnavailableError, OptionsDataStore, OptionsDataStoreError
from src.options.position import OptionLegPosition, OptionsPosition, PositionRiskProfile, analyze_position_risk
from src.options.capability_audit import OPTIONS_CAPABILITY_MATRIX, OptionsCapabilityRow, OptionsSourceCapability, summarize_capability

# --- Phase 19 additions (options-alpha discovery foundation) ---
from src.options.universe import (
    PHASE20_DYNAMIC_DISCOVERY_EVIDENCE,
    DynamicDiscoveryEvidence,
    OptionableUnderlying,
    UnderlyingFilterConfig,
    UnderlyingUniverse,
    phase19_verified_underlying_universe,
    phase20_verified_underlying_universe,
)
from src.options.moneyness import MoneynessBucket, MoneynessObservation, classify_moneyness, log_moneyness, moneyness_ratio
from src.options.expiration import DTEBucket, bucket_dte, days_to_expiration
from src.options.price_history import (
    STANDARD_FORWARD_HORIZONS,
    OptionPriceBar,
    close_to_close_return,
    daily_return_series,
    future_option_return,
    holding_period_return,
)
from src.options.contract_existence import ExistenceState, classify_existence
from src.options.research_observation import OptionResearchObservation, build_research_series
from src.options.cost_model import COST_SENSITIVITY_ASSUMPTIONS, CostAssumption, ResearchRealismLabel, apply_cost_assumption
from src.options.opportunity_score import (
    UNAVAILABLE_HISTORICALLY,
    ChainCandidate,
    ContractCandidate,
    OpportunityScore,
    SignalEvaluation,
    UnderlyingCandidate,
)

# --- Phase 20 additions (options research universe expansion & cross-sectional validation) ---
from src.options.research_eligibility import (
    ExclusionReason,
    ExistenceImpactSummary,
    InclusionReason,
    OptionChainCandidate,
    OptionContractCandidate,
    ResearchEligibleContract,
    evaluate_underlying_inclusion,
    summarize_existence_impact,
)
from src.options.expiration_diversity import (
    CROSS_SECTIONAL_IC_UNDEFINED,
    ExpirationCoverage,
    ExpirationDiversityReport,
    build_expiration_diversity_report,
    has_cross_sectional_variance,
)
from src.options.moneyness_diversity import (
    ALL_BUCKETS,
    MoneynessBucketStats,
    MoneynessDiversityReport,
    build_moneyness_diversity_report,
)
from src.options.data_balance import ConcentrationResult, DataBalanceReport, build_data_balance_report, compute_concentration
from src.options.return_normalization import NormalizedReturn, compute_normalized_return
from src.options.mechanical_baseline import BaselineClassification, MechanicalBaselineComparison, compare_option_vs_underlying_signal

__all__ = [
    "OptionContract",
    "OptionChainObservation",
    "OptionsFieldStatus",
    "DerivedGreeksMetadata",
    "Greeks",
    "GreeksProvenance",
    "DerivedIVMetadata",
    "IVObservation",
    "IVProvenance",
    "LiquidityMetrics",
    "compute_liquidity_metrics",
    "ContractExistenceEvidence",
    "assert_no_survivorship_bias_in_contract_universe",
    "contract_existed_at",
    "OptionsQualityIssue",
    "find_duplicate_contract_timestamp",
    "find_inconsistent_contract_metadata",
    "find_timestamp_ordering_issues",
    "validate_greeks",
    "validate_iv",
    "validate_observation",
    "HistoricalOptionsDataUnavailableError",
    "OptionsDataStore",
    "OptionsDataStoreError",
    "OptionLegPosition",
    "OptionsPosition",
    "PositionRiskProfile",
    "analyze_position_risk",
    "OPTIONS_CAPABILITY_MATRIX",
    "OptionsCapabilityRow",
    "OptionsSourceCapability",
    "summarize_capability",
    "OptionableUnderlying",
    "UnderlyingFilterConfig",
    "UnderlyingUniverse",
    "phase19_verified_underlying_universe",
    "MoneynessBucket",
    "MoneynessObservation",
    "classify_moneyness",
    "log_moneyness",
    "moneyness_ratio",
    "DTEBucket",
    "bucket_dte",
    "days_to_expiration",
    "STANDARD_FORWARD_HORIZONS",
    "OptionPriceBar",
    "close_to_close_return",
    "daily_return_series",
    "future_option_return",
    "holding_period_return",
    "ExistenceState",
    "classify_existence",
    "OptionResearchObservation",
    "build_research_series",
    "COST_SENSITIVITY_ASSUMPTIONS",
    "CostAssumption",
    "ResearchRealismLabel",
    "apply_cost_assumption",
    "UNAVAILABLE_HISTORICALLY",
    "ChainCandidate",
    "ContractCandidate",
    "OpportunityScore",
    "SignalEvaluation",
    "UnderlyingCandidate",
    "PHASE20_DYNAMIC_DISCOVERY_EVIDENCE",
    "DynamicDiscoveryEvidence",
    "phase20_verified_underlying_universe",
    "ExclusionReason",
    "ExistenceImpactSummary",
    "InclusionReason",
    "OptionChainCandidate",
    "OptionContractCandidate",
    "ResearchEligibleContract",
    "evaluate_underlying_inclusion",
    "summarize_existence_impact",
    "CROSS_SECTIONAL_IC_UNDEFINED",
    "ExpirationCoverage",
    "ExpirationDiversityReport",
    "build_expiration_diversity_report",
    "has_cross_sectional_variance",
    "ALL_BUCKETS",
    "MoneynessBucketStats",
    "MoneynessDiversityReport",
    "build_moneyness_diversity_report",
    "ConcentrationResult",
    "DataBalanceReport",
    "build_data_balance_report",
    "compute_concentration",
    "NormalizedReturn",
    "compute_normalized_return",
    "BaselineClassification",
    "MechanicalBaselineComparison",
    "compare_option_vs_underlying_signal",
]
