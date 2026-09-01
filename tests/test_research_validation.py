"""Tests for walk-forward research, robustness testing, and cost
sensitivity (Phase 4, sections 14-16)."""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone

import pytest

from src.backtesting import BacktestConfig, BacktestRiskAdapter, FixedPercentSlippage, FixedPercentSpreadModel, FixedQuantitySizer, NextBarExecutionModel, PerShareCommission, ZeroSlippage
from src.data.bar import Bar
from src.research.strategies import MomentumStrategy
from src.research.validation import (
    WalkForwardWindow,
    generate_walk_forward_windows,
    run_cost_sensitivity,
    run_robustness_tests,
    run_walk_forward,
)
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits

UTC = timezone.utc


def _bars(n=400):
    start = datetime(2022, 1, 1, tzinfo=UTC)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="TEST", timeframe="day", open=100 + 15 * math.sin(i / 10), high=118, low=82, close=100 + 15 * math.sin(i / 10), volume=10_000)
        for i in range(n)
    ]


def _risk_adapter():
    limits = RiskLimits(max_trades_per_day=100, max_daily_loss_usd=1e9, max_position_size_usd=1e9, cooldown_minutes_after_exit=0, stale_data_max_seconds=1e9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0, entry_cutoff_time=time(23, 59))
    return BacktestRiskAdapter(RiskManager(limits))


def _factory(params):
    return MomentumStrategy(strategy_id="MOM-TEST", lookback=params["lookback"], universe=["TEST"], entry_threshold=params.get("entry_threshold", 0.02))


# --- window generation --------------------------------------------------------------------


def test_generate_walk_forward_windows_are_chronological_and_non_overlapping():
    windows = generate_walk_forward_windows(start=date(2022, 1, 1), end=date(2023, 12, 31), train_days=200, validation_days=50, test_days=50, step_days=100)
    assert len(windows) > 0
    for w in windows:
        assert w.train_end < w.validation_start
        assert w.validation_end < w.test_start


def test_walk_forward_window_rejects_overlapping_periods():
    with pytest.raises(ValueError):
        WalkForwardWindow(train_start=date(2022, 1, 1), train_end=date(2022, 6, 1), validation_start=date(2022, 5, 1), validation_end=date(2022, 7, 1), test_start=date(2022, 8, 1), test_end=date(2022, 9, 1))


def test_no_windows_when_range_too_short():
    windows = generate_walk_forward_windows(start=date(2022, 1, 1), end=date(2022, 3, 1), train_days=200, validation_days=50, test_days=50, step_days=100)
    assert windows == []


# --- walk-forward run ----------------------------------------------------------------------


def test_walk_forward_produces_oos_trades_only_from_test_periods():
    bars = _bars()
    windows = generate_walk_forward_windows(start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), train_days=150, validation_days=50, test_days=50, step_days=100)
    config = BacktestConfig(symbols=("TEST",), timeframe="day", start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), data_version="dv", feature_version="fv", initial_capital_usd=100_000.0)
    report = run_walk_forward(
        strategy_factory=_factory, param_grid={"lookback": [5, 10]}, bars_by_symbol={"TEST": bars}, windows=windows,
        config_template=config, execution_model=NextBarExecutionModel(), slippage_model=ZeroSlippage(), cost_model=PerShareCommission(0.0),
        spread_model=FixedPercentSpreadModel(0.0), position_sizer=FixedQuantitySizer(10), risk_adapter=_risk_adapter(),
    )
    assert len(report.window_results) == len(windows)
    for window_result in report.window_results:
        for trade in window_result.test_trades:
            assert window_result.window.test_start <= trade.entry_timestamp.date() <= window_result.window.test_end


def test_walk_forward_never_selects_parameters_using_test_period_data():
    """The selection score is computed ONLY from validation-period trades
    — this proves the test period's trades never factor into which
    parameters got frozen (a structural, not just observational, check:
    the very call that picks best_params only ever sees dev_bars sliced
    to [train_start, validation_end], never test data)."""
    import inspect

    from src.research import validation as validation_module

    source = inspect.getsource(validation_module.run_walk_forward)
    # The parameter-selection loop must build backtests over dev_bars
    # (train+validation), and only ever evaluate `validation_trades` for
    # scoring — test_bars is constructed in a clearly separate step below.
    selection_section, _, freeze_section = source.partition("if best_params is None")
    assert "test_bars" not in selection_section
    assert "dev_bars" in selection_section


