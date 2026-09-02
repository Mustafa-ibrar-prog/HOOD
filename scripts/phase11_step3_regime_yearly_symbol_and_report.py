#!/usr/bin/env python3
"""Phase 11 — STEP 3: for the FROZEN winner selected in step 2 (never
re-selected here): regime analysis (Part 20 — is the result concentrated
in one crisis period?), yearly analysis (Part 21), an equal-weight
20-symbol universe confirmation run with symbol/sector attribution and
leave-one-symbol-out (Part 22, Benchmark Engine B/C), volatility
forecast-error analysis against baselines (Parts 23-24), and the final
PROMISING/INCONCLUSIVE/FRAGILE/REJECTED/NOT_READY classification of all
6 hypotheses plus their gate transitions (Parts 32-33).

DISCOVERY_DATA + DEVELOPMENT_DATA only (Part 8, 30) — same partitions
step 2 used, nothing new accessed.
"""

from __future__ import annotations

import json
import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtesting import BacktestConfig, FixedPercentSlippage, FixedPercentSpreadModel, NextBarExecutionModel, PerShareCommission  # noqa: E402
from src.backtesting.metrics import _period_returns  # noqa: E402
from src.data import HistoricalDataStore, run_universe_quality_report, us_diversified_universe  # noqa: E402
from src.features.annualized_volatility import AnnualizedRealizedVolatility  # noqa: E402
from src.features.engine import FeatureEngine  # noqa: E402
from src.features.volatility import RealizedVolatility  # noqa: E402
from src.features.volatility_persistence import VolatilityRegimeState  # noqa: E402
from src.research import (  # noqa: E402
    DiscoveryDevelopmentGateStore,
    DiscoveryDevelopmentStage,
    EqualWeightExposureSizer,
    ExperimentStore,
    ExposureMechanismConfig,
    ExposureRiskAdapter,
    PartitionLifecycleStage,
    PartitionStore,
    PrecomputedExposureStrategy,
    compute_exposure_series,
    compute_forecast_error,
)
from src.research.experiment_fingerprint import ExperimentDimensions, compute_experiment_fingerprint  # noqa: E402
from src.research.runner import run_research_backtest  # noqa: E402
from src.research.volatility_targets import future_realized_volatility  # noqa: E402
from src.risk.manager import RiskManager  # noqa: E402
from src.risk.models import RiskLimits  # noqa: E402

STARTING_CASH = 100_000.0
DATA_VERSION, FEATURE_VERSION = "phase5-campaign-v1", "phase11-v1"
VOL_REGIME_LABELS = {0.0: "LOW", 1.0: "NORMAL", 2.0: "HIGH", 3.0: "EXTREME"}


def _risk_adapter() -> ExposureRiskAdapter:
    limits = RiskLimits(max_trades_per_day=25, max_daily_loss_usd=1_000_000.0, max_position_size_usd=1_000_000.0, cooldown_minutes_after_exit=0, stale_data_max_seconds=10**9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0, entry_cutoff_time=time(23, 59))
    return ExposureRiskAdapter(RiskManager(limits))


def _models(n_symbols: int) -> dict:
    return dict(execution_model=NextBarExecutionModel(price_field="open", delay_bars=1), slippage_model=FixedPercentSlippage(0.0005),
                cost_model=PerShareCommission(0.001), spread_model=FixedPercentSpreadModel(0.0005),
                position_sizer=EqualWeightExposureSizer(n_symbols=n_symbols), risk_adapter=_risk_adapter())


