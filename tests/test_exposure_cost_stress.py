"""Phase 11, Parts 16, 27, 28: exposure cost/execution stress tests.
Proves the specific bug this module fixes: trade-level net_pnl (from
BacktestTrade, via src.research.validation's run_cost_sensitivity) can
badly mis-measure a continuously-rebalanced exposure strategy's TRUE P&L
(only the final, forced-close trade's isolated leg is captured), while
equity-curve-based total return (this module) captures it correctly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.backtesting import BacktestConfig, FixedPercentSlippage, FixedPercentSpreadModel, NextBarExecutionModel, PerShareCommission
from src.data.bar import Bar
from src.research.exposure_cost_stress import run_exposure_cost_stress, run_exposure_execution_stress
from src.research.exposure_risk_adapter import ExposureRiskAdapter
from src.research.exposure_sizing import EqualWeightExposureSizer
from src.research.exposure_strategy import PrecomputedExposureStrategy
from src.research.runner import run_research_backtest
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits


def _bars(n: int) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    for i in range(n):
        price += 1.0 if i % 3 else -0.5  # net upward drift
        bars.append(Bar(timestamp=start + timedelta(days=i), symbol="SPY", timeframe="day", open=price, high=price + 0.5, low=price - 0.5, close=price, volume=1000))
    return bars


def _risk_adapter() -> ExposureRiskAdapter:
    limits = RiskLimits(max_trades_per_day=25, max_daily_loss_usd=1_000_000.0, max_position_size_usd=1_000_000.0, cooldown_minutes_after_exit=0, stale_data_max_seconds=10**9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0, entry_cutoff_time=datetime(2024, 1, 1, 23, 59).time())
    return ExposureRiskAdapter(RiskManager(limits))


def _oscillating_exposure(bars: list[Bar]) -> dict:
    # oscillates the position size every 5 bars -> many partial buys/sells, never fully closing until forced-close
    return {b.timestamp: (0.9 if (i // 5) % 2 == 0 else 0.4) for i, b in enumerate(bars) if i % 5 == 0}


def test_ending_equity_based_pnl_differs_from_and_corrects_trade_level_pnl():
    bars = _bars(120)
    exposure = _oscillating_exposure(bars)
    strategy = PrecomputedExposureStrategy(strategy_id="TEST", exposure_by_symbol={"SPY": exposure}, universe=["SPY"], hypothesis_id="P11-VCE-TEST")
    config = BacktestConfig(symbols=("SPY",), timeframe="day", start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), data_version="v", feature_version="v", initial_capital_usd=100_000.0)
    models = dict(execution_model=NextBarExecutionModel(price_field="open", delay_bars=1), slippage_model=FixedPercentSlippage(0.0005),
                  cost_model=PerShareCommission(0.001), spread_model=FixedPercentSpreadModel(0.0005),
                  position_sizer=EqualWeightExposureSizer(n_symbols=1), risk_adapter=_risk_adapter())
    result = run_research_backtest(research_strategy=strategy, bars_by_symbol={"SPY": bars}, config=config, **models)

    trade_level_pnl = sum(t.net_pnl for t in result.trades)
    equity_curve_pnl = result.ending_equity - config.initial_capital_usd

    # With a net-upward-drifting price and >1 partial buy/sell along the way, the trade-level sum
    # (which only reflects the FINAL leg) should NOT equal the true equity-curve P&L.
    assert len(result.trades) == 1  # confirms the known limitation: only ONE consolidated trade is ever recorded
    assert abs(trade_level_pnl - equity_curve_pnl) > 1.0  # they meaningfully diverge


def test_cost_stress_uses_ending_equity_and_is_monotonically_non_increasing_in_cost():
    bars = _bars(120)
    exposure = _oscillating_exposure(bars)
    strategy = PrecomputedExposureStrategy(strategy_id="TEST", exposure_by_symbol={"SPY": exposure}, universe=["SPY"], hypothesis_id="P11-VCE-TEST")
    config = BacktestConfig(symbols=("SPY",), timeframe="day", start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), data_version="v", feature_version="v", initial_capital_usd=100_000.0)
    report = run_exposure_cost_stress(
        research_strategy=strategy, bars_by_symbol={"SPY": bars}, config=config,
        execution_model=NextBarExecutionModel(price_field="open", delay_bars=1), base_slippage_model=FixedPercentSlippage(0.0005),
        base_cost_model=PerShareCommission(0.001), spread_model=FixedPercentSpreadModel(0.0005),
        position_sizer=EqualWeightExposureSizer(n_symbols=1), risk_adapter=_risk_adapter(), multipliers=(1.0, 2.0, 3.0),
    )
    assert len(report.points) == 3
    equities = [p.ending_equity for p in report.points]
    assert equities[0] >= equities[1] >= equities[2]  # higher cost multiplier never helps


def test_execution_stress_reports_four_scenarios():
    bars = _bars(120)
    exposure = _oscillating_exposure(bars)
    strategy = PrecomputedExposureStrategy(strategy_id="TEST", exposure_by_symbol={"SPY": exposure}, universe=["SPY"], hypothesis_id="P11-VCE-TEST")
    config = BacktestConfig(symbols=("SPY",), timeframe="day", start=bars[0].timestamp.date(), end=bars[-1].timestamp.date(), data_version="v", feature_version="v", initial_capital_usd=100_000.0)
    report = run_exposure_execution_stress(
        research_strategy=strategy, bars_by_symbol={"SPY": bars}, config=config,
        base_execution_model=NextBarExecutionModel(price_field="open", delay_bars=1), base_slippage_model=FixedPercentSlippage(0.0005),
        base_cost_model=PerShareCommission(0.001), spread_model=FixedPercentSpreadModel(0.0005),
        position_sizer=EqualWeightExposureSizer(n_symbols=1), risk_adapter=_risk_adapter(),
    )
    assert len(report.points) == 4
    assert report.points[0].label.startswith("BASE")