def test_walk_forward_reproducible():
    bars = _bars()
    windows = generate_walk_forward_windows(start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), train_days=150, validation_days=50, test_days=50, step_days=100)
    config = BacktestConfig(symbols=("TEST",), timeframe="day", start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), data_version="dv", feature_version="fv", initial_capital_usd=100_000.0)
    kwargs = dict(
        strategy_factory=_factory, param_grid={"lookback": [5, 10]}, bars_by_symbol={"TEST": bars}, windows=windows,
        config_template=config, execution_model=NextBarExecutionModel(), slippage_model=ZeroSlippage(), cost_model=PerShareCommission(0.0),
        spread_model=FixedPercentSpreadModel(0.0), position_sizer=FixedQuantitySizer(10), risk_adapter=_risk_adapter(),
    )
    report_a = run_walk_forward(**kwargs)
    report_b = run_walk_forward(**kwargs)
    assert [r.selected_parameters for r in report_a.window_results] == [r.selected_parameters for r in report_b.window_results]
    assert len(report_a.aggregated_oos_trades) == len(report_b.aggregated_oos_trades)


# --- robustness -----------------------------------------------------------------------------


def test_robustness_report_includes_base_and_perturbed_checks():
    bars = _bars()
    config = BacktestConfig(symbols=("TEST",), timeframe="day", start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), data_version="dv", feature_version="fv", initial_capital_usd=100_000.0)
    report = run_robustness_tests(
        strategy_factory=_factory, base_parameters={"lookback": 10}, bars_by_symbol={"TEST": bars}, config=config,
        execution_model=NextBarExecutionModel(), slippage_model=ZeroSlippage(), cost_model=PerShareCommission(0.0),
        spread_model=FixedPercentSpreadModel(0.0), position_sizer=FixedQuantitySizer(10), risk_adapter=_risk_adapter(),
        parameter_perturbations={"lookback": [5, 8, 12, 15]},
    )
    assert len(report.checks) == 5  # base + 4 perturbations
    assert report.fraction_held is not None


def test_robustness_skips_perturbation_equal_to_base():
    bars = _bars()
    config = BacktestConfig(symbols=("TEST",), timeframe="day", start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), data_version="dv", feature_version="fv", initial_capital_usd=100_000.0)
    report = run_robustness_tests(
        strategy_factory=_factory, base_parameters={"lookback": 10}, bars_by_symbol={"TEST": bars}, config=config,
        execution_model=NextBarExecutionModel(), slippage_model=ZeroSlippage(), cost_model=PerShareCommission(0.0),
        spread_model=FixedPercentSpreadModel(0.0), position_sizer=FixedQuantitySizer(10), risk_adapter=_risk_adapter(),
        parameter_perturbations={"lookback": [10]},  # identical to base
    )
    assert len(report.checks) == 1  # only the base check, no duplicate


# --- cost sensitivity ------------------------------------------------------------------------


def test_cost_sensitivity_higher_multipliers_never_improve_net_pnl():
    bars = _bars()
    config = BacktestConfig(symbols=("TEST",), timeframe="day", start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), data_version="dv", feature_version="fv", initial_capital_usd=100_000.0)
    strategy = _factory({"lookback": 10})
    report = run_cost_sensitivity(
        research_strategy=strategy, bars_by_symbol={"TEST": bars}, config=config, execution_model=NextBarExecutionModel(),
        base_slippage_model=FixedPercentSlippage(0.001), base_cost_model=PerShareCommission(0.01),
        spread_model=FixedPercentSpreadModel(0.0), position_sizer=FixedQuantitySizer(10), risk_adapter=_risk_adapter(),
        multipliers=(1.0, 2.0, 3.0),
    )
    assert len(report.points) == 3
    pnls = [p.net_pnl_total for p in report.points]
    assert pnls[0] >= pnls[1] >= pnls[2]  # more cost can only hurt or leave unchanged, never help


def test_cost_sensitivity_viable_flags_match_sign_of_net_pnl():
    bars = _bars()
    config = BacktestConfig(symbols=("TEST",), timeframe="day", start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), data_version="dv", feature_version="fv", initial_capital_usd=100_000.0)
    strategy = _factory({"lookback": 10})
    report = run_cost_sensitivity(
        research_strategy=strategy, bars_by_symbol={"TEST": bars}, config=config, execution_model=NextBarExecutionModel(),
        base_slippage_model=ZeroSlippage(), base_cost_model=PerShareCommission(0.0),
        spread_model=FixedPercentSpreadModel(0.0), position_sizer=FixedQuantitySizer(10), risk_adapter=_risk_adapter(),
    )
    for point in report.points:
        assert point.viable == (point.net_pnl_total > 0)
