"""Tests for the parameter sweep framework (Phase 4, sections 6-7)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from src.backtesting import BacktestConfig, BacktestRiskAdapter, FixedPercentSpreadModel, FixedQuantitySizer, NextBarExecutionModel, PerShareCommission, ZeroSlippage
from src.data.bar import Bar
from src.research.sweep import run_parameter_sweep, summarize_parameter_stability
from src.research.strategies import MomentumStrategy
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits

UTC = timezone.utc


def _bars(n=100):
    import math

    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="TEST", timeframe="day", open=100 + 10 * math.sin(i / 6), high=112, low=88, close=100 + 10 * math.sin(i / 6), volume=10_000)
        for i in range(n)
    ]


def _risk_adapter():
    limits = RiskLimits(max_trades_per_day=100, max_daily_loss_usd=1e9, max_position_size_usd=1e9, cooldown_minutes_after_exit=0, stale_data_max_seconds=1e9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0, entry_cutoff_time=time(23, 59))
    return BacktestRiskAdapter(RiskManager(limits))


def _config(bars):
    return BacktestConfig(symbols=("TEST",), timeframe="day", start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), data_version="dv", feature_version="fv", initial_capital_usd=100_000.0)


def _factory(params):
    return MomentumStrategy(strategy_id="MOM-TEST", lookback=params["lookback"], universe=["TEST"], entry_threshold=params.get("entry_threshold", 0.02))


def _common(bars):
    return dict(
        bars_by_symbol={"TEST": bars}, config=_config(bars), execution_model=NextBarExecutionModel(),
        slippage_model=ZeroSlippage(), cost_model=PerShareCommission(0.0), spread_model=FixedPercentSpreadModel(0.0),
        position_sizer=FixedQuantitySizer(10), risk_adapter=_risk_adapter(),
    )


def test_sweep_runs_every_combination():
    bars = _bars()
    points = run_parameter_sweep(strategy_factory=_factory, param_grid={"lookback": [5, 10, 20]}, **_common(bars))
    assert len(points) == 3
    assert {p.parameters["lookback"] for p in points} == {5, 10, 20}


def test_sweep_with_two_dimensions_is_the_full_cartesian_product():
    bars = _bars()
    points = run_parameter_sweep(strategy_factory=_factory, param_grid={"lookback": [5, 10], "entry_threshold": [0.01, 0.02]}, **_common(bars))
    assert len(points) == 4


def test_sweep_rejects_empty_grid():
    bars = _bars()
    with pytest.raises(ValueError):
        run_parameter_sweep(strategy_factory=_factory, param_grid={}, **_common(bars))


def test_sweep_is_reproducible():
    bars = _bars()
    points_a = run_parameter_sweep(strategy_factory=_factory, param_grid={"lookback": [5, 10]}, **_common(bars))
    points_b = run_parameter_sweep(strategy_factory=_factory, param_grid={"lookback": [5, 10]}, **_common(bars))
    assert [p.metrics.trades.trade_count for p in points_a] == [p.metrics.trades.trade_count for p in points_b]
    assert [p.metrics.returns.total_return_pct for p in points_a] == [p.metrics.returns.total_return_pct for p in points_b]


def test_parameter_stability_reports_full_surface_not_just_the_winner():
    bars = _bars()
    points = run_parameter_sweep(strategy_factory=_factory, param_grid={"lookback": [5, 10, 20, 40]}, **_common(bars))
    stability = summarize_parameter_stability(points, metric_fn=lambda m: m.trades.expectancy, metric_name="expectancy")
    assert len(stability.values) == 4  # every combo's value preserved, not just the best


def test_stability_flags_a_strategy_that_only_works_at_one_combo():
    # Construct a stability report by hand: one huge outlier, the rest poor.
    from src.research.sweep import SweepPoint
    from src.backtesting.metrics import compute_performance_metrics

    fake_points = []
    for expectancy in [100.0, -5.0, -5.0, -5.0, -5.0]:
        # Build a PerformanceMetrics whose trades.expectancy equals the target value.
        from src.backtesting.journal import BacktestTrade

        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        trade = BacktestTrade(trade_id="t", backtest_id="b", strategy="s", symbol="TEST", entry_timestamp=t0, entry_price=1.0, exit_timestamp=t0 + timedelta(days=1), exit_price=1.0, quantity=1, gross_pnl=expectancy, fees=0.0, slippage=0.0, net_pnl=expectancy, holding_period_minutes=1.0, entry_reason="", exit_reason="", risk_decision="APPROVED")
        metrics = compute_performance_metrics(equity_curve=[], trades=[trade], starting_cash=1000.0)
        fake_points.append(SweepPoint(parameters={}, metrics=metrics))

    stability = summarize_parameter_stability(fake_points, metric_fn=lambda m: m.trades.expectancy, metric_name="expectancy", acceptable_threshold=0.0)
    assert stability.fraction_acceptable == pytest.approx(0.2)  # only 1 of 5 is positive
    assert stability.is_broadly_acceptable is False
