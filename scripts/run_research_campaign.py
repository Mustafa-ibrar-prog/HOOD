#!/usr/bin/env python3
"""Phase 4's first research campaign (section 24): 6 hypotheses tested
against the real 5-symbol daily dataset fetched via the read-only HOOD
connection and stored under logs/research_data/ (see
src.data.store.HistoricalDataStore). Nothing here places a live order —
this script only reads pre-stored historical bars and runs backtests.

Usage: python3 scripts/run_research_campaign.py
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
from src.data.store import HistoricalDataStore  # noqa: E402
from src.risk.manager import RiskManager  # noqa: E402
from src.risk.models import RiskLimits  # noqa: E402
from src.research import (  # noqa: E402
    ExperimentStore,
    HypothesisRegistry,
    MeanReversionStrategy,
    MomentumStrategy,
    VolatilityRegimeStrategy,
    VolumeConfirmedMomentumStrategy,
    bucket_trades_by_regime,
    campaign_hypotheses,
    classify_strategy,
    generate_walk_forward_windows,
    label_bars_by_regime,
    regime_performance_report,
    run_cost_sensitivity,
    run_research_backtest,
    run_robustness_tests,
    run_walk_forward,
    summarize_parameter_stability,
)
from src.research.sweep import run_parameter_sweep

UNIVERSE = ["NIO", "MARA", "SOFI", "SOUN", "PLUG"]
STARTING_CASH = 50_000.0
QUANTITY = 20

TRAIN_START, TRAIN_END = date(2021, 9, 1), date(2023, 8, 31)
VALIDATION_START, VALIDATION_END = date(2023, 9, 1), date(2024, 8, 31)
TEST_START, TEST_END = date(2024, 9, 1), date(2026, 8, 31)


def _risk_adapter() -> BacktestRiskAdapter:
    limits = RiskLimits(
        max_trades_per_day=10, max_daily_loss_usd=1_000_000.0, max_position_size_usd=20_000.0,
        cooldown_minutes_after_exit=0, stale_data_max_seconds=10**9, max_spread_pct=1.0,
        min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0,
        entry_cutoff_time=time(23, 59),
    )
    return BacktestRiskAdapter(RiskManager(limits))


def _models():
    return dict(
        execution_model=NextBarExecutionModel(price_field="open", delay_bars=1),
        slippage_model=FixedPercentSlippage(0.001),  # 10 bps
        cost_model=PerShareCommission(0.005),  # half a cent/share
        spread_model=FixedPercentSpreadModel(0.001),  # 10 bps modeled spread
        position_sizer=FixedQuantitySizer(QUANTITY),
        risk_adapter=_risk_adapter(),
    )


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    bars_by_symbol = {s: store.load(s, "day") for s in UNIVERSE}
    for s, bars in bars_by_symbol.items():
        print(f"{s}: {len(bars)} bars, {bars[0].timestamp.date()} -> {bars[-1].timestamp.date()}")

    hyp_registry = HypothesisRegistry(Path("logs/research_data/hypotheses.jsonl"))
    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))
    for h in campaign_hypotheses(UNIVERSE):
        if hyp_registry.get(h.hypothesis_id) is None:
            hyp_registry.register(h)

    full_config = BacktestConfig(
        symbols=tuple(UNIVERSE), timeframe="day", start=TRAIN_START, end=TEST_END,
        data_version="phase4-campaign-v1", feature_version="phase4-campaign-v1",
        initial_capital_usd=STARTING_CASH, benchmark_symbol=None,
    )

    def mom_factory(strategy_id, default_lookback, default_threshold):
        return lambda p: MomentumStrategy(strategy_id=strategy_id, lookback=p.get("lookback", default_lookback), universe=UNIVERSE, entry_threshold=p.get("entry_threshold", default_threshold))

    def mr_factory(strategy_id, default_lookback, default_z):
        return lambda p: MeanReversionStrategy(strategy_id=strategy_id, lookback=p.get("lookback", default_lookback), universe=UNIVERSE, entry_z=p.get("entry_z", default_z))

    specs = [
        ("MOM-001", "momentum", mom_factory("MOM-001", 5, 0.02), {"entry_threshold": [0.01, 0.02, 0.03]}, {"lookback": [3, 5, 8]}),
        ("MOM-002", "momentum", mom_factory("MOM-002", 20, 0.04), {"entry_threshold": [0.02, 0.04, 0.06]}, {"lookback": [15, 20, 25]}),
        ("MR-001", "mean_reversion", mr_factory("MR-001", 5, -1.5), {"entry_z": [-1.0, -1.5, -2.0]}, {"lookback": [3, 5, 8]}),
        ("MR-002", "mean_reversion", mr_factory("MR-002", 20, -1.5), {"entry_z": [-1.0, -1.5, -2.0]}, {"lookback": [15, 20, 25]}),
        ("VOL-001", "volatility_regime", lambda p: VolatilityRegimeStrategy(strategy_id="VOL-001", universe=UNIVERSE, low_vol_bucket_max=p.get("low_vol_bucket_max", 1)), {"low_vol_bucket_max": [0, 1, 2]}, {}),
        ("VOLM-001", "volume_confirmed_momentum", lambda p: VolumeConfirmedMomentumStrategy(strategy_id="VOLM-001", universe=UNIVERSE, min_relative_volume=p.get("min_relative_volume", 1.2)), {"min_relative_volume": [1.0, 1.2, 1.5]}, {}),
    ]

    windows = generate_walk_forward_windows(start=TRAIN_START, end=TEST_END, train_days=500, validation_days=150, test_days=150, step_days=200)
    print(f"\nWalk-forward windows: {len(windows)}")

    for hyp_id, family, factory, main_grid, robustness_grid in specs:
        print(f"\n{'=' * 90}\n{hyp_id} ({family})\n{'=' * 90}")
        base_params = {k: v[len(v) // 2] for k, v in main_grid.items()}

        base_strategy = factory(base_params)
        is_result = run_research_backtest(research_strategy=base_strategy, bars_by_symbol=bars_by_symbol, config=full_config, **_models())
        print(f"In-sample (full period) trades: {len(is_result.trades)}  net_pnl_total: {sum(t.net_pnl for t in is_result.trades):.2f}  Sharpe: {is_result.metrics.returns.sharpe_ratio}")

        sweep_points = run_parameter_sweep(strategy_factory=factory, param_grid=main_grid, bars_by_symbol=bars_by_symbol, config=full_config, **_models())
        stability = summarize_parameter_stability(sweep_points, metric_fn=lambda m: m.trades.expectancy, metric_name="expectancy")
        print(f"Parameter sweep ({len(sweep_points)} combos): fraction_acceptable={stability.fraction_acceptable} broadly_acceptable={stability.is_broadly_acceptable}")

        wf_grid = main_grid if not robustness_grid else robustness_grid
        wf_report = run_walk_forward(strategy_factory=factory, param_grid=wf_grid, bars_by_symbol=bars_by_symbol, windows=windows, config_template=full_config, **_models())
        oos = wf_report.aggregated_oos_metrics
        print(f"Walk-forward OOS trades: {oos.trades.trade_count}  win_rate={oos.trades.win_rate:.2%}  expectancy=${oos.trades.expectancy:.2f}  profit_factor={oos.trades.profit_factor}")

        cost_report = run_cost_sensitivity(research_strategy=base_strategy, bars_by_symbol=bars_by_symbol, config=full_config, execution_model=_models()["execution_model"], base_slippage_model=_models()["slippage_model"], base_cost_model=_models()["cost_model"], spread_model=_models()["spread_model"], position_sizer=_models()["position_sizer"], risk_adapter=_models()["risk_adapter"])
        print(f"Cost sensitivity: 1x viable={cost_report.viable_at_base}  2x viable={cost_report.viable_at_2x}  3x viable={cost_report.viable_at_3x}")

        robustness_report = None
        if robustness_grid:
            robustness_report = run_robustness_tests(strategy_factory=factory, base_parameters=base_params, bars_by_symbol=bars_by_symbol, config=full_config, parameter_perturbations=robustness_grid, **_models())
            print(f"Robustness: fraction_held={robustness_report.fraction_held}")

        regime_labels = {s: label_bars_by_regime(bars) for s, bars in bars_by_symbol.items()}
        merged_labels = {}
        for s in UNIVERSE:
            merged_labels.update(regime_labels[s])
        regime_buckets = bucket_trades_by_regime(is_result.trades, merged_labels)
        regime_report = regime_performance_report(regime_buckets, starting_cash=STARTING_CASH)
        for regime, rm in regime_report.items():
            print(f"  regime={regime}: trades={rm.trades.trade_count} win_rate={rm.trades.win_rate:.2%} expectancy=${rm.trades.expectancy:.2f}")

        classification = classify_strategy(oos_metrics=oos, in_sample_metrics=is_result.metrics, parameter_stability=stability, cost_sensitivity=cost_report, robustness=robustness_report)
        print(f"\nCLASSIFICATION: {classification.classification.value}")
        for r in classification.reasons:
            print(f"  - {r}")

        exp_store.record(
            data_version=full_config.data_version, feature_version=full_config.feature_version, symbols=UNIVERSE, timeframe="day",
            strategy_version=base_strategy.spec.version, prediction_horizon=base_strategy.spec.prediction_horizon_bars,
            train_period=(TRAIN_START.isoformat(), TRAIN_END.isoformat()), validation_period=(VALIDATION_START.isoformat(), VALIDATION_END.isoformat()),
            test_period=(TEST_START.isoformat(), TEST_END.isoformat()), parameters=base_params,
            metrics={"is_trade_count": len(is_result.trades), "is_sharpe": is_result.metrics.returns.sharpe_ratio, "is_expectancy": is_result.metrics.trades.expectancy},
            strategy_family=family, classification=classification.classification.value,
            oos_metrics={"trade_count": oos.trades.trade_count, "win_rate": oos.trades.win_rate, "expectancy": oos.trades.expectancy, "profit_factor": oos.trades.profit_factor, "sharpe_ratio": None},
            cost_sensitivity={"points": [{"cost_multiplier": p.cost_multiplier, "viable": p.viable, "net_pnl_total": p.net_pnl_total} for p in cost_report.points]},
            tags=("phase4-campaign",), notes="; ".join(classification.reasons),
        )

    print(f"\n{'=' * 90}\nAll {len(specs)} hypotheses recorded in {exp_store._path}\n{'=' * 90}")


if __name__ == "__main__":
    main()
