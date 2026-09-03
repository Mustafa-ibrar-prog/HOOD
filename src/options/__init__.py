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
]
