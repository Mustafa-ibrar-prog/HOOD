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

from src.research.alpha_decay import STANDARD_DECAY_HORIZONS, AlphaDecayReport, HorizonPoint, measure_alpha_decay
from src.research.analysis import FeatureAnalysisResult, QuantileResult, analyze_feature, pearson_correlation, rank_values, spearman_correlation
from src.research.baseline import RandomEntryTrade, buy_and_hold_curve, no_trade_curve, random_entry_baseline
from src.research.baseline_comparison import BaselineComparisonReport, compare_against_baselines
from src.research.classification import ClassificationResult, StrategyClassification, classify_strategy
from src.research.cross_sectional import SubgroupResult, by_sector, by_symbol, by_volatility_bucket, by_year, concentration_summary
from src.research.cross_sectional_alpha import CrossSectionalAlphaConfig, CrossSectionalAlphaReport, evaluate_cross_sectional_alpha
from src.research.cross_sectional_placebo import (
    CrossSectionalPlaceboResult,
    irrelevant_feature_control,
    random_feature_control,
    shifted_signal_placebo,
    shuffled_signal_placebo,
    time_shuffled_target_placebo,
)
from src.research.dataset import ResearchDataset, ResearchDatasetGenerator
from src.research.economic_significance import (
    CostStressPoint,
    CostStressReport,
    EconomicSignificanceReport,
    compute_capacity_proxy,
    cost_multiplier_edge,
    evaluate_economic_significance,
)
from src.research.experiment import ExperimentRecord, ExperimentStore
from src.research.experiment_fingerprint import ExperimentDimensions, compute_experiment_fingerprint, fingerprints_differ, which_dimensions_changed
from src.research.frozen_strategy import (
    FrozenStrategyDefinition,
    FrozenStrategyImmutabilityError,
    FrozenStrategyStore,
    build_mr002_frozen_definition,
    build_strategy_from_frozen,
)
from src.research.holdout import HoldoutLeakageError, HoldoutPeriod, assert_no_holdout_leakage, determine_holdout_split
from src.research.hypothesis import Hypothesis, HypothesisRegistry, HypothesisRegistryError
from src.research.hypothesis_generator import HypothesisFamily, generate_hypotheses
from src.research.hypothesis_similarity import (
    POTENTIAL_RESEARCH_REUSE,
    HypothesisFingerprint,
    ResearchReuseCheck,
    bucket_threshold,
    check_research_reuse,
    similarity_score,
)
from src.research.ic import ICPoint, ICSummary, compute_ic_series, ic_by_period, summarize_ic
from src.research.leave_one_out import LeaveOneOutReport, LeaveOneOutResult, leave_one_group_out, leave_one_symbol_out
from src.research.multiple_testing import (
    CorrectedResult,
    MultipleTestingReport,
    benjamini_hochberg_fdr,
    bonferroni_correction,
    holm_bonferroni_correction,
)
from src.research.overfitting_metrics import (
    DeflatedSharpeResult,
    EffectiveTrialsResult,
    PBOResult,
    deflated_sharpe_ratio,
    effective_number_of_trials,
    probability_of_backtest_overfitting,
)
from src.research.paper_trading_gate import GateDecision, ResearchGateStage, determine_gate_stage
from src.research.partition import (
    STAGES_ALLOWING_PARAMETER_SELECTION,
    PartitionAccessError,
    PartitionLifecycleStage,
    PartitionStore,
    ResearchDatasetPartition,
    assert_no_partition_overlap,
    assert_stage_allows_parameter_selection,
    determine_lifecycle_partitions,
    filter_rows_by_partition,
)
from src.research.pass_criteria import HoldoutPassCriteria, PassCriteriaEvaluation, PassCriterionResult, evaluate_pass_criteria
from src.research.placebo import (
    BootstrapCI,
    BootstrapReport,
    PlaceboTestResult,
    block_bootstrap_trade_statistics,
    bootstrap_trade_statistics,
    random_symbol_and_timing_placebo,
    randomized_entry_timing_placebo,
    stationary_bootstrap_trade_statistics,
)
from src.research.preregistration import (
    PreregistrationError,
    PreregistrationRecord,
    PreregistrationStore,
    preregistration_from_hypothesis,
    require_preregistered,
)
from src.research.purged_cv import PurgedCVConfig, PurgedFold, fold_has_leakage, generate_purged_folds
from src.research.quantile import CrossSectionalQuantileResult, QuantilePortfolioReport, cross_sectional_quantile_returns
from src.research.regime import bucket_trades_by_regime, ic_by_regime, label_bars_by_regime, regime_performance_report
from src.research.research_family import ResearchFamilySummary, prior_experiments_in_family, summarize_research_family
from src.research.research_gate import (
    CODE_COMPUTABLE_STAGES,
    FORWARD_ORDER,
    GateTransitionRecord,
    IllegalStageTransitionError,
    ResearchGateStore,
    ResearchLifecycleStage,
    StageRequiresHumanActionError,
    assert_code_may_set_stage,
    can_transition,
)
from src.research.research_matrix import ResearchMatrix, ResearchMatrixRow
from src.research.research_report import ResearchReport
from src.research.runner import filter_bars_by_date, run_research_backtest
from src.research.scorecard import SCORECARD_DIMENSIONS, DimensionVerdict, ResearchScorecard, ScorecardDimension, build_scorecard, classify_with_scorecard
from src.research.search_space import SearchSpaceSummary, compute_search_space_summary
from src.research.splits import DatasetSplit, SplitConfig, SplitConfigError, chronological_split
from src.research.stats_utils import normal_cdf, sharpe_ratio_from_returns, t_statistic, t_test_p_value, two_tailed_p_value_from_z
from src.research.strategies import MeanReversionStrategy, MomentumStrategy, VolatilityRegimeStrategy, VolumeConfirmedMomentumStrategy, campaign_hypotheses
from src.research.strategy import ResearchSignal, ResearchStrategy, ResearchStrategyBacktestAdapter, ResearchStrategySpec
from src.research.sweep import ParameterStabilityReport, SweepPoint, run_parameter_sweep, summarize_parameter_stability
from src.research.targets import future_return
from src.research.trade_distribution import TradeReturnDistribution, trade_return_distribution
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
    run_execution_robustness_extended,
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
    "run_execution_robustness_extended",
    "FrozenStrategyDefinition",
    "FrozenStrategyStore",
    "FrozenStrategyImmutabilityError",
    "build_mr002_frozen_definition",
    "build_strategy_from_frozen",
    "HoldoutPeriod",
    "HoldoutLeakageError",
    "determine_holdout_split",
    "assert_no_holdout_leakage",
    "HoldoutPassCriteria",
    "PassCriterionResult",
    "PassCriteriaEvaluation",
    "evaluate_pass_criteria",
    "ResearchGateStage",
    "GateDecision",
    "determine_gate_stage",
    "TradeReturnDistribution",
    "trade_return_distribution",
    "random_symbol_and_timing_placebo",
    # Phase 7 additions
    "STANDARD_DECAY_HORIZONS", "AlphaDecayReport", "HorizonPoint", "measure_alpha_decay",
    "BaselineComparisonReport", "compare_against_baselines",
    "CrossSectionalAlphaConfig", "CrossSectionalAlphaReport", "evaluate_cross_sectional_alpha",
    "CrossSectionalPlaceboResult", "irrelevant_feature_control", "random_feature_control", "shifted_signal_placebo", "shuffled_signal_placebo", "time_shuffled_target_placebo",
    "CostStressPoint", "CostStressReport", "EconomicSignificanceReport", "compute_capacity_proxy", "cost_multiplier_edge", "evaluate_economic_significance",
    "ExperimentDimensions", "compute_experiment_fingerprint", "fingerprints_differ", "which_dimensions_changed",
    "HypothesisFamily", "generate_hypotheses",
    "POTENTIAL_RESEARCH_REUSE", "HypothesisFingerprint", "ResearchReuseCheck", "bucket_threshold", "check_research_reuse", "similarity_score",
    "CorrectedResult", "MultipleTestingReport", "benjamini_hochberg_fdr", "bonferroni_correction", "holm_bonferroni_correction",
    "DeflatedSharpeResult", "EffectiveTrialsResult", "PBOResult", "deflated_sharpe_ratio", "effective_number_of_trials", "probability_of_backtest_overfitting",
    "STAGES_ALLOWING_PARAMETER_SELECTION", "PartitionAccessError", "PartitionLifecycleStage", "PartitionStore", "ResearchDatasetPartition",
    "assert_no_partition_overlap", "assert_stage_allows_parameter_selection", "determine_lifecycle_partitions", "filter_rows_by_partition",
    "block_bootstrap_trade_statistics", "stationary_bootstrap_trade_statistics",
    "PreregistrationError", "PreregistrationRecord", "PreregistrationStore", "preregistration_from_hypothesis", "require_preregistered",
    "PurgedCVConfig", "PurgedFold", "fold_has_leakage", "generate_purged_folds",
    "ic_by_regime",
    "ResearchFamilySummary", "prior_experiments_in_family", "summarize_research_family",
    "CODE_COMPUTABLE_STAGES", "FORWARD_ORDER", "GateTransitionRecord", "IllegalStageTransitionError", "ResearchGateStore",
    "ResearchLifecycleStage", "StageRequiresHumanActionError", "assert_code_may_set_stage", "can_transition",
    "SCORECARD_DIMENSIONS", "DimensionVerdict", "ResearchScorecard", "ScorecardDimension", "build_scorecard", "classify_with_scorecard",
    "normal_cdf", "sharpe_ratio_from_returns", "t_statistic", "t_test_p_value", "two_tailed_p_value_from_z",
]
