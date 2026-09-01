#!/usr/bin/env python3
"""Completes the Phase 5 campaign for VOL-001 and VOLM-001 only (MOM-001,
MOM-002, MR-001, MR-002 already completed and recorded). Uses a
single-value walk-forward grid (matching the base parameter, same as the
IS run) rather than re-sweeping the full param grid inside every window —
this keeps walk-forward tractable while still producing a genuine,
unmodified-methodology OOS result. The wide parameter-neighborhood sweep
(the actual parameter-robustness check) is UNCHANGED and still covers the
full grid.
"""

from __future__ import annotations

import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtesting import BacktestConfig, BacktestRiskAdapter, FixedPercentSlippage, FixedPercentSpreadModel, FixedQuantitySizer, NextBarExecutionModel, PerShareCommission  # noqa: E402
from src.data import HistoricalDataStore, run_universe_quality_report, us_diversified_universe  # noqa: E402
from src.risk.manager import RiskManager  # noqa: E402
from src.risk.models import RiskLimits  # noqa: E402
from src.research import (  # noqa: E402
    ExperimentStore,
    VolatilityRegimeStrategy,
    VolumeConfirmedMomentumStrategy,
    bootstrap_trade_statistics,
    bucket_trades_by_regime,
    by_sector,
    by_year,
    classify_strategy,
    concentration_summary,
    generate_walk_forward_windows,
    label_bars_by_regime,
    leave_one_symbol_out,
    randomized_entry_timing_placebo,
    regime_performance_report,
    run_cost_sensitivity,
    run_execution_robustness,
    run_research_backtest,
    run_walk_forward,
    summarize_parameter_stability,
)
from src.research.sweep import run_parameter_sweep

STARTING_CASH = 100_000.0
QUANTITY = 20
TRAIN_START, TEST_END = date(2021, 9, 1), date(2026, 8, 31)


def _risk_adapter() -> BacktestRiskAdapter:
    limits = RiskLimits(max_trades_per_day=10, max_daily_loss_usd=1_000_000.0, max_position_size_usd=20_000.0, cooldown_minutes_after_exit=0, stale_data_max_seconds=10**9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0, entry_cutoff_time=time(23, 59))
    return BacktestRiskAdapter(RiskManager(limits))


