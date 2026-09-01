"""Tests for the PROMISING/INCONCLUSIVE/FRAGILE/REJECTED classification
logic (Phase 4, section 17)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.backtesting.journal import BacktestTrade
from src.backtesting.metrics import compute_performance_metrics
from src.research.classification import MIN_OOS_TRADES_FOR_A_VERDICT, StrategyClassification, classify_strategy
from src.research.sweep import ParameterStabilityReport
from src.research.validation import CostSensitivityPoint, CostSensitivityReport, RobustnessCheck, RobustnessReport

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _trades(net_pnls: list[float]) -> list[BacktestTrade]:
    return [
        BacktestTrade(
            trade_id=f"T{i}", backtest_id="B", strategy="s", symbol="TEST", entry_timestamp=T0 + timedelta(days=i),
            entry_price=100.0, exit_timestamp=T0 + timedelta(days=i, hours=1), exit_price=100.0 + pnl / 10, quantity=10,
            gross_pnl=pnl, fees=0.0, slippage=0.0, net_pnl=pnl, holding_period_minutes=60.0, entry_reason="", exit_reason="", risk_decision="APPROVED",
        )
        for i, pnl in enumerate(net_pnls)
    ]


def _metrics(net_pnls: list[float]):
    return compute_performance_metrics(equity_curve=[], trades=_trades(net_pnls), starting_cash=10_000.0)


def test_too_few_oos_trades_is_inconclusive_regardless_of_result():
    metrics = _metrics([100.0] * (MIN_OOS_TRADES_FOR_A_VERDICT - 1))  # all winners, but too few
    result = classify_strategy(oos_metrics=metrics)
    assert result.classification == StrategyClassification.INCONCLUSIVE
    assert "insufficient" in result.reasons[0].lower()


def test_negative_oos_expectancy_is_rejected():
    metrics = _metrics([-10.0] * MIN_OOS_TRADES_FOR_A_VERDICT)
    result = classify_strategy(oos_metrics=metrics)
    assert result.classification == StrategyClassification.REJECTED


def test_positive_oos_no_other_signals_is_promising():
    metrics = _metrics([10.0] * MIN_OOS_TRADES_FOR_A_VERDICT)
    result = classify_strategy(oos_metrics=metrics)
    assert result.classification == StrategyClassification.PROMISING


def test_fails_at_2x_costs_is_fragile_not_promising():
    metrics = _metrics([10.0] * MIN_OOS_TRADES_FOR_A_VERDICT)
    cost_report = CostSensitivityReport(
        points=(CostSensitivityPoint(1.0, 1.0, 20, 200.0, True), CostSensitivityPoint(2.0, 2.0, 20, -50.0, False)),
        viable_at_base=True, viable_at_2x=False, viable_at_3x=None,
    )
    result = classify_strategy(oos_metrics=metrics, cost_sensitivity=cost_report)
    assert result.classification == StrategyClassification.FRAGILE
    assert any("2x" in r for r in result.reasons)


def test_large_in_sample_vs_oos_gap_is_fragile():
    is_metrics = _metrics([100.0] * MIN_OOS_TRADES_FOR_A_VERDICT)  # huge IS expectancy
    oos_metrics = _metrics([1.0] * MIN_OOS_TRADES_FOR_A_VERDICT)  # tiny OOS expectancy
    result = classify_strategy(oos_metrics=oos_metrics, in_sample_metrics=is_metrics)
    assert result.classification == StrategyClassification.FRAGILE


def test_unstable_parameters_is_fragile():
    metrics = _metrics([10.0] * MIN_OOS_TRADES_FOR_A_VERDICT)
    stability = ParameterStabilityReport(metric_name="expectancy", values=(10.0, -5.0, -5.0, -5.0), mean_value=-1.25, stdev_value=7.5, min_value=-5.0, max_value=10.0, fraction_acceptable=0.25, is_broadly_acceptable=False)
    result = classify_strategy(oos_metrics=metrics, parameter_stability=stability)
    assert result.classification == StrategyClassification.FRAGILE


def test_low_robustness_hold_rate_is_fragile():
    metrics = _metrics([10.0] * MIN_OOS_TRADES_FOR_A_VERDICT)
    robustness = RobustnessReport(checks=(
        RobustnessCheck("parameter", "base", "metric", 10.0, 10.0, True),
        RobustnessCheck("parameter", "p=5", "metric", 10.0, -5.0, False),
        RobustnessCheck("parameter", "p=15", "metric", 10.0, -5.0, False),
    ))
    result = classify_strategy(oos_metrics=metrics, robustness=robustness)
    assert result.classification == StrategyClassification.FRAGILE


def test_classification_never_a_bare_score_always_has_reasons():
    metrics = _metrics([10.0] * MIN_OOS_TRADES_FOR_A_VERDICT)
    result = classify_strategy(oos_metrics=metrics)
    assert len(result.reasons) > 0
