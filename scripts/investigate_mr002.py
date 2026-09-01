#!/usr/bin/env python3
"""Phase 5, section 18: a dedicated investigation of MR-002 (20-day mean
reversion), the one Phase 4 hypothesis with positive OOS expectancy but
0% robustness. Nothing here modifies MR-002 to make it perform better —
every run uses the exact same strategy definition and methodology as
Phase 4. This script only gathers evidence to answer: is MR-002 showing a
potentially generalizable effect, or was the Phase 4 result sample-
specific? Read-only historical data only — no orders.
"""

from __future__ import annotations

import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtesting import (  # noqa: E402
    BacktestConfig,
    BacktestRiskAdapter,
    FixedPercentSlippage,
    FixedPercentSpreadModel,
    FixedQuantitySizer,
    NextBarExecutionModel,
    PerShareCommission,
)
from src.data import HistoricalDataStore, us_diversified_universe, us_small_cap_volatile_universe  # noqa: E402
from src.risk.manager import RiskManager  # noqa: E402
from src.risk.models import RiskLimits  # noqa: E402
from src.research import (  # noqa: E402
    MeanReversionStrategy,
    bootstrap_trade_statistics,
    bucket_trades_by_regime,
    by_sector,
    by_symbol,
    by_year,
    generate_walk_forward_windows,
    label_bars_by_regime,
    leave_one_symbol_out,
    randomized_entry_timing_placebo,
    regime_performance_report,
    run_cost_sensitivity,
    run_execution_robustness,
    run_research_backtest,
    run_walk_forward,
)

STARTING_CASH = 50_000.0
QUANTITY = 20
TRAIN_START, TEST_END = date(2021, 9, 1), date(2026, 8, 31)


def _risk_adapter() -> BacktestRiskAdapter:
    limits = RiskLimits(max_trades_per_day=10, max_daily_loss_usd=1_000_000.0, max_position_size_usd=20_000.0, cooldown_minutes_after_exit=0, stale_data_max_seconds=10**9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0, entry_cutoff_time=time(23, 59))
    return BacktestRiskAdapter(RiskManager(limits))


def _models():
    return dict(execution_model=NextBarExecutionModel(price_field="open", delay_bars=1), slippage_model=FixedPercentSlippage(0.001), cost_model=PerShareCommission(0.005), spread_model=FixedPercentSpreadModel(0.001), position_sizer=FixedQuantitySizer(QUANTITY), risk_adapter=_risk_adapter())


def factory(params, universe_symbols):
    return MeanReversionStrategy(strategy_id="MR-002", lookback=params.get("lookback", 20), universe=universe_symbols, entry_z=params.get("entry_z", -1.5))


