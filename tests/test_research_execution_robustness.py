"""Tests for execution robustness (Phase 5, section 13)."""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone

from src.backtesting import BacktestConfig, BacktestRiskAdapter, FixedPercentSlippage, FixedPercentSpreadModel, FixedQuantitySizer, NextBarExecutionModel, PerShareCommission
from src.data.bar import Bar
from src.research.strategies import MomentumStrategy
from src.research.validation import run_execution_robustness
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits

UTC = timezone.utc


def _bars(n=200):
    start = datetime(2022, 1, 1, tzinfo=UTC)
    return [
        Bar(timestamp=start + timedelta(days=i), symbol="TEST", timeframe="day", open=100 + 12 * math.sin(i / 8), high=115, low=85, close=100 + 12 * math.sin(i / 8), volume=10_000)
        for i in range(n)
    ]


def _risk_adapter():
    limits = RiskLimits(max_trades_per_day=100, max_daily_loss_usd=1e9, max_position_size_usd=1e9, cooldown_minutes_after_exit=0, stale_data_max_seconds=1e9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0, entry_cutoff_time=time(23, 59))
    return BacktestRiskAdapter(RiskManager(limits))


def test_execution_robustness_covers_the_four_required_scenarios():
    bars = _bars()
    config = BacktestConfig(symbols=("TEST",), timeframe="day", start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), data_version="dv", feature_version="fv", initial_capital_usd=100_000.0)
    strategy = MomentumStrategy(strategy_id="MOM-TEST", lookback=10, universe=["TEST"], entry_threshold=0.02)
    report = run_execution_robustness(
        research_strategy=strategy, bars_by_symbol={"TEST": bars}, config=config,
        base_execution_model=NextBarExecutionModel(), base_slippage_model=FixedPercentSlippage(0.001),
        base_cost_model=PerShareCommission(0.005), spread_model=FixedPercentSpreadModel(0.0),
        position_sizer=FixedQuantitySizer(10), risk_adapter=_risk_adapter(),
    )
    assert len(report.points) == 4
    labels = [p.scenario for p in report.points]
    assert any("base" in l for l in labels)
    assert any("delay" in l for l in labels)
    assert any("slippage" in l for l in labels)
    assert any("cost" in l for l in labels)


def test_execution_robustness_fraction_viable_is_bounded():
    bars = _bars()
    config = BacktestConfig(symbols=("TEST",), timeframe="day", start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), data_version="dv", feature_version="fv", initial_capital_usd=100_000.0)
    strategy = MomentumStrategy(strategy_id="MOM-TEST", lookback=10, universe=["TEST"], entry_threshold=0.02)
    report = run_execution_robustness(
        research_strategy=strategy, bars_by_symbol={"TEST": bars}, config=config,
        base_execution_model=NextBarExecutionModel(), base_slippage_model=FixedPercentSlippage(0.001),
        base_cost_model=PerShareCommission(0.005), spread_model=FixedPercentSpreadModel(0.0),
        position_sizer=FixedQuantitySizer(10), risk_adapter=_risk_adapter(),
    )
    assert 0.0 <= report.fraction_viable <= 1.0


def test_execution_robustness_extra_delay_uses_a_later_execution_model():
    bars = _bars()
    config = BacktestConfig(symbols=("TEST",), timeframe="day", start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), data_version="dv", feature_version="fv", initial_capital_usd=100_000.0)
    strategy = MomentumStrategy(strategy_id="MOM-TEST", lookback=10, universe=["TEST"], entry_threshold=0.02)
    report = run_execution_robustness(
        research_strategy=strategy, bars_by_symbol={"TEST": bars}, config=config,
        base_execution_model=NextBarExecutionModel(delay_bars=1), base_slippage_model=FixedPercentSlippage(0.001),
        base_cost_model=PerShareCommission(0.005), spread_model=FixedPercentSpreadModel(0.0),
        position_sizer=FixedQuantitySizer(10), risk_adapter=_risk_adapter(),
    )
    base_point = next(p for p in report.points if "base" in p.scenario)
    delay_point = next(p for p in report.points if "delay" in p.scenario)
    # Different execution timing should generally produce a different
    # trade sequence/price path — not asserting direction, just that the
    # stress scenario actually changed something rather than being a no-op.
    assert base_point.trade_count != delay_point.trade_count or base_point.net_pnl_total != delay_point.net_pnl_total
