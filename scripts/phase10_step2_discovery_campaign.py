#!/usr/bin/env python3
"""Phase 10 — STEP 2: the full discovery-stage investigation of the
VOLATILITY_PERSISTENCE hypothesis family (P10-VP-001..010) on
DISCOVERY_DATA only. No backtest, no trading strategy, no
DEVELOPMENT_DATA/VALIDATION_DATA/FINAL_HOLDOUT_DATA access anywhere in
this script.

Covers Parts 8-23, 26: incremental-information (OLS), regime transitions,
mean reversion, compression/expansion, future-return/magnitude/drawdown
by volatility state, cross-sectional characterization, symbol/sector
robustness, baselines, temporal alignment, autocorrelation, placebo
battery, multiple-testing correction across the COMPLETE preregistered
family, statistical/economic/risk-management significance separation,
economic rationale, and a per-hypothesis PROMISING/INCONCLUSIVE/
FRAGILE/REJECTED/NOT_READY classification.
"""

from __future__ import annotations

import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import HistoricalDataStore, run_universe_quality_report, us_diversified_universe  # noqa: E402
from src.features import FeatureEngine  # noqa: E402
from src.features.volatility import RealizedVolatility  # noqa: E402
from src.features.volatility_persistence import (  # noqa: E402
    RealizedVolPercentile,
    VolatilityAcceleration,
    VolatilityChange,
    VolatilityCompression,
    VolatilityExpansion,
    VolatilityPersistenceScore,
    VolatilityRatio,
    VolatilityRegimeDuration,
    VolatilityRegimeState,
    VolatilityShock,
    VolatilityZScore,
)
from src.research import (  # noqa: E402
    DiscoveryDevelopmentGateStore,
    DiscoveryDevelopmentStage,
    ExperimentStore,
    PartitionLifecycleStage,
    PartitionStore,
    analyze_feature,
    analyze_regime_transitions,
    autocorrelation_profile,
    benjamini_hochberg_fdr,
    bonferroni_correction,
    bucket_stats_by_state,
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
from src.research.phase10_targets import (
    future_absolute_return,
    future_max_drawdown,
    future_risk_adjusted_return,
    future_volatility_change,
    future_volatility_direction,
)
from src.research.preregistration import PreregistrationStore
from src.research.targets import future_return
from src.research.volatility_targets import future_absolute_cumulative_return, future_max_absolute_move, future_realized_variance, future_realized_volatility

FEATURE_BUILDERS = {
    "realized_vol_5": lambda: RealizedVolatility(5),
    "realized_vol_10": lambda: RealizedVolatility(10),
    "realized_vol_20": lambda: RealizedVolatility(20),
    "realized_vol_60": lambda: RealizedVolatility(60),
    "volatility_zscore_20": lambda: VolatilityZScore(20),
    "volatility_percentile_60": lambda: RealizedVolPercentile(vol_window=20, lookback=60),
    "short_long_vol_ratio": lambda: VolatilityRatio(5, 20),
    "volatility_change_5": lambda: VolatilityChange(vol_window=20, period=5),
    "volatility_change_10": lambda: VolatilityChange(vol_window=20, period=10),
    "volatility_acceleration": lambda: VolatilityAcceleration(vol_window=20),
    "volatility_persistence_score": lambda: VolatilityPersistenceScore(vol_window=20, lookback=20),
    "volatility_regime": lambda: VolatilityRegimeState(window=20, lookback=100),
    "volatility_regime_duration": lambda: VolatilityRegimeDuration(window=20, lookback=100),
    "volatility_shock": lambda: VolatilityShock(vol_window=20, threshold=2.0),
    "volatility_compression": lambda: VolatilityCompression(vol_window=20, lookback=60, threshold=0.20),
    "volatility_expansion": lambda: VolatilityExpansion(vol_window=20, lookback=60, threshold=0.80),
}
FEATURE_SET = tuple(FEATURE_BUILDERS.keys())

TARGET_BUILDERS = {
    "future_realized_volatility": future_realized_volatility,
    "future_realized_variance": future_realized_variance,
    "future_volatility_change": future_volatility_change,
    "future_volatility_direction": future_volatility_direction,
    "future_absolute_return": future_absolute_return,
    "future_absolute_cumulative_return": future_absolute_cumulative_return,
    "future_max_absolute_move": future_max_absolute_move,
    "future_max_drawdown": future_max_drawdown,
    "future_return": future_return,
    "future_risk_adjusted_return": future_risk_adjusted_return,
}
TARGET_SET = tuple(TARGET_BUILDERS.keys())

HORIZON_SET = (1, 3, 5, 10, 20)
PRIMARY_TARGET = "future_realized_volatility"
PRIMARY_HORIZON = 5
PRIMARY_FEATURE = "realized_vol_20"
REGIME_SET = ("bull_high_vol", "bull_low_vol", "bear_high_vol", "bear_low_vol", "unknown")
VOL_REGIME_LABELS = {0.0: "LOW", 1.0: "NORMAL", 2.0: "HIGH", 3.0: "EXTREME"}


def build_panel(store: HistoricalDataStore, universe) -> tuple[list[dict], dict, dict]:
    """One row per (symbol, timestamp) with every preregistered feature,
    every target x horizon column, a string volatility-regime label, the
    Phase 7/9 5-regime cross-check label, and abs_daily_return."""
    feature_engine = FeatureEngine([builder() for builder in FEATURE_BUILDERS.values()])
    bars_by_symbol = {s: store.load(s, "day") for s in universe.symbols}
    panel: list[dict] = []
    vol_regime_label_by_symbol: dict[str, dict] = {}
    for sym, bars in bars_by_symbol.items():
        if not bars:
            continue
        frame = feature_engine.compute(bars)
        target_columns: dict[str, list] = {}
        for target_name, builder in TARGET_BUILDERS.items():
            for h in HORIZON_SET:
                target_columns[f"{target_name}_{h}"] = builder(bars, h)
        closes = [b.close for b in bars]
        abs_daily_return = [None] + [abs((closes[i] - closes[i - 1]) / closes[i - 1]) if closes[i - 1] else None for i in range(1, len(closes))]
        vol_regime_label_by_symbol[sym] = {}
        for i, ts in enumerate(frame.timestamps):
            row = {"timestamp": ts, "symbol": sym}
            for name in frame.feature_names:
                row[name] = frame.columns[name][i]
            for col_name, series in target_columns.items():
                row[col_name] = series[i]
            row["abs_daily_return"] = abs_daily_return[i]
            label = VOL_REGIME_LABELS.get(row.get("volatility_regime"))
            row["volatility_regime_label"] = label
            vol_regime_label_by_symbol[sym][ts] = label
            panel.append(row)
    return panel, bars_by_symbol, vol_regime_label_by_symbol


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    universe = us_diversified_universe()

    prereg_store = PreregistrationStore(Path("logs/research_data/phase10_preregistrations.jsonl"))
    require_preregistered(prereg_store, "P10-VOLPERSIST")
    for hyp_id in ("P10-VP-001", "P10-VP-002", "P10-VP-003", "P10-VP-004", "P10-VP-005", "P10-VP-006", "P10-VP-007", "P10-VP-008", "P10-VP-009", "P10-VP-010"):
        require_preregistered(prereg_store, hyp_id)

    partition_store = PartitionStore(Path("logs/research_data/phase7_partitions.jsonl"))
    discovery_partition = partition_store.active_by_stage(PartitionLifecycleStage.DISCOVERY)[0]
    print(f"DISCOVERY_DATA: {discovery_partition.start_date} .. {discovery_partition.end_date}", flush=True)
    print("SURVIVORSHIP-BIAS WARNING (Part 7, carried forward from Phase 7-9): US_DIVERSIFIED is a fixed, "
          "currently-listed 20-symbol universe with no delisting/survivorship correction.\n", flush=True)

    quality = run_universe_quality_report(store, universe, "day", min_bars_required=100)
    usable = [q.symbol for q in quality if q.available]
    print(f"Universe: {universe.name}  usable={len(usable)}/{len(universe.symbols)}", flush=True)

    print("Building the full feature/target panel (16 features x 10 targets x 5 horizons)...", flush=True)
    full_panel, bars_by_symbol_full, vol_regime_label_by_symbol = build_panel(store, universe)
    full_panel = [r for r in full_panel if r["symbol"] in usable]
    discovery_panel = filter_rows_by_partition(full_panel, discovery_partition)
    print(f"Full panel: {len(full_panel)} rows. DISCOVERY_DATA panel: {len(discovery_panel)} rows.\n", flush=True)

    regime5_labels: dict = {}
    for sym in usable:
        regime5_labels.update(label_bars_by_regime(bars_by_symbol_full[sym]))

    raw_p_values: list[tuple[str, float]] = []
    all_ic_results: dict[str, dict] = {}

    # ============================================================== PART A: MAIN SCREEN (160 tests)
    print(f"{'=' * 90}\nPART A — MAIN SCREEN: {len(FEATURE_SET)} features x {len(TARGET_SET)} targets @ horizon={PRIMARY_HORIZON}\n{'=' * 90}", flush=True)
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
            print(f"  {feature_name:26s} vs {target_name:34s}: spearman_IC={_fmt(spearman.average_ic)} pearson_IC={_fmt(pearson.average_ic)} "
                  f"spread={_fmt(quantiles.spread_q5_minus_q1)} monotonic={quantiles.is_monotonic}", flush=True)
            p = _ic_p_value(spearman_points)
            if p is not None:
                raw_p_values.append((key, p))

    # ============================================================== PART B: PREDICTIVE HORIZON TABLE (64 additional tests)
    print(f"\n{'=' * 90}\nPART B — PREDICTIVE HORIZON TABLE (all features x {PRIMARY_TARGET} across all horizons)\n{'=' * 90}", flush=True)
    horizon_table: dict[str, dict[int, dict]] = defaultdict(dict)
    for feature_name in FEATURE_SET:
        row_str = []
        for h in HORIZON_SET:
            target_col = f"{PRIMARY_TARGET}_{h}"
            spearman_points = compute_ic_series(discovery_panel, feature_name, target_col, min_universe_size=3)
            spearman = summarize_ic(spearman_points, feature_name=feature_name, target_name=target_col)
            horizon_table[feature_name][h] = {"spearman": spearman}
            row_str.append(f"h{h}:{_fmt(spearman.average_ic)}")
            if h != PRIMARY_HORIZON:
                p = _ic_p_value(spearman_points)
                if p is not None:
                    raw_p_values.append((f"{feature_name}|{PRIMARY_TARGET}|h{h}", p))
        print(f"  {feature_name:26s}: " + "  ".join(row_str), flush=True)

    # ============================================================== PART C: REGIME TABLE (80 additional tests)
    print(f"\n{'=' * 90}\nPART C — REGIME TABLE (Phase 7/9 bull/bear x high/low-vol taxonomy, all features @ primary target/horizon)\n{'=' * 90}", flush=True)
    regime_table: dict[str, dict] = {}
    target_col = f"{PRIMARY_TARGET}_{PRIMARY_HORIZON}"
    for feature_name in FEATURE_SET:
        regime_result = ic_by_regime(discovery_panel, feature_name, target_col, regime5_labels, min_universe_size=3)
        regime_table[feature_name] = regime_result
        print(f"  {feature_name:26s}: " + "; ".join(f"{r}={_fmt(s.average_ic)}(n={sum(1 for p in s.points if p.ic is not None)})" for r, s in regime_result.items()), flush=True)
        for regime_name, summary in regime_result.items():
            p_val = _ic_p_value(summary.points)
            if p_val is not None:
                raw_p_values.append((f"{feature_name}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}|regime={regime_name}", p_val))

    print(f"\nTotal raw p-values collected across the complete preregistered family: {len(raw_p_values)}", flush=True)

    # ============================================================== PART 8: DOES VOLATILITY ADD INFORMATION BEYOND ITSELF?
    print(f"\n{'=' * 90}\nPART 8 — INCREMENTAL_PREDICTIVE_INFORMATION (OLS): does each feature add info beyond lagged realized_vol_20?\n{'=' * 90}", flush=True)
    y = [r.get(target_col) for r in discovery_panel]
    lagged_vol = [r.get(PRIMARY_FEATURE) for r in discovery_panel]
    model_a = ols_regression(y, {"lagged_vol": lagged_vol}, min_observations=30)
    print(f"  Model A (future_vol ~ lagged_vol={PRIMARY_FEATURE}):  {model_a.render()}", flush=True)
    incremental_by_feature: dict[str, float | None] = {}
    incremental_significant: dict[str, bool] = {}
    for feature_name in FEATURE_SET:
        candidate = [r.get(feature_name) for r in discovery_panel]
        model_b = ols_regression(y, {"candidate": candidate}, min_observations=30)
        model_c = ols_regression(y, {"lagged_vol": lagged_vol, "candidate": candidate}, min_observations=30)
        if model_a.applicable and model_c.applicable:
            incremental = model_c.r_squared - model_a.r_squared
            incremental_by_feature[feature_name] = incremental
            p_candidate = model_c.coefficient_p_values.get("candidate", 1.0)
            incremental_significant[feature_name] = incremental > 0.01 and p_candidate < 0.05  # same practical-significance bar as Phase 9
            print(f"  {feature_name:26s}: R2_A={model_a.r_squared:.4f}  R2_C={model_c.r_squared:.4f}  "
                  f"delta_R2={incremental:.5f}  candidate_p={p_candidate:.4g}  {'<-- INCREMENTAL' if incremental_significant[feature_name] else ''}", flush=True)
        else:
            incremental_by_feature[feature_name] = None
            incremental_significant[feature_name] = False
            print(f"  {feature_name:26s}: NOT_APPLICABLE ({model_b.reason if not model_b.applicable else model_c.reason})", flush=True)

    # ============================================================== PART 9: VOLATILITY REGIME TRANSITIONS
    print(f"\n{'=' * 90}\nPART 9 — VOLATILITY REGIME TRANSITIONS (LOW/NORMAL/HIGH/EXTREME)\n{'=' * 90}", flush=True)
    pooled_labels: list[str | None] = []
    for sym in usable:
        bars = bars_by_symbol_full[sym]
        label_by_ts = vol_regime_label_by_symbol[sym]
        pooled_labels.extend(label_by_ts.get(b.timestamp) for b in bars)
        pooled_labels.append(None)  # gap between symbols — no spurious cross-symbol transition
    transitions = analyze_regime_transitions(pooled_labels, states=("LOW", "NORMAL", "HIGH", "EXTREME"))
    print(f"  n_transitions_observed={transitions.n_transitions_observed}", flush=True)
    for state in transitions.states:
        row = transitions.transition_probabilities[state]
        row_str = "; ".join(f"->{t}={_fmt(row.get(t))}" for t in transitions.states)
        print(f"  {state:8s}: persistence={_fmt(transitions.persistence_probability[state])}  n_episodes={transitions.n_episodes[state]}  "
              f"mean_duration={_fmt(transitions.mean_duration[state])}  median_duration={_fmt(transitions.median_duration[state])}  [{row_str}]", flush=True)

    # ============================================================== PART 10: VOLATILITY MEAN REVERSION
    print(f"\n{'=' * 90}\nPART 10 — VOLATILITY MEAN REVERSION AFTER A SHOCK (volatility_shock == 1.0)\n{'=' * 90}", flush=True)
    shock_rows = [r for r in discovery_panel if r.get("volatility_shock") == 1.0 and r.get(PRIMARY_FEATURE) is not None]
    print(f"  n_shock_events={len(shock_rows)}", flush=True)
    print("  delta = future_volatility_change (sqrt(horizon)-normalized to per-day units, see src/research/phase10_targets.py) "
          "— NOT a raw subtraction of a multi-day statistic from a per-day baseline.", flush=True)
    reversion_by_horizon: dict[int, dict] = {}
    for h in HORIZON_SET:
        deltas = [r[f"future_volatility_change_{h}"] for r in shock_rows if r.get(f"future_volatility_change_{h}") is not None]
        if deltas:
            pct_reverting = sum(1 for d in deltas if d < 0) / len(deltas)
            reversion_by_horizon[h] = {"n": len(deltas), "mean_delta": sum(deltas) / len(deltas), "median_delta": sorted(deltas)[len(deltas) // 2], "pct_reverting": pct_reverting}
            print(f"  h={h:2d}: n={len(deltas):5d}  mean_delta={reversion_by_horizon[h]['mean_delta']:+.5f}  "
                  f"median_delta={reversion_by_horizon[h]['median_delta']:+.5f}  pct_reverting={pct_reverting:.1%}", flush=True)
        else:
            reversion_by_horizon[h] = {"n": 0, "mean_delta": None, "median_delta": None, "pct_reverting": None}
            print(f"  h={h:2d}: no complete observations", flush=True)

    # ============================================================== PART 11: COMPRESSION / EXPANSION
    print(f"\n{'=' * 90}\nPART 11 — VOLATILITY COMPRESSION / EXPANSION\n{'=' * 90}", flush=True)
    baseline_up_prob = _fraction_positive(discovery_panel, f"future_volatility_direction_{PRIMARY_HORIZON}")
    print(f"  random-state baseline P(future_volatility_direction > 0) = {_fmt(baseline_up_prob)}", flush=True)
    for state_col, expect, label in (("volatility_compression", "EXPANSION", "compression -> subsequent expansion"), ("volatility_expansion", "CONTRACTION", "expansion -> subsequent contraction")):
        print(f"  {label}:", flush=True)
        for h in HORIZON_SET:
            state_rows = [r for r in discovery_panel if r.get(state_col) == 1.0]
            p_up = _fraction_positive(state_rows, f"future_volatility_direction_{h}")
            effect = None if p_up is None or baseline_up_prob is None else p_up - baseline_up_prob
            print(f"    h={h:2d}: n={len(state_rows):5d}  P(direction>0 | state)={_fmt(p_up)}  effect_vs_baseline={_fmt(effect)}", flush=True)

    # ============================================================== PART 12: VOLATILITY VS FUTURE RETURNS
    print(f"\n{'=' * 90}\nPART 12 — VOLATILITY REGIME VS FUTURE RETURNS (conditional distribution, NOT a correlation)\n{'=' * 90}", flush=True)
    return_stats = bucket_stats_by_state(discovery_panel, "volatility_regime_label", f"future_return_{PRIMARY_HORIZON}", min_count=20)
    for state in ("LOW", "NORMAL", "HIGH", "EXTREME"):
        s = return_stats.get(state)
        if s is None:
            print(f"  {state:8s}: no observations", flush=True)
            continue
        print(f"  {state:8s}: n={s.sample_count:5d}  mean={_fmt(s.mean_value)}  median={_fmt(s.median_value)}  stdev={_fmt(s.stdev_value)}  "
              f"sharpe_like={_fmt(s.sharpe_like)}  downside_dev={_fmt(s.downside_deviation)}  win_rate={_fmt(s.win_rate)}", flush=True)
    directional_info_present, directional_p_value, directional_detail = _directional_separation_welch(discovery_panel, "volatility_regime_label", f"future_return_{PRIMARY_HORIZON}")
    print(f"\n  Directional information present across volatility states (Welch t-test, most-extreme pair, p<0.05, "
          f"NOT overlap/autocorrelation-adjusted): {directional_info_present}  ({directional_detail}, p={_fmt(directional_p_value)})", flush=True)
    if not directional_info_present:
        print("  Explicitly reporting: no clear directional (bullish/bearish) signal from volatility state alone.", flush=True)
    else:
        print("  CAVEAT: this uses overlapping 5-bar forward windows (thousands of rows are not independent trials — true "
              "effective sample size is much smaller than the raw row count), so treat this as a modest, not decisive, signal.", flush=True)

    # ============================================================== PART 13: VOLATILITY VS FUTURE RETURN MAGNITUDE
    print(f"\n{'=' * 90}\nPART 13 — VOLATILITY REGIME VS FUTURE RETURN MAGNITUDE\n{'=' * 90}", flush=True)
    magnitude_key = f"volatility_regime|future_absolute_return|h{PRIMARY_HORIZON}"
    magnitude_result = all_ic_results.get(magnitude_key)
    if magnitude_result:
        print(f"  volatility_regime vs future_absolute_return: spearman_IC={_fmt(magnitude_result['spearman'].average_ic)} "
              f"pearson_IC={_fmt(magnitude_result['pearson'].average_ic)} spread={_fmt(magnitude_result['quantiles'].spread_q5_minus_q1)}", flush=True)
    print("  Horizon decay (volatility_regime vs future_absolute_return-equivalent proxy — see Part B horizon table for realized_vol_20):", flush=True)
    for h in HORIZON_SET:
        col = f"future_absolute_return_{h}"
        pts = compute_ic_series(discovery_panel, "volatility_regime", col, min_universe_size=3)
        s = summarize_ic(pts, feature_name="volatility_regime", target_name=col)
        print(f"    h={h:2d}: spearman_IC={_fmt(s.average_ic)}", flush=True)
    print(f"\n  Comparison baselines (Part 13's explicit ask):", flush=True)
    lagged_abs_ic = summarize_ic(compute_ic_series(discovery_panel, "abs_daily_return", f"future_absolute_return_{PRIMARY_HORIZON}", min_universe_size=3), feature_name="abs_daily_return", target_name=f"future_absolute_return_{PRIMARY_HORIZON}")
    lagged_vol_ic = all_ic_results.get(f"{PRIMARY_FEATURE}|future_absolute_return|h{PRIMARY_HORIZON}")
    print(f"    lagged |daily return| vs future_absolute_return: spearman_IC={_fmt(lagged_abs_ic.average_ic)}", flush=True)
    if lagged_vol_ic:
        print(f"    lagged realized_vol_20 vs future_absolute_return:  spearman_IC={_fmt(lagged_vol_ic['spearman'].average_ic)}", flush=True)

    # ============================================================== PART 14: VOLATILITY VS DRAWDOWN RISK
    print(f"\n{'=' * 90}\nPART 14 — VOLATILITY REGIME VS FUTURE DRAWDOWN RISK\n{'=' * 90}", flush=True)
    dd_stats = bucket_stats_by_state(discovery_panel, "volatility_regime_label", f"future_max_drawdown_{PRIMARY_HORIZON}", min_count=20)
    for state in ("LOW", "NORMAL", "HIGH", "EXTREME"):
        s = dd_stats.get(state)
        if s is None:
            print(f"  {state:8s}: no observations", flush=True)
            continue
        dd_values = sorted(r[f"future_max_drawdown_{PRIMARY_HORIZON}"] for r in discovery_panel if r.get("volatility_regime_label") == state and r.get(f"future_max_drawdown_{PRIMARY_HORIZON}") is not None)
        p95 = dd_values[int(0.95 * (len(dd_values) - 1))] if dd_values else None
        prob_exceeds_5pct = (sum(1 for v in dd_values if v > 0.05) / len(dd_values)) if dd_values else None
        print(f"  {state:8s}: n={s.sample_count:5d}  mean_dd={_fmt(s.mean_value)}  median_dd={_fmt(s.median_value)}  "
              f"p95_dd={_fmt(p95)}  P(dd>5%)={_fmt(prob_exceeds_5pct)}", flush=True)

    # ============================================================== PART 15: CROSS-SECTIONAL vs TIME-SERIES CHARACTERIZATION
    print(f"\n{'=' * 90}\nPART 15 — CROSS-SECTIONAL vs TIME-SERIES-ONLY CHARACTERIZATION (primary feature/target)\n{'=' * 90}", flush=True)
    pooled_ic = all_ic_results[f"{PRIMARY_FEATURE}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}"]["spearman"].average_ic
    per_symbol_corrs = []
    for sym in usable:
        sym_rows = [r for r in discovery_panel if r["symbol"] == sym]
        result = analyze_feature(sym_rows, PRIMARY_FEATURE, target_col, n_quantiles=3)
        if result.spearman_correlation is not None:
            per_symbol_corrs.append(result.spearman_correlation)
    avg_symbol_corr = sum(per_symbol_corrs) / len(per_symbol_corrs) if per_symbol_corrs else None
    print(f"  pooled cross-sectional IC = {_fmt(pooled_ic)}   average per-symbol (own time-series) correlation = {_fmt(avg_symbol_corr)}", flush=True)
    if avg_symbol_corr is not None and pooled_ic is not None and avg_symbol_corr > 0.3 and abs(avg_symbol_corr) > abs(pooled_ic):
        characterization_cs = "TIME-SERIES ONLY (per-symbol effect much stronger than the pooled cross-sectional ranking)"
    elif avg_symbol_corr is not None and pooled_ic is not None and avg_symbol_corr > 0 and pooled_ic > 0:
        characterization_cs = "BOTH TIME-SERIES AND CROSS-SECTIONALLY INFORMATIVE"
    else:
        characterization_cs = "INCONCLUSIVE_CHARACTERIZATION"
    print(f"  Characterization: {characterization_cs}", flush=True)

    # ============================================================== PART 16: SYMBOL / SECTOR ROBUSTNESS
    print(f"\n{'=' * 90}\nPART 16 — SYMBOL & SECTOR ROBUSTNESS (primary feature/target)\n{'=' * 90}", flush=True)
    for sym in usable:
        sym_rows = [r for r in discovery_panel if r["symbol"] == sym]
        result = analyze_feature(sym_rows, PRIMARY_FEATURE, target_col, n_quantiles=3)
        print(f"  {sym}: n={result.sample_count}  spearman={_fmt(result.spearman_correlation)}  pearson={_fmt(result.pearson_correlation)}", flush=True)

    print("\nLeave-one-symbol-out (cross-sectional IC excluding each symbol):", flush=True)
    loo_swings = []
    for sym in usable:
        rows_without = [r for r in discovery_panel if r["symbol"] != sym]
        without_points = compute_ic_series(rows_without, PRIMARY_FEATURE, target_col, min_universe_size=3)
        without_ic = summarize_ic(without_points, feature_name=PRIMARY_FEATURE, target_name=target_col).average_ic
        swing = abs((without_ic or 0) - (pooled_ic or 0))
        loo_swings.append((sym, without_ic, swing))
    loo_swings.sort(key=lambda t: t[2], reverse=True)
    for sym, without_ic, swing in loo_swings[:5]:
        print(f"  without {sym}: IC={_fmt(without_ic)}  swing_from_full={_fmt(swing)}", flush=True)
    sign_flips = [sym for sym, ic, _ in loo_swings if ic is not None and pooled_ic is not None and (ic > 0) != (pooled_ic > 0)]
    print(f"  max swing: {loo_swings[0][2]:.4f}  sign_flips_without: {sign_flips}", flush=True)

    print("\nLeave-one-sector-out:", flush=True)
    for sector_name, sector_symbols in universe.by_sector().items():
        rows_without = [r for r in discovery_panel if r["symbol"] not in sector_symbols]
        without_points = compute_ic_series(rows_without, PRIMARY_FEATURE, target_col, min_universe_size=3)
        without_ic = summarize_ic(without_points, feature_name=PRIMARY_FEATURE, target_name=target_col).average_ic
        print(f"  without sector={sector_name} ({list(sector_symbols)}): IC={_fmt(without_ic)}", flush=True)

    # ============================================================== PART 17: BASELINES
    print(f"\n{'=' * 90}\nPART 17 — BASELINES\n{'=' * 90}", flush=True)
    random_ctrl = random_feature_control(discovery_panel, target_col=target_col, n_trials=100, seed=301, min_universe_size=3)
    random_mean_ic = sum(random_ctrl.placebo_distribution) / len(random_ctrl.placebo_distribution) if random_ctrl.placebo_distribution else None
    print(f"  1. random feature: mean_IC={_fmt(random_mean_ic)}", flush=True)
    shuffled_vol = shuffled_signal_placebo(discovery_panel, feature_col=PRIMARY_FEATURE, target_col=target_col, n_trials=100, seed=302)
    print(f"  2. shuffled volatility: observed_IC={_fmt(shuffled_vol.observed_statistic)}  p={shuffled_vol.empirical_p_value}", flush=True)
    print(f"  3. lagged realized volatility (realized_vol_20) IS the primary feature: IC={_fmt(pooled_ic)} (see Part 8 for incremental-info vs this baseline)", flush=True)
    print(f"  4. lagged absolute return: see Part 13 (lagged |daily return| vs future_absolute_return)", flush=True)
    simple_regime_ic = all_ic_results.get(f"volatility_regime|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}")
    print(f"  5. simple volatility regime (volatility_regime vs {PRIMARY_TARGET}): IC={_fmt(simple_regime_ic['spearman'].average_ic) if simple_regime_ic else 'N/A'}", flush=True)

    # ============================================================== PART 18: TEMPORAL ALIGNMENT
    print(f"\n{'=' * 90}\nPART 18 — TEMPORAL ALIGNMENT TEST\n{'=' * 90}", flush=True)
    alignment_concerns: dict[str, bool] = {}
    for feature_name in (PRIMARY_FEATURE, "volatility_regime", "volatility_compression"):
        true_ic_f = all_ic_results[f"{feature_name}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}"]["spearman"].average_ic
        concern = False
        for shift in (1, 2, 5, 10):
            shifted = shifted_signal_placebo(discovery_panel, feature_col=feature_name, target_col=target_col, shift_bars=shift)
            shifted_ic = shifted.placebo_distribution[0] if shifted.placebo_distribution else None
            flag = shifted_ic is not None and true_ic_f is not None and abs(shifted_ic) >= abs(true_ic_f)
            concern = concern or flag
            print(f"  {feature_name:22s} shift=+{shift}: true_IC={_fmt(true_ic_f)}  shifted_IC={_fmt(shifted_ic)}  {'<-- TEMPORAL_ALIGNMENT_CONCERN' if flag else ''}", flush=True)
        alignment_concerns[feature_name] = concern
        print(f"  {feature_name} TEMPORAL_ALIGNMENT_CONCERN: {concern}\n", flush=True)

    # ============================================================== PART 19: AUTOCORRELATION
    print(f"{'=' * 90}\nPART 19 — AUTOCORRELATION (lags 1,2,3,5,10,20,40)\n{'=' * 90}", flush=True)
    lags = (1, 2, 3, 5, 10, 20, 40)
    autocorr_series_names = {
        "realized_vol_20": lambda bars: RealizedVolatility(20).compute(bars),
        "abs_daily_return": lambda bars: [None] + [abs((bars[i].close - bars[i - 1].close) / bars[i - 1].close) if bars[i - 1].close else None for i in range(1, len(bars))],
        "volatility_change_5": lambda bars: VolatilityChange(vol_window=20, period=5).compute(bars),
        "volatility_shock": lambda bars: VolatilityShock(vol_window=20, threshold=2.0).compute(bars),
        "volatility_regime": lambda bars: VolatilityRegimeState(window=20, lookback=100).compute(bars),
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
        print(f"  {series_name:20s}: " + "  ".join(f"lag{lag}={_fmt(avgs.get(lag))}" for lag in lags), flush=True)

    primary_true_ic = all_ic_results[f"{PRIMARY_FEATURE}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}"]["spearman"].average_ic
    rv_autocorr_lag1 = autocorr_summary["realized_vol_20"].get(1)
    persistence_vs_prediction = (
        "PERSISTENCE_CLUSTERING_DOMINANT" if (rv_autocorr_lag1 is not None and rv_autocorr_lag1 > 0.5 and alignment_concerns[PRIMARY_FEATURE])
        else "PREDICTIVE" if (primary_true_ic is not None and abs(primary_true_ic) > 0.02 and not alignment_concerns[PRIMARY_FEATURE])
        else "INCONCLUSIVE_CHARACTERIZATION"
    )
    print(f"\n  PERSISTENCE vs PREDICTION characterization: {persistence_vs_prediction}", flush=True)

    # ============================================================== PART 20: PLACEBO TESTING
    print(f"\n{'=' * 90}\nPART 20 — PLACEBO BATTERY\n{'=' * 90}", flush=True)
    shuffled_feature = shuffled_signal_placebo(discovery_panel, feature_col=PRIMARY_FEATURE, target_col=target_col, n_trials=200, seed=303)
    time_shuffled = time_shuffled_target_placebo(discovery_panel, feature_col=PRIMARY_FEATURE, target_col=target_col, n_trials=200, seed=304)
    print(f"  shuffled_feature (random cross-sectional ranking): observed={_fmt(shuffled_feature.observed_statistic)} p={shuffled_feature.empirical_p_value}", flush=True)
    print(f"  shifted_feature: see Part 18 above", flush=True)
    print(f"  time_shuffled_target: observed={_fmt(time_shuffled.observed_statistic)} p={time_shuffled.empirical_p_value}", flush=True)
    rng = random.Random(305)
    shuffled_regime_labels = list(pooled_labels)
    rng.shuffle(shuffled_regime_labels)
    shuffled_transitions = analyze_regime_transitions(shuffled_regime_labels, states=("LOW", "NORMAL", "HIGH", "EXTREME"))
    print(f"  random_regime_assignment / randomized_state_transitions (shuffled regime-label order, same marginal frequencies):", flush=True)
    for state in transitions.states:
        print(f"    {state:8s}: true_persistence={_fmt(transitions.persistence_probability[state])}  shuffled_persistence={_fmt(shuffled_transitions.persistence_probability[state])}", flush=True)

    # ============================================================== PART 21: MULTIPLE TESTING
    print(f"\n{'=' * 90}\nPART 21 — MULTIPLE-TESTING CORRECTION (complete family, n={len(raw_p_values)})\n{'=' * 90}", flush=True)
    for method in (bonferroni_correction, holm_bonferroni_correction, benjamini_hochberg_fdr):
        report = method(raw_p_values, alpha=0.05)
        print(f"  {report.method}: n_significant={report.n_significant}/{report.n_tests}", flush=True)
    primary_key = f"{PRIMARY_FEATURE}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}"
    bh_report = benjamini_hochberg_fdr(raw_p_values, alpha=0.05)
    primary_bh = next((r for r in bh_report.results if r.label == primary_key), None)
    print(f"\n  Primary test ({primary_key}) BH-adjusted p-value: {primary_bh.adjusted_p_value if primary_bh else 'N/A'}  significant={primary_bh.significant_at_alpha if primary_bh else 'N/A'}", flush=True)
    bh_significant_keys = {r.label for r in bh_report.results if r.significant_at_alpha}

    complete_rows = [r for r in discovery_panel[:2000] if all(r.get(name) is not None for name in FEATURE_SET)][:500]
    feature_value_series = {name: [r[name] for r in complete_rows] for name in FEATURE_SET}
    eff_trials = effective_number_of_trials(list(feature_value_series.values()))
    print(f"  {eff_trials.render()}", flush=True)

    # ============================================================== PART 22: STATISTICAL vs ECONOMIC vs RISK-MANAGEMENT SIGNIFICANCE
    print(f"\n{'=' * 90}\nPART 22 — STATISTICAL vs ECONOMIC vs RISK-MANAGEMENT SIGNIFICANCE (primary feature)\n{'=' * 90}", flush=True)
    statistical_information = primary_key in bh_significant_keys
    # realized_vol_20 IS the OLS baseline (Part 8 skips it as its own candidate, so it can never show
    # "incremental info beyond itself" by construction) — economic value is assessed at the FAMILY
    # level: does ANY feature show genuine incremental information, combined with a directional signal.
    any_feature_incremental = any(incremental_significant.values())
    economic_information = any_feature_incremental and directional_info_present
    dd_ic_pts = compute_ic_series(discovery_panel, "volatility_regime", f"future_max_drawdown_{PRIMARY_HORIZON}", min_universe_size=3)
    dd_ic = summarize_ic(dd_ic_pts, feature_name="volatility_regime", target_name=f"future_max_drawdown_{PRIMARY_HORIZON}").average_ic
    risk_management_information = dd_ic is not None and dd_ic > 0.03
    print(f"  STATISTICAL_INFORMATION  (BH-significant, primary test): {statistical_information}", flush=True)
    print(f"  ECONOMIC_INFORMATION     (any feature shows incremental info [{any_feature_incremental}] AND directional return signal present [{directional_info_present}]): {economic_information}", flush=True)
    print(f"  RISK_MANAGEMENT_INFORMATION (volatility_regime -> future_max_drawdown IC={_fmt(dd_ic)} > 0.03): {risk_management_information}", flush=True)

    # ============================================================== PART 23: ECONOMIC RATIONALE
    print(f"\n{'=' * 90}\nPART 23 — ECONOMIC_RATIONALE (not CAUSAL_PROOF)\n{'=' * 90}", flush=True)
    print("  Plausible mechanisms for any surviving relationship: volatility clustering (well-documented GARCH-type behavior), "
          "information arrival (news/earnings clusters both volume and volatility), liquidity conditions (thinner books widen "
          "realized moves), market-wide risk repricing (VIX-like regime shifts), behavioral feedback (forced deleveraging, "
          "momentum-chasing during stress). None of this is claimed as a proven causal mechanism.", flush=True)

    # ============================================================== FINAL: PER-HYPOTHESIS CLASSIFICATION & GATE (Parts 26-27)
    print(f"\n{'=' * 90}\nPER-HYPOTHESIS CLASSIFICATION (Part 26)\n{'=' * 90}", flush=True)
    gate_store = DiscoveryDevelopmentGateStore(Path("logs/research_data/phase10_gate_transitions.jsonl"))
    classifications: dict[str, tuple[str, list[str]]] = {}

    def _advance_and_classify(hyp_id: str, verdict: str, reasons: list[str]) -> None:
        classifications[hyp_id] = (verdict, reasons)
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.IDEA, reason="new VOLATILITY_PERSISTENCE hypothesis, not derived from a prior phase", evidence_summary="")
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.PREREGISTERED, reason="preregistered before any analysis ran", evidence_summary="")
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DISCOVERY_TESTED, reason="discovery family completed", evidence_summary="; ".join(reasons))
        if verdict == "PROMISING":
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DISCOVERY_SUPPORTED, reason="classified PROMISING", evidence_summary="; ".join(reasons))
        else:
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.NOT_READY, reason=f"classified {verdict}", evidence_summary="; ".join(reasons))
        print(f"  {hyp_id}: {verdict} — " + "; ".join(reasons), flush=True)

    # P10-VP-001: volatility persistence baseline
    reasons = []
    verdict = "PROMISING" if (statistical_information and not alignment_concerns[PRIMARY_FEATURE]) else "FRAGILE" if statistical_information else "REJECTED"
    reasons.append(f"primary IC={_fmt(primary_true_ic)}, BH-significant={statistical_information}, TEMPORAL_ALIGNMENT_CONCERN={alignment_concerns[PRIMARY_FEATURE]}, persistence_char={persistence_vs_prediction}")
    if persistence_vs_prediction == "PERSISTENCE_CLUSTERING_DOMINANT":
        reasons.append("expected raw persistence confirmed, but this alone is NOT alpha (see Part 8 for incremental info)")
    _advance_and_classify("P10-VP-001", verdict, reasons)

    # P10-VP-002: regime persistence
    avg_persistence = sum(v for v in transitions.persistence_probability.values() if v is not None) / max(1, sum(1 for v in transitions.persistence_probability.values() if v is not None))
    shuffled_avg_persistence = sum(v for v in shuffled_transitions.persistence_probability.values() if v is not None) / max(1, sum(1 for v in shuffled_transitions.persistence_probability.values() if v is not None))
    verdict = "PROMISING" if avg_persistence > shuffled_avg_persistence + 0.10 else "INCONCLUSIVE"
    _advance_and_classify("P10-VP-002", verdict, [f"avg_persistence={avg_persistence:.3f} vs shuffled={shuffled_avg_persistence:.3f}, n_transitions={transitions.n_transitions_observed}"])

    # P10-VP-003: mean reversion
    late_horizon_reversion = reversion_by_horizon.get(20, {}).get("pct_reverting")
    verdict = "PROMISING" if (late_horizon_reversion is not None and late_horizon_reversion > 0.60) else "INCONCLUSIVE"
    _advance_and_classify("P10-VP-003", verdict, [f"n_shocks={len(shock_rows)}, pct_reverting_by_h20={_fmt(late_horizon_reversion)}"])

    # P10-VP-004: volatility momentum
    accel_key = f"volatility_acceleration|future_volatility_change|h{PRIMARY_HORIZON}"
    accel_ic = all_ic_results.get(accel_key, {}).get("spearman")
    verdict = "PROMISING" if (accel_ic is not None and accel_key in bh_significant_keys and accel_ic.average_ic and accel_ic.average_ic > 0) else "INCONCLUSIVE" if accel_ic else "NOT_READY"
    _advance_and_classify("P10-VP-004", verdict, [f"IC={_fmt(accel_ic.average_ic if accel_ic else None)}, BH-significant={accel_key in bh_significant_keys}"])

    # P10-VP-005: term structure
    ratio_key = f"short_long_vol_ratio|future_volatility_direction|h{PRIMARY_HORIZON}"
    ratio_ic = all_ic_results.get(ratio_key, {}).get("spearman")
    verdict = "PROMISING" if (ratio_ic is not None and ratio_key in bh_significant_keys) else "INCONCLUSIVE" if ratio_ic else "NOT_READY"
    _advance_and_classify("P10-VP-005", verdict, [f"IC={_fmt(ratio_ic.average_ic if ratio_ic else None)}, BH-significant={ratio_key in bh_significant_keys}"])

    # P10-VP-006: regime -> magnitude
    verdict = "PROMISING" if (magnitude_key in bh_significant_keys and magnitude_result and magnitude_result["spearman"].average_ic and magnitude_result["spearman"].average_ic > 0) else "INCONCLUSIVE"
    _advance_and_classify("P10-VP-006", verdict, [f"IC={_fmt(magnitude_result['spearman'].average_ic if magnitude_result else None)}, BH-significant={magnitude_key in bh_significant_keys}"])

    # P10-VP-007: regime -> return distribution
    verdict = "PROMISING" if directional_info_present else "REJECTED"
    _advance_and_classify("P10-VP-007", verdict, [f"directional_info_present={directional_info_present} ({directional_detail}, Welch p={_fmt(directional_p_value)}); "
                                                    f"overlapping-window caveat applies — treat as modest, not decisive"])

    # P10-VP-008: regime -> drawdown
    verdict = "PROMISING" if risk_management_information else "INCONCLUSIVE"
    _advance_and_classify("P10-VP-008", verdict, [f"volatility_regime vs future_max_drawdown IC={_fmt(dd_ic)}"])

    # P10-VP-009 / P10-VP-010: compression/expansion
    comp_effect = None
    exp_effect = None
    comp_rows_h = [r for r in discovery_panel if r.get("volatility_compression") == 1.0]
    exp_rows_h = [r for r in discovery_panel if r.get("volatility_expansion") == 1.0]
    comp_up = _fraction_positive(comp_rows_h, f"future_volatility_direction_{PRIMARY_HORIZON}")
    exp_up = _fraction_positive(exp_rows_h, f"future_volatility_direction_{PRIMARY_HORIZON}")
    if comp_up is not None and baseline_up_prob is not None:
        comp_effect = comp_up - baseline_up_prob
    if exp_up is not None and baseline_up_prob is not None:
        exp_effect = baseline_up_prob - exp_up  # positive means expansion reduces P(further up), i.e. contraction signal
    verdict9 = "PROMISING" if (comp_effect is not None and comp_effect > 0.10) else "INCONCLUSIVE"
    _advance_and_classify("P10-VP-009", verdict9, [f"P(direction>0|compression)={_fmt(comp_up)} vs baseline={_fmt(baseline_up_prob)}, effect={_fmt(comp_effect)}"])
    verdict10 = "PROMISING" if (exp_effect is not None and exp_effect > 0.10) else "INCONCLUSIVE"
    _advance_and_classify("P10-VP-010", verdict10, [f"P(direction>0|expansion)={_fmt(exp_up)} vs baseline={_fmt(baseline_up_prob)}, effect={_fmt(exp_effect)}"])

    n_promising = sum(1 for v, _ in classifications.values() if v == "PROMISING")
    print(f"\n{n_promising}/{len(classifications)} hypotheses classified PROMISING.", flush=True)
    if n_promising > 0:
        print("RECOMMENDATION: PROMISING hypotheses may justify a SEPARATE, separately preregistered development-stage phase "
              "in the FUTURE — NOT created automatically here (Part 24). Per Part 19: 'volatility predicts volatility' (raw "
              "persistence) is expected and is NOT itself alpha — economic value requires surviving Part 8's incremental-info "
              "test AND showing genuine directional/economic content (Part 22), not just statistical significance.", flush=True)
    else:
        print("RECOMMENDATION: no hypothesis in this family cleared the PROMISING bar. STOP — do not invent a trading implementation.", flush=True)

    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))
    dims_fp = ExperimentDimensions(feature_definition=PRIMARY_FEATURE, parameter_range={"feature_set": list(FEATURE_SET), "target_set": list(TARGET_SET), "horizon_set": list(HORIZON_SET)}, universe_name=universe.name, target_definition=PRIMARY_TARGET, execution_model="n/a-discovery", cost_model="n/a-discovery", validation_methodology="cross-sectional discovery family on DISCOVERY_DATA")
    exp_store.record(
        data_version="phase5-campaign-v1", feature_version="phase10-discovery-v1", symbols=usable, timeframe="day",
        strategy_version="1.0", prediction_horizon=PRIMARY_HORIZON, train_period=(str(discovery_partition.start_date), str(discovery_partition.end_date)),
        parameters={"n_tests": len(raw_p_values), "n_hypotheses": len(classifications)},
        metrics={"primary_ic": primary_true_ic, "n_promising": n_promising},
        strategy_family="volatility_persistence", classification=("DISCOVERY_SUPPORTED" if n_promising > 0 else "NOT_READY"),
        tags=("phase10-discovery", universe.name), notes=f"{n_promising}/{len(classifications)} PROMISING; classifications={ {k: v[0] for k, v in classifications.items()} }",
        hypothesis_id="P10-VOLPERSIST", universe_name=universe.name, experiment_fingerprint=compute_experiment_fingerprint(dims_fp),
        research_family_id="P10-VOLPERSIST-DISCOVERY-2026-09",
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


def _fraction_positive(rows: list[dict], col: str) -> float | None:
    values = [r[col] for r in rows if r.get(col) is not None]
    if not values:
        return None
    return sum(1 for v in values if v > 0) / len(values)


def _directional_separation_welch(panel_rows: list[dict], state_col: str, target_col: str, *, min_count: int = 20) -> tuple[bool, float | None, str]:
    """Welch's t-test between the two volatility-regime states with the
    highest and lowest mean target value — a real significance test
    rather than an arbitrary magnitude threshold (Part 22's explicit
    "keep statistical vs economic significance separate" goal). Returns
    (present, p_value, detail-string). `present` requires BOTH p < 0.05
    AND a non-trivial magnitude gap (> 0.002, ~20bp over the primary
    5-bar horizon) — a tiny but "significant" gap from thousands of
    overlapping rows is not economically meaningful."""
    from src.research.stats_utils import two_tailed_p_value_from_z

    by_state: dict[str, list[float]] = {}
    for row in panel_rows:
        state, value = row.get(state_col), row.get(target_col)
        if state is not None and value is not None:
            by_state.setdefault(state, []).append(value)
    groups = {s: vs for s, vs in by_state.items() if len(vs) >= min_count}
    if len(groups) < 2:
        return False, None, "insufficient groups"

    means = {s: sum(vs) / len(vs) for s, vs in groups.items()}
    hi_state, lo_state = max(means, key=means.get), min(means, key=means.get)
    if hi_state == lo_state:
        return False, None, "no separation between states"
    hi, lo = groups[hi_state], groups[lo_state]
    mean_hi, mean_lo = means[hi_state], means[lo_state]
    var_hi = sum((v - mean_hi) ** 2 for v in hi) / (len(hi) - 1)
    var_lo = sum((v - mean_lo) ** 2 for v in lo) / (len(lo) - 1)
    se = (var_hi / len(hi) + var_lo / len(lo)) ** 0.5
    gap = mean_hi - mean_lo
    if se == 0:
        return False, None, f"{hi_state} vs {lo_state}: zero standard error"
    z = gap / se
    p = two_tailed_p_value_from_z(z)
    detail = f"{hi_state}(mean={mean_hi:.5f}) vs {lo_state}(mean={mean_lo:.5f}), gap={gap:.5f}"
    present = p < 0.05 and abs(gap) > 0.002
    return present, p, detail


if __name__ == "__main__":
    main()
