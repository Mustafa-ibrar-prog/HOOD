#!/usr/bin/env python3
"""Phase 11 — STEP 2: runs the FULL preregistered 12-variant exposure
grid on SPY (Benchmark Engine A, Part 3) via the real event-driven
BacktestEngine, on DISCOVERY_DATA only (Part 29's TRAIN/VALIDATE step —
selection happens HERE, using only this period), reports every variant
(nothing hidden), FREEZES the selected winner, then re-runs ONLY that
frozen winner on DEVELOPMENT_DATA (the out-of-sample FREEZE/TEST step) —
never re-selecting after seeing development-period results.

Also runs, on the winner only: cost/execution stress, block/stationary
bootstrap, PBO (across the full 12-variant grid), Deflated Sharpe Ratio
(n_trials=12, the actual searched grid size), and the randomized-exposure
/shuffled-volatility placebo controls (Parts 25-26).

DISCOVERY_DATA + DEVELOPMENT_DATA only — no VALIDATION_DATA/
FINAL_HOLDOUT_DATA access anywhere in this script (Part 8, 30).
"""

from __future__ import annotations

import json
import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtesting import BacktestConfig, FixedPercentSlippage, FixedPercentSpreadModel, NextBarExecutionModel, PerShareCommission  # noqa: E402
from src.backtesting.metrics import _period_returns  # noqa: E402
from src.data import HistoricalDataStore  # noqa: E402
from src.research import (  # noqa: E402
    EqualWeightExposureSizer,
    ExperimentStore,
    ExposureMechanismConfig,
    ExposureRiskAdapter,
    PartitionLifecycleStage,
    PartitionStore,
    PrecomputedExposureStrategy,
    compute_exposure_series,
    random_exposure_series,
    require_preregistered,
    shuffled_exposure_series,
)
from src.research.baseline import buy_and_hold_curve  # noqa: E402
from src.research.experiment_fingerprint import ExperimentDimensions, compute_experiment_fingerprint  # noqa: E402
from src.research.overfitting_metrics import deflated_sharpe_ratio, probability_of_backtest_overfitting  # noqa: E402
from src.research.preregistration import PreregistrationStore  # noqa: E402
from src.research.exposure_cost_stress import run_exposure_cost_stress, run_exposure_execution_stress  # noqa: E402
from src.research.return_series_bootstrap import block_bootstrap_return_series, stationary_bootstrap_return_series  # noqa: E402
from src.research.runner import run_research_backtest  # noqa: E402
from src.risk.manager import RiskManager  # noqa: E402
from src.risk.models import RiskLimits  # noqa: E402

SYMBOL = "SPY"  # Benchmark Engine A (Part 3) — the primary variant-selection workhorse; Engine B/C (equal-weight universe) is confirmed separately in step 3
STARTING_CASH = 100_000.0
PBO_N_PERIODS = 8  # small, CSCV-tractable (C(8,4)=70), even (required)
SELECTION_METRIC = "sharpe"  # fixed BEFORE this script ran — the DISCOVERY-period ranking rule, never changed after seeing results
DATA_VERSION, FEATURE_VERSION = "phase5-campaign-v1", "phase11-v1"

MECHANISM_ORDER = ("STATIC", "VOL_TARGET", "REGIME", "COMPRESSION_EXPANSION")


def _risk_adapter() -> ExposureRiskAdapter:
    limits = RiskLimits(max_trades_per_day=25, max_daily_loss_usd=1_000_000.0, max_position_size_usd=1_000_000.0, cooldown_minutes_after_exit=0, stale_data_max_seconds=10**9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0, entry_cutoff_time=time(23, 59))
    return ExposureRiskAdapter(RiskManager(limits))


def _models(n_symbols: int) -> dict:
    return dict(
        execution_model=NextBarExecutionModel(price_field="open", delay_bars=1), slippage_model=FixedPercentSlippage(0.0005),
        cost_model=PerShareCommission(0.001), spread_model=FixedPercentSpreadModel(0.0005),
        position_sizer=EqualWeightExposureSizer(n_symbols=n_symbols), risk_adapter=_risk_adapter(),
    )