def _models():
    return dict(execution_model=NextBarExecutionModel(price_field="open", delay_bars=1), slippage_model=FixedPercentSlippage(0.001), cost_model=PerShareCommission(0.005), spread_model=FixedPercentSpreadModel(0.001), position_sizer=FixedQuantitySizer(QUANTITY), risk_adapter=_risk_adapter())


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    universe = us_diversified_universe()
    quality = run_universe_quality_report(store, universe, "day", min_bars_required=100)
    usable = [s.symbol for s in quality if s.available]
    bars_by_symbol = {s: store.load(s, "day") for s in usable}
    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))
    full_config = BacktestConfig(symbols=tuple(usable), timeframe="day", start=TRAIN_START, end=TEST_END, data_version="phase5-campaign-v1", feature_version="phase5-campaign-v1", initial_capital_usd=STARTING_CASH)
    windows = generate_walk_forward_windows(start=TRAIN_START, end=TEST_END, train_days=500, validation_days=150, test_days=150, step_days=200)

    regime_labels = {}
    for s in usable:
        regime_labels.update(label_bars_by_regime(bars_by_symbol[s]))

    specs = [
        ("VOL-001", "volatility_regime", lambda p: VolatilityRegimeStrategy(strategy_id="VOL-001", universe=usable, low_vol_bucket_max=p.get("low_vol_bucket_max", 1)), {"low_vol_bucket_max": [0, 1, 2, 3, 4]}, {"low_vol_bucket_max": [1]}),
        ("VOLM-001", "volume_confirmed_momentum", lambda p: VolumeConfirmedMomentumStrategy(strategy_id="VOLM-001", universe=usable, min_relative_volume=p.get("min_relative_volume", 1.2)), {"min_relative_volume": [0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0]}, {"min_relative_volume": [1.2]}),
    ]

    for hyp_id, family, factory, wide_grid, wf_grid in specs:
        print(f"{'=' * 90}\n{hyp_id} ({family})\n{'=' * 90}", flush=True)
        base_params = {k: v[len(v) // 2] for k, v in wide_grid.items()}
        base_strategy = factory(base_params)

        is_result = run_research_backtest(research_strategy=base_strategy, bars_by_symbol=bars_by_symbol, config=full_config, **_models())
        print(f"IS trades={len(is_result.trades)} net_pnl={sum(t.net_pnl for t in is_result.trades):.2f} sharpe={is_result.metrics.returns.sharpe_ratio}", flush=True)

        wide_points = run_parameter_sweep(strategy_factory=factory, param_grid=wide_grid, bars_by_symbol=bars_by_symbol, config=full_config, **_models())
        wide_stability = summarize_parameter_stability(wide_points, metric_fn=lambda m: m.trades.expectancy, metric_name="expectancy")
        print(f"Wide sweep values={[round(v, 2) if v is not None else None for v in wide_stability.values]} fraction_acceptable={wide_stability.fraction_acceptable}", flush=True)

        wf_report = run_walk_forward(strategy_factory=factory, param_grid=wf_grid, bars_by_symbol=bars_by_symbol, windows=windows, config_template=full_config, **_models())
        oos = wf_report.aggregated_oos_metrics
        print(f"OOS trades={oos.trades.trade_count} win_rate={oos.trades.win_rate:.2%} expectancy=${oos.trades.expectancy:.2f} profit_factor={oos.trades.profit_factor}", flush=True)

        cost_report = run_cost_sensitivity(research_strategy=base_strategy, bars_by_symbol=bars_by_symbol, config=full_config, execution_model=_models()["execution_model"], base_slippage_model=_models()["slippage_model"], base_cost_model=_models()["cost_model"], spread_model=_models()["spread_model"], position_sizer=_models()["position_sizer"], risk_adapter=_models()["risk_adapter"])
        print(f"Cost sensitivity: 1x={cost_report.viable_at_base} 2x={cost_report.viable_at_2x} 3x={cost_report.viable_at_3x}", flush=True)

        exec_report = run_execution_robustness(research_strategy=base_strategy, bars_by_symbol=bars_by_symbol, config=full_config, base_execution_model=_models()["execution_model"], base_slippage_model=_models()["slippage_model"], base_cost_model=_models()["cost_model"], spread_model=_models()["spread_model"], position_sizer=_models()["position_sizer"], risk_adapter=_models()["risk_adapter"])
        print(f"Execution robustness fraction_viable={exec_report.fraction_viable}", flush=True)

        loo = leave_one_symbol_out(is_result.trades, starting_cash=STARTING_CASH)
        print(f"Leave-one-out max_swing={loo.max_expectancy_swing} sign_flips={loo.sign_flips_without}", flush=True)

        sector_breakdown = by_sector(is_result.trades, universe, starting_cash=STARTING_CASH)
        print("By sector: " + "; ".join(f"{s}=${r.net_pnl_total:.0f}" for s, r in sector_breakdown.items()), flush=True)
        year_breakdown = by_year(is_result.trades, starting_cash=STARTING_CASH)
        print("By year: " + "; ".join(f"{y}=${r.net_pnl_total:.0f}" for y, r in year_breakdown.items()), flush=True)
        regime_buckets = bucket_trades_by_regime(is_result.trades, regime_labels)
        regime_report = regime_performance_report(regime_buckets, starting_cash=STARTING_CASH)
        print("By regime: " + "; ".join(f"{r}=${m.trades.expectancy:.2f}/trade" for r, m in regime_report.items()), flush=True)
        conc = concentration_summary(is_result.trades)
        print(f"Top contributors: {sorted(conc.items(), key=lambda kv: abs(kv[1]), reverse=True)[:3]}", flush=True)

        placebo = randomized_entry_timing_placebo(observed_trades=wf_report.aggregated_oos_trades, bars_by_symbol=bars_by_symbol, holding_period_bars=base_strategy.spec.holding_period_bars, quantity=QUANTITY, n_trials=100, seed=42)
        print(f"Placebo fraction_as_extreme_or_better={placebo.fraction_as_extreme_or_better}", flush=True)
        bootstrap = bootstrap_trade_statistics(list(wf_report.aggregated_oos_trades), n_resamples=1000, seed=42)
        print(bootstrap.render(), flush=True)

        classification = classify_strategy(oos_metrics=oos, in_sample_metrics=is_result.metrics, parameter_stability=wide_stability, cost_sensitivity=cost_report, robustness=None)
        print(f"\nCLASSIFICATION: {classification.classification.value}", flush=True)
        for r in classification.reasons:
            print(f"  - {r}", flush=True)

        exp_store.record(
            data_version=full_config.data_version, feature_version=full_config.feature_version, symbols=usable, timeframe="day",
            strategy_version=base_strategy.spec.version, prediction_horizon=base_strategy.spec.prediction_horizon_bars,
            train_period=(TRAIN_START.isoformat(), TEST_END.isoformat()), parameters=base_params,
            metrics={"is_trade_count": len(is_result.trades), "is_sharpe": is_result.metrics.returns.sharpe_ratio, "is_expectancy": is_result.metrics.trades.expectancy},
            strategy_family=family, classification=classification.classification.value,
            oos_metrics={"trade_count": oos.trades.trade_count, "win_rate": oos.trades.win_rate, "expectancy": oos.trades.expectancy, "profit_factor": oos.trades.profit_factor},
            cost_sensitivity={"points": [{"cost_multiplier": p.cost_multiplier, "viable": p.viable, "net_pnl_total": p.net_pnl_total} for p in cost_report.points]},
            tags=("phase5-campaign", "US_DIVERSIFIED"), notes="; ".join(classification.reasons),
            hypothesis_id=hyp_id, universe_name=universe.name,
        )
        print(flush=True)

    from src.research import compute_search_space_summary
    print(compute_search_space_summary(exp_store.load_all()).render(), flush=True)


if __name__ == "__main__":
    main()
