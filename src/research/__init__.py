"""Research tooling: turn (bars + features) into datasets, split them
chronologically, test features for a measurable relationship with future
returns, and track every experiment run — all explicitly separate from
the live/paper trading path (src/orchestrator.py, src/strategy/,
src/execution/), which never imports from this package.

RESEARCH ONLY. Nothing in this package places, modifies, or evaluates a
live trade, and nothing here automatically turns a statistically
interesting result into a trading strategy — that stays a human decision.

Phase 4 additions: a standardized ResearchStrategy interface, a
HypothesisRegistry, six research strategy families, Information
Coefficient / cross-sectional quantile / regime analysis, parameter
sweeps, walk-forward research, robustness and cost-sensitivity testing,
rule-based PROMISING/INCONCLUSIVE/FRAGILE/REJECTED classification,
baseline comparisons, and a structured research report — see
src/research/research_report.py's module docstring for how they compose.
"""

from __future__ import annotations

from src.research.analysis import FeatureAnalysisResult, QuantileResult, analyze_feature, pearson_correlation, rank_values, spearman_correlation
from src.research.baseline import RandomEntryTrade, buy_and_hold_curve, no_trade_curve, random_entry_baseline
from src.research.classification import ClassificationResult, StrategyClassification, classify_strategy
from src.research.cross_sectional import SubgroupResult, by_sector, by_symbol, by_volatility_bucket, by_year, concentration_summary
from src.research.dataset import ResearchDataset, ResearchDatasetGenerator
from src.research.experiment import ExperimentRecord, ExperimentStore
from src.research.hypothesis import Hypothesis, HypothesisRegistry, HypothesisRegistryError
from src.research.ic import ICPoint, ICSummary, compute_ic_series, ic_by_period, summarize_ic
from src.research.leave_one_out import LeaveOneOutReport, LeaveOneOutResult, leave_one_group_out, leave_one_symbol_out
from src.research.placebo import BootstrapCI, BootstrapReport, PlaceboTestResult, bootstrap_trade_statistics, randomized_entry_timing_placebo
from src.research.quantile import CrossSectionalQuantileResult, QuantilePortfolioReport, cross_sectional_quantile_returns
from src.research.regime import bucket_trades_by_regime, label_bars_by_regime, regime_performance_report
from src.research.research_matrix import ResearchMatrix, ResearchMatrixRow
from src.research.research_report import ResearchReport
from src.research.runner import filter_bars_by_date, run_research_backtest
from src.research.search_space import SearchSpaceSummary, compute_search_space_summary
from src.research.splits import DatasetSplit, SplitConfig, SplitConfigError, chronological_split
from src.research.strategies import MeanReversionStrategy, MomentumStrategy, VolatilityRegimeStrategy, VolumeConfirmedMomentumStrategy, campaign_hypotheses
from src.research.strategy import ResearchSignal, ResearchStrategy, ResearchStrategyBacktestAdapter, ResearchStrategySpec
from src.research.sweep import ParameterStabilityReport, SweepPoint, run_parameter_sweep, summarize_parameter_stability
from src.research.targets import future_return
from src.research.validation import (
    CostSensitivityPoint,
    CostSensitivityReport,
    ExecutionRobustnessPoint,
    ExecutionRobustnessReport,
    RobustnessCheck,
    RobustnessReport,
    WalkForwardReport,
    WalkForwardWindow,
    WalkForwardWindowResult,
    generate_walk_forward_windows,
    run_cost_sensitivity,
    run_execution_robustness,
    run_robustness_tests,
    run_walk_forward,
)

__all__ = [
    "future_return",
    "ResearchDataset",
    "ResearchDatasetGenerator",
    "SplitConfig",
    "SplitConfigError",
    "DatasetSplit",
    "chronological_split",
    "analyze_feature",
    "FeatureAnalysisResult",
    "QuantileResult",
    "pearson_correlation",
    "spearman_correlation",
    "rank_values",
    "ExperimentRecord",
    "ExperimentStore",
    "Hypothesis",
    "HypothesisRegistry",
    "HypothesisRegistryError",
    "ResearchStrategy",
    "ResearchStrategySpec",
    "ResearchSignal",
    "ResearchStrategyBacktestAdapter",
    "MomentumStrategy",
    "MeanReversionStrategy",
    "VolatilityRegimeStrategy",
    "VolumeConfirmedMomentumStrategy",
    "campaign_hypotheses",
    "run_research_backtest",
    "filter_bars_by_date",
    "ICPoint",
    "ICSummary",
    "compute_ic_series",
    "summarize_ic",
    "ic_by_period",
    "CrossSectionalQuantileResult",
    "QuantilePortfolioReport",
    "cross_sectional_quantile_returns",
    "label_bars_by_regime",
    "bucket_trades_by_regime",
    "regime_performance_report",
    "SweepPoint",
    "ParameterStabilityReport",
    "run_parameter_sweep",
    "summarize_parameter_stability",
    "WalkForwardWindow",
    "WalkForwardWindowResult",
    "WalkForwardReport",
    "generate_walk_forward_windows",
    "run_walk_forward",
    "RobustnessCheck",
    "RobustnessReport",
    "run_robustness_tests",
    "CostSensitivityPoint",
    "CostSensitivityReport",
    "run_cost_sensitivity",
    "StrategyClassification",
    "ClassificationResult",
    "classify_strategy",
    "buy_and_hold_curve",
    "no_trade_curve",
    "random_entry_baseline",
    "RandomEntryTrade",
    "ResearchReport",
    "SubgroupResult",
    "by_symbol",
    "by_sector",
    "by_year",
    "by_volatility_bucket",
    "concentration_summary",
    "LeaveOneOutReport",
    "LeaveOneOutResult",
    "leave_one_symbol_out",
    "leave_one_group_out",
    "PlaceboTestResult",
    "randomized_entry_timing_placebo",
    "BootstrapCI",
    "BootstrapReport",
    "bootstrap_trade_statistics",
    "SearchSpaceSummary",
    "compute_search_space_summary",
    "ResearchMatrix",
    "ResearchMatrixRow",
    "ExecutionRobustnessPoint",
    "ExecutionRobustnessReport",
    "run_execution_robustness",
]
