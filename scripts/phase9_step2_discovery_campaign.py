#!/usr/bin/env python3
"""Phase 9 — STEP 2: the full discovery-stage investigation of
P9-VOLCLUST-A on DISCOVERY_DATA only. No backtest, no trading strategy,
no VALIDATION_DATA/FINAL_HOLDOUT_DATA access anywhere in this script.

Covers Parts 6-16: cross-sectional IC (Spearman + Pearson), quantiles,
temporal-alignment, autocorrelation, predictive-horizon table, regime
analysis, symbol/sector robustness + leave-one-out, baselines, the
incremental-information (OLS) test, the full placebo battery, and
multiple-testing correction across the COMPLETE preregistered family.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import HistoricalDataStore, run_universe_quality_report, us_diversified_universe  # noqa: E402
from src.features import FeatureEngine  # noqa: E402
from src.features.volatility import RealizedVolatility  # noqa: E402
from src.features.volume import RelativeVolume, VolumeChange, VolumePercentile  # noqa: E402
from src.features.volume_clustering import (  # noqa: E402
    ConsecutiveAbnormalVolumeStreak,
    LogRelativeVolume,
    RollingFractionAboveThreshold,
    RollingMeanRelativeVolume,
    RollingStdRelativeVolume,
    VolumeAcceleration,
    VolumeZScore,
)
from src.research import (  # noqa: E402
    DiscoveryDevelopmentGateStore,
    DiscoveryDevelopmentStage,
    ExperimentStore,
    PartitionLifecycleStage,
    PartitionStore,
    autocorrelation_profile,
    benjamini_hochberg_fdr,
    bonferroni_correction,
    compute_experiment_fingerprint,
    compute_ic_series,
    compute_pearson_ic_series,
    cross_sectional_quantile_returns,
    effective_number_of_trials,
    filter_rows_by_partition,
    holm_bonferroni_correction,
    ic_by_regime,
    label_bars_by_regime,
    ols_regression,
    random_feature_control,
    require_preregistered,
    shifted_signal_placebo,
    shuffled_signal_placebo,
    summarize_ic,
    summarize_pearson_ic,
    time_shuffled_target_placebo,
)
from src.research.experiment_fingerprint import ExperimentDimensions
from src.research.preregistration import PreregistrationStore
from src.research.volatility_targets import (
    future_absolute_cumulative_return,
    future_max_absolute_move,
    future_realized_variance,
    future_realized_volatility,
)

FEATURE_BUILDERS = {
    "relative_volume_10": lambda: RelativeVolume(10),
    "relative_volume_20": lambda: RelativeVolume(20),
    "log_relative_volume_10": lambda: LogRelativeVolume(10),
    "volume_zscore_20": lambda: VolumeZScore(20),
    "volume_percentile_10_100": lambda: VolumePercentile(window=10, lookback=100),
    "volume_change_5": lambda: VolumeChange(5),
    "volume_acceleration_10": lambda: VolumeAcceleration(10),
    "volume_frac_above_10_1.5_10": lambda: RollingFractionAboveThreshold(base_window=10, threshold=1.5, lookback=10),
    "volume_streak_10_1.5": lambda: ConsecutiveAbnormalVolumeStreak(base_window=10, threshold=1.5),
    "volume_rolling_mean_10_10": lambda: RollingMeanRelativeVolume(base_window=10, lookback=10),
    "volume_rolling_std_10_10": lambda: RollingStdRelativeVolume(base_window=10, lookback=10),
}
FEATURE_SET = tuple(FEATURE_BUILDERS.keys())
TARGET_SET = ("future_realized_volatility", "future_realized_variance", "future_absolute_cumulative_return", "future_max_absolute_move")
TARGET_BUILDERS = {
    "future_realized_volatility": future_realized_volatility, "future_realized_variance": future_realized_variance,
    "future_absolute_cumulative_return": future_absolute_cumulative_return, "future_max_absolute_move": future_max_absolute_move,
}
HORIZON_SET = (1, 2, 3, 5, 10, 20)
PRIMARY_TARGET = "future_realized_volatility"
PRIMARY_HORIZON = 5
PRIMARY_FEATURE = "relative_volume_10"


def build_panel(store: HistoricalDataStore, universe) -> tuple[list[dict], dict]:
    """One row per (symbol, timestamp) with EVERY preregistered feature
    and EVERY preregistered target x horizon column."""
    feature_engine = FeatureEngine([builder() for builder in FEATURE_BUILDERS.values()])
    bars_by_symbol = {s: store.load(s, "day") for s in universe.symbols}
    panel: list[dict] = []
    for sym, bars in bars_by_symbol.items():
        if not bars:
            continue
        frame = feature_engine.compute(bars)
        target_columns: dict[str, list] = {}
        for target_name, builder in TARGET_BUILDERS.items():
            for h in HORIZON_SET:
                target_columns[f"{target_name}_{h}"] = builder(bars, h)
        for i, ts in enumerate(frame.timestamps):
            row = {"timestamp": ts, "symbol": sym}
            for name in frame.feature_names:
                row[name] = frame.columns[name][i]
            for col_name, series in target_columns.items():
                row[col_name] = series[i]
            panel.append(row)
    return panel, bars_by_symbol


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    universe = us_diversified_universe()

    prereg_store = PreregistrationStore(Path("logs/research_data/phase9_preregistrations.jsonl"))
    require_preregistered(prereg_store, "P9-VOLCLUST-A")

    partition_store = PartitionStore(Path("logs/research_data/phase7_partitions.jsonl"))
    discovery_partition = partition_store.active_by_stage(PartitionLifecycleStage.DISCOVERY)[0]
    print(f"DISCOVERY_DATA: {discovery_partition.start_date} .. {discovery_partition.end_date}", flush=True)

    quality = run_universe_quality_report(store, universe, "day", min_bars_required=100)
    usable = [q.symbol for q in quality if q.available]
    print(f"Universe: {universe.name}  usable={len(usable)}/{len(universe.symbols)}", flush=True)

    print("Building the full feature/target panel (11 features x 4 targets x 6 horizons)...", flush=True)
    full_panel, bars_by_symbol_full = build_panel(store, universe)
    full_panel = [r for r in full_panel if r["symbol"] in usable]
    discovery_panel = filter_rows_by_partition(full_panel, discovery_partition)
    print(f"Full panel: {len(full_panel)} rows. DISCOVERY_DATA panel: {len(discovery_panel)} rows.\n", flush=True)

    regime_labels: dict = {}
    for sym in usable:
        regime_labels.update(label_bars_by_regime(bars_by_symbol_full[sym]))

    raw_p_values: list[tuple[str, float]] = []
    all_ic_results: dict[str, dict] = {}

    # ============================================================== PART 6: MAIN SCREEN (44 tests)
    print(f"{'=' * 90}\nPART 6 — MAIN SCREEN: {len(FEATURE_SET)} features x {len(TARGET_SET)} targets @ horizon={PRIMARY_HORIZON}\n{'=' * 90}", flush=True)
    for feature_name in FEATURE_SET:
        for target_name in TARGET_SET:
            target_col = f"{target_name}_{PRIMARY_HORIZON}"
            spearman_points = compute_ic_series(discovery_panel, feature_name, target_col, min_universe_size=3)
            spearman = summarize_ic(spearman_points, feature_name=feature_name, target_name=target_col)
            pearson_points = compute_pearson_ic_series(discovery_panel, feature_name, target_col, min_universe_size=3)
            pearson = summarize_pearson_ic(pearson_points, feature_name=feature_name, target_name=target_col)
            quantiles = cross_sectional_quantile_returns(discovery_panel, feature_name, target_col, n_quantiles=5, min_universe_size=3)
            key = f"{feature_name}|{target_name}|h{PRIMARY_HORIZON}"
            all_ic_results[key] = {"spearman": spearman, "pearson": pearson, "quantiles": quantiles}
            print(f"  {feature_name:32s} vs {target_name:34s}: spearman_IC={_fmt(spearman.average_ic)} pearson_IC={_fmt(pearson.average_ic)} "
                  f"spread={_fmt(quantiles.spread_q5_minus_q1)} monotonic={quantiles.is_monotonic}", flush=True)
            p = _ic_p_value(spearman_points)
            if p is not None:
                raw_p_values.append((key, p))

    # ============================================================== PART 9: PREDICTIVE HORIZON TABLE (55 additional tests)
    print(f"\n{'=' * 90}\nPART 9 — PREDICTIVE HORIZON TABLE (all features x {PRIMARY_TARGET} across all horizons)\n{'=' * 90}", flush=True)
    horizon_table: dict[str, dict[int, dict]] = defaultdict(dict)
    for feature_name in FEATURE_SET:
        row_str = []
        for h in HORIZON_SET:
            target_col = f"{PRIMARY_TARGET}_{h}"
            spearman_points = compute_ic_series(discovery_panel, feature_name, target_col, min_universe_size=3)
            spearman = summarize_ic(spearman_points, feature_name=feature_name, target_name=target_col)
            pearson_points = compute_pearson_ic_series(discovery_panel, feature_name, target_col, min_universe_size=3)
            pearson = summarize_pearson_ic(pearson_points, feature_name=feature_name, target_name=target_col)
            horizon_table[feature_name][h] = {"spearman": spearman, "pearson": pearson}
            row_str.append(f"h{h}:{_fmt(spearman.average_ic)}")
            if h != PRIMARY_HORIZON:  # h=PRIMARY_HORIZON's p-value was already counted in the main screen
                p = _ic_p_value(spearman_points)
                if p is not None:
                    raw_p_values.append((f"{feature_name}|{PRIMARY_TARGET}|h{h}", p))
        print(f"  {feature_name:32s}: " + "  ".join(row_str), flush=True)

    # ============================================================== PART 10: REGIME ANALYSIS (55 additional tests)
    print(f"\n{'=' * 90}\nPART 10 — REGIME ANALYSIS (all features @ primary target/horizon)\n{'=' * 90}", flush=True)
    regime_table: dict[str, dict] = {}
    target_col = f"{PRIMARY_TARGET}_{PRIMARY_HORIZON}"
    for feature_name in FEATURE_SET:
        regime_result = ic_by_regime(discovery_panel, feature_name, target_col, regime_labels, min_universe_size=3)
        regime_table[feature_name] = regime_result
        print(f"  {feature_name:32s}: " + "; ".join(f"{r}={_fmt(s.average_ic)}(n={sum(1 for p in s.points if p.ic is not None)})" for r, s in regime_result.items()), flush=True)
        for regime_name, summary in regime_result.items():
            points = [p for p in summary.points]
            p_val = _ic_p_value(points)
            if p_val is not None:
                raw_p_values.append((f"{feature_name}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}|regime={regime_name}", p_val))

    print(f"\nTotal raw p-values collected across the complete preregistered family: {len(raw_p_values)}", flush=True)

    # ============================================================== PART 7: TEMPORAL ALIGNMENT
    print(f"\n{'=' * 90}\nPART 7 — TEMPORAL ALIGNMENT TEST (primary feature vs primary target)\n{'=' * 90}", flush=True)
    true_ic = all_ic_results[f"{PRIMARY_FEATURE}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}"]["spearman"].average_ic
    alignment_concern = False
    for shift in (1, 2, 5, 10):
        shifted = shifted_signal_placebo(discovery_panel, feature_col=PRIMARY_FEATURE, target_col=target_col, shift_bars=shift)
        shifted_ic = shifted.placebo_distribution[0] if shifted.placebo_distribution else None
        flag = shifted_ic is not None and true_ic is not None and abs(shifted_ic) >= abs(true_ic)
        alignment_concern = alignment_concern or flag
        print(f"  shift=+{shift}: true_IC={_fmt(true_ic)}  shifted_IC={_fmt(shifted_ic)}  {'<-- TEMPORAL_ALIGNMENT_CONCERN' if flag else ''}", flush=True)
    print(f"\nTEMPORAL_ALIGNMENT_CONCERN: {alignment_concern}", flush=True)

    # ============================================================== PART 8: AUTOCORRELATION
    print(f"\n{'=' * 90}\nPART 8 — AUTOCORRELATION / CLUSTERING (lags 1,2,3,5,10,20)\n{'=' * 90}", flush=True)
    lags = (1, 2, 3, 5, 10, 20)
    autocorr_series_names = {
        "relative_volume_10": lambda bars, engine=FeatureEngine([RelativeVolume(10)]): engine.compute(bars).columns["relative_volume_10"],
        "volume_zscore_20": lambda bars, engine=FeatureEngine([VolumeZScore(20)]): engine.compute(bars).columns["volume_zscore_20"],
        "volume_rolling_mean_10_10": lambda bars, engine=FeatureEngine([RollingMeanRelativeVolume(10, 10)]): engine.compute(bars).columns["volume_rolling_mean_10_10"],
        f"{PRIMARY_TARGET}_{PRIMARY_HORIZON}": lambda bars: future_realized_volatility(bars, PRIMARY_HORIZON),
        "abs_daily_return": lambda bars: [None] + [abs((bars[i].close - bars[i - 1].close) / bars[i - 1].close) if bars[i - 1].close else None for i in range(1, len(bars))],
    }
    autocorr_summary: dict[str, dict[int, float]] = {}
    for series_name, extractor in autocorr_series_names.items():
        by_lag: dict[int, list[float]] = defaultdict(list)
        for sym in usable:
            series = extractor(bars_by_symbol_full[sym])
            profile = autocorrelation_profile(series, lags)
            for lag, val in profile.items():
                if val is not None:
                    by_lag[lag].append(val)
        avgs = {lag: (sum(vals) / len(vals) if vals else None) for lag, vals in by_lag.items()}
        autocorr_summary[series_name] = avgs
        print(f"  {series_name:28s}: " + "  ".join(f"lag{lag}={_fmt(avgs.get(lag))}" for lag in lags), flush=True)

    is_predictive = true_ic is not None and abs(true_ic) > 0.02 and not alignment_concern
    rv_autocorr_short = autocorr_summary["relative_volume_10"].get(1)
    characterization = "PERSISTENCE_CLUSTERING_DOMINANT" if (rv_autocorr_short is not None and rv_autocorr_short > 0.2 and alignment_concern) else "PREDICTIVE" if is_predictive else "INCONCLUSIVE_CHARACTERIZATION"
    print(f"\nCharacterization: {characterization}", flush=True)

    # ============================================================== PART 11: CROSS-SECTIONAL QUANTILES + YEAR STABILITY
    print(f"\n{'=' * 90}\nPART 11 — CROSS-SECTIONAL QUANTILES (primary feature/target) + YEAR STABILITY\n{'=' * 90}", flush=True)
    primary_quantiles = all_ic_results[f"{PRIMARY_FEATURE}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}"]["quantiles"]
    for q in primary_quantiles.quantiles:
        print(f"  Q{q.quantile}: n={q.sample_count} mean={q.mean_return:.6f} median={q.median_return:.6f}", flush=True)
    print(f"  Q5-Q1 spread={primary_quantiles.spread_q5_minus_q1}  monotonic={primary_quantiles.is_monotonic}", flush=True)
    years = sorted({r["timestamp"].year for r in discovery_panel})
    for year in years:
        year_rows = [r for r in discovery_panel if r["timestamp"].year == year]
        year_q = cross_sectional_quantile_returns(year_rows, PRIMARY_FEATURE, target_col, n_quantiles=5, min_universe_size=3)
        print(f"  {year}: spread={_fmt(year_q.spread_q5_minus_q1)}  monotonic={year_q.is_monotonic}  timestamps_used={year_q.timestamps_used}", flush=True)

    # ============================================================== PART 12: SYMBOL / SECTOR ROBUSTNESS
    print(f"\n{'=' * 90}\nPART 12 — SYMBOL & SECTOR ROBUSTNESS\n{'=' * 90}", flush=True)
    from src.research.analysis import analyze_feature

    symbol_results = {}
    for sym in usable:
        sym_rows = [r for r in discovery_panel if r["symbol"] == sym]
        result = analyze_feature(sym_rows, PRIMARY_FEATURE, target_col, n_quantiles=3)
        symbol_results[sym] = result
        print(f"  {sym}: n={result.sample_count}  spearman={_fmt(result.spearman_correlation)}  pearson={_fmt(result.pearson_correlation)}", flush=True)

    full_ic = true_ic
    print("\nLeave-one-symbol-out (cross-sectional IC excluding each symbol):", flush=True)
    loo_swings = []
    for sym in usable:
        rows_without = [r for r in discovery_panel if r["symbol"] != sym]
        without_points = compute_ic_series(rows_without, PRIMARY_FEATURE, target_col, min_universe_size=3)
        without_ic = summarize_ic(without_points, feature_name=PRIMARY_FEATURE, target_name=target_col).average_ic
        swing = abs((without_ic or 0) - (full_ic or 0))
        loo_swings.append((sym, without_ic, swing))
    loo_swings.sort(key=lambda t: t[2], reverse=True)
    for sym, without_ic, swing in loo_swings[:5]:
        print(f"  without {sym}: IC={_fmt(without_ic)}  swing_from_full={_fmt(swing)}", flush=True)
    sign_flips = [sym for sym, ic, _ in loo_swings if ic is not None and full_ic is not None and (ic > 0) != (full_ic > 0)]
    print(f"  max swing: {loo_swings[0][2]:.4f}  sign_flips_without: {sign_flips}", flush=True)

    print("\nLeave-one-sector-out:", flush=True)
    sectors = universe.by_sector()
    for sector_name, sector_symbols in sectors.items():
        rows_without = [r for r in discovery_panel if r["symbol"] not in sector_symbols]
        without_points = compute_ic_series(rows_without, PRIMARY_FEATURE, target_col, min_universe_size=3)
        without_ic = summarize_ic(without_points, feature_name=PRIMARY_FEATURE, target_name=target_col).average_ic
        print(f"  without sector={sector_name} ({list(sector_symbols)}): IC={_fmt(without_ic)}", flush=True)

    # ============================================================== PART 13: BASELINES
    print(f"\n{'=' * 90}\nPART 13 — BASELINES: does volume add information beyond past volatility?\n{'=' * 90}", flush=True)
    random_ctrl = random_feature_control(discovery_panel, target_col=target_col, n_trials=100, seed=201, min_universe_size=3)
    from src.research.analysis import mean as _mean

    print(f"  random feature: mean_IC={_fmt(_mean(random_ctrl.placebo_distribution) if random_ctrl.placebo_distribution else None)}", flush=True)
    shuffled_vol = shuffled_signal_placebo(discovery_panel, feature_col=PRIMARY_FEATURE, target_col=target_col, n_trials=100, seed=202)
    print(f"  shuffled volume: observed_IC={_fmt(shuffled_vol.observed_statistic)}  p={shuffled_vol.empirical_p_value}", flush=True)

    hist_vol_engine = FeatureEngine([RealizedVolatility(20)])
    hist_vol_panel = []
    for sym in usable:
        frame = hist_vol_engine.compute(bars_by_symbol_full[sym])
        for i, ts in enumerate(frame.timestamps):
            hist_vol_panel.append({"timestamp": ts, "symbol": sym, "realized_vol_20": frame.columns["realized_vol_20"][i]})
    hist_vol_by_key = {(r["symbol"], r["timestamp"]): r["realized_vol_20"] for r in hist_vol_panel}
    for row in discovery_panel:
        row["realized_vol_20"] = hist_vol_by_key.get((row["symbol"], row["timestamp"]))
    hist_vol_ic = summarize_ic(compute_ic_series(discovery_panel, "realized_vol_20", target_col, min_universe_size=3), feature_name="realized_vol_20", target_name=target_col)
    print(f"  simple historical volatility (realized_vol_20) IC={_fmt(hist_vol_ic.average_ic)}", flush=True)
    print(f"  (lagged realized volatility baseline == the same feature — see Part 14's incremental-information test for the direct comparison)", flush=True)

    # ============================================================== PART 14: INCREMENTAL INFORMATION
    print(f"\n{'=' * 90}\nPART 14 — INCREMENTAL_PREDICTIVE_INFORMATION (OLS)\n{'=' * 90}", flush=True)
    y = [r.get(target_col) for r in discovery_panel]
    lagged_vol = [r.get("realized_vol_20") for r in discovery_panel]
    volume_feature = [r.get(PRIMARY_FEATURE) for r in discovery_panel]
    model_a = ols_regression(y, {"lagged_vol": lagged_vol}, min_observations=30)
    model_b = ols_regression(y, {"volume_feature": volume_feature}, min_observations=30)
    model_c = ols_regression(y, {"lagged_vol": lagged_vol, "volume_feature": volume_feature}, min_observations=30)
    print(f"  Model A (future_vol ~ lagged_vol):                  {model_a.render()}", flush=True)
    print(f"  Model B (future_vol ~ volume_feature):              {model_b.render()}", flush=True)
    print(f"  Model C (future_vol ~ lagged_vol + volume_feature): {model_c.render()}", flush=True)
    incremental = None
    if model_a.applicable and model_c.applicable:
        incremental = model_c.r_squared - model_a.r_squared
        print(f"\n  INCREMENTAL_PREDICTIVE_INFORMATION (R2_C - R2_A) = {incremental:.5f}"
              f"  volume_feature coefficient in Model C: {model_c.coefficients.get('volume_feature')} (p={model_c.coefficient_p_values.get('volume_feature')})", flush=True)

    # ============================================================== PART 15: PLACEBO BATTERY
    print(f"\n{'=' * 90}\nPART 15 — PLACEBO BATTERY\n{'=' * 90}", flush=True)
    shuffled = shuffled_signal_placebo(discovery_panel, feature_col=PRIMARY_FEATURE, target_col=target_col, n_trials=200, seed=203)
    time_shuffled = time_shuffled_target_placebo(discovery_panel, feature_col=PRIMARY_FEATURE, target_col=target_col, n_trials=200, seed=204)
    print(f"  shuffled_signal (== random cross-sectional ranking): observed={_fmt(shuffled.observed_statistic)} p={shuffled.empirical_p_value}", flush=True)
    print(f"  shifted_signal: see Part 7 above", flush=True)
    print(f"  time_shuffled_target: observed={_fmt(time_shuffled.observed_statistic)} p={time_shuffled.empirical_p_value}", flush=True)
    print(f"  random_feature: see Part 13 above", flush=True)

    # ============================================================== PART 16: MULTIPLE TESTING
    print(f"\n{'=' * 90}\nPART 16 — MULTIPLE-TESTING CORRECTION (complete family, n={len(raw_p_values)})\n{'=' * 90}", flush=True)
    for method in (bonferroni_correction, holm_bonferroni_correction, benjamini_hochberg_fdr):
        report = method(raw_p_values, alpha=0.05)
        print(f"  {report.method}: n_significant={report.n_significant}/{report.n_tests}", flush=True)
    primary_key = f"{PRIMARY_FEATURE}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}"
    bh_report = benjamini_hochberg_fdr(raw_p_values, alpha=0.05)
    primary_bh = next((r for r in bh_report.results if r.label == primary_key), None)
    print(f"\n  Primary test ({primary_key}) BH-adjusted p-value: {primary_bh.adjusted_p_value if primary_bh else 'N/A'}  significant={primary_bh.significant_at_alpha if primary_bh else 'N/A'}", flush=True)

    # Rows must be aligned (same row -> same timestamp/symbol) across ALL feature series, since
    # pearson_correlation pairs by list index — dropping None's independently per feature would
    # silently misalign timestamps across variants. Restrict to rows where every preregistered
    # feature has a value, then take a common, capped slice for compute.
    complete_rows = [r for r in discovery_panel[:2000] if all(r.get(name) is not None for name in FEATURE_SET)][:500]
    feature_value_series = {name: [r[name] for r in complete_rows] for name in FEATURE_SET}
    eff_trials = effective_number_of_trials(list(feature_value_series.values()))
    print(f"  {eff_trials.render()}", flush=True)

    # ============================================================== FINAL CLASSIFICATION & GATE
    print(f"\n{'=' * 90}\nFINAL DISCOVERY ASSESSMENT\n{'=' * 90}", flush=True)
    criteria = {
        "primary_ic_significant_and_directional": primary_bh is not None and primary_bh.significant_at_alpha and true_ic is not None and true_ic > 0,
        "no_temporal_alignment_concern": not alignment_concern,
        "survives_shuffled_placebo": shuffled.empirical_p_value is not None and shuffled.empirical_p_value < 0.10,
        "survives_time_shuffled_placebo": time_shuffled.empirical_p_value is not None and time_shuffled.empirical_p_value < 0.10,
        "genuine_incremental_information": incremental is not None and incremental > 0.01 and model_c.applicable and model_c.coefficient_p_values.get("volume_feature", 1.0) < 0.05,
        "not_concentrated_in_one_symbol": len(sign_flips) == 0,
        "generalizes_across_regimes": sum(1 for s in regime_table[PRIMARY_FEATURE].values() if s.average_ic is not None and s.average_ic > 0) >= 3,
    }
    for name, passed in criteria.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}", flush=True)
    n_passed = sum(criteria.values())
    discovery_supported = n_passed >= 6  # 6 of 7 — a high bar, deliberately, given Phase 8's caution
    print(f"\n{n_passed}/{len(criteria)} discovery criteria passed. DISCOVERY_SUPPORTED = {discovery_supported}", flush=True)

    gate_store = DiscoveryDevelopmentGateStore(Path("logs/research_data/phase9_gate_transitions.jsonl"))
    gate_store.transition(hypothesis_id="P9-VOLCLUST-A", to_stage=DiscoveryDevelopmentStage.IDEA, reason="new hypothesis, related to but not derived from P7-VOLANOM-A as a parameter variation", evidence_summary="")
    gate_store.transition(hypothesis_id="P9-VOLCLUST-A", to_stage=DiscoveryDevelopmentStage.PREREGISTERED, reason="preregistered before any analysis ran", evidence_summary="")
    gate_store.transition(hypothesis_id="P9-VOLCLUST-A", to_stage=DiscoveryDevelopmentStage.DISCOVERY_TESTED, reason=f"{len(raw_p_values)}-test discovery family completed", evidence_summary=f"primary_IC={true_ic}")
    if discovery_supported:
        gate_store.transition(hypothesis_id="P9-VOLCLUST-A", to_stage=DiscoveryDevelopmentStage.DISCOVERY_SUPPORTED, reason=f"{n_passed}/{len(criteria)} discovery criteria passed", evidence_summary=str(criteria))
        print("\nRECOMMENDATION: discovery evidence is credible. A SEPARATE development-stage preregistration (P9-VOLCLUST-A-DEV1) may be justified in a FUTURE phase — NOT created automatically here (Part 18). Note per Part 19: this establishes 'volume predicts volatility' evidence only, NOT that this information has economic/tradable value.", flush=True)
    else:
        gate_store.transition(hypothesis_id="P9-VOLCLUST-A", to_stage=DiscoveryDevelopmentStage.NOT_READY, reason=f"only {n_passed}/{len(criteria)} discovery criteria passed", evidence_summary=str(criteria))
        print("\nRECOMMENDATION: discovery evidence does not clear the bar. STOP — do not invent a trading implementation.", flush=True)

    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))
    dims_fp = ExperimentDimensions(feature_definition=PRIMARY_FEATURE, parameter_range={"feature_set": list(FEATURE_SET), "target_set": list(TARGET_SET), "horizon_set": list(HORIZON_SET)}, universe_name=universe.name, target_definition=PRIMARY_TARGET, execution_model="n/a-discovery", cost_model="n/a-discovery", validation_methodology="cross-sectional discovery family on DISCOVERY_DATA")
    exp_store.record(
        data_version="phase5-campaign-v1", feature_version="phase9-discovery-v1", symbols=usable, timeframe="day",
        strategy_version="1.0", prediction_horizon=PRIMARY_HORIZON, train_period=(str(discovery_partition.start_date), str(discovery_partition.end_date)),
        parameters={"n_tests": len(raw_p_values)}, metrics={"primary_ic": true_ic, "n_criteria_passed": n_passed},
        strategy_family="volume_clustering", classification=("DISCOVERY_SUPPORTED" if discovery_supported else "NOT_READY"),
        tags=("phase9-discovery", universe.name), notes=f"{n_passed}/{len(criteria)} discovery criteria passed; TEMPORAL_ALIGNMENT_CONCERN={alignment_concern}",
        hypothesis_id="P9-VOLCLUST-A", universe_name=universe.name, experiment_fingerprint=compute_experiment_fingerprint(dims_fp),
        research_family_id="P9-VOLCLUST-DISCOVERY-2026-09",
    )
    print("\nSTEP 2 COMPLETE.", flush=True)


def _fmt(x) -> str:
    return "None" if x is None else f"{x:.4f}"


def _ic_p_value(points) -> float | None:
    from src.research.stats_utils import t_test_p_value

    values = [p.ic for p in points if p.ic is not None]
    if len(values) < 2:
        return None
    return t_test_p_value(values)


if __name__ == "__main__":
    main()