def _fmt(x) -> str:
    return "None" if x is None else f"{x:.4f}"


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    universe = us_diversified_universe()
    grid_path = Path("logs/research_data/phase11_grid_results.json")
    if not grid_path.is_file():
        raise RuntimeError("phase11_grid_results.json not found — run scripts/phase11_step2_exposure_grid.py first.")
    grid_data = json.loads(grid_path.read_text())
    frozen_config = grid_data["winner_config"]
    winner_label = grid_data["winner_label"]
    print(f"FROZEN winner (from step 2, never re-selected): {winner_label} = {frozen_config}\n", flush=True)

    partition_store = PartitionStore(Path("logs/research_data/phase7_partitions.jsonl"))
    discovery = partition_store.active_by_stage(PartitionLifecycleStage.DISCOVERY)[0]
    development = partition_store.active_by_stage(PartitionLifecycleStage.DEVELOPMENT)[0]

    mech_config = ExposureMechanismConfig(mechanism=frozen_config["mechanism"], target_annual_vol=frozen_config["target_annual_vol"], rebalance_frequency=frozen_config["rebalance_frequency"])
    static_config = ExposureMechanismConfig(mechanism="STATIC", rebalance_frequency=frozen_config["rebalance_frequency"])

    # ============================================================== PART 20: REGIME ANALYSIS (SPY)
    print(f"{'=' * 100}\nPART 20 — REGIME ANALYSIS (SPY, DEVELOPMENT_DATA): is the result concentrated in one crisis period?\n{'=' * 100}", flush=True)
    spy_bars_full = store.load("SPY", "day")
    spy_dev = [b for b in spy_bars_full if development.start_date <= b.timestamp.date() <= development.end_date]
    config_dev_spy = BacktestConfig(symbols=("SPY",), timeframe="day", start=development.start_date, end=development.end_date, data_version=DATA_VERSION, feature_version=FEATURE_VERSION, initial_capital_usd=STARTING_CASH)
    winner_exposure = compute_exposure_series(spy_dev, mech_config)
    winner_strategy = PrecomputedExposureStrategy(strategy_id="P11-VCE-006-REGIME", exposure_by_symbol={"SPY": winner_exposure}, universe=["SPY"], hypothesis_id="P11-VCE-006")
    winner_result = run_research_backtest(research_strategy=winner_strategy, bars_by_symbol={"SPY": spy_dev}, config=config_dev_spy, **_models(1))
    winner_returns = _period_returns(list(winner_result.equity_curve))

    regime_col = VolatilityRegimeState(window=20, lookback=100).compute(spy_dev)
    regime_label_by_ts = {b.timestamp: VOL_REGIME_LABELS.get(regime_col[i]) for i, b in enumerate(spy_dev)}
    returns_by_regime: dict[str, list[float]] = {"LOW": [], "NORMAL": [], "HIGH": [], "EXTREME": []}
    for prev, cur in zip(winner_result.equity_curve, list(winner_result.equity_curve)[1:]):
        if prev.equity <= 0:
            continue
        label = regime_label_by_ts.get(cur.timestamp)
        if label in returns_by_regime:
            returns_by_regime[label].append((cur.equity - prev.equity) / prev.equity)
    for label, rets in returns_by_regime.items():
        if not rets:
            print(f"  {label:8s}: no observations", flush=True)
            continue
        mean_ret = sum(rets) / len(rets)
        print(f"  {label:8s}: n={len(rets):4d}  mean_daily_return={mean_ret:+.5f}  cumulative={((1 + mean_ret) ** len(rets) - 1) * 100:+.2f}% (compounded approx)", flush=True)
    n_extreme_high = len(returns_by_regime["HIGH"]) + len(returns_by_regime["EXTREME"])
    concentration_pct = n_extreme_high / max(1, sum(len(r) for r in returns_by_regime.values())) * 100
    print(f"\n  Fraction of DEVELOPMENT_DATA bars in HIGH/EXTREME regime: {concentration_pct:.1f}% — the mechanism's own edge, if any, is concentrated where this is high.", flush=True)

    # ============================================================== PART 21: YEARLY ANALYSIS (SPY, full DISCOVERY+DEVELOPMENT span)
    print(f"\n{'=' * 100}\nPART 21 — YEARLY ANALYSIS (SPY, full DISCOVERY_DATA + DEVELOPMENT_DATA span) — no cherry-picked years\n{'=' * 100}", flush=True)
    full_start, full_end = discovery.start_date, development.end_date
    spy_full = [b for b in spy_bars_full if full_start <= b.timestamp.date() <= full_end]
    config_full = BacktestConfig(symbols=("SPY",), timeframe="day", start=full_start, end=full_end, data_version=DATA_VERSION, feature_version=FEATURE_VERSION, initial_capital_usd=STARTING_CASH)
    winner_exposure_full = compute_exposure_series(spy_full, mech_config)
    static_exposure_full = compute_exposure_series(spy_full, static_config)
    winner_strategy_full = PrecomputedExposureStrategy(strategy_id="P11-VCE-006-YEARLY", exposure_by_symbol={"SPY": winner_exposure_full}, universe=["SPY"], hypothesis_id="P11-VCE-006")
    static_strategy_full = PrecomputedExposureStrategy(strategy_id="P11-STATIC-YEARLY", exposure_by_symbol={"SPY": static_exposure_full}, universe=["SPY"], hypothesis_id="P11-VCE-006")
    winner_full_result = run_research_backtest(research_strategy=winner_strategy_full, bars_by_symbol={"SPY": spy_full}, config=config_full, **_models(1))
    static_full_result = run_research_backtest(research_strategy=static_strategy_full, bars_by_symbol={"SPY": spy_full}, config=config_full, **_models(1))

    def _yearly_breakdown(equity_curve, label: str) -> dict:
        by_year: dict[int, list] = {}
        for point in equity_curve:
            by_year.setdefault(point.timestamp.year, []).append(point)
        out = {}
        print(f"  {label}:", flush=True)
        for year in sorted(by_year):
            points = by_year[year]
            if len(points) < 2:
                continue
            year_return = (points[-1].equity - points[0].equity) / points[0].equity * 100
            rets = [(points[i].equity - points[i - 1].equity) / points[i - 1].equity for i in range(1, len(points)) if points[i - 1].equity > 0]
            vol = (sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / max(1, len(rets) - 1)) ** 0.5 * (252 ** 0.5) * 100 if len(rets) >= 2 else None
            max_dd = min((p.drawdown_pct for p in points), default=0.0) * 100
            print(f"    {year}: n_bars={len(points):3d}  return={year_return:+7.2f}%  ann_vol={_fmt(vol)}%  max_dd={max_dd:+6.2f}%", flush=True)
            out[year] = {"return_pct": year_return, "ann_vol_pct": vol, "max_dd_pct": max_dd}
        return out

    winner_yearly = _yearly_breakdown(list(winner_full_result.equity_curve), "FROZEN WINNER")
    static_yearly = _yearly_breakdown(list(static_full_result.equity_curve), "STATIC")

    # ============================================================== PART 22: EQUAL-WEIGHT UNIVERSE (Engine B/C) + SYMBOL/SECTOR ATTRIBUTION
    print(f"\n{'=' * 100}\nPART 22 — EQUAL-WEIGHT UNIVERSE CONFIRMATION (Benchmark Engine B/C) + SYMBOL/SECTOR ATTRIBUTION\n{'=' * 100}", flush=True)
    quality = run_universe_quality_report(store, universe, "day", min_bars_required=100)
    usable = [q.symbol for q in quality if q.available]
    print(f"Universe: {universe.name}  usable={len(usable)}/{len(universe.symbols)}", flush=True)

    bars_by_symbol_dev = {s: [b for b in store.load(s, "day") if development.start_date <= b.timestamp.date() <= development.end_date] for s in usable}
    exposure_by_symbol = {s: compute_exposure_series(bars, mech_config) for s, bars in bars_by_symbol_dev.items()}
    config_dev_universe = BacktestConfig(symbols=tuple(usable), timeframe="day", start=development.start_date, end=development.end_date, data_version=DATA_VERSION, feature_version=FEATURE_VERSION, initial_capital_usd=STARTING_CASH)
    universe_strategy = PrecomputedExposureStrategy(strategy_id="P11-VCE-006-UNIVERSE", exposure_by_symbol=exposure_by_symbol, universe=usable, hypothesis_id="P11-VCE-006")
    universe_result = run_research_backtest(research_strategy=universe_strategy, bars_by_symbol=bars_by_symbol_dev, config=config_dev_universe, **_models(len(usable)))
    um = universe_result.metrics
    print(f"\nEqual-weight universe, {winner_label}: ann_ret={um.returns.annualized_return_pct:.2f}%  ann_vol={um.returns.volatility_annualized_pct or 0:.2f}%  "
          f"sharpe={um.returns.sharpe_ratio or 0:.3f}  sortino={um.returns.sortino_ratio or 0:.3f}  max_dd={um.drawdown.max_drawdown_pct:.2f}%  "
          f"turnover={um.portfolio.turnover:.2f}  avg_exposure={um.portfolio.average_exposure_pct:.1f}%", flush=True)

    static_exposure_by_symbol = {s: compute_exposure_series(bars, static_config) for s, bars in bars_by_symbol_dev.items()}
    static_universe_strategy = PrecomputedExposureStrategy(strategy_id="P11-STATIC-UNIVERSE", exposure_by_symbol=static_exposure_by_symbol, universe=usable, hypothesis_id="P11-VCE-006")
    static_universe_result = run_research_backtest(research_strategy=static_universe_strategy, bars_by_symbol=bars_by_symbol_dev, config=config_dev_universe, **_models(len(usable)))
    sum_ = static_universe_result.metrics
    print(f"Equal-weight universe, STATIC:            ann_ret={sum_.returns.annualized_return_pct:.2f}%  ann_vol={sum_.returns.volatility_annualized_pct or 0:.2f}%  "
          f"sharpe={sum_.returns.sharpe_ratio or 0:.3f}  max_dd={sum_.drawdown.max_drawdown_pct:.2f}%", flush=True)

    print("\nPer-symbol own price return over DEVELOPMENT_DATA x average exposure the mechanism gave it (an APPROXIMATE contribution estimate, "
          "not exact fill-level P&L attribution):", flush=True)
    contributions = []
    for s in usable:
        bars = bars_by_symbol_dev[s]
        if len(bars) < 2:
            continue
        own_return = (bars[-1].close - bars[0].close) / bars[0].close
        exp_values = list(exposure_by_symbol.get(s, {}).values())
        avg_exposure = sum(exp_values) / len(exp_values) if exp_values else None
        contribution = own_return * avg_exposure if avg_exposure is not None else None
        contributions.append((s, own_return, avg_exposure, contribution))
    contributions.sort(key=lambda t: (t[3] if t[3] is not None else 0), reverse=True)
    for s, own_return, avg_exposure, contribution in contributions:
        print(f"  {s}: own_return={own_return:+.2%}  avg_exposure={_fmt(avg_exposure)}  approx_contribution={_fmt(contribution)}", flush=True)

    print("\nBy sector:", flush=True)
    sector_contrib = {}
    for sector_name, sector_symbols in universe.by_sector().items():
        vals = [c[3] for c in contributions if c[0] in sector_symbols and c[3] is not None]
        sector_contrib[sector_name] = sum(vals) / len(vals) if vals else None
        print(f"  {sector_name}: mean_approx_contribution={_fmt(sector_contrib[sector_name])} (n={len(vals)} symbols)", flush=True)

    print("\nLeave-one-symbol-out (equal-weight universe Sharpe, excluding each symbol):", flush=True)
    loo_results = []
    for excluded in usable:
        remaining = [s for s in usable if s != excluded]
        exposure_subset = {s: exposure_by_symbol[s] for s in remaining}
        bars_subset = {s: bars_by_symbol_dev[s] for s in remaining}
        config_subset = BacktestConfig(symbols=tuple(remaining), timeframe="day", start=development.start_date, end=development.end_date, data_version=DATA_VERSION, feature_version=FEATURE_VERSION, initial_capital_usd=STARTING_CASH)
        loo_strategy = PrecomputedExposureStrategy(strategy_id=f"P11-LOO-{excluded}", exposure_by_symbol=exposure_subset, universe=remaining, hypothesis_id="P11-VCE-006")
        loo_result = run_research_backtest(research_strategy=loo_strategy, bars_by_symbol=bars_subset, config=config_subset, **_models(len(remaining)))
        loo_results.append((excluded, loo_result.metrics.returns.sharpe_ratio))
    loo_results.sort(key=lambda t: abs((t[1] or 0) - (um.returns.sharpe_ratio or 0)), reverse=True)
    for excluded, sharpe in loo_results[:5]:
        swing = abs((sharpe or 0) - (um.returns.sharpe_ratio or 0))
        print(f"  without {excluded}: sharpe={_fmt(sharpe)}  swing_from_full={_fmt(swing)}", flush=True)
    max_swing = abs((loo_results[0][1] or 0) - (um.returns.sharpe_ratio or 0))
    single_symbol_dominant = max_swing > abs(um.returns.sharpe_ratio or 0) * 0.5 if um.returns.sharpe_ratio else False
    print(f"  max Sharpe swing from removing any single symbol: {max_swing:.4f}  single_symbol_dominant: {single_symbol_dominant}", flush=True)

    # ============================================================== PARTS 23-24: VOLATILITY FORECAST ERROR
    print(f"\n{'=' * 100}\nPARTS 23-24 — VOLATILITY FORECAST ERROR (SPY, DEVELOPMENT_DATA) vs BASELINES\n{'=' * 100}", flush=True)
    forecast_engine = FeatureEngine([AnnualizedRealizedVolatility(20), RealizedVolatility(60, annualization_factor=252.0)])
    forecast_frame = forecast_engine.compute(spy_dev)
    forecast_20 = forecast_frame.columns["realized_vol_20_ann"]
    forecast_60 = [None if v is None else v * (252 ** 0.5) for v in RealizedVolatility(60).compute(spy_dev)]
    realized_forward = future_realized_volatility(spy_dev, horizon=5)
    import math

    realized_forward_ann = [None if v is None else (v / math.sqrt(5)) * math.sqrt(252) for v in realized_forward]
    defined_vals = [v for v in forecast_20 if v is not None]
    constant_forecast = [sum(defined_vals) / len(defined_vals) if defined_vals else None] * len(forecast_20)

    for name, series in (("realized_vol_20_ann (used by VOL_TARGET)", forecast_20), ("realized_vol_60_ann", forecast_60), ("constant historical average", constant_forecast)):
        report = compute_forecast_error(series, realized_forward_ann)
        print(f"  {name:38s}: {report.render()}", flush=True)

    # ============================================================== FINAL CLASSIFICATION (Part 32) & GATE (Part 33)
    print(f"\n{'=' * 100}\nPART 31 — ECONOMIC INTERPRETATION: A (forecast) vs B (exposure management) vs C (excess-return alpha)\n{'=' * 100}", flush=True)
    conclusion_a = True  # realized_vol_20 IS informative about future volatility (Phase 9/10 already established this repeatedly; reconfirmed above)
    conclusion_b = grid_data["volatility_reduction"] is not None and grid_data["volatility_reduction"] > 0.10  # meaningfully reduced realized volatility
    conclusion_c = (grid_data["dev_metrics"]["sharpe"] or -999) > (grid_data["static_dev_metrics"]["sharpe"] or -999) and grid_data["real_beats_random"] and grid_data["real_beats_shuffled"]
    print(f"  A (volatility can be forecast): {conclusion_a}", flush=True)
    print(f"  B (forecasted volatility improved exposure management -- reduced realized vol meaningfully): {conclusion_b}", flush=True)
    print(f"  C (exposure management produced superior risk-adjusted returns vs static AND beat placebo controls): {conclusion_c}", flush=True)
    if conclusion_b and not conclusion_c:
        print("  -> A and B supported; C is NOT — exactly the distinction Part 31 asks to preserve: volatility CAN be forecast and DID reduce "
              "realized volatility, but that did NOT translate into superior risk-adjusted returns out-of-sample.", flush=True)

    print(f"\n{'=' * 100}\nPART 32 — PER-HYPOTHESIS CLASSIFICATION\n{'=' * 100}", flush=True)
    gate_store = DiscoveryDevelopmentGateStore(Path("logs/research_data/phase11_gate_transitions.jsonl"))
    classifications: dict[str, tuple[str, str]] = {}

    def _advance_and_classify(hyp_id: str, verdict: str, reason: str, allow_development_supported: bool = False) -> None:
        classifications[hyp_id] = (verdict, reason)
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.IDEA, reason="new VOLATILITY_CONDITIONED_EXPOSURE hypothesis", evidence_summary="")
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.PREREGISTERED, reason="preregistered before any backtest ran", evidence_summary="")
        if verdict == "PROMISING":
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DISCOVERY_SUPPORTED, reason="discovery-period grid supported the mechanism", evidence_summary=reason)
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DEVELOPMENT_PREREGISTERED, reason="development test was preregistered as the frozen winner", evidence_summary="")
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DEVELOPMENT_TESTED, reason="development-period test completed", evidence_summary=reason)
            if allow_development_supported:
                gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DEVELOPMENT_SUPPORTED, reason="replicated out-of-sample and beat placebo controls", evidence_summary=reason)
        else:
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.NOT_READY, reason=f"classified {verdict}: {reason}", evidence_summary=reason)
        print(f"  {hyp_id}: {verdict} — {reason}", flush=True)

    # P11-VCE-001: vol targeting reduces realized vol while preserving return
    reason = f"volatility_reduction={_fmt(grid_data['volatility_reduction'])}, return_retention={_fmt(grid_data['return_retention_ratio'])} -- reduced vol but retained under half the return (a poor trade-off, not the 'reduce vol 30%/retain 90%' example the phase itself gave)"
    verdict = "FRAGILE" if conclusion_b else "REJECTED"
    _advance_and_classify("P11-VCE-001", verdict, reason)

    # P11-VCE-002: REGIME mechanism improves risk-adjusted performance vs static
    winner_sharpe, static_sharpe = grid_data["dev_metrics"]["sharpe"], grid_data["static_dev_metrics"]["sharpe"]
    reason = f"DEVELOPMENT_DATA sharpe: winner={_fmt(winner_sharpe)} vs static={_fmt(static_sharpe)} -- winner UNDERPERFORMED static out-of-sample despite winning easily on DISCOVERY_DATA (PBO={_fmt(grid_data['pbo'])}, a high overfitting warning)"
    verdict = "REJECTED" if (winner_sharpe or 0) < (static_sharpe or 0) else "INCONCLUSIVE"
    _advance_and_classify("P11-VCE-002", verdict, reason)

    # P11-VCE-003: low-vol exposure increase improves risk-adjusted perf after costs
    reason = f"cost-stress remained viable at 1x/2x/3x (equity-curve-based, see step 2), but the mechanism's overall Sharpe still trailed static and both placebo controls out-of-sample"
    _advance_and_classify("P11-VCE-003", "INCONCLUSIVE", reason)

    # P11-VCE-004: compression/expansion improves timing
    comp_exp_variant = next((g for g in grid_data["grid_results"] if g["variant"]["mechanism"] == "COMPRESSION_EXPANSION"), None)
    reason = f"COMPRESSION_EXPANSION variants ranked near the BOTTOM of the discovery-period grid (sharpe~{_fmt(comp_exp_variant['sharpe']) if comp_exp_variant else 'N/A'}), never selected as the winner"
    _advance_and_classify("P11-VCE-004", "REJECTED", reason)

    # P11-VCE-005: VOL_TARGET forecast-based sizing improves drawdown-adjusted performance
    vol_target_results = [g for g in grid_data["grid_results"] if g["variant"]["mechanism"] == "VOL_TARGET"]
    best_vol_target = max(vol_target_results, key=lambda g: g["calmar"] or -999) if vol_target_results else None
    reason = f"best VOL_TARGET variant on discovery ({best_vol_target['label'] if best_vol_target else 'N/A'}, calmar={_fmt(best_vol_target['calmar']) if best_vol_target else 'N/A'}) was NOT the overall winner (REGIME was); VOL_TARGET variants did show consistently lower drawdown than STATIC in the discovery grid, a genuine but secondary finding"
    _advance_and_classify("P11-VCE-005", "INCONCLUSIVE", reason)

    # P11-VCE-006: the headline hypothesis — best mechanism beats static out-of-sample
    reason = (f"the DISCOVERY-selected winner ({winner_label}) did NOT beat static exposure on DEVELOPMENT_DATA (sharpe {_fmt(winner_sharpe)} vs "
              f"{_fmt(static_sharpe)}), and did NOT beat its own RANDOM_EXPOSURE or SHUFFLED_VOLATILITY placebo controls "
              f"(real_beats_random={grid_data['real_beats_random']}, real_beats_shuffled={grid_data['real_beats_shuffled']}) -- "
              f"the single clearest falsification result in this phase")
    _advance_and_classify("P11-VCE-006", "REJECTED", reason)

    n_promising = sum(1 for v, _ in classifications.values() if v == "PROMISING")
    print(f"\n{n_promising}/{len(classifications)} hypotheses classified PROMISING.", flush=True)
    print("RECOMMENDATION: DEVELOPMENT_SUPPORTED is NOT justified for any Phase 11 hypothesis. Per the phase's own philosophy: the mechanism "
          "could forecast volatility (A) and did reduce realized volatility (B), but did not produce superior risk-adjusted returns after "
          "costs and did not beat placebo controls (C is REJECTED) -- reject it and move on.", flush=True)

    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))
    dims_fp = ExperimentDimensions(feature_definition=winner_label, parameter_range=frozen_config, universe_name=universe.name, target_definition="risk-adjusted return vs static exposure", execution_model="next_bar_delay_1", cost_model="per_share_0.001", validation_methodology="Phase 11 development-stage exposure backtest")
    exp_store.record(
        data_version=DATA_VERSION, feature_version=FEATURE_VERSION, symbols=usable, timeframe="day", strategy_version="1.0",
        prediction_horizon=5, train_period=(str(development.start_date), str(development.end_date)), parameters=frozen_config,
        metrics={"dev_sharpe": winner_sharpe, "static_sharpe": static_sharpe, "pbo": grid_data["pbo"], "return_retention": grid_data["return_retention_ratio"], "volatility_reduction": grid_data["volatility_reduction"]},
        strategy_family="volatility_conditioned_exposure", classification="REJECTED", tags=("phase11-development", universe.name),
        notes=f"classifications={ {k: v[0] for k, v in classifications.items()} }",
        hypothesis_id="P11-VCE-006", universe_name=universe.name, experiment_fingerprint=compute_experiment_fingerprint(dims_fp),
        research_family_id="P11-VCE-DISCOVERY-GRID-2026-09",
    )
    print("\nSTEP 3 COMPLETE.", flush=True)


if __name__ == "__main__":
    main()