def _grid() -> list[dict]:
    from src.research.exposure_mechanisms import REBALANCE_FREQUENCIES, TARGET_VOL_CANDIDATES

    grid = []
    for freq in REBALANCE_FREQUENCIES:
        grid.append({"mechanism": "STATIC", "target_annual_vol": None, "rebalance_frequency": freq})
        for tv in TARGET_VOL_CANDIDATES:
            grid.append({"mechanism": "VOL_TARGET", "target_annual_vol": tv, "rebalance_frequency": freq})
        grid.append({"mechanism": "REGIME", "target_annual_vol": None, "rebalance_frequency": freq})
        grid.append({"mechanism": "COMPRESSION_EXPANSION", "target_annual_vol": None, "rebalance_frequency": freq})
    return grid


def _variant_label(v: dict) -> str:
    if v["mechanism"] == "VOL_TARGET":
        return f"VOL_TARGET({v['target_annual_vol']:.0%})/{v['rebalance_frequency']}"
    return f"{v['mechanism']}/{v['rebalance_frequency']}"


def _run_variant(bars: list, v: dict, config: BacktestConfig, models: dict, strategy_id: str):
    mech_config = ExposureMechanismConfig(mechanism=v["mechanism"], target_annual_vol=v["target_annual_vol"], rebalance_frequency=v["rebalance_frequency"])
    exposure = compute_exposure_series(bars, mech_config)
    strategy = PrecomputedExposureStrategy(strategy_id=strategy_id, exposure_by_symbol={SYMBOL: exposure}, universe=[SYMBOL], hypothesis_id="P11-VCE-006")
    result = run_research_backtest(research_strategy=strategy, bars_by_symbol={SYMBOL: bars}, config=config, **models)
    returns = _period_returns(list(result.equity_curve))
    return result, exposure, returns