def investigate(universe, store, label: str) -> None:
    print(f"\n{'#' * 90}\nMR-002 on {label} ({universe.name}, {len(universe.symbols)} symbols)\n{'#' * 90}")
    bars_by_symbol = {s: store.load(s, "day") for s in universe.symbols}
    bars_by_symbol = {s: b for s, b in bars_by_symbol.items() if b}
    usable = list(bars_by_symbol.keys())
    config = BacktestConfig(symbols=tuple(usable), timeframe="day", start=TRAIN_START, end=TEST_END, data_version="mr002-investigation-v1", feature_version="mr002-investigation-v1", initial_capital_usd=STARTING_CASH)
    strategy = factory({}, usable)

    is_result = run_research_backtest(research_strategy=strategy, bars_by_symbol=bars_by_symbol, config=config, **_models())
    print(f"IS: trades={len(is_result.trades)} net_pnl={sum(t.net_pnl for t in is_result.trades):.2f} expectancy=${is_result.metrics.trades.expectancy:.2f}")

    windows = generate_walk_forward_windows(start=TRAIN_START, end=TEST_END, train_days=500, validation_days=150, test_days=150, step_days=200)
    wf = run_walk_forward(strategy_factory=lambda p: factory(p, usable), param_grid={"lookback": [15, 20, 25]}, bars_by_symbol=bars_by_symbol, windows=windows, config_template=config, **_models())
    oos = wf.aggregated_oos_metrics
    print(f"OOS: trades={oos.trades.trade_count} expectancy=${oos.trades.expectancy:.2f} win_rate={oos.trades.win_rate:.2%} profit_factor={oos.trades.profit_factor}")

    print("\n-- Why was OOS expectancy positive? Symbol/sector/year/regime attribution on the IS run --")
    sym_breakdown = by_symbol(is_result.trades, starting_cash=STARTING_CASH)
    for sym, r in sorted(sym_breakdown.items(), key=lambda kv: kv[1].net_pnl_total, reverse=True):
        print(f"  {sym}: trades={r.trade_count} net_pnl={r.net_pnl_total:.2f} win_rate={r.metrics.trades.win_rate:.2%}")

    if len(universe.by_sector()) > 1:
        sec_breakdown = by_sector(is_result.trades, universe, starting_cash=STARTING_CASH)
        print("  By sector: " + "; ".join(f"{s}=${r.net_pnl_total:.0f}(n={r.trade_count})" for s, r in sec_breakdown.items()))

    year_breakdown = by_year(is_result.trades, starting_cash=STARTING_CASH)
    print("  By year: " + "; ".join(f"{y}=${r.net_pnl_total:.0f}(n={r.trade_count})" for y, r in year_breakdown.items()))

    regime_labels = {}
    for s, b in bars_by_symbol.items():
        regime_labels.update(label_bars_by_regime(b))
    regime_buckets = bucket_trades_by_regime(is_result.trades, regime_labels)
    regime_report = regime_performance_report(regime_buckets, starting_cash=STARTING_CASH)
    print("  By regime: " + "; ".join(f"{r}=${m.trades.expectancy:.2f}/trade(n={m.trades.trade_count})" for r, m in regime_report.items()))

    print("\n-- Does performance depend on specific symbols? (leave-one-out on IS trades) --")
    loo = leave_one_symbol_out(is_result.trades, starting_cash=STARTING_CASH)
    print(f"  max_expectancy_swing={loo.max_expectancy_swing}  sign_flips_without={loo.sign_flips_without}")

    print("\n-- Does performance survive higher costs? --")
    m = _models()
    cost_report = run_cost_sensitivity(
        research_strategy=strategy, bars_by_symbol=bars_by_symbol, config=config, execution_model=m["execution_model"],
        base_slippage_model=m["slippage_model"], base_cost_model=m["cost_model"], spread_model=m["spread_model"],
        position_sizer=m["position_sizer"], risk_adapter=m["risk_adapter"],
    )
    for p in cost_report.points:
        print(f"  {p.cost_multiplier}x: net_pnl_total={p.net_pnl_total:.2f} viable={p.viable}")

    print("\n-- Does performance survive execution stress? --")
    exec_report = run_execution_robustness(research_strategy=strategy, bars_by_symbol=bars_by_symbol, config=config, base_execution_model=_models()["execution_model"], base_slippage_model=_models()["slippage_model"], base_cost_model=_models()["cost_model"], spread_model=_models()["spread_model"], position_sizer=_models()["position_sizer"], risk_adapter=_models()["risk_adapter"])
    for p in exec_report.points:
        print(f"  {p.scenario}: net_pnl_total={p.net_pnl_total:.2f} viable={p.viable}")

    print("\n-- Does performance survive small parameter changes? (narrow neighborhood around lookback=20) --")
    from src.research.sweep import run_parameter_sweep, summarize_parameter_stability

    narrow_grid = {"lookback": [15, 18, 20, 22, 25]}
    narrow_points = run_parameter_sweep(strategy_factory=lambda p: factory(p, usable), param_grid=narrow_grid, bars_by_symbol=bars_by_symbol, config=config, **_models())
    for point in narrow_points:
        print(f"  lookback={point.parameters['lookback']}: trades={point.metrics.trades.trade_count} expectancy=${point.metrics.trades.expectancy:.2f}")
    stability = summarize_parameter_stability(narrow_points, metric_fn=lambda m: m.trades.expectancy, metric_name="expectancy")
    print(f"  fraction_acceptable={stability.fraction_acceptable}  broadly_acceptable={stability.is_broadly_acceptable}")

    print("\n-- Placebo / bootstrap on OOS trades --")
    placebo = randomized_entry_timing_placebo(observed_trades=wf.aggregated_oos_trades, bars_by_symbol=bars_by_symbol, holding_period_bars=strategy.spec.holding_period_bars, quantity=QUANTITY, n_trials=200, seed=42)
    print(f"  placebo fraction_as_extreme_or_better={placebo.fraction_as_extreme_or_better}")
    bootstrap = bootstrap_trade_statistics(list(wf.aggregated_oos_trades), n_resamples=1000, seed=42)
    print("  " + bootstrap.render().replace("\n", "\n  "))


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    investigate(us_small_cap_volatile_universe(), store, "ORIGINAL Phase 4 universe")
    investigate(us_diversified_universe(), store, "EXPANDED Phase 5 universe")


if __name__ == "__main__":
    main()
