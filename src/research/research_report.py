"""The structured research report (Phase 4, section 19) — assembles
everything else in this package into the one human-readable artifact a
completed experiment produces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from src.backtesting.journal import BacktestTrade
from src.backtesting.metrics import PerformanceMetrics
from src.research.classification import ClassificationResult
from src.research.hypothesis import Hypothesis
from src.research.sweep import ParameterStabilityReport
from src.research.validation import CostSensitivityReport, WalkForwardReport


@dataclass(frozen=True)
class ResearchReport:
    experiment_id: str
    strategy_name: str
    hypothesis: Hypothesis
    universe: tuple[str, ...]
    timeframe: str
    data_version: str
    feature_version: str
    parameters: Mapping[str, Any]
    train_period: tuple[str, str] | None
    validation_period: tuple[str, str] | None
    test_period: tuple[str, str] | None
    transaction_costs: str
    slippage: str
    in_sample_metrics: PerformanceMetrics
    benchmark_return_pct: float | None
    walk_forward: WalkForwardReport | None
    parameter_stability: ParameterStabilityReport | None
    cost_sensitivity: CostSensitivityReport | None
    regime_summary: Mapping[str, PerformanceMetrics] = field(default_factory=dict)
    classification: ClassificationResult | None = None
    conclusion: str = ""

    def render(self) -> str:
        m = self.in_sample_metrics
        oos = self.walk_forward.aggregated_oos_metrics if self.walk_forward else None
        lines = [
            f"EXPERIMENT ID: {self.experiment_id}",
            f"Strategy: {self.strategy_name}",
            f"Hypothesis: {self.hypothesis.hypothesis_id} — {self.hypothesis.name}: {self.hypothesis.description}",
            f"Universe: {', '.join(self.universe)}",
            f"Timeframe: {self.timeframe}",
            f"Data version: {self.data_version}",
            f"Feature version: {self.feature_version}",
            f"Parameters: {dict(self.parameters)}",
            f"Training period: {self.train_period}",
            f"Validation period: {self.validation_period}",
            f"Test period: {self.test_period}",
            f"Transaction costs: {self.transaction_costs}",
            f"Slippage: {self.slippage}",
            "",
            f"Number of trades (in-sample): {m.trades.trade_count}",
            f"Gross return: {m.returns.total_return_pct:.4f}%",
            f"Net return (after costs/slippage): {m.returns.total_return_pct:.4f}%  (see trade-level gross vs net for the cost breakdown)",
            f"CAGR: {m.returns.cagr_pct}",
            f"Volatility (annualized): {m.returns.volatility_annualized_pct}",
            f"Sharpe: {m.returns.sharpe_ratio}",
            f"Sortino: {m.returns.sortino_ratio}",
            f"Maximum drawdown: {m.drawdown.max_drawdown_pct:.4f}%",
            f"Profit factor: {m.trades.profit_factor}",
            f"Expectancy: ${m.trades.expectancy:.2f}/trade",
            f"Benchmark return: {self.benchmark_return_pct}",
            "",
        ]
        if oos is not None:
            lines += [
                "OUT-OF-SAMPLE (walk-forward aggregated):",
                f"  windows: {len(self.walk_forward.window_results)}",
                f"  OOS trade count: {oos.trades.trade_count}",
                f"  OOS win rate: {oos.trades.win_rate:.2%}" if oos.trades.trade_count else "  OOS win rate: n/a",
                f"  OOS expectancy: ${oos.trades.expectancy:.2f}/trade",
                f"  OOS profit factor: {oos.trades.profit_factor}",
                f"  distinct parameter combos selected across windows: {self.walk_forward.distinct_parameter_selections}",
                "",
            ]
        if self.parameter_stability is not None:
            ps = self.parameter_stability
            lines += [
                f"PARAMETER STABILITY ({ps.metric_name}):",
                f"  mean={ps.mean_value} stdev={ps.stdev_value} min={ps.min_value} max={ps.max_value}",
                f"  fraction of grid acceptable: {ps.fraction_acceptable}  broadly acceptable: {ps.is_broadly_acceptable}",
                "",
            ]
        if self.cost_sensitivity is not None:
            cs = self.cost_sensitivity
            lines += [
                "COST SENSITIVITY:",
                f"  viable at 1x costs: {cs.viable_at_base}",
                f"  viable at 2x costs: {cs.viable_at_2x}",
                f"  viable at 3x costs: {cs.viable_at_3x}",
                "",
            ]
        if self.regime_summary:
            lines.append("REGIME RESULTS:")
            for regime, rm in self.regime_summary.items():
                lines.append(f"  {regime}: trades={rm.trades.trade_count} win_rate={rm.trades.win_rate:.2%} expectancy=${rm.trades.expectancy:.2f} profit_factor={rm.trades.profit_factor}")
            lines.append("")
        if self.classification is not None:
            lines.append(f"CLASSIFICATION: {self.classification.classification.value}")
            for reason in self.classification.reasons:
                lines.append(f"  - {reason}")
            lines.append("")
        lines.append(f"CONCLUSION: {self.conclusion}")
        return "\n".join(lines)
