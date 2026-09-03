#!/usr/bin/env python3
"""Phase 22, STEP 3 — the discovery campaign for all 13 preregistered
`options_specific_alpha` hypotheses. Every hypothesis runs through the
SAME battery (temporal / symbol / expiration / moneyness / call-put /
mandatory outlier / underlying-control / mechanical-leverage note /
IC-based placebo (7 types) / temporal-shift / dependence-aware bootstrap
/ cost sensitivity / economic significance / PBO-DSR where valid), then
a shared multiple-testing correction across the WHOLE family, a 7-
dimension robustness scorecard, and a Part 24 final classification.

Every hypothesis here uses a cross-sectional IC as its primary metric
(Part 8's own guidance: don't make a group-difference the primary
hypothesis this phase) -- so, unlike Phase 21, ONE placebo battery
suffices for the whole family; there is no metric-mismatch risk to
guard against by construction. `tests/test_phase22_metric_compatibility.
py` proves this invariant mechanically rather than just asserting it in
a docstring.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.store import HistoricalDataStore  # noqa: E402
from src.options.cost_model import COST_SENSITIVITY_ASSUMPTIONS, FIVE_X_ASSUMPTION, apply_cost_assumption  # noqa: E402
from src.options.dependence_bootstrap import symbol_cluster_bootstrap_ic  # noqa: E402
from src.options.mechanical_baseline import compare_option_vs_underlying_signal  # noqa: E402
from src.options.outlier_treatment import compute_outlier_attribution, top_observations, winsorize  # noqa: E402
from src.options.placebo_extensions import block_preserving_shuffle_placebo, symbol_identity_shuffle_placebo, within_symbol_time_shuffle_placebo  # noqa: E402
from src.options.universe import phase20_verified_underlying_universe  # noqa: E402
from src.research import (  # noqa: E402
    DiscoveryDevelopmentGateStore,
    DiscoveryDevelopmentStage,
    ExperimentStore,
    benjamini_hochberg_fdr,
    bonferroni_correction,
    compute_ic_series,
    deflated_sharpe_ratio,
    holm_bonferroni_correction,
    label_bars_by_regime,
    probability_of_backtest_overfitting,
    random_feature_control,
    require_preregistered,
    shifted_signal_placebo,
    shuffled_signal_placebo,
    summarize_ic,
    time_shuffled_target_placebo,
)
from src.research.analysis import mean as _mean  # noqa: E402
from src.research.analysis import stdev as _stdev  # noqa: E402
from src.research.experiment_fingerprint import ExperimentDimensions, compute_experiment_fingerprint  # noqa: E402
from src.research.preregistration import PreregistrationStore  # noqa: E402
from src.research.regression import ols_regression  # noqa: E402
from src.research.return_series_bootstrap import block_bootstrap_return_series, stationary_bootstrap_return_series  # noqa: E402
from src.research.stats_utils import t_test_p_value  # noqa: E402

RESEARCH_PANEL = Path("logs/research_data/phase22_research_panel.jsonl")
UNDERLYING_TARGET = "underlying_forward_return_5"
FAMILY = "options_specific_alpha"

# hypothesis_id -> (feature_col, target_col, expected_direction, check_dte_variance)
HYPOTHESES: dict[str, tuple[str, str, str, bool]] = {
    "P22-OPT-001": ("option_naive_excess_momentum_5", "option_naive_excess_return_5", "positive", False),
    "P22-OPT-002": ("option_beta_scaled_excess_momentum_5", "option_beta_scaled_excess_return_5", "positive", False),
    "P22-OPT-003": ("underlying_vol_ratio_5_20", "forward_return_5", "unsigned", False),
    "P22-OPT-004": ("underlying_vol_ratio_5_20", "abs_forward_return_5", "positive", False),
    "P22-OPT-005": ("underlying_squared_return", "forward_return_5", "unsigned", False),
    "P22-OPT-006": ("option_momentum_5", "forward_return_5", "positive", False),
    "P22-OPT-007": ("option_momentum_10", "forward_return_5", "negative", False),
    "P22-OPT-008": ("option_vol_ratio_5_20", "forward_return_5", "unsigned", False),
    "P22-OPT-009": ("option_underlying_return_ratio_5", "forward_return_5", "unsigned", False),
    "P22-OPT-010": ("vol_expansion_x_moneyness", "forward_return_5", "unsigned", False),
    "P22-OPT-011": ("squared_move_x_dte", "forward_return_5", "unsigned", True),
    "P22-OPT-012": ("underlying_lagged_realized_vol", "forward_return_5", "unsigned", False),
    "P22-OPT-013": ("option_range_expansion_5", "mfe_5", "positive", False),
}
PBO_DSR_VARIANT_POOL = ("dte", "moneyness_ratio", "underlying_lagged_realized_vol", "option_gap")


def _fmt(x) -> str:
    return "None" if x is None else f"{x:.5f}"


def load_panel() -> list[dict]:
    rows = [json.loads(line) for line in RESEARCH_PANEL.read_text().splitlines() if line.strip()]
    for r in rows:
        r["timestamp"] = date.fromisoformat(r["timestamp"])
        r["symbol"] = r["option_id"]
    return [r for r in rows if r.get("is_research_eligible")]


def pooled_ic(rows: list[dict], feature_col: str, target_col: str) -> float | None:
    points = compute_ic_series(rows, feature_col, target_col, min_universe_size=3)
    return summarize_ic(points, feature_name=feature_col, target_name=target_col).average_ic


def pooled_ic_p(rows: list[dict], feature_col: str, target_col: str) -> float | None:
    points = compute_ic_series(rows, feature_col, target_col, min_universe_size=3)
    return t_test_p_value([p.ic for p in points if p.ic is not None])


def has_sufficient_dte_variance(rows: list[dict], *, min_distinct_buckets: int = 3, min_stdev_days: float = 5.0) -> bool:
    dtes = [r["dte"] for r in rows if r.get("dte") is not None]
    buckets = {r["dte_bucket"] for r in rows if r.get("dte_bucket") is not None}
    if len(buckets) < min_distinct_buckets or len(dtes) < 30:
        return False
    return _stdev(dtes) >= min_stdev_days


def run_hypothesis(hyp_id: str, feature_col: str, target_col: str, panel: list[dict], universe, *, expected_direction: str, check_dte_variance: bool, raw_p_values: list, regime_by_symbol_date: dict) -> dict:
    print(f"\n{'#' * 100}\n{hyp_id}: feature={feature_col} target={target_col} expected_direction={expected_direction}\n{'#' * 100}", flush=True)
    result: dict = {"hypothesis_id": hyp_id, "feature": feature_col, "target": target_col}

    rows = [r for r in panel if r.get(feature_col) is not None and r.get(target_col) is not None]
    print(f"  eligible rows with both feature and target present: {len(rows)} / {len(panel)}", flush=True)

    if check_dte_variance and not has_sufficient_dte_variance(rows):
        print("  INSUFFICIENT_DTE_VARIANCE -- refusing to compute a potentially misleading statistic.", flush=True)
        result["classification"] = "DATA_INSUFFICIENT"
        result["reason"] = "INSUFFICIENT_DTE_VARIANCE"
        return result

    if len(rows) < 100:
        print(f"  DATA_INSUFFICIENT -- only {len(rows)} eligible rows.", flush=True)
        result["classification"] = "DATA_INSUFFICIENT"
        result["reason"] = f"only {len(rows)} eligible rows (< 100)"
        return result

    pooled_effect = pooled_ic(rows, feature_col, target_col)
    pooled_p = pooled_ic_p(rows, feature_col, target_col)
    print(f"  POOLED IC: {_fmt(pooled_effect)}  p={_fmt(pooled_p)}", flush=True)
    result["pooled_effect"] = pooled_effect
    if pooled_p is not None:
        raw_p_values.append((f"{hyp_id}|pooled", pooled_p))

    if pooled_effect is None:
        result["classification"] = "DATA_INSUFFICIENT"
        result["reason"] = "pooled IC undefined (insufficient cross-sectional universe at every timestamp)"
        return result

    # ---- temporal falsification ----
    years = sorted({r["timestamp"].year for r in rows})
    year_effects = {}
    for year in years:
        yr = [r for r in rows if r["timestamp"].year == year]
        e = pooled_ic(yr, feature_col, target_col)
        p = pooled_ic_p(yr, feature_col, target_col)
        year_effects[year] = e
        print(f"    {year}: IC={_fmt(e)}  p={_fmt(p)}  n={len(yr)}", flush=True)
        if p is not None:
            raw_p_values.append((f"{hyp_id}|year={year}", p))
    year_vals = [v for v in year_effects.values() if v is not None]
    signs = [1 if v > 0 else (-1 if v < 0 else 0) for v in year_vals]
    sign_consistency = (max(signs.count(1), signs.count(-1)) / len(signs)) if signs else None
    print(f"    sign_consistency(years)={_fmt(sign_consistency)}  n_years={len(year_vals)}", flush=True)
    result["sign_consistency_years"] = sign_consistency

    # ---- volatility regime breakdown (Theme G; reuses the family-wide regime labeling computed once in main()) ----
    regime_buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        label = regime_by_symbol_date.get(r["underlying_symbol"], {}).get(r["timestamp"], "unknown")
        regime_buckets[label].append(r)
    for label in sorted(regime_buckets):
        regime_rows = regime_buckets[label]
        if len(regime_rows) < 30:
            continue
        regime_ic = pooled_ic(regime_rows, feature_col, target_col)
        regime_abs_ic = pooled_ic(regime_rows, feature_col, "abs_forward_return_5") if "abs_forward_return_5" in regime_rows[0] else None
        print(f"    regime={label:16s}: IC(target)={_fmt(regime_ic)}  IC(vs abs_forward_return_5, opportunity proxy)={_fmt(regime_abs_ic)}  n={len(regime_rows)}", flush=True)

    # ---- symbol falsification (leave-one-underlying-out) ----
    per_symbol = {}
    for sym in universe.symbols:
        sym_rows = [r for r in rows if r["underlying_symbol"] == sym]
        per_symbol[sym] = pooled_ic(sym_rows, feature_col, target_col) if len(sym_rows) >= 30 else None
    sym_vals = [v for v in per_symbol.values() if v is not None]
    pos_frac = sum(1 for v in sym_vals if v > 0) / len(sym_vals) if sym_vals else None
    print(f"    per-symbol IC: {[(s, round(v, 4) if v is not None else None) for s, v in per_symbol.items()]}", flush=True)
    print(f"    positive_symbol_fraction={_fmt(pos_frac)}  n_symbols_with_ic={len(sym_vals)}", flush=True)
    result["symbol_positive_fraction"] = pos_frac

    # ---- expiration falsification ----
    expirations = sorted({r["expiration"] for r in rows})
    for exp in expirations:
        exp_rows = [r for r in rows if r["expiration"] == exp]
        if len(exp_rows) < 30:
            print(f"    {exp}: INSUFFICIENT_SAMPLE (n={len(exp_rows)})", flush=True)
            continue
        print(f"    {exp}: IC={_fmt(pooled_ic(exp_rows, feature_col, target_col))}  n={len(exp_rows)}", flush=True)

    # ---- moneyness falsification ----
    buckets = ("deep_itm", "itm", "near_atm", "otm", "deep_otm")
    bucket_effects = {}
    for b in buckets:
        b_rows = [r for r in rows if r.get("moneyness_bucket") == b]
        if len(b_rows) < 30:
            print(f"    moneyness={b}: INSUFFICIENT_SAMPLE (n={len(b_rows)})", flush=True)
            continue
        bucket_effects[b] = pooled_ic(b_rows, feature_col, target_col)
        print(f"    moneyness={b}: IC={_fmt(bucket_effects[b])}  n={len(b_rows)}", flush=True)
    b_signs = [1 if v > 0 else -1 for v in bucket_effects.values() if v is not None]
    print(f"    sign_consistency(moneyness buckets)={_fmt(max(b_signs.count(1), b_signs.count(-1)) / len(b_signs) if b_signs else None)}", flush=True)

    # ---- call/put ----
    call_rows = [r for r in rows if r["call_put"] == "call"]
    put_rows = [r for r in rows if r["call_put"] == "put"]
    call_ic = pooled_ic(call_rows, feature_col, target_col) if len(call_rows) >= 30 else None
    put_ic = pooled_ic(put_rows, feature_col, target_col) if len(put_rows) >= 30 else None
    print(f"    calls-only IC={_fmt(call_ic)} (n={len(call_rows)})  puts-only IC={_fmt(put_ic)} (n={len(put_rows)})", flush=True)
    call_put_same_sign = call_ic is not None and put_ic is not None and (call_ic > 0) == (put_ic > 0)
    print(f"    survives in both calls and puts with the same sign: {call_put_same_sign}", flush=True)

    # ---- mandatory outlier falsification ----
    target_vals = [r[target_col] for r in rows]
    attribution = compute_outlier_attribution(target_vals)
    print(f"    outlier attribution on {target_col} (n={len(target_vals)}): top_1%_share={_fmt(attribution.top_1pct_share)}  "
          f"top_5%_share={_fmt(attribution.top_5pct_share)}", flush=True)
    top1pos_idx = {o.index for o in top_observations(target_vals, n=max(1, len(target_vals) // 100), by="positive")}
    top1neg_idx = {o.index for o in top_observations(target_vals, n=max(1, len(target_vals) // 100), by="negative")}
    rows_no_top1pos = [r for i, r in enumerate(rows) if i not in top1pos_idx]
    rows_no_top1neg = [r for i, r in enumerate(rows) if i not in top1neg_idx]
    e_no_top1pos = pooled_ic(rows_no_top1pos, feature_col, target_col)
    e_no_top1neg = pooled_ic(rows_no_top1neg, feature_col, target_col)
    print(f"    remove top 1% positive: IC={_fmt(e_no_top1pos)}   remove top 1% negative: IC={_fmt(e_no_top1neg)}", flush=True)
    winsorized_effect_5pct = None
    for frac in (0.01, 0.025, 0.05):
        w_targets = winsorize(target_vals, fraction=frac)
        w_rows = [dict(r, **{target_col: t}) for r, t in zip(rows, w_targets)]
        w_effect = pooled_ic(w_rows, feature_col, target_col)
        print(f"    winsorize {frac:.1%}: IC={_fmt(w_effect)}", flush=True)
        if frac == 0.05:
            winsorized_effect_5pct = w_effect
    outlier_dependent = winsorized_effect_5pct is not None and (
        (pooled_effect > 0) != (winsorized_effect_5pct > 0) or abs(winsorized_effect_5pct) < abs(pooled_effect) * 0.3
    )
    print(f"    OUTLIER_DEPENDENT: {outlier_dependent}", flush=True)
    result["outlier_dependent"] = outlier_dependent

    # ---- underlying control (Model A/B/C) ----
    baseline = compare_option_vs_underlying_signal(rows, feature_col=feature_col, option_target_col=target_col, underlying_target_col=UNDERLYING_TARGET)
    print(f"    Model A (feature -> {UNDERLYING_TARGET}): IC={_fmt(baseline.underlying_ic)}", flush=True)
    print(f"    Model B (feature -> {target_col}):        IC={_fmt(baseline.option_ic)}", flush=True)
    print(f"    gap={_fmt(baseline.gap)}  -> {baseline.classification}", flush=True)
    y = [r.get(target_col) for r in rows]
    underlying_ret = [r.get(UNDERLYING_TARGET) for r in rows]
    feature_vals = [r.get(feature_col) for r in rows]
    model_u = ols_regression(y, {"underlying_ret": underlying_ret}, min_observations=30)
    model_uf = ols_regression(y, {"underlying_ret": underlying_ret, "feature": feature_vals}, min_observations=30)
    incremental_r2 = feature_p = None
    if model_u.applicable and model_uf.applicable:
        incremental_r2 = model_uf.r_squared - model_u.r_squared
        feature_p = model_uf.coefficient_p_values.get("feature")
    print(f"    Model C incremental R2={_fmt(incremental_r2)}  feature_p={_fmt(feature_p)}", flush=True)
    feature_p_for_gate = feature_p if feature_p is not None else 1.0  # NOT `feature_p or 1.0` -- 0.0 is a legitimate, highly-significant p-value and is falsy in Python
    if baseline.classification == "option_adds_information" and incremental_r2 is not None and incremental_r2 > 0.005 and feature_p_for_gate < 0.05:
        underlying_control_verdict = "TRUE_OPTION_SPECIFIC_INFORMATION"
    elif baseline.classification == "inherited_from_underlying" or incremental_r2 is None or incremental_r2 <= 0.005:
        underlying_control_verdict = "INHERITED_FROM_UNDERLYING"
    else:
        underlying_control_verdict = "UNCERTAIN"
    print(f"    UNDERLYING-CONTROL VERDICT: {underlying_control_verdict}", flush=True)
    result["underlying_control_verdict"] = underlying_control_verdict

    # ---- placebo battery (7 types, all IC-based -- matches this family's own metric exactly) ----
    shuffled = shuffled_signal_placebo(rows, feature_col=feature_col, target_col=target_col, n_trials=150, seed=6001)
    time_shuf = within_symbol_time_shuffle_placebo(rows, feature_col=feature_col, target_col=target_col, n_trials=150, seed=6002)
    sym_shuf = symbol_identity_shuffle_placebo(rows, feature_col=feature_col, target_col=target_col, n_trials=150, seed=6003)
    random_sig = random_feature_control(rows, target_col=target_col, n_trials=80, seed=6004, min_universe_size=3)
    rand_target = time_shuffled_target_placebo(rows, feature_col=feature_col, target_col=target_col, n_trials=150, seed=6005)
    block_shuf = block_preserving_shuffle_placebo(rows, feature_col=feature_col, target_col=target_col, block_size=5, n_trials=150, seed=6006)
    print(f"    placebo p-values: shuffle={shuffled.empirical_p_value}  time_shuffle={time_shuf.empirical_p_value}  "
          f"symbol_shuffle={sym_shuf.empirical_p_value}  random_target={rand_target.empirical_p_value}  "
          f"block_shuffle={block_shuf.empirical_p_value}  mean_placebo_IC(random_signal)={_fmt(_mean(random_sig.placebo_distribution) if random_sig.placebo_distribution else None)}", flush=True)
    placebo_ps = [p.empirical_p_value for p in (shuffled, time_shuf, sym_shuf, rand_target, block_shuf) if p.empirical_p_value is not None]
    for name, p in (("shuffle", shuffled.empirical_p_value), ("time_shuffle", time_shuf.empirical_p_value), ("symbol_shuffle", sym_shuf.empirical_p_value), ("random_target", rand_target.empirical_p_value), ("block_shuffle", block_shuf.empirical_p_value)):
        if p is not None:
            raw_p_values.append((f"{hyp_id}|placebo_{name}", p))
    placebo_clearly_distinguishable = all(p is not None and p < 0.10 for p in placebo_ps) if placebo_ps else False
    print(f"    clearly distinguishable from ALL placebo distributions (p<0.10 each): {placebo_clearly_distinguishable}", flush=True)
    result["placebo_clearly_distinguishable"] = placebo_clearly_distinguishable

    # ---- temporal shift ----
    for shift in (1, 2, 5, 10):
        shifted = shifted_signal_placebo(rows, feature_col=feature_col, target_col=target_col, shift_bars=shift)
        shifted_val = shifted.placebo_distribution[0] if shifted.placebo_distribution else None
        flag = shifted_val is not None and abs(shifted_val) >= abs(pooled_effect)
        print(f"    shift=+{shift}: true={_fmt(pooled_effect)}  shifted={_fmt(shifted_val)}  {'<-- shifted >= true' if flag else ''}", flush=True)

    # ---- dependence-aware bootstrap ----
    ic_points = compute_ic_series(rows, feature_col, target_col, min_universe_size=3)
    ic_series = [p.ic for p in ic_points if p.ic is not None]
    ci_summaries = {}
    for conf in (0.90, 0.95):
        if len(ic_series) >= 4:
            block_report = block_bootstrap_return_series(ic_series, block_size=5, n_resamples=1000, seed=7001, confidence_level=conf)
            stationary_report = stationary_bootstrap_return_series(ic_series, mean_block_length=5.0, n_resamples=1000, seed=7002, confidence_level=conf)
            if block_report.mean_trade_return_ci is not None:
                ci = block_report.mean_trade_return_ci
                print(f"    time-block bootstrap of IC series ({conf:.0%}): mean={ci.point_estimate:.5f}  [{ci.lower:.5f}, {ci.upper:.5f}]", flush=True)
            if stationary_report.mean_trade_return_ci is not None:
                ci = stationary_report.mean_trade_return_ci
                print(f"    stationary bootstrap of IC series ({conf:.0%}): mean={ci.point_estimate:.5f}  [{ci.lower:.5f}, {ci.upper:.5f}]", flush=True)
        sym_cluster = symbol_cluster_bootstrap_ic(rows, feature_col=feature_col, target_col=target_col, n_resamples=500, seed=7003, confidence_level=conf, min_universe_size=3)
        print(f"    {sym_cluster.render()}", flush=True)
        ci_summaries[f"symbol_cluster_{int(conf * 100)}"] = (sym_cluster.lower_bound, sym_cluster.upper_bound)
    result["symbol_cluster_ci_90"] = ci_summaries.get("symbol_cluster_90")

    # ---- cost sensitivity ----
    mean_entry = _mean([r["option_close"] for r in rows])
    cost_survives = []
    for assumption in list(COST_SENSITIVITY_ASSUMPTIONS) + [FIVE_X_ASSUMPTION]:
        net = apply_cost_assumption(abs(pooled_effect), mean_entry, assumption) if mean_entry > 0 else None
        survives = net is not None and net > 0
        cost_survives.append(survives)
        print(f"    {assumption.label}: net={_fmt(net)}  survives={survives}", flush=True)
    cost_fragile = not cost_survives[0]
    print(f"    COST_FRAGILE: {cost_fragile}", flush=True)
    result["cost_fragile"] = cost_fragile

    # ---- economic significance ----
    contracts_affordable = int(1000 / (mean_entry * 100)) if mean_entry > 0 else 0
    print(f"    mean premium=${_fmt(mean_entry)}/share -> ~{contracts_affordable} contract(s) affordable on $1,000 "
          f"(feasibility check only, not a target)", flush=True)

    # ---- PBO / DSR ----
    if len(ic_series) >= 8:
        n_periods = 6
        all_days = sorted({r["timestamp"] for r in rows})
        day_start, day_end = all_days[0], all_days[-1]
        total_days = (day_end - day_start).days + 1
        variants = [feature_col] + [v for v in PBO_DSR_VARIANT_POOL if v != feature_col][:3]
        period_matrix = []
        for v in variants:
            v_points = compute_ic_series(rows, v, target_col, min_universe_size=3)
            period_buckets: list[list[float]] = [[] for _ in range(n_periods)]
            for p in v_points:
                if p.ic is None:
                    continue
                offset = (p.timestamp - day_start).days
                bucket = min(n_periods - 1, max(0, (offset * n_periods) // max(1, total_days)))
                period_buckets[bucket].append(p.ic)
            period_matrix.append([sum(b) / len(b) if b else 0.0 for b in period_buckets])
        pbo = probability_of_backtest_overfitting(period_matrix)
        dsr = deflated_sharpe_ratio(ic_series, n_trials=len(variants))
        print(f"    {pbo.render()}", flush=True)
        print(f"    DSR: {dsr.render()}", flush=True)
    else:
        print(f"    NOT_APPLICABLE_WITH_REASON: only {len(ic_series)} usable IC-series points (<8) -- PBO/DSR need a "
              f"longer per-timestamp IC series than this hypothesis's eligible sample provides.", flush=True)

    # ---- robustness scorecard (Part 25) ----
    scorecard = {
        "statistical_significance": pooled_p is not None and pooled_p < 0.05,
        "temporal_stability": (sign_consistency if sign_consistency is not None else 0.0) >= 0.6,
        "symbol_stability": pos_frac is not None and (pos_frac >= 0.55 or pos_frac <= 0.45),
        "outlier_stability": not outlier_dependent,
        "placebo_separation": placebo_clearly_distinguishable,
        "underlying_control": underlying_control_verdict == "TRUE_OPTION_SPECIFIC_INFORMATION",
        "cost_sensitivity": not cost_fragile,
    }
    n_pass = sum(scorecard.values())
    print("    scorecard: " + ", ".join(f"{k}={'PASS' if v else 'FAIL'}" for k, v in scorecard.items()), flush=True)
    print(f"    {n_pass}/7 dimensions passed", flush=True)
    result["scorecard"] = scorecard
    result["n_pass"] = n_pass

    # ---- Part 24 final classification (priority order, documented) ----
    if underlying_control_verdict == "INHERITED_FROM_UNDERLYING":
        classification = "INHERITED_FROM_UNDERLYING"
    elif outlier_dependent:
        classification = "OUTLIER_DEPENDENT"
    elif n_pass >= 6 and placebo_clearly_distinguishable and not cost_fragile:
        classification = "DISCOVERY_SUPPORTED"
    elif n_pass >= 4:
        classification = "FRAGILE"
    elif pooled_p is not None and pooled_p < 0.05:
        classification = "INCONCLUSIVE"
    else:
        classification = "REJECTED"
    result["classification"] = classification
    print(f"    ==> FINAL CLASSIFICATION: {classification}", flush=True)
    return result


def main() -> None:
    universe = phase20_verified_underlying_universe()
    prereg_store = PreregistrationStore(Path("logs/research_data/phase22_preregistrations.jsonl"))
    for hyp_id in HYPOTHESES:
        require_preregistered(prereg_store, hyp_id)

    panel = load_panel()
    print(f"Loaded panel: {len(panel)} eligible rows, {len({r['option_id'] for r in panel})} contracts, "
          f"{len({r['underlying_symbol'] for r in panel})} underlyings. MARK_TO_MARKET_HISTORICAL_RESEARCH only.", flush=True)

    print(f"\n{'=' * 100}\nMECHANICAL LEVERAGE CONTROL (applies to the whole family -- Part 10)\n{'=' * 100}", flush=True)
    print("HISTORICAL_GREEKS_UNAVAILABLE -- no delta-adjusted exposure can be computed for any historical date; none "
          "are reconstructed and presented as observed.", flush=True)
    dollar_returns = [(r["option_close"] - r["option_open"]) * 100 for r in panel if r.get("option_close") is not None and r.get("option_open") is not None]
    print(f"dollar P&L per contract (open->close, same-day, n={len(dollar_returns)}): mean=${_fmt(_mean(dollar_returns))}  "
          f"stdev=${_fmt(_stdev(dollar_returns))}", flush=True)

    equity_store = HistoricalDataStore(Path("logs/research_data"))
    regime_by_symbol_date: dict[str, dict] = {}
    for sym in universe.symbols:
        bars = equity_store.load(sym, "day")
        labels = label_bars_by_regime(bars)
        regime_by_symbol_date[sym] = {ts.date(): label for ts, label in labels.items()}

    raw_p_values: list[tuple[str, float]] = []
    results: dict[str, dict] = {}
    for hyp_id, (feature_col, target_col, direction, check_dte) in HYPOTHESES.items():
        results[hyp_id] = run_hypothesis(
            hyp_id, feature_col, target_col, panel, universe, expected_direction=direction, check_dte_variance=check_dte,
            raw_p_values=raw_p_values, regime_by_symbol_date=regime_by_symbol_date,
        )

    # ---- multiple testing (whole family) ----
    print(f"\n{'#' * 100}\nMULTIPLE-TESTING CORRECTION (complete Phase 22 family, {len(raw_p_values)} raw p-values)\n{'#' * 100}", flush=True)
    for method in (bonferroni_correction, holm_bonferroni_correction, benjamini_hochberg_fdr):
        report = method(raw_p_values, alpha=0.05)
        print(f"  {report.method}: n_significant={report.n_significant}/{report.n_tests}", flush=True)

    print(f"\n{'#' * 100}\nFINAL CLASSIFICATIONS\n{'#' * 100}", flush=True)
    counts: dict[str, int] = defaultdict(int)
    gate_store = DiscoveryDevelopmentGateStore(Path("logs/research_data/phase22_gate_transitions.jsonl"))
    for hyp_id, r in results.items():
        classification = r["classification"]
        counts[classification] += 1
        print(f"  {hyp_id}: {classification}", flush=True)
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.IDEA, reason="Phase 22 discovery", evidence_summary="")
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.PREREGISTERED, reason="preregistered in Phase 22 step 2", evidence_summary="")
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DISCOVERY_TESTED, reason="Phase 22 discovery campaign completed", evidence_summary=classification)
        if classification == "DISCOVERY_SUPPORTED":
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DISCOVERY_SUPPORTED, reason=classification, evidence_summary=classification)
        else:
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.NOT_READY, reason=f"classified {classification}", evidence_summary=classification)

    print(f"\nCounts: {dict(counts)}", flush=True)
    n_discovery_supported = counts.get("DISCOVERY_SUPPORTED", 0)
    print(f"{n_discovery_supported}/{len(results)} hypotheses classified DISCOVERY_SUPPORTED.", flush=True)
    print("DISCOVERY_SUPPORTED means 'worth deeper investigation', NOT profitable, NOT validated, NOT ready for trading.", flush=True)
    print("No strategy is created. No order is placed. No parameter was tuned to improve these results.", flush=True)

    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))
    dims_fp = ExperimentDimensions(
        feature_definition="options_specific_alpha_family_v1", parameter_range={"hypotheses": list(HYPOTHESES.keys())},
        universe_name=universe.name, target_definition="varies per hypothesis", execution_model="n/a-discovery-only",
        cost_model="assumption-only-1x-2x-3x-5x", validation_methodology="Phase 22 discovery campaign",
    )
    exp_store.record(
        data_version="phase22-feature-panel-v1", feature_version="phase22-discovery-v1", symbols=list(universe.symbols), timeframe="day",
        strategy_version="1.0", prediction_horizon=5, train_period=("2021-12-01", "2023-06-15"),
        parameters={"n_hypotheses": len(HYPOTHESES), "n_p_values": len(raw_p_values)}, metrics={"n_discovery_supported": n_discovery_supported},
        strategy_family=FAMILY, classification=("DISCOVERY_SUPPORTED" if n_discovery_supported > 0 else "NO_DISCOVERY_SUPPORTED"),
        tags=("phase22-discovery", universe.name, "mark-to-market-historical-research"),
        notes=f"final_classifications={{k: v['classification'] for k, v in results.items()}}",
        hypothesis_id="P22-DISCOVERY-FAMILY", universe_name=universe.name, experiment_fingerprint=compute_experiment_fingerprint(dims_fp),
        research_family_id="P22-DISCOVERY-2026-09",
    )
    print("\nSTEP 3 COMPLETE.", flush=True)


if __name__ == "__main__":
    main()