def _period_bucket_returns(equity_curve, start_date, end_date, n_periods: int) -> list[float]:
    """Splits the equity curve's own period returns into `n_periods`
    equal-width calendar sub-periods and returns each sub-period's MEAN
    return — the input probability_of_backtest_overfitting needs
    (Phase 7's PBO, applied here to RETURNS instead of trade P&L, since
    this strategy has no discrete trades — see
    src/research/return_series_bootstrap.py's module docstring for the
    same reasoning applied to bootstrap)."""
    total_days = (end_date - start_date).days + 1
    buckets: list[list[float]] = [[] for _ in range(n_periods)]
    for prev, cur in zip(equity_curve, equity_curve[1:]):
        if prev.equity <= 0:
            continue
        ret = (cur.equity - prev.equity) / prev.equity
        day_offset = (cur.timestamp.date() - start_date).days
        bucket = min(n_periods - 1, max(0, (day_offset * n_periods) // total_days))
        buckets[bucket].append(ret)
    return [sum(b) / len(b) if b else 0.0 for b in buckets]


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))

    prereg_store = PreregistrationStore(Path("logs/research_data/phase11_preregistrations.jsonl"))
    require_preregistered(prereg_store, "P11-VCE-FAMILY")
    for hid in ("P11-VCE-001", "P11-VCE-002", "P11-VCE-003", "P11-VCE-004", "P11-VCE-005", "P11-VCE-006"):
        require_preregistered(prereg_store, hid)

    partition_store = PartitionStore(Path("logs/research_data/phase7_partitions.jsonl"))
    discovery = partition_store.active_by_stage(PartitionLifecycleStage.DISCOVERY)[0]
    development = partition_store.active_by_stage(PartitionLifecycleStage.DEVELOPMENT)[0]
    print(f"DISCOVERY_DATA (selection period): {discovery.start_date} .. {discovery.end_date}", flush=True)
    print(f"DEVELOPMENT_DATA (frozen out-of-sample test period): {development.start_date} .. {development.end_date}\n", flush=True)

    all_bars = store.load(SYMBOL, "day")
    bars_discovery = [b for b in all_bars if discovery.start_date <= b.timestamp.date() <= discovery.end_date]
    bars_development = [b for b in all_bars if development.start_date <= b.timestamp.date() <= development.end_date]
    print(f"{SYMBOL}: {len(bars_discovery)} discovery bars, {len(bars_development)} development bars\n", flush=True)

    config_disc = BacktestConfig(symbols=(SYMBOL,), timeframe="day", start=discovery.start_date, end=discovery.end_date, data_version=DATA_VERSION, feature_version=FEATURE_VERSION, initial_capital_usd=STARTING_CASH)
    config_dev = BacktestConfig(symbols=(SYMBOL,), timeframe="day", start=development.start_date, end=development.end_date, data_version=DATA_VERSION, feature_version=FEATURE_VERSION, initial_capital_usd=STARTING_CASH)

    grid = _grid()
    assert len(grid) == 12
    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))

    print(f"{'=' * 100}\nDISCOVERY-PERIOD GRID ({len(grid)} variants, SPY) — every variant reported, none hidden\n{'=' * 100}", flush=True)
    grid_results = []
    period_matrix: list[list[float]] = []
    for i, v in enumerate(grid):
        result, exposure, returns = _run_variant(bars_discovery, v, config_disc, _models(1), strategy_id=f"P11-GRID-{i}")
        m = result.metrics
        periods = _period_bucket_returns(list(result.equity_curve), discovery.start_date, discovery.end_date, PBO_N_PERIODS)
        period_matrix.append(periods)
        label = _variant_label(v)
        print(f"[{i:2d}] {label:24s} ann_ret={m.returns.annualized_return_pct:7.2f}%  ann_vol={m.returns.volatility_annualized_pct or 0:6.2f}%  "
              f"sharpe={m.returns.sharpe_ratio or 0:6.3f}  sortino={m.returns.sortino_ratio or 0:6.3f}  calmar={m.returns.calmar_ratio or 0:6.3f}  "
              f"max_dd={m.drawdown.max_drawdown_pct:6.2f}%  turnover={m.portfolio.turnover:5.2f}  avg_exposure={m.portfolio.average_exposure_pct:5.1f}%", flush=True)
        grid_results.append({"index": i, "variant": v, "label": label,
                              "annualized_return_pct": m.returns.annualized_return_pct, "annualized_vol_pct": m.returns.volatility_annualized_pct,
                              "sharpe": m.returns.sharpe_ratio, "sortino": m.returns.sortino_ratio, "calmar": m.returns.calmar_ratio,
                              "max_drawdown_pct": m.drawdown.max_drawdown_pct, "turnover": m.portfolio.turnover, "avg_exposure_pct": m.portfolio.average_exposure_pct,
                              "n_returns": len(returns)})
        dims_fp = ExperimentDimensions(feature_definition=label, parameter_range=v, universe_name="US_DIVERSIFIED", target_definition="risk-adjusted return vs static exposure", execution_model="next_bar_delay_1", cost_model="per_share_0.001", validation_methodology="Phase 11 discovery-period exposure grid")
        exp_store.record(
            data_version=DATA_VERSION, feature_version=FEATURE_VERSION, symbols=[SYMBOL], timeframe="day", strategy_version="1.0",
            prediction_horizon=5, train_period=(str(discovery.start_date), str(discovery.end_date)), parameters=v,
            metrics={"sharpe": m.returns.sharpe_ratio, "sortino": m.returns.sortino_ratio, "calmar": m.returns.calmar_ratio, "annualized_return_pct": m.returns.annualized_return_pct, "annualized_vol_pct": m.returns.volatility_annualized_pct},
            strategy_family="volatility_conditioned_exposure", classification="GRID_POINT_NOT_YET_CLASSIFIED", tags=("phase11-discovery-grid", "US_DIVERSIFIED"),
            notes="raw discovery-period grid point — step 3 classifies the hypotheses, not individual grid points",
            hypothesis_id="P11-VCE-006", universe_name="US_DIVERSIFIED", experiment_fingerprint=compute_experiment_fingerprint(dims_fp),
            research_family_id="P11-VCE-DISCOVERY-GRID-2026-09",
        )

    # --- SELECTION (Part 29: TRAIN/VALIDATE here, on DISCOVERY_DATA only) ------------------------
    winner_idx = max(range(len(grid_results)), key=lambda i: (grid_results[i][SELECTION_METRIC] or -999))
    winner = grid_results[winner_idx]
    print(f"\nSELECTED (by {SELECTION_METRIC} on DISCOVERY_DATA only): [{winner_idx}] {winner['label']}  sharpe={winner['sharpe']:.3f}", flush=True)
    print("FROZEN — this exact variant, and only this one, is re-run on DEVELOPMENT_DATA below (never re-selected).", flush=True)
    frozen_config = grid[winner_idx]

    # --- PBO across the full discovery-period grid (Part 27) -------------------------------------
    print(f"\n{'=' * 100}\nPBO (Probability of Backtest Overfitting) — all {len(grid)} discovery-period variants, {PBO_N_PERIODS} sub-periods\n{'=' * 100}", flush=True)
    pbo = probability_of_backtest_overfitting(period_matrix)
    print(f"  {pbo.render()}", flush=True)

    # --- FROZEN WINNER on DEVELOPMENT_DATA (Part 29: FREEZE/TEST) --------------------------------
    print(f"\n{'=' * 100}\nFROZEN WINNER ON DEVELOPMENT_DATA (out-of-sample, never re-selected): {winner['label']}\n{'=' * 100}", flush=True)
    dev_result, dev_exposure, dev_returns = _run_variant(bars_development, frozen_config, config_dev, _models(1), strategy_id="P11-VCE-006-FROZEN")
    dm = dev_result.metrics
    print(f"  ann_ret={dm.returns.annualized_return_pct:.2f}%  ann_vol={dm.returns.volatility_annualized_pct or 0:.2f}%  sharpe={dm.returns.sharpe_ratio or 0:.3f}  "
          f"sortino={dm.returns.sortino_ratio or 0:.3f}  calmar={dm.returns.calmar_ratio or 0:.3f}  max_dd={dm.drawdown.max_drawdown_pct:.2f}%  "
          f"turnover={dm.portfolio.turnover:.2f}  avg_exposure={dm.portfolio.average_exposure_pct:.1f}%", flush=True)

    # --- STATIC benchmark on DEVELOPMENT_DATA, for direct comparison -----------------------------
    static_variant = next(v for v in grid if v["mechanism"] == "STATIC" and v["rebalance_frequency"] == frozen_config["rebalance_frequency"])
    static_dev_result, _static_dev_exposure, static_dev_returns = _run_variant(bars_development, static_variant, config_dev, _models(1), strategy_id="P11-STATIC-DEV")
    sm = static_dev_result.metrics
    print(f"\n  STATIC (same rebalance freq) on DEVELOPMENT_DATA: ann_ret={sm.returns.annualized_return_pct:.2f}%  ann_vol={sm.returns.volatility_annualized_pct or 0:.2f}%  "
          f"sharpe={sm.returns.sharpe_ratio or 0:.3f}  max_dd={sm.drawdown.max_drawdown_pct:.2f}%", flush=True)

    # --- BUY-AND-HOLD SPY benchmark (frictionless, Part 3/10) -------------------------------------
    bh_curve_disc = buy_and_hold_curve(bars_discovery, starting_cash=STARTING_CASH)
    bh_curve_dev = buy_and_hold_curve(bars_development, starting_cash=STARTING_CASH)
    bh_dev_returns = _period_returns(bh_curve_dev)
    bh_dev_total_return = ((bh_curve_dev[-1].equity - STARTING_CASH) / STARTING_CASH * 100) if bh_curve_dev else None
    print(f"  BUY_AND_HOLD_SPY on DEVELOPMENT_DATA: total_return={bh_dev_total_return:.2f}%" if bh_dev_total_return is not None else "  BUY_AND_HOLD_SPY: N/A", flush=True)

    # --- RETURN RETENTION (Part 12) + VOLATILITY REDUCTION ---------------------------------------
    print(f"\n{'=' * 100}\nPART 12 — RETURN RETENTION RATIO (frozen winner vs STATIC, DEVELOPMENT_DATA)\n{'=' * 100}", flush=True)
    vol_reduction = None
    return_retention = None
    if sm.returns.volatility_annualized_pct and dm.returns.volatility_annualized_pct is not None:
        vol_reduction = 1 - (dm.returns.volatility_annualized_pct / sm.returns.volatility_annualized_pct)
    if sm.returns.annualized_return_pct and dm.returns.annualized_return_pct is not None and sm.returns.annualized_return_pct != 0:
        return_retention = dm.returns.annualized_return_pct / sm.returns.annualized_return_pct
    print(f"  volatility_reduction_vs_static: {vol_reduction:.1%}" if vol_reduction is not None else "  volatility_reduction_vs_static: N/A", flush=True)
    print(f"  return_retention_ratio_vs_static: {return_retention:.1%}" if return_retention is not None else "  return_retention_ratio_vs_static: N/A", flush=True)

    # --- COST STRESS + EXECUTION STRESS on the frozen winner (Part 16, 27) -----------------------
    # Uses EQUITY-CURVE-based total return, not trade-level net_pnl — see
    # src/research/exposure_cost_stress.py's module docstring for why the trade-level
    # helpers (src.research.validation) mis-measure a continuously-rebalanced strategy's true P&L.
    print(f"\n{'=' * 100}\nCOST SENSITIVITY (1x/2x/3x) — frozen winner, DEVELOPMENT_DATA (equity-curve-based)\n{'=' * 100}", flush=True)
    mech_config = ExposureMechanismConfig(mechanism=frozen_config["mechanism"], target_annual_vol=frozen_config["target_annual_vol"], rebalance_frequency=frozen_config["rebalance_frequency"])
    frozen_strategy = PrecomputedExposureStrategy(strategy_id="P11-VCE-006-COSTSTRESS", exposure_by_symbol={SYMBOL: dev_exposure}, universe=[SYMBOL], hypothesis_id="P11-VCE-006")
    m2 = _models(1)
    cost_report = run_exposure_cost_stress(research_strategy=frozen_strategy, bars_by_symbol={SYMBOL: bars_development}, config=config_dev,
                                            execution_model=m2["execution_model"], base_slippage_model=m2["slippage_model"], base_cost_model=m2["cost_model"],
                                            spread_model=m2["spread_model"], position_sizer=m2["position_sizer"], risk_adapter=m2["risk_adapter"], multipliers=(1.0, 2.0, 3.0))
    print(cost_report.render(), flush=True)

    print(f"\n{'=' * 100}\nEXECUTION ROBUSTNESS (extended) — frozen winner, DEVELOPMENT_DATA (equity-curve-based)\n{'=' * 100}", flush=True)
    m3 = _models(1)
    exec_report = run_exposure_execution_stress(research_strategy=frozen_strategy, bars_by_symbol={SYMBOL: bars_development}, config=config_dev,
                                                 base_execution_model=m3["execution_model"], base_slippage_model=m3["slippage_model"], base_cost_model=m3["cost_model"],
                                                 spread_model=m3["spread_model"], position_sizer=m3["position_sizer"], risk_adapter=m3["risk_adapter"])
    print(exec_report.render(), flush=True)

    # --- BOOTSTRAP (Part 27) ----------------------------------------------------------------------
    print(f"\n{'=' * 100}\nBOOTSTRAP (block + stationary) — frozen winner's DEVELOPMENT_DATA daily returns (n={len(dev_returns)})\n{'=' * 100}", flush=True)
    block_report = block_bootstrap_return_series(dev_returns, block_size=5, n_resamples=2000, seed=401)
    stationary_report = stationary_bootstrap_return_series(dev_returns, mean_block_length=5.0, n_resamples=2000, seed=402)
    print(f"  {block_report.render()}", flush=True)
    print(f"  {stationary_report.render()}", flush=True)

    # --- DEFLATED SHARPE RATIO (Part 27) ------------------------------------------------------------
    print(f"\n{'=' * 100}\nDEFLATED SHARPE RATIO — frozen winner's DEVELOPMENT_DATA returns, n_trials={len(grid)} (the actual searched grid)\n{'=' * 100}", flush=True)
    dsr = deflated_sharpe_ratio(dev_returns, n_trials=len(grid))
    print(f"  {dsr.render()}", flush=True)

    # --- PLACEBO CONTROLS (Parts 25-26), on DEVELOPMENT_DATA, applied to the frozen winner --------
    print(f"\n{'=' * 100}\nPLACEBO CONTROLS — frozen winner's exposure mechanism vs RANDOM_EXPOSURE / SHUFFLED_VOLATILITY (DEVELOPMENT_DATA)\n{'=' * 100}", flush=True)
    random_series = random_exposure_series(dev_exposure, seed=501)
    shuffled_series = shuffled_exposure_series(dev_exposure, seed=502)
    random_strategy = PrecomputedExposureStrategy(strategy_id="P11-RANDOM-CONTROL", exposure_by_symbol={SYMBOL: random_series}, universe=[SYMBOL], hypothesis_id="P11-VCE-006")
    shuffled_strategy = PrecomputedExposureStrategy(strategy_id="P11-SHUFFLED-CONTROL", exposure_by_symbol={SYMBOL: shuffled_series}, universe=[SYMBOL], hypothesis_id="P11-VCE-006")
    random_result = run_research_backtest(research_strategy=random_strategy, bars_by_symbol={SYMBOL: bars_development}, config=config_dev, **_models(1))
    shuffled_result = run_research_backtest(research_strategy=shuffled_strategy, bars_by_symbol={SYMBOL: bars_development}, config=config_dev, **_models(1))
    rm_, sm_ = random_result.metrics, shuffled_result.metrics
    print(f"  REAL mechanism:      sharpe={dm.returns.sharpe_ratio or 0:.3f}  ann_vol={dm.returns.volatility_annualized_pct or 0:.2f}%  max_dd={dm.drawdown.max_drawdown_pct:.2f}%", flush=True)
    print(f"  RANDOM_EXPOSURE:     sharpe={rm_.returns.sharpe_ratio or 0:.3f}  ann_vol={rm_.returns.volatility_annualized_pct or 0:.2f}%  max_dd={rm_.drawdown.max_drawdown_pct:.2f}%", flush=True)
    print(f"  SHUFFLED_VOLATILITY: sharpe={sm_.returns.sharpe_ratio or 0:.3f}  ann_vol={sm_.returns.volatility_annualized_pct or 0:.2f}%  max_dd={sm_.drawdown.max_drawdown_pct:.2f}%", flush=True)
    real_beats_random = (dm.returns.sharpe_ratio or -999) > (rm_.returns.sharpe_ratio or -999)
    real_beats_shuffled = (dm.returns.sharpe_ratio or -999) > (sm_.returns.sharpe_ratio or -999)
    print(f"  real_beats_random_exposure (Sharpe): {real_beats_random}   real_beats_shuffled_volatility (Sharpe): {real_beats_shuffled}", flush=True)

    # --- TAIL RISK (Part 15) ------------------------------------------------------------------------
    from src.research.tail_risk import compute_tail_risk

    print(f"\n{'=' * 100}\nTAIL RISK — frozen winner vs STATIC, DEVELOPMENT_DATA\n{'=' * 100}", flush=True)
    winner_tail = compute_tail_risk(dev_returns)
    static_tail = compute_tail_risk(static_dev_returns)
    print(f"  winner: {winner_tail.render()}", flush=True)
    print(f"  static: {static_tail.render()}", flush=True)

    # --- RECOVERY TIME (Part 14) --------------------------------------------------------------------
    from src.research.tail_risk import recovery_time_bars

    winner_recovery = recovery_time_bars(list(dev_result.equity_curve))
    static_recovery = recovery_time_bars(list(static_dev_result.equity_curve))
    print(f"  winner max-drawdown recovery (bars): {winner_recovery}   static max-drawdown recovery (bars): {static_recovery}", flush=True)

    # --- PERSIST for step 3 ---------------------------------------------------------------------
    out = {
        "discovery_start": str(discovery.start_date), "discovery_end": str(discovery.end_date),
        "development_start": str(development.start_date), "development_end": str(development.end_date),
        "grid_results": grid_results, "winner_index": winner_idx, "winner_config": frozen_config, "winner_label": winner["label"],
        "selection_metric": SELECTION_METRIC, "pbo": pbo.pbo, "dsr": dsr.deflated_sharpe_ratio if dsr.applicable else None,
        "dev_metrics": {"sharpe": dm.returns.sharpe_ratio, "sortino": dm.returns.sortino_ratio, "calmar": dm.returns.calmar_ratio,
                         "annualized_return_pct": dm.returns.annualized_return_pct, "annualized_vol_pct": dm.returns.volatility_annualized_pct,
                         "max_drawdown_pct": dm.drawdown.max_drawdown_pct, "turnover": dm.portfolio.turnover, "avg_exposure_pct": dm.portfolio.average_exposure_pct},
        "static_dev_metrics": {"sharpe": sm.returns.sharpe_ratio, "annualized_return_pct": sm.returns.annualized_return_pct, "annualized_vol_pct": sm.returns.volatility_annualized_pct, "max_drawdown_pct": sm.drawdown.max_drawdown_pct},
        "return_retention_ratio": return_retention, "volatility_reduction": vol_reduction,
        "real_beats_random": real_beats_random, "real_beats_shuffled": real_beats_shuffled,
        "cost_sensitivity": [{"label": p.label, "ending_equity": p.ending_equity, "total_return_pct": p.total_return_pct, "viable": p.viable} for p in cost_report.points],
        "execution_robustness": [{"label": p.label, "ending_equity": p.ending_equity, "total_return_pct": p.total_return_pct, "viable": p.viable} for p in exec_report.points],
        "winner_recovery_bars": winner_recovery, "static_recovery_bars": static_recovery,
        "n_grid_variants": len(grid), "n_placebo_controls": 2,
    }
    out_path = Path("logs/research_data/phase11_grid_results.json")
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWritten to {out_path}", flush=True)
    print("\nSTEP 2 COMPLETE.", flush=True)


if __name__ == "__main__":
    main()
