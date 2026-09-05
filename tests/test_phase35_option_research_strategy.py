"""Phase 35, Part D/E — the research adapter, end-to-end on synthetic
but structurally real data, through the REAL, unmodified backtesting
framework (src.research.runner.run_research_backtest)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from src.backtesting.execution_models import FixedPercentSlippage, FixedPercentSpreadModel, NextBarExecutionModel, PerShareCommission
from src.backtesting.interfaces import BacktestConfig
from src.backtesting.risk_adapter import BacktestRiskAdapter
from src.backtesting.sizing import FixedQuantitySizer
from src.options.phase35_option_research_strategy import MomentumBreakoutOptionResearchStrategy, build_bars_for_matched_trade
from src.options.phase35_option_trade_matching import MatchedOptionTrade
from src.research.runner import run_research_backtest
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits


def _generous_risk_adapter():
    return BacktestRiskAdapter(RiskManager(RiskLimits(
        max_trades_per_day=1000, max_daily_loss_usd=1e9, max_position_size_usd=1e9, cooldown_minutes_after_exit=0,
        stale_data_max_seconds=1e9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0,
        max_extended_move_pct=100.0, entry_cutoff_time=time(23, 59),
    )))


def _row(d, bid, ask):
    return {"timestamp": datetime(d.year, d.month, d.day, tzinfo=timezone.utc), "bid": bid, "ask": ask, "volume": 40}


def test_entry_price_matches_the_fill_bar_not_the_signal_bar():
    """Regression guard for the exact bug this phase found and fixed:
    entry_price must equal the SECOND bar's price (the real fill, per
    NextBarExecutionModel's delay_bars=1), never the first (signal) bar's
    price."""
    entry_row = _row(date(2020, 1, 10), 1.4, 1.6)
    mgmt = (_row(date(2020, 1, 11), 1.5, 1.7), _row(date(2020, 1, 20), 3.4, 3.6))
    for r, exp in ((entry_row, date(2020, 2, 10)), (mgmt[0], date(2020, 2, 10)), (mgmt[1], date(2020, 2, 10))):
        r["option_id"], r["expiration"], r["strike"] = "OPT1", exp, 100.0
    trade = MatchedOptionTrade("TEST", date(2020, 1, 10), "OPT1", date(2020, 2, 10), 100.0, entry_row, mgmt, 0)
    bars = build_bars_for_matched_trade(trade)
    underlying_series = [(date(2020, 1, 10), 100.0), (date(2020, 1, 11), 100.5), (date(2020, 1, 20), 110.0)]
    strategy = MomentumBreakoutOptionResearchStrategy({"OPT1": trade}, {"TEST": underlying_series}, universe=("TEST",))

    config = BacktestConfig(symbols=("OPT1",), timeframe="day", start=date(2020, 1, 1), end=date(2020, 2, 1), data_version="v1", feature_version="v1", initial_capital_usd=1_000_000.0)
    result = run_research_backtest(
        research_strategy=strategy, bars_by_symbol={"OPT1": bars}, config=config,
        execution_model=NextBarExecutionModel(price_field="open", delay_bars=1),
        slippage_model=FixedPercentSlippage(0.0), cost_model=PerShareCommission(0.0),
        spread_model=FixedPercentSpreadModel(0.0), position_sizer=FixedQuantitySizer(100), risk_adapter=_generous_risk_adapter(),
    )
    assert len(result.trades) == 1
    trade_result = result.trades[0]
    assert trade_result.entry_price == 1.6  # mid(1.5, 1.7) -- the FILL bar (Jan 11), not the signal bar (Jan 10, mid=1.5)
    assert trade_result.quantity == 100


def test_a_two_bar_trade_only_enters_no_exit_evaluated():
    """With only entry + 1 management row (the fill bar itself), there is
    no THIRD bar to evaluate an exit from -- the position is entered and
    then force-closed at period end, never fabricated an exit decision."""
    entry_row = _row(date(2020, 1, 10), 1.4, 1.6)
    entry_row.update(option_id="OPT1", expiration=date(2020, 2, 10), strike=100.0)
    mgmt = (dict(_row(date(2020, 1, 11), 1.5, 1.7), option_id="OPT1", expiration=date(2020, 2, 10), strike=100.0),)
    trade = MatchedOptionTrade("TEST", date(2020, 1, 10), "OPT1", date(2020, 2, 10), 100.0, entry_row, mgmt, 0)
    bars = build_bars_for_matched_trade(trade)
    assert len(bars) == 2
    strategy = MomentumBreakoutOptionResearchStrategy({"OPT1": trade}, {"TEST": []}, universe=("TEST",))
    config = BacktestConfig(symbols=("OPT1",), timeframe="day", start=date(2020, 1, 1), end=date(2020, 2, 1), data_version="v1", feature_version="v1", initial_capital_usd=1_000_000.0)
    result = run_research_backtest(
        research_strategy=strategy, bars_by_symbol={"OPT1": bars}, config=config,
        execution_model=NextBarExecutionModel(price_field="open", delay_bars=1),
        slippage_model=FixedPercentSlippage(0.0), cost_model=PerShareCommission(0.0),
        spread_model=FixedPercentSpreadModel(0.0), position_sizer=FixedQuantitySizer(100), risk_adapter=_generous_risk_adapter(),
    )
    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "end-of-period forced close"


def test_no_trade_when_bars_are_too_short_to_fill():
    """A single-bar 'trade' (entry_row only, no management rows) can never
    fill (delay_bars=1 needs a later bar) -- this must never crash or
    fabricate a trade."""
    entry_row = _row(date(2020, 1, 10), 1.4, 1.6)
    entry_row.update(option_id="OPT1", expiration=date(2020, 2, 10), strike=100.0)
    trade = MatchedOptionTrade("TEST", date(2020, 1, 10), "OPT1", date(2020, 2, 10), 100.0, entry_row, (), 0)
    bars = build_bars_for_matched_trade(trade)
    assert len(bars) == 1
    strategy = MomentumBreakoutOptionResearchStrategy({"OPT1": trade}, {"TEST": []}, universe=("TEST",))
    config = BacktestConfig(symbols=("OPT1",), timeframe="day", start=date(2020, 1, 1), end=date(2020, 2, 1), data_version="v1", feature_version="v1", initial_capital_usd=1_000_000.0)
    result = run_research_backtest(
        research_strategy=strategy, bars_by_symbol={"OPT1": bars}, config=config,
        execution_model=NextBarExecutionModel(price_field="open", delay_bars=1),
        slippage_model=FixedPercentSlippage(0.0), cost_model=PerShareCommission(0.0),
        spread_model=FixedPercentSpreadModel(0.0), position_sizer=FixedQuantitySizer(100), risk_adapter=_generous_risk_adapter(),
    )
    assert len(result.trades) == 0
