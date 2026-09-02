#!/usr/bin/env python3
"""Phase 13 — STEP 2: the full discovery-stage investigation of the
OVERNIGHT_INTRADAY_DECOMPOSITION hypothesis family (P13-OID-001..008) on
DISCOVERY_DATA only. No backtest, no trading strategy, no
DEVELOPMENT_DATA/VALIDATION_DATA/FINAL_HOLDOUT_DATA access anywhere. Must
be run AFTER scripts/phase13_step0_data_quality_gate.py (PROCEED) and
scripts/phase13_step1_preregister_hypotheses.py.

Covers Parts 8-25: cross-sectional IC, per-symbol time-series analysis,
quantile portfolios, reversal-vs-continuation, extreme-move analysis,
interaction OLS, disagreement-state analysis, volatility-adjusted return,
baselines, a 5-part placebo battery (incl. explicit autocorrelation
reporting for the alignment control), multiple-testing correction,
bootstrap, PBO, DSR, purged-CV leakage demo, regime/year/quarter
stability, and breadth/concentration.
"""

from __future__ import annotations

import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import HistoricalDataStore, run_universe_quality_report, us_diversified_universe  # noqa: E402
from src.features import FeatureEngine  # noqa: E402
from src.features.momentum import RateOfChange  # noqa: E402
from src.features.overnight_intraday import (  # noqa: E402
    AbsIntradayReturn,
    AbsOvernightReturn,
    GapExtremeness,
    IntradayExtremeness,
    IntradayReturn,
    OvernightIntradayDisagreement,
    OvernightIntradayInteraction,
    OvernightIntradayState,
    OvernightReturn,
)
from src.features.volatility import RealizedVolatility  # noqa: E402
from src.research import (  # noqa: E402
    DiscoveryDevelopmentGateStore,
    DiscoveryDevelopmentStage,
    ExperimentStore,
    PartitionLifecycleStage,
    PartitionStore,
    analyze_feature,
    autocorrelation_profile,
    benjamini_hochberg_fdr,
    block_bootstrap_return_series,
    bonferroni_correction,
    bucket_stats_by_state,
    compute_experiment_fingerprint,
    compute_ic_series,
    compute_pearson_ic_series,
    cross_sectional_quantile_returns,
    deflated_sharpe_ratio,
    effective_number_of_trials,
    filter_rows_by_partition,
    future_intraday_return,
    future_overnight_return,
    holm_bonferroni_correction,
    ic_by_regime,
    label_bars_by_regime,
    ols_regression,
    probability_of_backtest_overfitting,
    random_feature_control,
    require_preregistered,
    shifted_signal_placebo,
    shuffled_signal_placebo,
    stationary_bootstrap_return_series,
    summarize_ic,
    summarize_pearson_ic,
    time_shuffled_target_placebo,
)
from src.research.baseline import buy_and_hold_curve  # noqa: E402
from src.research.experiment_fingerprint import ExperimentDimensions  # noqa: E402
from src.research.phase10_targets import future_absolute_return  # noqa: E402
from src.research.preregistration import PreregistrationStore  # noqa: E402
from src.research.purged_cv import PurgedCVConfig, PurgedFold, fold_has_leakage, generate_purged_folds  # noqa: E402
from src.research.stats_utils import t_test_p_value  # noqa: E402
from src.research.targets import future_return  # noqa: E402
from src.research.volatility_targets import future_realized_volatility  # noqa: E402

VOL_WINDOW = 20
PRIMARY_HORIZON = 1
SECONDARY_HORIZON = 5
REGIME_SET = ("bull_high_vol", "bull_low_vol", "bear_high_vol", "bear_low_vol", "unknown")
FEATURE_SET = ("overnight_return", "intraday_return", "abs_overnight_return", "abs_intraday_return", "overnight_intraday_disagreement", "gap_extremeness_20", "intraday_extremeness_20")
TARGET_SET = ("next_close_to_close_return", "next_overnight_return", "next_intraday_return")
PRIMARY_TARGET = "next_close_to_close_return"
PRIMARY_FEATURE = "overnight_return"
COST_RATES_BPS = (10, 20, 30)
STARTING_CASH = 100_000.0


def _fmt(x) -> str:
    return "None" if x is None else f"{x:.5f}"


def _ic_p_value(points) -> float | None:
    values = [p.ic for p in points if p.ic is not None]
    if len(values) < 2:
        return None
    return t_test_p_value(values)


def _welch_p_value(a: list[float], b: list[float]) -> float | None:
    """Welch's t-test (unequal variance) two-sample p-value, built from
    scratch on top of the existing analysis/stats_utils primitives (Part 26
    requires "reasonable statistical confidence," not just a bare magnitude
    threshold — a magnitude-only check was the initial version of the
    P13-OID-007/008 classifications and was too weak relative to every
    other hypothesis's BH-significance-gated bar; fixed before finalizing)."""
    if len(a) < 2 or len(b) < 2:
        return None
    from src.research.analysis import mean as _mean
    from src.research.analysis import stdev as _stdev
    from src.research.stats_utils import two_tailed_p_value_from_z

    mean_a, mean_b = _mean(a), _mean(b)
    se = ((_stdev(a) ** 2) / len(a) + (_stdev(b) ** 2) / len(b)) ** 0.5
    if se == 0:
        return None
    z = (mean_a - mean_b) / se
    return two_tailed_p_value_from_z(z)


