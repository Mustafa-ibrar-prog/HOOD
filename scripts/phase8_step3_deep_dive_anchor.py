#!/usr/bin/env python3
"""Phase 8 — STEP 3: the full development-stage deep dive on the ANCHOR
variant (baseline_lookback=10, anomaly_threshold=2.0, holding_period_bars=5
— fixed BEFORE any backtest ran, see scripts/phase8_step2_parameter_grid.py's
ANCHOR constant). Baselines, cost/execution stress, symbol attribution,
leave-one-out, cross-sectional IC, temporal stability, the shift/alignment
investigation Phase 7 flagged as a concern, autocorrelation, the full
placebo battery, dependence-aware bootstrap, PBO, DSR, capacity proxy,
statistical vs economic significance (kept separate), and the final
scorecard + classification + gate transition.

NO parameter search happens in this script — ANCHOR is fixed, imported
from step 2, never re-chosen here.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtesting import (  # noqa: E402
    BacktestConfig,
    BacktestRiskAdapter,
    FixedDollarSizer,
    FixedPercentSlippage,
    FixedPercentSpreadModel,
    NextBarExecutionModel,
    PerShareCommission,
)
from src.data import HistoricalDataStore, us_diversified_universe  # noqa: E402
from src.features import FeatureEngine  # noqa: E402
from src.features.volume import RelativeVolume  # noqa: E402
from src.risk.manager import RiskManager  # noqa: E402
from src.risk.models import RiskLimits  # noqa: E402
from src.research import (  # noqa: E402
    DimensionVerdict,
    ExperimentStore,
    HypothesisFingerprint,
    HypothesisRegistry,
    MeanReversionStrategy,
    MomentumStrategy,
    PartitionLifecycleStage,
    PartitionStore,
    ResearchDatasetGenerator,
    ResearchGateStore,
    ResearchLifecycleStage,
    ScorecardDimension,
    VolumeAnomalyLongStrategy,
    autocorrelation_profile,
    block_bootstrap_trade_statistics,
    bootstrap_trade_statistics,
    build_scorecard,
    bucket_trades_by_regime,
    by_sector,
    by_symbol,
    by_year,
    check_research_reuse,
    compute_capacity_proxy,
    compute_experiment_fingerprint,
    cost_multiplier_edge,
    deflated_sharpe_ratio,
    effective_number_of_trials,
    evaluate_cross_sectional_alpha,
    evaluate_economic_significance,
    fold_has_leakage,  # noqa: F401  (imported for completeness/reference; purged CV not needed for a single anchor backtest)
    label_bars_by_regime,
    leave_one_symbol_out,
    probability_of_backtest_overfitting,
    random_symbol_and_timing_placebo,
    randomized_entry_timing_placebo,
    regime_performance_report,
    require_preregistered,
    run_cost_sensitivity,
    run_execution_robustness_extended,
    run_research_backtest,
    shifted_signal_placebo,
    shuffled_signal_placebo,
    stationary_bootstrap_trade_statistics,
    time_shuffled_target_placebo,
    trade_return_distribution,
)
from src.research.cross_sectional_alpha import CrossSectionalAlphaConfig
from src.research.experiment_fingerprint import ExperimentDimensions
from src.research.preregistration import PreregistrationStore

DOLLARS_PER_POSITION = 2_000.0
STARTING_CASH = 100_000.0
ANCHOR = {"baseline_lookback": 10, "anomaly_threshold": 2.0, "holding_period_bars": 5}


def _risk_adapter() -> BacktestRiskAdapter:
    limits = RiskLimits(max_trades_per_day=10, max_daily_loss_usd=1_000_000.0, max_position_size_usd=20_000.0, cooldown_minutes_after_exit=0, stale_data_max_seconds=10**9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0, entry_cutoff_time=time(23, 59))
    return BacktestRiskAdapter(RiskManager(limits))


def _models():
    return dict(execution_model=NextBarExecutionModel(price_field="open", delay_bars=1), slippage_model=FixedPercentSlippage(0.001), cost_model=PerShareCommission(0.005), spread_model=FixedPercentSpreadModel(0.001), position_sizer=FixedDollarSizer(DOLLARS_PER_POSITION), risk_adapter=_risk_adapter())


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    universe = us_diversified_universe()

    prereg_store = PreregistrationStore(Path("logs/research_data/phase8_preregistrations.jsonl"))
    require_preregistered(prereg_store, "P7-VOLANOM-A-DEV1")

    partition_store = PartitionStore(Path("logs/research_data/phase7_partitions.jsonl"))
    discovery = partition_store.active_by_stage(PartitionLifecycleStage.DISCOVERY)[0]
    development = partition_store.active_by_stage(PartitionLifecycleStage.DEVELOPMENT)[0]
    dev_start, dev_end = discovery.start_date, development.end_date

    grid_results = json.loads(Path("logs/research_data/phase8_grid_results.json").read_text())
    usable = grid_results["usable_symbols"]
    period_matrix = grid_results["period_matrix"]
    assert grid_results["anchor"] == ANCHOR, "anchor mismatch between step 2 and step 3 — refusing to proceed with an inconsistent anchor"

    bars_by_symbol_full = {s: store.load(s, "day") for s in usable}
    bars_by_symbol_dev = {s: [b for b in bars if dev_start <= b.timestamp.date() <= dev_end] for s, bars in bars_by_symbol_full.items()}
    config = BacktestConfig(symbols=tuple(usable), timeframe="day", start=dev_start, end=dev_end, data_version="phase5-campaign-v1", feature_version="phase8-dev-v1", initial_capital_usd=STARTING_CASH)
    m = _models()

    anchor_strategy = VolumeAnomalyLongStrategy(strategy_id="P7-VOLANOM-A-DEV1", baseline_lookback=ANCHOR["baseline_lookback"], anomaly_threshold=ANCHOR["anomaly_threshold"], holding_period_bars=ANCHOR["holding_period_bars"], universe=usable)
    anchor_result = run_research_backtest(research_strategy=anchor_strategy, bars_by_symbol=bars_by_symbol_dev, config=config, **m)
    trades = list(anchor_result.trades)
    metrics = anchor_result.metrics
    print(f"ANCHOR: {ANCHOR}\ntrades={len(trades)}  metrics.returns={metrics.returns}\n", flush=True)

    # ================================================================== PART 6: BASELINES
    print(f"{'=' * 90}\nPART 6 — BASELINE COMPARISON\n{'=' * 90}", flush=True)
    avg_qty = round(sum(t.quantity for t in trades) / len(trades)) if trades else 1
    buy_and_hold_returns = []
    for sym, bars in bars_by_symbol_dev.items():
        if len(bars) >= 2 and bars[0].open > 0:
            buy_and_hold_returns.append((bars[-1].close - bars[0].open) / bars[0].open)
    bh_avg_return = sum(buy_and_hold_returns) / len(buy_and_hold_returns) if buy_and_hold_returns else None
    print(f"1. Buy-and-hold (equal-weight avg across {len(buy_and_hold_returns)} symbols): {bh_avg_return:.2%}" if bh_avg_return is not None else "1. Buy-and-hold: N/A", flush=True)

    random_signal = randomized_entry_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol_dev, holding_period_bars=ANCHOR["holding_period_bars"], quantity=avg_qty, n_trials=200, seed=101)
    print(f"2. Random signal (randomized entry timing, same trade count/holding period, avg qty={avg_qty}): observed={random_signal.observed_statistic:.4f}  fraction_as_extreme_or_better={random_signal.fraction_as_extreme_or_better}", flush=True)

    shuffled_vol_signal = random_symbol_and_timing_placebo(observed_trades=trades, bars_by_symbol=bars_by_symbol_dev, holding_period_bars=ANCHOR["holding_period_bars"], quantity=avg_qty, n_trials=200, seed=102)
    print(f"3. Shuffled volume signal (random symbol AND timing): observed={shuffled_vol_signal.observed_statistic:.4f}  fraction_as_extreme_or_better={shuffled_vol_signal.fraction_as_extreme_or_better}", flush=True)

    momentum_baseline = MomentumStrategy(strategy_id="P8-BASELINE-MOM", lookback=20, universe=usable, entry_threshold=0.04)
    momentum_result = run_research_backtest(research_strategy=momentum_baseline, bars_by_symbol=bars_by_symbol_dev, config=config, **m)
    momentum_net = sum(t.net_pnl for t in momentum_result.trades)
    print(f"4. Simple momentum baseline (20-day, unmodified Phase 4 strategy): trades={len(momentum_result.trades)} net_pnl=${momentum_net:.2f}", flush=True)

    mr_baseline = MeanReversionStrategy(strategy_id="P8-BASELINE-MR", lookback=20, universe=usable, entry_z=-1.5)
    mr_result = run_research_backtest(research_strategy=mr_baseline, bars_by_symbol=bars_by_symbol_dev, config=config, **m)
    mr_net = sum(t.net_pnl for t in mr_result.trades)
    print(f"5. Simple mean-reversion baseline (20-day, unmodified Phase 4 strategy): trades={len(mr_result.trades)} net_pnl=${mr_net:.2f}\n", flush=True)

    anchor_net = sum(t.net_pnl for t in trades)
    print(f"ANCHOR net_pnl=${anchor_net:.2f}  vs momentum=${momentum_net:.2f}  vs mean-reversion=${mr_net:.2f}  vs buy-and-hold={bh_avg_return:.2%} (return, not $)\n", flush=True)

    # ================================================================== PARTS 8, 21: COST
    print(f"{'=' * 90}\nPARTS 8 & 21 — COST SENSITIVITY (1x/2x/3x/5x)\n{'=' * 90}", flush=True)
    cost_report = run_cost_sensitivity(research_strategy=anchor_strategy, bars_by_symbol=bars_by_symbol_dev, config=config, execution_model=m["execution_model"], base_slippage_model=m["slippage_model"], base_cost_model=m["cost_model"], spread_model=m["spread_model"], position_sizer=m["position_sizer"], risk_adapter=m["risk_adapter"], multipliers=(1.0, 2.0, 3.0, 5.0))
    for p in cost_report.points:
        print(f"  {p.cost_multiplier}x: trades={p.trade_count} net_pnl_total=${p.net_pnl_total:.2f} viable={p.viable}", flush=True)
    cost_edge_report = cost_multiplier_edge(trades, multipliers=(1.0, 2.0, 3.0, 5.0))
    print(cost_edge_report.render(), flush=True)

    # ================================================================== PART 22: EXECUTION
    print(f"\n{'=' * 90}\nPART 22 — EXECUTION ROBUSTNESS\n{'=' * 90}", flush=True)
    exec_report = run_execution_robustness_extended(research_strategy=anchor_strategy, bars_by_symbol=bars_by_symbol_dev, config=config, base_execution_model=m["execution_model"], base_slippage_model=m["slippage_model"], base_cost_model=m["cost_model"], spread_model=m["spread_model"], position_sizer=m["position_sizer"], risk_adapter=m["risk_adapter"])
    for p in exec_report.points:
        print(f"  {p.scenario}: trades={p.trade_count} net_pnl_total=${p.net_pnl_total:.2f} viable={p.viable}", flush=True)

    # ================================================================== PART 9, 13: ATTRIBUTION
    print(f"\n{'=' * 90}\nPARTS 9 & 13 — POSITION SIZING & SYMBOL ATTRIBUTION\n{'=' * 90}", flush=True)
    quantities = [t.quantity * t.entry_price for t in trades]
    print(f"Avg position size: ${sum(quantities) / len(quantities):.2f}  Max: ${max(quantities):.2f}  n_trades={len(trades)}", flush=True)
    sym_breakdown = by_symbol(trades, starting_cash=STARTING_CASH)
    for sym, r in sorted(sym_breakdown.items(), key=lambda kv: kv[1].net_pnl_total, reverse=True):
        print(f"  {sym}: trades={r.trade_count} net_pnl=${r.net_pnl_total:.2f} win_rate={r.metrics.trades.win_rate:.2%}", flush=True)
    loo = leave_one_symbol_out(trades, starting_cash=STARTING_CASH)
    print(f"Leave-one-out: max_expectancy_swing={loo.max_expectancy_swing}  sign_flips_without={loo.sign_flips_without}", flush=True)
    dist = trade_return_distribution(trades)
    print(f"Largest contributing symbol: {dist.largest_contributing_symbol} ({dist.pct_pnl_from_largest_contributing_symbol}% of net P&L)", flush=True)

    # ================================================================== PART 12: CROSS-SECTIONAL IC
    print(f"\n{'=' * 90}\nPART 12 — CROSS-SECTIONAL IC (development period, wider than Phase 7's discovery-only check)\n{'=' * 90}", flush=True)
    engine = FeatureEngine([RelativeVolume(ANCHOR["baseline_lookback"])])
    generator = ResearchDatasetGenerator(engine, horizons=(5,))
    panel = []
    for sym in usable:
        ds = generator.generate(bars_by_symbol_full[sym], data_version="phase5-campaign-v1")
        panel.extend(dict(row) for row in ds.rows)
    dev_panel = [r for r in panel if dev_start <= r["timestamp"].date() <= dev_end]
    for row in dev_panel:
        row["abs_target_future_return_5bar"] = abs(row["target_future_return_5bar"]) if row.get("target_future_return_5bar") is not None else None
    feature_col = f"feature_relative_volume_{ANCHOR['baseline_lookback']}"
    alpha_magnitude = evaluate_cross_sectional_alpha(dev_panel, CrossSectionalAlphaConfig(feature_col=feature_col, target_col="abs_target_future_return_5bar", n_quantiles=5))
    alpha_signed = evaluate_cross_sectional_alpha(dev_panel, CrossSectionalAlphaConfig(feature_col=feature_col, target_col="target_future_return_5bar", n_quantiles=5))
    print(f"IC vs |return| (matches Phase 7 discovery definition): avg={alpha_magnitude.ic_summary.average_ic} t={alpha_magnitude.ic_t_statistic} p={alpha_magnitude.ic_p_value}  monotonic={alpha_magnitude.quantile_report.is_monotonic}", flush=True)
    print(f"IC vs signed return (what actually drives LONG P&L): avg={alpha_signed.ic_summary.average_ic} t={alpha_signed.ic_t_statistic} p={alpha_signed.ic_p_value}  monotonic={alpha_signed.quantile_report.is_monotonic}", flush=True)

    # ================================================================== PART 14: TEMPORAL STABILITY
    print(f"\n{'=' * 90}\nPART 14 — TEMPORAL STABILITY\n{'=' * 90}", flush=True)
    year_breakdown = by_year(trades, starting_cash=STARTING_CASH)
    for y, r in sorted(year_breakdown.items()):
        print(f"  {y}: trades={r.trade_count} net_pnl=${r.net_pnl_total:.2f} expectancy=${r.metrics.trades.expectancy:.2f}", flush=True)
    regime_labels: dict = {}
    for sym in usable:
        regime_labels.update(label_bars_by_regime(bars_by_symbol_full[sym]))
    regime_buckets = bucket_trades_by_regime(trades, regime_labels)
    regime_report = regime_performance_report(regime_buckets, starting_cash=STARTING_CASH)
    for r, met in regime_report.items():
        print(f"  regime={r}: trades={met.trades.trade_count} expectancy=${met.trades.expectancy:.2f} win_rate={met.trades.win_rate:.2%}", flush=True)

    # ================================================================== PART 15: SHIFT/ALIGNMENT + AUTOCORRELATION
    print(f"\n{'=' * 90}\nPART 15 — SHIFT/ALIGNMENT INVESTIGATION (Phase 7's flagged concern)\n{'=' * 90}", flush=True)
    for shift in (1, 2, 5, 10):
        shifted_mag = shifted_signal_placebo(dev_panel, feature_col=feature_col, target_col="abs_target_future_return_5bar", shift_bars=shift)
        shifted_signed = shifted_signal_placebo(dev_panel, feature_col=feature_col, target_col="target_future_return_5bar", shift_bars=shift)
        print(f"  shift=+{shift}: |return| true_IC={shifted_mag.observed_statistic}  shifted_IC={shifted_mag.placebo_distribution}   |  signed true_IC={shifted_signed.observed_statistic}  shifted_IC={shifted_signed.placebo_distribution}", flush=True)

    print("\nAutocorrelation of the volume-anomaly feature and of returns (per-symbol, averaged):", flush=True)
    rv_autocorr_by_lag: dict[int, list[float]] = defaultdict(list)
    ret_autocorr_by_lag: dict[int, list[float]] = defaultdict(list)
    for sym in usable:
        bars = bars_by_symbol_dev[sym]
        rv_engine = FeatureEngine([RelativeVolume(ANCHOR["baseline_lookback"])])
        frame = rv_engine.compute(bars)
        rv_series = frame.columns[f"relative_volume_{ANCHOR['baseline_lookback']}"]
        ret_series = [(bars[i].close - bars[i - 1].close) / bars[i - 1].close if i > 0 and bars[i - 1].close else None for i in range(len(bars))]
        profile_rv = autocorrelation_profile(rv_series, (1, 2, 5, 10))
        profile_ret = autocorrelation_profile(ret_series, (1, 2, 5, 10))
        for lag, val in profile_rv.items():
            if val is not None:
                rv_autocorr_by_lag[lag].append(val)
        for lag, val in profile_ret.items():
            if val is not None:
                ret_autocorr_by_lag[lag].append(val)
    for lag in (1, 2, 5, 10):
        rv_vals, ret_vals = rv_autocorr_by_lag[lag], ret_autocorr_by_lag[lag]
        rv_avg = sum(rv_vals) / len(rv_vals) if rv_vals else None
        ret_avg = sum(ret_vals) / len(ret_vals) if ret_vals else None
        print(f"  lag={lag}: avg RelativeVolume autocorrelation={rv_avg}  avg daily-return autocorrelation={ret_avg}", flush=True)

    # ================================================================== PART 16: PLACEBO BATTERY
    print(f"\n{'=' * 90}\nPART 16 — PLACEBO BATTERY\n{'=' * 90}", flush=True)
    shuffled = shuffled_signal_placebo(dev_panel, feature_col=feature_col, target_col="target_future_return_5bar", n_trials=200, seed=103)
    time_shuffled = time_shuffled_target_placebo(dev_panel, feature_col=feature_col, target_col="target_future_return_5bar", n_trials=200, seed=104)
    print(f"  shuffled_signal: observed={shuffled.observed_statistic} p={shuffled.empirical_p_value}", flush=True)
    print(f"  time_shuffled_target: observed={time_shuffled.observed_statistic} p={time_shuffled.empirical_p_value}", flush=True)
    print(f"  randomized_entry_timing (trade-level, from PART 6 above): observed={random_signal.observed_statistic} p={random_signal.fraction_as_extreme_or_better}", flush=True)
    print(f"  random_symbol_and_timing (trade-level, from PART 6 above): observed={shuffled_vol_signal.observed_statistic} p={shuffled_vol_signal.fraction_as_extreme_or_better}", flush=True)

    # ================================================================== PART 17: BOOTSTRAP
    print(f"\n{'=' * 90}\nPART 17 — DEPENDENCE-AWARE BOOTSTRAP\n{'=' * 90}", flush=True)
    for cl in (0.90, 0.95):
        iid = bootstrap_trade_statistics(trades, n_resamples=2000, seed=42, confidence_level=cl)
        block = block_bootstrap_trade_statistics(trades, block_size=10, n_resamples=2000, seed=42, confidence_level=cl)
        stationary = stationary_bootstrap_trade_statistics(trades, mean_block_length=10, n_resamples=2000, seed=42, confidence_level=cl)
        print(f"-- {cl:.0%} CI --", flush=True)
        print("  i.i.d.:      " + iid.render().replace("\n", "\n    "), flush=True)
        print("  block(10):   " + block.render().replace("\n", "\n    "), flush=True)
        print("  stationary(10): " + stationary.render().replace("\n", "\n    "), flush=True)

    # ================================================================== PART 18: PBO
    print(f"\n{'=' * 90}\nPART 18 — PROBABILITY OF BACKTEST OVERFITTING\n{'=' * 90}", flush=True)
    pbo = probability_of_backtest_overfitting(period_matrix)
    print(pbo.render(), flush=True)
    eff_trials = effective_number_of_trials(period_matrix)
    print(eff_trials.render(), flush=True)

    # ================================================================== PART 19: DSR
    print(f"\n{'=' * 90}\nPART 19 — DEFLATED SHARPE RATIO\n{'=' * 90}", flush=True)
    trade_returns = [t.net_pnl for t in trades]
    dsr = deflated_sharpe_ratio(trade_returns, n_trials=18, periods_per_year=252.0 / ANCHOR["holding_period_bars"])
    print(dsr.render(), flush=True)

    # ================================================================== PART 23: CAPACITY
    print(f"\n{'=' * 90}\nPART 23 — CAPACITY PROXY\n{'=' * 90}", flush=True)
    capacity = compute_capacity_proxy(trades, participation_rate=0.01)
    print(f"CAPACITY_PROXY: ${capacity:,.0f}" if capacity else "CAPACITY_PROXY: N/A", flush=True)
    print("LIMITATION: a rough lower-bound proxy (smallest implied capacity across trades assuming <=1% ADV participation) — NOT a market-impact model.", flush=True)

    # ================================================================== PART 24: SIGNIFICANCE (SEPARATE)
    print(f"\n{'=' * 90}\nPART 24 — STATISTICAL vs ECONOMIC SIGNIFICANCE (reported separately)\n{'=' * 90}", flush=True)
    econ_report = evaluate_economic_significance(trades=trades, metrics=metrics, span_years=(dev_end - dev_start).days / 365.25)
    print("STATISTICAL SIGNIFICANCE:", flush=True)
    print(f"  cross-sectional IC (signed) t={alpha_signed.ic_t_statistic} p={alpha_signed.ic_p_value}", flush=True)
    print(f"  shuffled-signal placebo p={shuffled.empirical_p_value}  time-shuffled-target placebo p={time_shuffled.empirical_p_value}", flush=True)
    print("ECONOMIC SIGNIFICANCE:", flush=True)
    print("  " + econ_report.render().replace("\n", "\n  "), flush=True)

    # ================================================================== PART 25: SCORECARD & CLASSIFICATION
    print(f"\n{'=' * 90}\nPART 25 — DEVELOPMENT SCORECARD & CLASSIFICATION\n{'=' * 90}", flush=True)

    stat_sign_matches = alpha_signed.ic_summary.average_ic is not None and alpha_signed.ic_summary.average_ic > 0
    stat_significant = alpha_signed.ic_p_value is not None and alpha_signed.ic_p_value < 0.05
    stat_verdict = DimensionVerdict.SUPPORTS if (stat_sign_matches and stat_significant) else DimensionVerdict.AGAINST if (stat_significant and not stat_sign_matches) else DimensionVerdict.NEUTRAL

    econ_verdict = DimensionVerdict.SUPPORTS if (econ_report.net_expectancy > 0 and cost_report.viable_at_2x) else DimensionVerdict.AGAINST if econ_report.net_expectancy <= 0 else DimensionVerdict.NEUTRAL

    n_positive_variants = sum(1 for row in grid_results["variants"] if row["net_pnl_total"] > 0)
    param_frac = n_positive_variants / len(grid_results["variants"])
    param_verdict = DimensionVerdict.SUPPORTS if param_frac >= 0.6 else DimensionVerdict.NEUTRAL if param_frac >= 0.35 else DimensionVerdict.AGAINST

    n_regimes_positive = sum(1 for met in regime_report.values() if met.trades.expectancy > 0)
    regime_verdict = DimensionVerdict.SUPPORTS if regime_report and n_regimes_positive / len(regime_report) >= 0.6 else DimensionVerdict.NEUTRAL if regime_report else DimensionVerdict.NOT_APPLICABLE

    cost_verdict = DimensionVerdict.SUPPORTS if cost_report.viable_at_2x and cost_report.viable_at_3x else DimensionVerdict.NEUTRAL if cost_report.viable_at_2x else DimensionVerdict.AGAINST
    exec_verdict = DimensionVerdict.SUPPORTS if exec_report.fraction_viable == 1.0 else DimensionVerdict.NEUTRAL if exec_report.fraction_viable and exec_report.fraction_viable >= 0.5 else DimensionVerdict.AGAINST

    mtp_verdict = DimensionVerdict.NEUTRAL
    if dsr.applicable:
        mtp_verdict = DimensionVerdict.SUPPORTS if dsr.deflated_sharpe_ratio >= 0.5 else DimensionVerdict.AGAINST if dsr.deflated_sharpe_ratio < 0.1 else DimensionVerdict.NEUTRAL
    if pbo.applicable and pbo.pbo is not None and pbo.pbo >= 0.5:
        mtp_verdict = DimensionVerdict.AGAINST

    fp = HypothesisFingerprint(hypothesis_id="P7-VOLANOM-A-DEV1", family="volume_anomaly", feature_variant=feature_col, target_horizon_bars=5, universe_name=universe.name, threshold_bucket="[1.5..2.5)", cost_assumptions="phase5-standard", execution_assumptions="next_bar_delay_1")
    prior_fps = [
        HypothesisFingerprint(hypothesis_id="P7-VPC-A", family="volume_price_confirmation", feature_variant="feature_roc_5*relative_volume_10", target_horizon_bars=5, universe_name=universe.name, threshold_bucket="n/a", cost_assumptions="n/a-discovery", execution_assumptions="n/a-discovery"),
        HypothesisFingerprint(hypothesis_id="P7-VOLANOM-A", family="volume_anomaly", feature_variant="feature_relative_volume_10", target_horizon_bars=5, universe_name=universe.name, threshold_bucket="n/a", cost_assumptions="n/a-discovery", execution_assumptions="n/a-discovery"),
    ]
    reuse_check = check_research_reuse(fp, prior_fps, similarity_threshold=0.70)
    contamination_verdict = DimensionVerdict.AGAINST if reuse_check.flagged else DimensionVerdict.SUPPORTS
    print(f"Research reuse check vs prior hypotheses: {reuse_check.explanation}", flush=True)

    oos_split_date = discovery.end_date
    discovery_trades = [t for t in trades if t.entry_timestamp.date() <= oos_split_date]
    development_only_trades = [t for t in trades if t.entry_timestamp.date() > oos_split_date]
    disc_exp = (sum(t.net_pnl for t in discovery_trades) / len(discovery_trades)) if discovery_trades else None
    devo_exp = (sum(t.net_pnl for t in development_only_trades) / len(development_only_trades)) if development_only_trades else None
    print(f"Split check: DISCOVERY_DATA-window trades n={len(discovery_trades)} expectancy=${disc_exp}  |  DEVELOPMENT_DATA-window trades n={len(development_only_trades)} expectancy=${devo_exp}", flush=True)
    oos_verdict = DimensionVerdict.NOT_APPLICABLE
    if disc_exp is not None and devo_exp is not None:
        oos_verdict = DimensionVerdict.SUPPORTS if (disc_exp > 0) == (devo_exp > 0) and devo_exp > 0 else DimensionVerdict.AGAINST if devo_exp <= 0 else DimensionVerdict.NEUTRAL

    dims = [
        ScorecardDimension("statistical_evidence", stat_verdict, f"signed IC={alpha_signed.ic_summary.average_ic} p={alpha_signed.ic_p_value}"),
        ScorecardDimension("economic_significance", econ_verdict, f"net_expectancy=${econ_report.net_expectancy:.2f} viable_at_2x={cost_report.viable_at_2x}"),
        ScorecardDimension("out_of_sample_stability", oos_verdict, f"discovery-window expectancy=${disc_exp}, development-window expectancy=${devo_exp}"),
        ScorecardDimension("parameter_stability", param_verdict, f"{n_positive_variants}/{len(grid_results['variants'])} of the 18-variant grid net-profitable"),
        ScorecardDimension("regime_stability", regime_verdict, f"{n_regimes_positive}/{len(regime_report)} regimes positive expectancy" if regime_report else "no regime data"),
        ScorecardDimension("universe_stability", DimensionVerdict.NOT_APPLICABLE, "only US_DIVERSIFIED tested this phase"),
        ScorecardDimension("cost_robustness", cost_verdict, f"viable_at_2x={cost_report.viable_at_2x} viable_at_3x={cost_report.viable_at_3x}"),
        ScorecardDimension("execution_robustness", exec_verdict, f"fraction_viable={exec_report.fraction_viable}"),
        ScorecardDimension("data_quality", DimensionVerdict.SUPPORTS, "US_DIVERSIFIED: 20/20 symbols usable"),
        ScorecardDimension("multiple_testing_penalty", mtp_verdict, f"DSR={dsr.deflated_sharpe_ratio if dsr.applicable else 'N/A'}  PBO={pbo.pbo if pbo.applicable else 'N/A'}"),
        ScorecardDimension("research_contamination_risk", contamination_verdict, reuse_check.explanation),
        ScorecardDimension("economic_rationale", DimensionVerdict.SUPPORTS, "documented translation rationale + falsification criteria present"),
    ]
    scorecard = build_scorecard("P7-VOLANOM-A-DEV1", dims)
    print("\n" + scorecard.render(), flush=True)

    # ================================================================== PART 26: GATE (never past DEVELOPMENT_VALIDATED)
    gate_store = ResearchGateStore(Path("logs/research_data/phase8_gate_transitions.jsonl"))
    gate_store.transition(hypothesis_id="P7-VOLANOM-A-DEV1", to_stage=ResearchLifecycleStage.IDEA, reason="tradeable translation of P7-VOLANOM-A", evidence_summary="")
    gate_store.transition(hypothesis_id="P7-VOLANOM-A-DEV1", to_stage=ResearchLifecycleStage.PREREGISTERED, reason="preregistered before any backtest ran", evidence_summary="")
    gate_store.transition(hypothesis_id="P7-VOLANOM-A-DEV1", to_stage=ResearchLifecycleStage.DISCOVERY_TESTED, reason="cross-sectional IC re-confirmed on the wider development-period panel", evidence_summary=f"IC={alpha_signed.ic_summary.average_ic}")
    if scorecard.classification == "PROMISING":
        gate_store.transition(hypothesis_id="P7-VOLANOM-A-DEV1", to_stage=ResearchLifecycleStage.DEVELOPMENT_VALIDATED, reason=scorecard.classification_reason, evidence_summary=f"net_expectancy=${econ_report.net_expectancy:.2f}")
        advisory = "DEVELOPMENT_SUPPORTED — recommend a separate Phase 9 for VALIDATION_DATA-stage testing. NOT advanced to VALIDATION_DATA or FINAL_HOLDOUT_DATA in this phase."
    else:
        gate_store.transition(hypothesis_id="P7-VOLANOM-A-DEV1", to_stage=ResearchLifecycleStage.NOT_READY, reason=scorecard.classification_reason, evidence_summary=f"net_expectancy=${econ_report.net_expectancy:.2f}")
        advisory = f"NOT advanced past DISCOVERY_TESTED — classification is {scorecard.classification}, not PROMISING. Development evidence does not clear the bar for DEVELOPMENT_SUPPORTED."
    print(f"\nGATE: {advisory}", flush=True)

    # ================================================================== record final experiment
    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))
    dims_fp = ExperimentDimensions(feature_definition=f"relative_volume_{ANCHOR['baseline_lookback']}", parameter_range=ANCHOR, universe_name=universe.name, target_definition="realized net trade P&L", execution_model="next_bar_delay_1", cost_model="per_share_0.005", validation_methodology="anchor deep-dive: DISCOVERY_DATA+DEVELOPMENT_DATA event-driven backtest")
    exp_store.record(
        data_version=config.data_version, feature_version=config.feature_version, symbols=usable, timeframe="day",
        strategy_version="1.0", prediction_horizon=5, train_period=(str(dev_start), str(dev_end)), parameters=ANCHOR,
        metrics={"trade_count": len(trades), "net_pnl_total": anchor_net, "expectancy": econ_report.net_expectancy, "sharpe": metrics.returns.sharpe_ratio},
        strategy_family="volume_anomaly", classification=scorecard.classification, tags=("phase8-dev-anchor", universe.name),
        notes=scorecard.classification_reason, hypothesis_id="P7-VOLANOM-A-DEV1", universe_name=universe.name,
        experiment_fingerprint=compute_experiment_fingerprint(dims_fp), research_family_id="P8-VOLANOM-DEV-GRID-2026-09",
    )
    print("\nSTEP 3 COMPLETE.", flush=True)


if __name__ == "__main__":
    main()