def build_panel(store, universe, usable: list[str]) -> tuple[list[dict], dict]:
    bars_by_symbol = {s: store.load(s, "day") for s in usable}
    engine = FeatureEngine([
        OvernightReturn(), IntradayReturn(), AbsOvernightReturn(), AbsIntradayReturn(),
        OvernightIntradayDisagreement(), GapExtremeness(VOL_WINDOW), IntradayExtremeness(VOL_WINDOW),
        OvernightIntradayState(), OvernightIntradayInteraction(), RealizedVolatility(VOL_WINDOW), RateOfChange(1),
    ])
    panel: list[dict] = []
    for sym in usable:
        bars = bars_by_symbol[sym]
        if not bars:
            continue
        frame = engine.compute(bars)
        raw_vol = frame.columns[f"realized_vol_{VOL_WINDOW}"]
        lagged_vol = [None] + list(raw_vol[:-1])  # same "excludes current bar" convention as GapExtremeness/IntradayExtremeness

        target_cols: dict[str, list] = {}
        for h in (PRIMARY_HORIZON, SECONDARY_HORIZON):
            target_cols[f"next_close_to_close_return_{h}"] = future_return(bars, h)
            target_cols[f"next_overnight_return_{h}"] = future_overnight_return(bars, h)
            target_cols[f"next_intraday_return_{h}"] = future_intraday_return(bars, h)
        target_cols[f"future_absolute_return_{PRIMARY_HORIZON}"] = future_absolute_return(bars, PRIMARY_HORIZON)
        target_cols[f"future_realized_volatility_{PRIMARY_HORIZON}"] = future_realized_volatility(bars, PRIMARY_HORIZON)

        for i, ts in enumerate(frame.timestamps):
            row = {"timestamp": ts, "symbol": sym}
            for name in FEATURE_SET:
                row[name] = frame.columns[name][i]
            row["overnight_intraday_state"] = frame.columns["overnight_intraday_state"][i]
            row["overnight_intraday_state_label"] = OvernightIntradayState.label_for(row["overnight_intraday_state"])
            row["overnight_intraday_interaction"] = frame.columns["overnight_intraday_interaction"][i]
            row["lagged_realized_vol_20"] = lagged_vol[i]
            row["lagged_close_to_close_1d"] = frame.columns["roc_1"][i]
            row["negative_control"] = (hash(sym) % 1000) / 1000.0
            for col_name, series in target_cols.items():
                row[col_name] = series[i]
            risk_adj = None
            future_ret_1 = row.get(f"next_close_to_close_return_{PRIMARY_HORIZON}")
            lv = row.get("lagged_realized_vol_20")
            if future_ret_1 is not None and lv is not None and lv != 0:
                risk_adj = future_ret_1 / lv
            row["risk_adjusted_future_return_1"] = risk_adj
            panel.append(row)
    return panel, bars_by_symbol


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    universe = us_diversified_universe()

    prereg_store = PreregistrationStore(Path("logs/research_data/phase13_preregistrations.jsonl"))
    require_preregistered(prereg_store, "P13-OID-FAMILY")
    for i in range(1, 9):
        require_preregistered(prereg_store, f"P13-OID-{i:03d}")

    partition_store = PartitionStore(Path("logs/research_data/phase7_partitions.jsonl"))
    discovery = partition_store.active_by_stage(PartitionLifecycleStage.DISCOVERY)[0]
    print(f"DISCOVERY_DATA: {discovery.start_date} .. {discovery.end_date}", flush=True)
    print("UNIVERSE LIMITATION: US_DIVERSIFIED is CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED.\n", flush=True)

    quality = run_universe_quality_report(store, universe, "day", min_bars_required=100)
    usable = [q.symbol for q in quality if q.available]
    print(f"Universe: {universe.name}  usable={len(usable)}/{len(universe.symbols)}", flush=True)

    print("Building the full feature/target panel (7 main-screen features + state + interaction, 3 targets x 2 horizons)...", flush=True)
    full_panel, bars_by_symbol_full = build_panel(store, universe, usable)
    discovery_panel = filter_rows_by_partition(full_panel, discovery)
    excluded = sum(1 for r in full_panel if r["timestamp"].date() >= discovery.start_date and r["timestamp"].date() <= discovery.end_date and r.get(PRIMARY_FEATURE) is None)
    print(f"Full panel: {len(full_panel)} rows. DISCOVERY_DATA panel: {len(discovery_panel)} rows. "
          f"(Part 22: exclusion is by None-propagation, never a silent fill — {excluded} discovery-window rows had an undefined primary feature.)\n", flush=True)

    regime_labels: dict = {}
    for sym in usable:
        regime_labels.update(label_bars_by_regime(bars_by_symbol_full[sym]))

    raw_p_values: list[tuple[str, float]] = []
    all_ic_results: dict[str, dict] = {}

    # ============================================================== PART A: MAIN SCREEN @ h=1 (21 tests)
    print(f"{'=' * 100}\nPART A — MAIN SCREEN @ h={PRIMARY_HORIZON}: {len(FEATURE_SET)} features x {len(TARGET_SET)} targets\n{'=' * 100}", flush=True)
    for feature_name in FEATURE_SET:
        row_str = []
        for target_name in TARGET_SET:
            target_col = f"{target_name}_{PRIMARY_HORIZON}"
            spearman_points = compute_ic_series(discovery_panel, feature_name, target_col, min_universe_size=3)
            spearman = summarize_ic(spearman_points, feature_name=feature_name, target_name=target_col)
            pearson_points = compute_pearson_ic_series(discovery_panel, feature_name, target_col, min_universe_size=3)
            pearson = summarize_pearson_ic(pearson_points, feature_name=feature_name, target_name=target_col)
            quantiles = cross_sectional_quantile_returns(discovery_panel, feature_name, target_col, n_quantiles=5, min_universe_size=3)
            key = f"{feature_name}|{target_name}|h{PRIMARY_HORIZON}"
            all_ic_results[key] = {"spearman": spearman, "pearson": pearson, "quantiles": quantiles, "spearman_points": spearman_points}
            row_str.append(f"{target_name[5:12]}:spear={_fmt(spearman.average_ic)}")
            p = _ic_p_value(spearman_points)
            if p is not None:
                raw_p_values.append((key, p))
        print(f"  {feature_name:32s}: " + "  ".join(row_str), flush=True)

    print(f"\nQuantile detail (primary target/horizon):", flush=True)
    primary_target_col = f"{PRIMARY_TARGET}_{PRIMARY_HORIZON}"
    for feature_name in FEATURE_SET:
        q = all_ic_results[f"{feature_name}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}"]["quantiles"]
        print(f"  {feature_name:32s}: spread={_fmt(q.spread_q5_minus_q1)}  monotonic={q.is_monotonic}  n_ts={q.timestamps_used}", flush=True)
        for qr in q.quantiles:
            print(f"      Q{qr.quantile}: n={qr.sample_count:5d} mean={qr.mean_return:.5f} hit_rate={qr.hit_rate:.2%} vol={qr.volatility:.5f} sharpe_like={_fmt(qr.mean_return / qr.volatility if qr.volatility else None)}", flush=True)

    # ============================================================== PART B: SECONDARY HORIZON (7 tests, primary target)
    print(f"\n{'=' * 100}\nPART B — SECONDARY HORIZON h={SECONDARY_HORIZON} ({PRIMARY_TARGET})\n{'=' * 100}", flush=True)
    secondary_target_col = f"{PRIMARY_TARGET}_{SECONDARY_HORIZON}"
    for feature_name in FEATURE_SET:
        spearman_points = compute_ic_series(discovery_panel, feature_name, secondary_target_col, min_universe_size=3)
        spearman = summarize_ic(spearman_points, feature_name=feature_name, target_name=secondary_target_col)
        key = f"{feature_name}|{PRIMARY_TARGET}|h{SECONDARY_HORIZON}"
        all_ic_results[key] = {"spearman": spearman, "spearman_points": spearman_points}
        print(f"  {feature_name:32s}: spearman_IC={_fmt(spearman.average_ic)}", flush=True)
        p = _ic_p_value(spearman_points)
        if p is not None:
            raw_p_values.append((key, p))

    # ============================================================== PART C: REGIME TABLE (35 tests)
    print(f"\n{'=' * 100}\nPART C — REGIME TABLE (all features @ primary target/horizon)\n{'=' * 100}", flush=True)
    regime_table: dict[str, dict] = {}
    for feature_name in FEATURE_SET:
        regime_result = ic_by_regime(discovery_panel, feature_name, primary_target_col, regime_labels, min_universe_size=3)
        regime_table[feature_name] = regime_result
        print(f"  {feature_name:32s}: " + "; ".join(f"{r}={_fmt(s.average_ic)}(n={sum(1 for p in s.points if p.ic is not None)})" for r, s in regime_result.items()), flush=True)
        for regime_name, summary in regime_result.items():
            p_val = _ic_p_value(summary.points)
            if p_val is not None:
                raw_p_values.append((f"{feature_name}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}|regime={regime_name}", p_val))

    print(f"\nTotal raw p-values collected across the complete preregistered family: {len(raw_p_values)}", flush=True)

    pooled_ic = all_ic_results[f"{PRIMARY_FEATURE}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}"]["spearman"].average_ic

    # ============================================================== PART 9: TIME-SERIES ANALYSIS (per symbol)
    print(f"\n{'=' * 100}\nPART 9 — PER-SYMBOL TIME-SERIES ANALYSIS (primary feature/target)\n{'=' * 100}", flush=True)
    per_symbol_positive = 0
    per_symbol_results = {}
    for sym in usable:
        sym_rows = [r for r in discovery_panel if r["symbol"] == sym]
        result = analyze_feature(sym_rows, PRIMARY_FEATURE, primary_target_col, n_quantiles=3)
        y = [r.get(primary_target_col) for r in sym_rows]
        x = [r.get(PRIMARY_FEATURE) for r in sym_rows]
        ols = ols_regression(y, {"feature": x}, min_observations=30)
        per_symbol_results[sym] = (result, ols)
        if result.spearman_correlation is not None and result.spearman_correlation > 0:
            per_symbol_positive += 1
        coef_str = f"coef={_fmt(ols.coefficients.get('feature'))} t={ols.coefficient_t_stats.get('feature', 0):.2f} p={ols.coefficient_p_values.get('feature', 1):.4g}" if ols.applicable else "NOT_APPLICABLE"
        print(f"  {sym}: n={result.sample_count}  spearman={_fmt(result.spearman_correlation)}  pearson={_fmt(result.pearson_correlation)}  OLS: {coef_str}", flush=True)
    print(f"\n  symbols with positive per-symbol IC: {per_symbol_positive}/{len(usable)}", flush=True)
    print("  DEPENDENCE-AWARE CAVEAT: per-symbol OLS t-stats above assume i.i.d. residuals — daily returns are typically only "
          "weakly serially dependent but NOT strictly independent; the block/stationary bootstrap intervals in Part 18 below "
          "are the dependence-aware check these OLS p-values should be read alongside, not in place of.", flush=True)

    # ============================================================== PART 10: REVERSAL VS CONTINUATION (P13-OID-002/003)
    print(f"\n{'=' * 100}\nPART 10 — REVERSAL VS CONTINUATION (pooled top-quintile |overnight|, |intraday|)\n{'=' * 100}", flush=True)

    def _top_quintile_sign_consistency(feature_col: str, raw_col: str, target_col: str) -> dict:
        rows_with_vals = [r for r in discovery_panel if r.get(feature_col) is not None and r.get(raw_col) is not None and r.get(target_col) is not None]
        sorted_rows = sorted(rows_with_vals, key=lambda r: r[feature_col])
        n = len(sorted_rows)
        top_quintile = sorted_rows[int(n * 0.8):]
        sign_consistency = [1.0 if (r[raw_col] > 0) == (r[target_col] > 0) else (0.0 if (r[raw_col] > 0) != (r[target_col] > 0) else 0.5) for r in top_quintile if r[raw_col] != 0]
        mean_signed_product = sum((1 if r[raw_col] > 0 else -1) * r[target_col] for r in top_quintile) / len(top_quintile) if top_quintile else None
        return {"n": len(top_quintile), "fraction_same_sign": (sum(sign_consistency) / len(sign_consistency)) if sign_consistency else None, "mean_signed_product": mean_signed_product}

    overnight_extreme = _top_quintile_sign_consistency("abs_overnight_return", "overnight_return", primary_target_col)
    print(f"  overnight (top quintile |overnight_return|, n={overnight_extreme['n']}): fraction_same_sign_as_target={_fmt(overnight_extreme['fraction_same_sign'])}  "
          f"mean(sign(overnight)*target)={_fmt(overnight_extreme['mean_signed_product'])}  "
          f"-> {'CONTINUATION' if (overnight_extreme['mean_signed_product'] or 0) > 0 else 'REVERSAL'}", flush=True)
    intraday_extreme = _top_quintile_sign_consistency("abs_intraday_return", "intraday_return", primary_target_col)
    print(f"  intraday (top quintile |intraday_return|, n={intraday_extreme['n']}): fraction_same_sign_as_target={_fmt(intraday_extreme['fraction_same_sign'])}  "
          f"mean(sign(intraday)*target)={_fmt(intraday_extreme['mean_signed_product'])}  "
          f"-> {'CONTINUATION' if (intraday_extreme['mean_signed_product'] or 0) > 0 else 'REVERSAL'}", flush=True)

    # ============================================================== PART 11: EXTREME MOVE ANALYSIS
    print(f"\n{'=' * 100}\nPART 11 — EXTREME MOVE ANALYSIS (pooled quantile buckets, directional vs magnitude predictability)\n{'=' * 100}", flush=True)
    for feature_col in ("abs_overnight_return", "abs_intraday_return"):
        rows_with_vals = [r for r in discovery_panel if r.get(feature_col) is not None]
        sorted_rows = sorted(rows_with_vals, key=lambda r: r[feature_col])
        n = len(sorted_rows)
        print(f"  {feature_col}:", flush=True)
        for q in range(5):
            bucket = sorted_rows[(q * n) // 5 : ((q + 1) * n) // 5]
            rets = [r.get(primary_target_col) for r in bucket if r.get(primary_target_col) is not None]
            abs_rets = [r.get(f"future_absolute_return_{PRIMARY_HORIZON}") for r in bucket if r.get(f"future_absolute_return_{PRIMARY_HORIZON}") is not None]
            future_vols = [r.get(f"future_realized_volatility_{PRIMARY_HORIZON}") for r in bucket if r.get(f"future_realized_volatility_{PRIMARY_HORIZON}") is not None]
            mean_ret = sum(rets) / len(rets) if rets else None
            mean_abs_ret = sum(abs_rets) / len(abs_rets) if abs_rets else None
            mean_vol = sum(future_vols) / len(future_vols) if future_vols else None
            print(f"    Q{q + 1}: n={len(bucket):5d}  future_return={_fmt(mean_ret)}  future_abs_return={_fmt(mean_abs_ret)}  future_realized_vol={_fmt(mean_vol)}", flush=True)

    # ============================================================== PART 12: INTERACTION REGRESSION (P13-OID-006)
    print(f"\n{'=' * 100}\nPART 12 — OVERNIGHT/INTRADAY INTERACTION (OLS, preregistered before any result seen)\n{'=' * 100}", flush=True)
    y = [r.get(primary_target_col) for r in discovery_panel]
    overnight = [r.get("overnight_return") for r in discovery_panel]
    intraday = [r.get("intraday_return") for r in discovery_panel]
    interaction = [r.get("overnight_intraday_interaction") for r in discovery_panel]
    model_ab = ols_regression(y, {"overnight": overnight, "intraday": intraday}, min_observations=30)
    model_abc = ols_regression(y, {"overnight": overnight, "intraday": intraday, "interaction": interaction}, min_observations=30)
    print(f"  Model AB  (future_return ~ overnight + intraday):              {model_ab.render()}", flush=True)
    print(f"  Model ABC (future_return ~ overnight + intraday + overnight*intraday): {model_abc.render()}", flush=True)
    interaction_incremental = None
    if model_ab.applicable and model_abc.applicable:
        interaction_incremental = model_abc.r_squared - model_ab.r_squared
        interaction_p = model_abc.coefficient_p_values.get("interaction", 1.0)
        print(f"\n  Interaction incremental R2 = {interaction_incremental:.5f}  interaction_coefficient_p={interaction_p:.4g}", flush=True)

    # ============================================================== PART 13: DISAGREEMENT ANALYSIS (P13-OID-007)
    print(f"\n{'=' * 100}\nPART 13 — DISAGREEMENT STATE ANALYSIS (4 preregistered states)\n{'=' * 100}", flush=True)
    state_stats = bucket_stats_by_state(discovery_panel, "overnight_intraday_state_label", primary_target_col, min_count=20)
    for label in OvernightIntradayState.LABELS:
        s = state_stats.get(label)
        kind = "AGREEMENT" if label in ("+/+", "-/-") else "DISAGREEMENT"
        if s is None:
            print(f"  {label} ({kind}): no observations", flush=True)
            continue
        print(f"  {label} ({kind}): n={s.sample_count:6d}  mean={_fmt(s.mean_value)}  median={_fmt(s.median_value)}  stdev={_fmt(s.stdev_value)}  "
              f"sharpe_like={_fmt(s.sharpe_like)}  win_rate={_fmt(s.win_rate)}", flush=True)
    agreement_means = [state_stats[l].mean_value for l in ("+/+", "-/-") if l in state_stats and state_stats[l].mean_value is not None]
    disagreement_means = [state_stats[l].mean_value for l in ("+/-", "-/+") if l in state_stats and state_stats[l].mean_value is not None]
    print(f"\n  mean(agreement states)={_fmt(sum(agreement_means) / len(agreement_means) if agreement_means else None)}  "
          f"mean(disagreement states)={_fmt(sum(disagreement_means) / len(disagreement_means) if disagreement_means else None)}", flush=True)
    agreement_rows = [r[primary_target_col] for r in discovery_panel if r.get("overnight_intraday_state_label") in ("+/+", "-/-") and r.get(primary_target_col) is not None]
    disagreement_rows = [r[primary_target_col] for r in discovery_panel if r.get("overnight_intraday_state_label") in ("+/-", "-/+") and r.get(primary_target_col) is not None]

    # ============================================================== PART 14: VOLATILITY-ADJUSTED RETURN (P13-OID-008)
    print(f"\n{'=' * 100}\nPART 14 — VOLATILITY-ADJUSTED RETURN (extreme combined gap+intraday state)\n{'=' * 100}", flush=True)
    combined_rows = [r for r in discovery_panel if r.get("gap_extremeness_20") is not None and r.get("intraday_extremeness_20") is not None]
    for r in combined_rows:
        r["_combined_extremeness"] = abs(r["gap_extremeness_20"]) + abs(r["intraday_extremeness_20"])
    sorted_combined = sorted(combined_rows, key=lambda r: r["_combined_extremeness"])
    n = len(sorted_combined)
    top_quintile = sorted_combined[int(n * 0.8):]
    bottom_quintile = sorted_combined[: int(n * 0.2)]
    for label, bucket in (("Q5 (most extreme)", top_quintile), ("Q1 (least extreme)", bottom_quintile)):
        risk_adj = [r.get("risk_adjusted_future_return_1") for r in bucket if r.get("risk_adjusted_future_return_1") is not None]
        rets = [r.get(primary_target_col) for r in bucket if r.get(primary_target_col) is not None]
        abs_rets = [r.get(f"future_absolute_return_{PRIMARY_HORIZON}") for r in bucket if r.get(f"future_absolute_return_{PRIMARY_HORIZON}") is not None]
        future_vols = [r.get(f"future_realized_volatility_{PRIMARY_HORIZON}") for r in bucket if r.get(f"future_realized_volatility_{PRIMARY_HORIZON}") is not None]
        print(f"  {label}: n={len(bucket):5d}  mean_risk_adjusted_future_return={_fmt(sum(risk_adj) / len(risk_adj) if risk_adj else None)}  "
              f"mean_future_return={_fmt(sum(rets) / len(rets) if rets else None)}  mean_future_abs_return={_fmt(sum(abs_rets) / len(abs_rets) if abs_rets else None)}  "
              f"mean_future_realized_vol={_fmt(sum(future_vols) / len(future_vols) if future_vols else None)}", flush=True)

    # ============================================================== PART 15: BASELINES
    print(f"\n{'=' * 100}\nPART 15 — BASELINES\n{'=' * 100}", flush=True)
    random_ctrl = random_feature_control(discovery_panel, target_col=primary_target_col, n_trials=100, seed=801, min_universe_size=3)
    random_mean_ic = sum(random_ctrl.placebo_distribution) / len(random_ctrl.placebo_distribution) if random_ctrl.placebo_distribution else None
    print(f"  1. random feature: mean_IC={_fmt(random_mean_ic)}", flush=True)
    shuffled = shuffled_signal_placebo(discovery_panel, feature_col=PRIMARY_FEATURE, target_col=primary_target_col, n_trials=100, seed=802)
    print(f"  2. shuffled feature: observed_IC={_fmt(shuffled.observed_statistic)}  p={shuffled.empirical_p_value}", flush=True)
    negctrl_ic = summarize_ic(compute_ic_series(discovery_panel, "negative_control", primary_target_col, min_universe_size=3), feature_name="negative_control", target_name=primary_target_col)
    print(f"  3. negative-control feature (symbol-hash): IC={_fmt(negctrl_ic.average_ic)}", flush=True)
    momentum_ic = summarize_ic(compute_ic_series(discovery_panel, "lagged_close_to_close_1d", primary_target_col, min_universe_size=3), feature_name="lagged_close_to_close_1d", target_name=primary_target_col)
    print(f"  4. raw close-to-close momentum (yesterday's 1d return): IC={_fmt(momentum_ic.average_ic)}", flush=True)
    vol_ic = summarize_ic(compute_ic_series(discovery_panel, "lagged_realized_vol_20", primary_target_col, min_universe_size=3), feature_name="lagged_realized_vol_20", target_name=primary_target_col)
    print(f"  5. lagged realized volatility: IC={_fmt(vol_ic.average_ic)}", flush=True)
    spy_bars = [b for b in bars_by_symbol_full["SPY"] if discovery.start_date <= b.timestamp.date() <= discovery.end_date]
    bh_curve = buy_and_hold_curve(spy_bars, starting_cash=STARTING_CASH)
    bh_return = (bh_curve[-1].equity - STARTING_CASH) / STARTING_CASH if bh_curve else None
    print(f"  6. buy-and-hold SPY over DISCOVERY_DATA: total_return={_fmt(bh_return)}  (reference only — no signal-driven backtest this phase)", flush=True)
    ew_returns = []
    for sym in usable:
        bars = [b for b in bars_by_symbol_full[sym] if discovery.start_date <= b.timestamp.date() <= discovery.end_date]
        if len(bars) >= 2 and bars[0].close > 0:
            ew_returns.append((bars[-1].close - bars[0].close) / bars[0].close)
    print(f"  7. equal-weight US_DIVERSIFIED over DISCOVERY_DATA: mean_symbol_total_return={_fmt(sum(ew_returns) / len(ew_returns) if ew_returns else None)}  (reference only)", flush=True)

    # ============================================================== PART 16: PLACEBO BATTERY
    print(f"\n{'=' * 100}\nPART 16 — PLACEBO BATTERY\n{'=' * 100}", flush=True)
    print(f"  A. cross-sectional feature shuffle: observed_IC={_fmt(shuffled.observed_statistic)}  p={shuffled.empirical_p_value}  (see baseline 2 above)", flush=True)
    time_shuffled = time_shuffled_target_placebo(discovery_panel, feature_col=PRIMARY_FEATURE, target_col=primary_target_col, n_trials=200, seed=803)
    print(f"  B. time shuffle: observed_IC={_fmt(time_shuffled.observed_statistic)}  p={time_shuffled.empirical_p_value}", flush=True)

    rng = random.Random(804)
    random_sign_rows = [dict(r) for r in discovery_panel]
    for r in random_sign_rows:
        if r.get(PRIMARY_FEATURE) is not None:
            r[PRIMARY_FEATURE] = abs(r[PRIMARY_FEATURE]) * rng.choice((1, -1))
    random_sign_ic = summarize_ic(compute_ic_series(random_sign_rows, PRIMARY_FEATURE, primary_target_col, min_universe_size=3), feature_name=PRIMARY_FEATURE, target_name=primary_target_col)
    print(f"  C. random-sign placebo (magnitude preserved, sign randomized): IC={_fmt(random_sign_ic.average_ic)}  (true_IC={_fmt(pooled_ic)})", flush=True)
    print(f"  D. negative-control feature: IC={_fmt(negctrl_ic.average_ic)}  (see baseline 3 above)", flush=True)

    alignment_concern = False
    for shift in (1, 2, 5):
        shifted = shifted_signal_placebo(discovery_panel, feature_col=PRIMARY_FEATURE, target_col=primary_target_col, shift_bars=shift)
        shifted_ic = shifted.placebo_distribution[0] if shifted.placebo_distribution else None
        flag = shifted_ic is not None and pooled_ic is not None and abs(shifted_ic) >= abs(pooled_ic)
        alignment_concern = alignment_concern or flag
        print(f"  E. alignment control shift=+{shift}: true_IC={_fmt(pooled_ic)}  shifted_IC={_fmt(shifted_ic)}  {'<-- CONCERN' if flag else ''}", flush=True)

    print("\n  Feature/target autocorrelation (required context for interpreting E, per Part 16's explicit instruction):", flush=True)
    lags = (1, 2, 3, 5, 10)
    for series_name, extractor in (
        (PRIMARY_FEATURE, lambda bars: OvernightReturn().compute(bars)),
        (primary_target_col, lambda bars: future_return(bars, PRIMARY_HORIZON)),
    ):
        by_lag: dict[int, list[float]] = defaultdict(list)
        for sym in usable:
            series = extractor(bars_by_symbol_full[sym])
            profile = autocorrelation_profile(series, lags)
            for lag, val in profile.items():
                if val is not None:
                    by_lag[lag].append(val)
        avgs = {lag: (sum(vals) / len(vals) if vals else None) for lag, vals in by_lag.items()}
        print(f"    {series_name:28s}: " + "  ".join(f"lag{lag}={_fmt(avgs.get(lag))}" for lag in lags), flush=True)
    print("  INTERPRETATION: overnight_return is, by construction, a DAILY, largely non-overlapping series (unlike a "
          "20-day trailing momentum feature) — low feature/target autocorrelation at every lag (printed above) would mean "
          "an elevated shifted-alignment IC (if any) CANNOT be explained by the same autocorrelation artifact Phase 12 "
          "found for return_20d, and should instead be treated as a genuine implementation concern requiring investigation, "
          "per Part 16's explicit instruction not to wave away a shifted-signal finding by assumption.", flush=True)

    # ============================================================== PART 17: MULTIPLE TESTING
    print(f"\n{'=' * 100}\nPART 17 — MULTIPLE-TESTING CORRECTION (complete family, n={len(raw_p_values)})\n{'=' * 100}", flush=True)
    for method in (bonferroni_correction, holm_bonferroni_correction, benjamini_hochberg_fdr):
        report = method(raw_p_values, alpha=0.05)
        print(f"  {report.method}: n_significant={report.n_significant}/{report.n_tests}", flush=True)
    bh_report = benjamini_hochberg_fdr(raw_p_values, alpha=0.05)
    bh_significant_keys = {r.label for r in bh_report.results if r.significant_at_alpha}
    primary_key = f"{PRIMARY_FEATURE}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}"
    primary_bh = next((r for r in bh_report.results if r.label == primary_key), None)
    print(f"\n  Primary test ({primary_key}) BH-adjusted p={primary_bh.adjusted_p_value if primary_bh else 'N/A'}  significant={primary_bh.significant_at_alpha if primary_bh else 'N/A'}", flush=True)
    complete_rows = [r for r in discovery_panel[:2000] if all(r.get(name) is not None for name in FEATURE_SET)][:500]
    feature_value_series = {name: [r[name] for r in complete_rows] for name in FEATURE_SET}
    eff_trials = effective_number_of_trials(list(feature_value_series.values()))
    print(f"  {eff_trials.render()}", flush=True)

    # ============================================================== PART 18: BOOTSTRAP
    print(f"\n{'=' * 100}\nPART 18 — BOOTSTRAP (block + stationary) on {PRIMARY_FEATURE}'s IC series and Q5-Q1 spread series\n{'=' * 100}", flush=True)
    primary_ic_series = [p.ic for p in all_ic_results[f"{PRIMARY_FEATURE}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}"]["spearman_points"] if p.ic is not None]
    for conf in (0.90, 0.95):
        block_report = block_bootstrap_return_series(primary_ic_series, block_size=5, n_resamples=2000, seed=901, confidence_level=conf)
        print(f"  IC series, block bootstrap ({conf:.0%} CI): {block_report.render()}", flush=True)

    by_ts: dict = defaultdict(list)
    for row in discovery_panel:
        f, t = row.get(PRIMARY_FEATURE), row.get(primary_target_col)
        if f is not None and t is not None:
            by_ts[row["timestamp"]].append((f, t))
    q5_series, q1_series = [], []
    for ts in sorted(by_ts):
        triples = by_ts[ts]
        if len(triples) < 3:
            continue
        ranked = sorted(triples, key=lambda t: t[0])
        n = len(ranked)
        q1_vals = [t for _f, t in ranked[: max(1, n // 5)]]
        q5_vals = [t for _f, t in ranked[-max(1, n // 5):]]
        q1_series.append(sum(q1_vals) / len(q1_vals))
        q5_series.append(sum(q5_vals) / len(q5_vals))
    spread_series = [q5 - q1 for q5, q1 in zip(q5_series, q1_series)]
    for conf in (0.90, 0.95):
        spread_report = stationary_bootstrap_return_series(spread_series, mean_block_length=5.0, n_resamples=2000, seed=902, confidence_level=conf)
        print(f"  Q5-Q1 spread series, stationary bootstrap ({conf:.0%} CI): {spread_report.render()}", flush=True)

    # ============================================================== PART 19: PBO / DSR
    print(f"\n{'=' * 100}\nPART 19 — PBO / DSR (across the {len(FEATURE_SET)} preregistered main-screen features)\n{'=' * 100}", flush=True)
    n_periods = 8
    period_matrix: list[list[float]] = []
    disc_start, disc_end = discovery.start_date, discovery.end_date
    total_days = (disc_end - disc_start).days + 1
    for feature_name in FEATURE_SET:
        points = all_ic_results[f"{feature_name}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}"]["spearman_points"]
        buckets: list[list[float]] = [[] for _ in range(n_periods)]
        for p in points:
            if p.ic is None:
                continue
            day_offset = (p.timestamp.date() - disc_start).days
            bucket = min(n_periods - 1, max(0, (day_offset * n_periods) // total_days))
            buckets[bucket].append(p.ic)
        period_matrix.append([sum(b) / len(b) if b else 0.0 for b in buckets])
    pbo = probability_of_backtest_overfitting(period_matrix)
    print(f"  {pbo.render()}", flush=True)
    best_feature_idx = max(range(len(FEATURE_SET)), key=lambda i: abs(all_ic_results[f"{FEATURE_SET[i]}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}"]["spearman"].average_ic or 0))
    best_feature = FEATURE_SET[best_feature_idx]
    best_ic_series = [p.ic for p in all_ic_results[f"{best_feature}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}"]["spearman_points"] if p.ic is not None]
    dsr = deflated_sharpe_ratio(best_ic_series, n_trials=len(FEATURE_SET))
    print(f"  DSR applied to {best_feature}'s own per-timestamp IC series (n_trials={len(FEATURE_SET)}): {dsr.render()}", flush=True)

    # ============================================================== PART 20: PURGED/EMBARGOED CV DEMO
    print(f"\n{'=' * 100}\nPART 20 — PURGED/EMBARGOED CV LEAKAGE DEMONSTRATION\n{'=' * 100}", flush=True)
    sample_bars = bars_by_symbol_full["SPY"]
    sample_timestamps = [b.timestamp for b in sample_bars]
    cv_config = PurgedCVConfig(n_splits=6, prediction_horizon_bars=PRIMARY_HORIZON, purge_window_bars=2, embargo_bars=2)
    purged_folds = generate_purged_folds(sample_timestamps, cv_config)
    purged_leakage = [fold_has_leakage(f, sample_timestamps, prediction_horizon_bars=PRIMARY_HORIZON) for f in purged_folds]
    print(f"  purged CV: {sum(purged_leakage)}/{len(purged_folds)} folds show leakage (expected: 0)", flush=True)

    def _naive_folds(n: int, n_splits: int) -> list[PurgedFold]:
        base_size = n // n_splits
        remainder = n % n_splits
        folds = []
        start = 0
        for k in range(n_splits):
            size = base_size + (1 if k < remainder else 0)
            test_idx = tuple(range(start, start + size))
            train_idx = tuple(i for i in range(n) if i not in test_idx)
            folds.append(PurgedFold(fold_index=k, test_indices=test_idx, train_indices=train_idx, purged_count=0, embargoed_count=0))
            start += size
        return folds

    naive_folds = _naive_folds(len(sample_timestamps), 6)
    naive_leakage = [fold_has_leakage(f, sample_timestamps, prediction_horizon_bars=PRIMARY_HORIZON) for f in naive_folds]
    print(f"  naive (unpurged) CV: {sum(naive_leakage)}/{len(naive_folds)} folds show leakage (expected: > 0)", flush=True)
    print("  Rolling-volatility/rolling-statistics causality: GapExtremeness/IntradayExtremeness use a volatility figure "
          "LAGGED by one full bar relative to RealizedVolatility's own causal convention (see "
          "src/features/overnight_intraday.py's module docstring) — independently proven by "
          "tests/test_overnight_intraday_features.py's no-lookahead + explicit lagged-baseline tests.", flush=True)

    # ============================================================== PART 21-22-23: REGIME/YEAR/QUARTER + BREADTH + COSTS
    print(f"\n{'=' * 100}\nPART 21 — TIME STABILITY (year, quarter, primary feature/target)\n{'=' * 100}", flush=True)
    years = sorted({r["timestamp"].year for r in discovery_panel})
    for year in years:
        year_rows = [r for r in discovery_panel if r["timestamp"].year == year]
        year_ic = summarize_ic(compute_ic_series(year_rows, PRIMARY_FEATURE, primary_target_col, min_universe_size=3), feature_name=PRIMARY_FEATURE, target_name=primary_target_col)
        print(f"  {year}: IC={_fmt(year_ic.average_ic)}  n_rows={len(year_rows)}", flush=True)
    print("\n  By quarter:", flush=True)
    quarters = sorted({(r["timestamp"].year, (r["timestamp"].month - 1) // 3 + 1) for r in discovery_panel})
    for year, q in quarters:
        q_rows = [r for r in discovery_panel if r["timestamp"].year == year and (r["timestamp"].month - 1) // 3 + 1 == q]
        if len(q_rows) < 30:
            continue
        q_ic = summarize_ic(compute_ic_series(q_rows, PRIMARY_FEATURE, primary_target_col, min_universe_size=3), feature_name=PRIMARY_FEATURE, target_name=primary_target_col)
        print(f"  {year}Q{q}: IC={_fmt(q_ic.average_ic)}  n_rows={len(q_rows)}", flush=True)

    print(f"\n{'=' * 100}\nPART 25 — BREADTH / CONCENTRATION\n{'=' * 100}", flush=True)
    loo_swings = []
    for sym in usable:
        rows_without = [r for r in discovery_panel if r["symbol"] != sym]
        without_ic = summarize_ic(compute_ic_series(rows_without, PRIMARY_FEATURE, primary_target_col, min_universe_size=3), feature_name=PRIMARY_FEATURE, target_name=primary_target_col).average_ic
        swing = abs((without_ic or 0) - (pooled_ic or 0))
        loo_swings.append((sym, without_ic, swing))
    loo_swings.sort(key=lambda t: t[2], reverse=True)
    for sym, without_ic, swing in loo_swings[:5]:
        print(f"  without {sym}: IC={_fmt(without_ic)}  swing={_fmt(swing)}", flush=True)
    sign_flips = [sym for sym, ic, _ in loo_swings if ic is not None and pooled_ic is not None and (ic > 0) != (pooled_ic > 0)]
    print(f"  max swing: {loo_swings[0][2]:.5f}  sign_flips_without: {sign_flips}", flush=True)
    print("\n  Leave-one-sector-out:", flush=True)
    for sector_name, sector_symbols in universe.by_sector().items():
        rows_without = [r for r in discovery_panel if r["symbol"] not in sector_symbols]
        without_ic = summarize_ic(compute_ic_series(rows_without, PRIMARY_FEATURE, primary_target_col, min_universe_size=3), feature_name=PRIMARY_FEATURE, target_name=primary_target_col).average_ic
        print(f"  without sector={sector_name}: IC={_fmt(without_ic)}", flush=True)

    # ============================================================== PART 23: TURNOVER AND COST SENSITIVITY
    print(f"\n{'=' * 100}\nPART 23 — TURNOVER AND ESTIMATED TRANSACTION COSTS (Q5-Q1 diagnostic, daily rebalance)\n{'=' * 100}", flush=True)
    quantile_membership: dict = {}
    for ts in sorted(by_ts):
        triples = by_ts[ts]
        if len(triples) < 3:
            continue
        # re-derive membership sets (feature, target) -> need symbol too; recompute from discovery_panel directly for this ts
        rows_ts = [r for r in discovery_panel if r["timestamp"] == ts and r.get(PRIMARY_FEATURE) is not None]
        ranked = sorted(rows_ts, key=lambda r: r[PRIMARY_FEATURE])
        n = len(ranked)
        q5_members = {r["symbol"] for r in ranked[-max(1, n // 5):]}
        quantile_membership[ts] = q5_members
    ts_sorted = sorted(quantile_membership.keys())
    turnovers = []
    for prev_ts, cur_ts in zip(ts_sorted, ts_sorted[1:]):
        prev_m, cur_m = quantile_membership[prev_ts], quantile_membership[cur_ts]
        if not prev_m and not cur_m:
            continue
        changed = len(prev_m.symmetric_difference(cur_m))
        denom = max(1, len(prev_m) + len(cur_m))
        turnovers.append(changed / denom)
    avg_turnover = sum(turnovers) / len(turnovers) if turnovers else 0.0
    gross_spread = all_ic_results[f"{PRIMARY_FEATURE}|{PRIMARY_TARGET}|h{PRIMARY_HORIZON}"]["quantiles"].spread_q5_minus_q1
    print(f"  avg Q5 daily turnover (h={PRIMARY_HORIZON}, i.e. rebalanced EVERY session): {avg_turnover:.3f}   gross Q5-Q1 spread: {_fmt(gross_spread)}", flush=True)
    print("  WARNING (Part 23's explicit instruction): this is a DAILY-rebalanced signal — transaction costs apply on "
          "essentially every session, unlike a 20-day-momentum signal's much lower turnover.", flush=True)
    for mult, bps in zip((1, 2, 3), COST_RATES_BPS):
        cost_drag = avg_turnover * (bps / 10_000) * 2
        net_spread = None if gross_spread is None else gross_spread - cost_drag
        print(f"  {mult}x ({bps}bps one-way): estimated cost_drag={cost_drag:.5f}  net_Q5-Q1_spread={_fmt(net_spread)}  "
              f"viable={'True' if (net_spread or -1) > 0 else 'False'}", flush=True)

    # ============================================================== FINAL CLASSIFICATION (Part 26) & GATE (Part 30)
    print(f"\n{'=' * 100}\nFINAL PER-HYPOTHESIS CLASSIFICATION\n{'=' * 100}", flush=True)
    gate_store = DiscoveryDevelopmentGateStore(Path("logs/research_data/phase13_gate_transitions.jsonl"))
    classifications: dict[str, tuple[str, str]] = {}

    def _advance_and_classify(hyp_id: str, verdict: str, reason: str) -> None:
        classifications[hyp_id] = (verdict, reason)
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.IDEA, reason="new OVERNIGHT_INTRADAY_DECOMPOSITION hypothesis", evidence_summary="")
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.PREREGISTERED, reason="preregistered before any analysis ran", evidence_summary="")
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DISCOVERY_TESTED, reason="discovery family completed", evidence_summary=reason)
        if verdict == "DISCOVERY_SUPPORTED":
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DISCOVERY_SUPPORTED, reason=reason, evidence_summary=reason)
        else:
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.NOT_READY, reason=f"classified {verdict}: {reason}", evidence_summary=reason)
        print(f"  {hyp_id}: {verdict} — {reason}", flush=True)

    def _classify_feature(feature_name: str, target_name: str = PRIMARY_TARGET) -> tuple[str, str]:
        key = f"{feature_name}|{target_name}|h{PRIMARY_HORIZON}"
        bh_sig = key in bh_significant_keys
        result = all_ic_results.get(key)
        if result is None:
            return "NOT_READY", "no result computed for this key"
        ic = result["spearman"].average_ic
        q = result.get("quantiles")
        reason = f"IC={_fmt(ic)}, BH-significant={bh_sig}, monotonic={q.is_monotonic if q else 'N/A'}, breadth={per_symbol_positive}/{len(usable)}"
        if not bh_sig:
            return ("REJECTED" if ic is not None and abs(ic) < 0.01 else "INCONCLUSIVE"), reason
        if q is not None and not q.is_monotonic:
            return "FRAGILE", reason
        if per_symbol_positive < len(usable) * 0.5:
            return "FRAGILE", reason
        return "DISCOVERY_SUPPORTED", reason

    v, r = _classify_feature("overnight_return")
    _advance_and_classify("P13-OID-001", v, r)

    verdict_002 = "DISCOVERY_SUPPORTED" if (overnight_extreme["mean_signed_product"] or 0) < -0.001 else "REJECTED" if (overnight_extreme["mean_signed_product"] or 0) > 0 else "INCONCLUSIVE"
    _advance_and_classify("P13-OID-002", verdict_002, f"top-quintile |overnight| mean(sign*target)={_fmt(overnight_extreme['mean_signed_product'])} (negative required for reversal)")
    verdict_003 = "DISCOVERY_SUPPORTED" if (overnight_extreme["mean_signed_product"] or 0) > 0.001 else "REJECTED" if (overnight_extreme["mean_signed_product"] or 0) < 0 else "INCONCLUSIVE"
    _advance_and_classify("P13-OID-003", verdict_003, f"top-quintile |overnight| mean(sign*target)={_fmt(overnight_extreme['mean_signed_product'])} (positive required for continuation)")

    v, r = _classify_feature("intraday_return")
    _advance_and_classify("P13-OID-004", v, r)

    verdict_005 = "DISCOVERY_SUPPORTED" if (intraday_extreme["mean_signed_product"] or 0) < -0.001 else "REJECTED" if (intraday_extreme["mean_signed_product"] or 0) > 0 else "INCONCLUSIVE"
    _advance_and_classify("P13-OID-005", verdict_005, f"top-quintile |intraday| mean(sign*target)={_fmt(intraday_extreme['mean_signed_product'])} (negative required for reversal)")

    verdict_006 = "DISCOVERY_SUPPORTED" if (interaction_incremental is not None and interaction_incremental > 0.005 and model_abc.applicable and model_abc.coefficient_p_values.get("interaction", 1.0) < 0.05) else "INCONCLUSIVE"
    _advance_and_classify("P13-OID-006", verdict_006, f"interaction incremental R2={_fmt(interaction_incremental)}, interaction_p={model_abc.coefficient_p_values.get('interaction') if model_abc.applicable else 'N/A'}")

    agreement_mean = sum(agreement_means) / len(agreement_means) if agreement_means else None
    disagreement_mean = sum(disagreement_means) / len(disagreement_means) if disagreement_means else None
    state_gap = None if agreement_mean is None or disagreement_mean is None else abs(agreement_mean - disagreement_mean)
    state_p_value = _welch_p_value(agreement_rows, disagreement_rows)
    state_significant = state_p_value is not None and state_p_value < 0.05
    verdict_007 = "DISCOVERY_SUPPORTED" if (state_gap is not None and state_gap > 0.005 and state_significant) else ("REJECTED" if state_p_value is not None and not state_significant else "INCONCLUSIVE")
    _advance_and_classify("P13-OID-007", verdict_007, f"agreement_mean={_fmt(agreement_mean)}, disagreement_mean={_fmt(disagreement_mean)}, gap={_fmt(state_gap)}, Welch_p={_fmt(state_p_value)}")

    top_risk_adj = [r.get("risk_adjusted_future_return_1") for r in top_quintile if r.get("risk_adjusted_future_return_1") is not None]
    bottom_risk_adj = [r.get("risk_adjusted_future_return_1") for r in bottom_quintile if r.get("risk_adjusted_future_return_1") is not None]
    top_mean_ra = sum(top_risk_adj) / len(top_risk_adj) if top_risk_adj else None
    bottom_mean_ra = sum(bottom_risk_adj) / len(bottom_risk_adj) if bottom_risk_adj else None
    ra_gap = None if top_mean_ra is None or bottom_mean_ra is None else top_mean_ra - bottom_mean_ra

    ra_p_value = _welch_p_value(top_risk_adj, bottom_risk_adj)
    ra_significant = ra_p_value is not None and ra_p_value < 0.05
    verdict_008 = "DISCOVERY_SUPPORTED" if (ra_gap is not None and abs(ra_gap) > 0.01 and ra_significant) else ("REJECTED" if ra_p_value is not None and not ra_significant else "INCONCLUSIVE")
    _advance_and_classify("P13-OID-008", verdict_008, f"Q5_mean_risk_adj_return={_fmt(top_mean_ra)}, Q1_mean_risk_adj_return={_fmt(bottom_mean_ra)}, gap={_fmt(ra_gap)}, Welch_p={_fmt(ra_p_value)}")

    n_supported = sum(1 for v, _ in classifications.values() if v == "DISCOVERY_SUPPORTED")
    print(f"\n{n_supported}/{len(classifications)} hypotheses classified DISCOVERY_SUPPORTED.", flush=True)
    print("Per Part 30: this phase STOPS after the discovery report. No development-stage strategy is created here.", flush=True)

    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))
    dims_fp = ExperimentDimensions(feature_definition=PRIMARY_FEATURE, parameter_range={"feature_set": list(FEATURE_SET), "target_set": list(TARGET_SET), "vol_window": VOL_WINDOW}, universe_name=universe.name, target_definition=PRIMARY_TARGET, execution_model="n/a-discovery", cost_model="n/a-discovery", validation_methodology="cross-sectional discovery family on DISCOVERY_DATA")
    exp_store.record(
        data_version="phase5-campaign-v1", feature_version="phase13-discovery-v1", symbols=usable, timeframe="day",
        strategy_version="1.0", prediction_horizon=PRIMARY_HORIZON, train_period=(str(discovery.start_date), str(discovery.end_date)),
        parameters={"n_tests": len(raw_p_values)}, metrics={"primary_ic": pooled_ic, "n_discovery_supported": n_supported},
        strategy_family="overnight_intraday_decomposition", classification=("DISCOVERY_SUPPORTED" if n_supported > 0 else "NOT_READY"),
        tags=("phase13-discovery", universe.name), notes=f"{n_supported}/{len(classifications)} DISCOVERY_SUPPORTED; classifications={ {k: v[0] for k, v in classifications.items()} }",
        hypothesis_id="P13-OID-FAMILY", universe_name=universe.name, experiment_fingerprint=compute_experiment_fingerprint(dims_fp),
        research_family_id="P13-OID-DISCOVERY-2026-09",
    )
    print("\nSTEP 2 COMPLETE.", flush=True)


if __name__ == "__main__":
    main()
