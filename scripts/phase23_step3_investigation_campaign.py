#!/usr/bin/env python3
"""Phase 23, STEP 3 — the adversarial investigation of the FROZEN
P22-OPT-013 parent (option_range_expansion_5 -> mfe_5). Parts 3, 4, 5,
6, 9, 10, 11, 12, 13, 14, 15, 19, 20, 21, and the Part 27 final
classification (first vocabulary: ROBUST_DISCOVERY_CANDIDATE /
FRAGILE_DISCOVERY / OVERLAP_DEPENDENT / REGIME_DEPENDENT /
EXPIRATION_DEPENDENT / MONEYNESS_DEPENDENT / OUTLIER_DEPENDENT /
UNDERLYING_INHERITED / NON_DIRECTIONAL_ONLY / DATA_INSUFFICIENT /
REJECTED). The goal is to break the discovery, not improve it -- every
check below is reported even when it weakens the case.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.store import HistoricalDataStore  # noqa: E402
from src.options.dependence_bootstrap import cluster_bootstrap_ic, symbol_cluster_bootstrap_ic  # noqa: E402
from src.options.outlier_treatment import compute_outlier_attribution, top_observations, winsorize  # noqa: E402
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
    require_preregistered,
    summarize_ic,
)
from src.research.analysis import mean as _mean  # noqa: E402
from src.research.analysis import pearson_correlation  # noqa: E402
from src.research.analysis import stdev as _stdev  # noqa: E402
from src.research.experiment_fingerprint import ExperimentDimensions, compute_experiment_fingerprint  # noqa: E402
from src.research.preregistration import PreregistrationStore  # noqa: E402
from src.research.regression import ols_regression  # noqa: E402
from src.research.return_series_bootstrap import block_bootstrap_return_series, stationary_bootstrap_return_series  # noqa: E402
from src.research.stats_utils import t_test_p_value  # noqa: E402

PANEL_PATH = Path("logs/research_data/phase23_research_panel.jsonl")
FEATURE = "option_range_expansion_5"
PARENT_TARGET = "mfe_5"
INV_ID = "P23-INV-P22-OPT-013"
UNDERLYING_TARGET_5 = "underlying_forward_return_5"

CONTROL_HIERARCHY = (
    ("control_1_underlying_forward_return", "underlying_forward_return_5"),
    ("control_2_underlying_abs_forward_return", "abs_underlying_forward_return_5"),
    ("control_3_underlying_realized_vol", "underlying_lagged_realized_vol"),
    ("control_4_underlying_vol_expansion", "underlying_vol_ratio_5_20"),
    ("control_5_underlying_range_expansion", "underlying_range_expansion_5"),
    ("control_6_option_trailing_return", "option_momentum_5"),
    ("control_7_option_trailing_volatility", "option_vol_ratio_5_20"),
    ("control_8_option_recent_range_level", "option_true_range_proxy_10"),
    ("control_9_moneyness_distance_from_atm", "abs_log_moneyness"),
    ("control_10_dte", "dte"),
)
TARGET_VALIDATION_FAMILY = (
    ("A", "forward_return_1"), ("B", "forward_return_3"), ("C", "forward_return_5"), ("D", "forward_return_10"),
    ("E", "forward_return_20"), ("F", "mfe_5"), ("G", "mae_5"), ("H", "mfe_minus_mae_5"),
    ("I", "forward_return_5"), ("J", "target_positive_indicator_5"),
)
MECHANISM_CANDIDATES = (
    ("option price volatility", "option_vol_ratio_5_20"),
    ("recent option momentum", "option_momentum_5"),
    ("option price acceleration", "option_return_acceleration"),
    ("large recent option movement (gap)", "option_gap"),
    ("underlying volatility", "underlying_lagged_realized_vol"),
    ("underlying volatility expansion", "underlying_vol_ratio_5_20"),
    ("underlying range expansion", "underlying_range_expansion_5"),
    ("contract age / expiration proximity (DTE)", "dte"),
    ("moneyness (distance from ATM)", "abs_log_moneyness"),
    ("call/put characteristic", "call_put_numeric"),
    ("persistence of option price movement", "option_trend_persistence_10"),
)
SIGNAL_CLUSTER_THRESHOLD = 1.5  # a preregistered midpoint of the tradeable grid, used ONLY for the clustering study (Part 10)


def _fmt(x) -> str:
    return "None" if x is None else f"{x:.5f}"


def load_panel() -> list[dict]:
    rows = [json.loads(line) for line in PANEL_PATH.read_text().splitlines() if line.strip()]
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


def main() -> None:
    universe = phase20_verified_underlying_universe()
    prereg_store = PreregistrationStore(Path("logs/research_data/phase23_preregistrations.jsonl"))
    require_preregistered(prereg_store, INV_ID)

    panel = load_panel()
    base = [r for r in panel if r.get(FEATURE) is not None and r.get(PARENT_TARGET) is not None]
    print(f"Loaded panel: {len(panel)} eligible rows; base sample for {FEATURE}->{PARENT_TARGET}: {len(base)} rows.\n", flush=True)

    raw_p_values: list[tuple[str, float]] = []
    flags: dict[str, bool] = {}

    # ============================================================== PART 3: MECHANISM DECOMPOSITION
    print(f"{'=' * 100}\nPART 3 — MECHANISM DECOMPOSITION\n{'=' * 100}", flush=True)
    print("Pooled Pearson correlation between the P22 feature and related candidate mechanisms (NOT alpha -- mechanism identification only):", flush=True)
    for label, col in MECHANISM_CANDIDATES:
        rows = [r for r in base if r.get(col) is not None]
        if len(rows) < 30:
            print(f"  {label:45s} [{col}]: INSUFFICIENT_SAMPLE (n={len(rows)})", flush=True)
            continue
        corr = pearson_correlation([r[FEATURE] for r in rows], [r[col] for r in rows])
        print(f"  {label:45s} [{col}]: r={_fmt(corr)}  n={len(rows)}", flush=True)

    # ============================================================== PART 4: CONTROL HIERARCHY (cumulative OLS)
    print(f"\n{'=' * 100}\nPART 4 — CUMULATIVE CONTROL HIERARCHY\n{'=' * 100}", flush=True)
    control_cols = [c for _, c in CONTROL_HIERARCHY]
    full_rows = [r for r in base if all(r.get(c) is not None for c in control_cols)]
    print(f"  rows with feature+target+ALL 10 controls present: {len(full_rows)}", flush=True)
    y = [r[PARENT_TARGET] for r in full_rows]
    feat_vals = [r[FEATURE] for r in full_rows]
    survives_all_controls = None
    for k in range(1, len(CONTROL_HIERARCHY) + 1):
        active = control_cols[:k]
        predictors_without = {c: [r[c] for r in full_rows] for c in active}
        predictors_with = dict(predictors_without, feature=feat_vals)
        m_without = ols_regression(y, predictors_without, min_observations=30)
        m_with = ols_regression(y, predictors_with, min_observations=30)
        incr_r2 = feature_p = None
        if m_without.applicable and m_with.applicable:
            incr_r2 = m_with.r_squared - m_without.r_squared
            feature_p = m_with.coefficient_p_values.get("feature")
        print(f"  after {CONTROL_HIERARCHY[k - 1][0]}: incremental_R2={_fmt(incr_r2)}  feature_p={_fmt(feature_p)}", flush=True)
        if feature_p is not None:
            raw_p_values.append((f"control_stack_k={k}", feature_p))
        if k == len(CONTROL_HIERARCHY):
            survives_all_controls = incr_r2 is not None and incr_r2 > 0.005 and (feature_p if feature_p is not None else 1.0) < 0.05
    print(f"  SURVIVES ALL 10 CONTROLS: {survives_all_controls}", flush=True)
    flags["underlying_inherited"] = not bool(survives_all_controls)

    # ============================================================== PART 5: TARGET-VALIDATION FAMILY
    print(f"\n{'=' * 100}\nPART 5 — TARGET-VALIDATION FAMILY (A-J)\n{'=' * 100}", flush=True)
    target_results: dict[str, float | None] = {}
    for letter, target_col in TARGET_VALIDATION_FAMILY:
        if letter == "I":
            rows = [r for r in base if r.get("forward_return_5") is not None and r["forward_return_5"] > 0]
        else:
            rows = [r for r in panel if r.get(FEATURE) is not None and r.get(target_col) is not None]
        if len(rows) < 30:
            print(f"  Target {letter} [{target_col}]: INSUFFICIENT_SAMPLE (n={len(rows)})", flush=True)
            target_results[letter] = None
            continue
        ic = pooled_ic(rows, FEATURE, target_col)
        p = pooled_ic_p(rows, FEATURE, target_col)
        target_results[letter] = ic
        print(f"  Target {letter} [{target_col}]: IC={_fmt(ic)}  p={_fmt(p)}  n={len(rows)}", flush=True)
        if p is not None:
            raw_p_values.append((f"target_{letter}", p))
    directional_target_c = target_results.get("C")
    magnitude_targets_positive = all((target_results.get(l) or 0) > 0 for l in ("F", "J")) if target_results.get("F") is not None else False

    # ============================================================== PART 6: DIRECTIONAL VS NON-DIRECTIONAL
    print(f"\n{'=' * 100}\nPART 6 — DIRECTIONAL VS NON-DIRECTIONAL EFFECT\n{'=' * 100}", flush=True)
    print(f"  IC vs signed forward_return_5 (Target C)  : {_fmt(directional_target_c)}", flush=True)
    print(f"  IC vs abs_forward_return_5 (magnitude)     : {_fmt(pooled_ic([r for r in panel if r.get(FEATURE) is not None and r.get('abs_forward_return_5') is not None], FEATURE, 'abs_forward_return_5'))}", flush=True)
    print(f"  IC vs mfe_5 (favorable excursion, parent)  : {_fmt(target_results.get('F'))}", flush=True)
    print(f"  IC vs mae_5 (adverse excursion)             : {_fmt(target_results.get('G'))}", flush=True)
    print(f"  IC vs target_positive_indicator_5 (P(win))  : {_fmt(target_results.get('J'))}", flush=True)
    call_rows = [r for r in base if r["call_put"] == "call"]
    put_rows = [r for r in base if r["call_put"] == "put"]
    call_ic = pooled_ic(call_rows, FEATURE, PARENT_TARGET) if len(call_rows) >= 30 else None
    put_ic = pooled_ic(put_rows, FEATURE, PARENT_TARGET) if len(put_rows) >= 30 else None
    print(f"  calls-only IC={_fmt(call_ic)} (n={len(call_rows)})   puts-only IC={_fmt(put_ic)} (n={len(put_rows)})", flush=True)
    up_rows = [r for r in base if (r.get("underlying_daily_return") or 0) > 0]
    down_rows = [r for r in base if (r.get("underlying_daily_return") or 0) < 0]
    up_ic = pooled_ic(up_rows, FEATURE, PARENT_TARGET) if len(up_rows) >= 30 else None
    down_ic = pooled_ic(down_rows, FEATURE, PARENT_TARGET) if len(down_rows) >= 30 else None
    print(f"  underlying-up-day IC={_fmt(up_ic)} (n={len(up_rows)})   underlying-down-day IC={_fmt(down_ic)} (n={len(down_rows)})", flush=True)
    directional_significant = directional_target_c is not None and abs(directional_target_c) > 0.02 and pooled_ic_p(base, FEATURE, "forward_return_5") is not None and pooled_ic_p(base, FEATURE, "forward_return_5") < 0.05
    non_directional_only = magnitude_targets_positive and not directional_significant
    print(f"  NON_DIRECTIONAL_ONLY (predicts magnitude/favorable-excursion but not a directional return): {non_directional_only}", flush=True)
    flags["non_directional_only"] = non_directional_only

    # ============================================================== PART 9: OVERLAPPING WINDOW TEST
    print(f"\n{'=' * 100}\nPART 9 — OVERLAPPING VS NON-OVERLAPPING WINDOW TEST\n{'=' * 100}", flush=True)
    overlap_ic = pooled_ic(base, FEATURE, PARENT_TARGET)
    by_contract: dict[str, list[dict]] = defaultdict(list)
    for r in base:
        by_contract[r["option_id"]].append(r)
    non_overlap_rows: list[dict] = []
    for cid, rows in by_contract.items():
        rows = sorted(rows, key=lambda r: r["timestamp"])
        non_overlap_rows.extend(rows[i] for i in range(0, len(rows), 5))  # horizon=5 -> every 5th row = non-overlapping forward windows
    non_overlap_ic = pooled_ic(non_overlap_rows, FEATURE, PARENT_TARGET)
    non_overlap_p = pooled_ic_p(non_overlap_rows, FEATURE, PARENT_TARGET)
    print(f"  overlapping (standard): IC={_fmt(overlap_ic)}  n={len(base)}", flush=True)
    print(f"  non-overlapping (every 5th obs per contract): IC={_fmt(non_overlap_ic)}  p={_fmt(non_overlap_p)}  n={len(non_overlap_rows)}", flush=True)
    if non_overlap_p is not None:
        raw_p_values.append(("non_overlapping_sample", non_overlap_p))
    overlap_dependent = non_overlap_ic is None or overlap_ic is None or (non_overlap_ic < overlap_ic * 0.5) or (non_overlap_p or 1.0) >= 0.10
    print(f"  OVERLAP_DEPENDENT: {overlap_dependent}", flush=True)
    flags["overlap_dependent"] = overlap_dependent

    # ============================================================== PART 10: SIGNAL PERSISTENCE / CLUSTERING
    print(f"\n{'=' * 100}\nPART 10 — SIGNAL PERSISTENCE AND CLUSTERING (threshold={SIGNAL_CLUSTER_THRESHOLD})\n{'=' * 100}", flush=True)
    cluster_lengths: list[int] = []
    gaps: list[int] = []
    first_signal_rows: list[dict] = []
    every_signal_rows: list[dict] = []
    total_days = 0
    flagged_days = 0
    for cid, rows in by_contract.items():
        rows = sorted(rows, key=lambda r: r["timestamp"])
        total_days += len(rows)
        flags_seq = [(r.get(FEATURE) is not None and r[FEATURE] > SIGNAL_CLUSTER_THRESHOLD) for r in rows]
        flagged_days += sum(flags_seq)
        run_len = 0
        gap_len = 0
        in_run = False
        for i, f in enumerate(flags_seq):
            if f:
                if not in_run:
                    first_signal_rows.append(rows[i])
                    if gap_len > 0:
                        gaps.append(gap_len)
                    gap_len = 0
                    in_run = True
                run_len += 1
                every_signal_rows.append(rows[i])
            else:
                if in_run:
                    cluster_lengths.append(run_len)
                    run_len = 0
                    in_run = False
                gap_len += 1
        if in_run:
            cluster_lengths.append(run_len)
    signal_freq = flagged_days / total_days if total_days else None
    print(f"  signal frequency: {_fmt(signal_freq)}  ({flagged_days}/{total_days} contract-days)", flush=True)
    print(f"  average cluster length: {_fmt(_mean(cluster_lengths) if cluster_lengths else None)}  (n_clusters={len(cluster_lengths)})", flush=True)
    print(f"  average gap between clusters: {_fmt(_mean(gaps) if gaps else None)}  (n_gaps={len(gaps)})", flush=True)
    first_only_eligible = [r for r in first_signal_rows if r.get(PARENT_TARGET) is not None]
    every_eligible = [r for r in every_signal_rows if r.get(PARENT_TARGET) is not None]
    first_ic = pooled_ic(first_only_eligible, FEATURE, PARENT_TARGET) if len(first_only_eligible) >= 30 else None
    every_ic = pooled_ic(every_eligible, FEATURE, PARENT_TARGET) if len(every_eligible) >= 30 else None
    print(f"  first-signal-only: IC={_fmt(first_ic)}  n={len(first_only_eligible)}", flush=True)
    print(f"  every-signal:      IC={_fmt(every_ic)}  n={len(every_eligible)}", flush=True)
    print(f"  NOTE: {len(every_signal_rows) - len(first_signal_rows)} of {len(every_signal_rows)} signal-days are repeats within a cluster -- "
          f"treating each as an independent trade would overstate the number of genuinely distinct opportunities.", flush=True)

    # ============================================================== PART 11: 2022 CONCENTRATION DECOMPOSITION
    print(f"\n{'=' * 100}\nPART 11 — 2022 CONCENTRATION DECOMPOSITION (candidates A-F, fixed before this run)\n{'=' * 100}", flush=True)
    equity_store = HistoricalDataStore(Path("logs/research_data"))
    regime_by_symbol_date: dict[str, dict] = {}
    for sym in universe.symbols:
        bars = equity_store.load(sym, "day")
        labels = label_bars_by_regime(bars)
        regime_by_symbol_date[sym] = {ts.date(): label for ts, label in labels.items()}
    print("  Candidate A (regime): IC by (year, regime):", flush=True)
    for year in (2021, 2022, 2023):
        year_rows = [r for r in base if r["timestamp"].year == year]
        by_regime: dict[str, list[dict]] = defaultdict(list)
        for r in year_rows:
            label = regime_by_symbol_date.get(r["underlying_symbol"], {}).get(r["timestamp"], "unknown")
            by_regime[label].append(r)
        for label, rows in sorted(by_regime.items()):
            if len(rows) < 30:
                continue
            print(f"    {year} / {label:16s}: IC={_fmt(pooled_ic(rows, FEATURE, PARENT_TARGET))}  n={len(rows)}", flush=True)

    print("  Candidate B (expiration) x year cross-tab (row counts, and IC where n>=30):", flush=True)
    for year in (2021, 2022, 2023):
        for exp in sorted({r["expiration"] for r in base}):
            rows = [r for r in base if r["timestamp"].year == year and r["expiration"] == exp]
            if not rows:
                continue
            ic = pooled_ic(rows, FEATURE, PARENT_TARGET) if len(rows) >= 30 else None
            print(f"    {year} x {exp}: n={len(rows)}  IC={_fmt(ic)}", flush=True)

    print("  Candidate C (symbols): which symbols contribute to 2021/2022 vs 2023 row counts:", flush=True)
    for year in (2021, 2022, 2023):
        year_rows = [r for r in base if r["timestamp"].year == year]
        syms = sorted({r["underlying_symbol"] for r in year_rows})
        print(f"    {year}: {len(syms)} distinct symbols present: {syms}", flush=True)

    print("  Candidate D (moneyness/call-put) x year:", flush=True)
    for year in (2021, 2022, 2023):
        year_rows = [r for r in base if r["timestamp"].year == year]
        cp_counts = {cp: sum(1 for r in year_rows if r["call_put"] == cp) for cp in ("call", "put")}
        print(f"    {year}: call/put row counts={cp_counts}", flush=True)

    print("  Candidate E (data availability): row/contract counts by year:", flush=True)
    for year in (2021, 2022, 2023):
        year_rows = [r for r in base if r["timestamp"].year == year]
        n_contracts = len({r["option_id"] for r in year_rows})
        print(f"    {year}: n_rows={len(year_rows)}  n_contracts={n_contracts}", flush=True)
    print("  Candidate F (random variation): with only 3 years of data, this cannot be statistically ruled out; "
          "see the final report's honest treatment of this limitation.", flush=True)

    # ============================================================== PART 12: SYMBOL CONCENTRATION
    print(f"\n{'=' * 100}\nPART 12 — SYMBOL CONCENTRATION\n{'=' * 100}", flush=True)
    per_symbol_ic: dict[str, float | None] = {}
    for sym in universe.symbols:
        sym_rows = [r for r in base if r["underlying_symbol"] == sym]
        per_symbol_ic[sym] = pooled_ic(sym_rows, FEATURE, PARENT_TARGET) if len(sym_rows) >= 30 else None
    print(f"  per-symbol IC: {[(s, round(v, 4) if v is not None else None) for s, v in per_symbol_ic.items()]}", flush=True)
    usable = {s: v for s, v in per_symbol_ic.items() if v is not None}
    equal_weight_avg = _mean(list(usable.values())) if usable else None
    print(f"  equal-weight average across symbols: {_fmt(equal_weight_avg)}   pooled (row-weighted) IC: {_fmt(overlap_ic)}", flush=True)
    if usable:
        strongest_sym = max(usable, key=lambda s: usable[s])
        weakest_sym = min(usable, key=lambda s: usable[s])
        without_strongest = pooled_ic([r for r in base if r["underlying_symbol"] != strongest_sym], FEATURE, PARENT_TARGET)
        without_weakest = pooled_ic([r for r in base if r["underlying_symbol"] != weakest_sym], FEATURE, PARENT_TARGET)
        print(f"  strongest symbol={strongest_sym} (IC={_fmt(usable[strongest_sym])}); without it: IC={_fmt(without_strongest)}", flush=True)
        print(f"  weakest symbol={weakest_sym} (IC={_fmt(usable[weakest_sym])}); without it: IC={_fmt(without_weakest)}", flush=True)
    sym_cluster = symbol_cluster_bootstrap_ic(base, feature_col=FEATURE, target_col=PARENT_TARGET, n_resamples=800, seed=8001, confidence_level=0.90, min_universe_size=3)
    print(f"  {sym_cluster.render()}", flush=True)

    # ============================================================== PART 13: EXPIRATION CONCENTRATION
    print(f"\n{'=' * 100}\nPART 13 — EXPIRATION CONCENTRATION\n{'=' * 100}", flush=True)
    expirations = sorted({r["expiration"] for r in base})
    per_exp_ic = {}
    for exp in expirations:
        rows = [r for r in base if r["expiration"] == exp]
        per_exp_ic[exp] = pooled_ic(rows, FEATURE, PARENT_TARGET) if len(rows) >= 30 else None
        print(f"  {exp}: IC={_fmt(per_exp_ic[exp])}  n={len(rows)}", flush=True)
    expiration_dependent = False
    for exp in expirations:
        without = pooled_ic([r for r in base if r["expiration"] != exp], FEATURE, PARENT_TARGET)
        print(f"  without {exp}: IC={_fmt(without)}", flush=True)
        if without is None or (overlap_ic is not None and (without <= 0 or without < overlap_ic * 0.3)):
            expiration_dependent = True
    print(f"  EXPIRATION_DEPENDENT: {expiration_dependent}", flush=True)
    flags["expiration_dependent"] = expiration_dependent

    # ============================================================== PART 14: MONEYNESS
    print(f"\n{'=' * 100}\nPART 14 — MONEYNESS BUCKETS\n{'=' * 100}", flush=True)
    buckets = ("deep_itm", "itm", "near_atm", "otm", "deep_otm")
    per_bucket_ic = {}
    for b in buckets:
        rows = [r for r in base if r.get("moneyness_bucket") == b]
        if len(rows) < 30:
            print(f"  {b}: INSUFFICIENT_SAMPLE (n={len(rows)})", flush=True)
            continue
        per_bucket_ic[b] = pooled_ic(rows, FEATURE, PARENT_TARGET)
        print(f"  {b}: IC={_fmt(per_bucket_ic[b])}  n={len(rows)}", flush=True)
    bucket_equal_avg = _mean(list(per_bucket_ic.values())) if per_bucket_ic else None
    bucket_signs = [1 if v > 0 else -1 for v in per_bucket_ic.values()]
    sign_consistency_buckets = max(bucket_signs.count(1), bucket_signs.count(-1)) / len(bucket_signs) if bucket_signs else None
    print(f"  equal-weight bucket average: {_fmt(bucket_equal_avg)}   sign_consistency={_fmt(sign_consistency_buckets)}", flush=True)
    moneyness_dependent = sign_consistency_buckets is not None and sign_consistency_buckets < 0.6
    print(f"  MONEYNESS_DEPENDENT: {moneyness_dependent}", flush=True)
    flags["moneyness_dependent"] = moneyness_dependent

    # ============================================================== PART 15: CALL/PUT SYMMETRY
    print(f"\n{'=' * 100}\nPART 15 — CALL/PUT SYMMETRY\n{'=' * 100}", flush=True)
    cp_equal_avg = _mean([v for v in (call_ic, put_ic) if v is not None]) if (call_ic is not None or put_ic is not None) else None
    print(f"  calls IC={_fmt(call_ic)}  puts IC={_fmt(put_ic)}  equal-weight average={_fmt(cp_equal_avg)}  pooled={_fmt(overlap_ic)}", flush=True)
    requires_specific_side = call_ic is not None and put_ic is not None and ((call_ic > 0) != (put_ic > 0))
    print(f"  requires a specific side (sign differs between calls and puts): {requires_specific_side}", flush=True)

    # ============================================================== PART 19: FALSE-DISCOVERY / CLUSTERED BOOTSTRAP
    print(f"\n{'=' * 100}\nPART 19 — CLUSTERED BOOTSTRAP (FALSE-DISCOVERY CONTROL)\n{'=' * 100}", flush=True)
    ic_points = compute_ic_series(base, FEATURE, PARENT_TARGET, min_universe_size=3)
    ic_series = [p.ic for p in ic_points if p.ic is not None]
    for conf in (0.90, 0.95):
        block_report = block_bootstrap_return_series(ic_series, block_size=5, n_resamples=1000, seed=9001, confidence_level=conf)
        stationary_report = stationary_bootstrap_return_series(ic_series, mean_block_length=5.0, n_resamples=1000, seed=9002, confidence_level=conf)
        if block_report.mean_trade_return_ci is not None:
            ci = block_report.mean_trade_return_ci
            print(f"  time-block bootstrap of IC series ({conf:.0%}): [{ci.lower:.5f}, {ci.upper:.5f}]", flush=True)
        if stationary_report.mean_trade_return_ci is not None:
            ci = stationary_report.mean_trade_return_ci
            print(f"  stationary bootstrap of IC series ({conf:.0%}): [{ci.lower:.5f}, {ci.upper:.5f}]", flush=True)
        symc = symbol_cluster_bootstrap_ic(base, feature_col=FEATURE, target_col=PARENT_TARGET, n_resamples=500, seed=9003, confidence_level=conf, min_universe_size=3)
        print(f"  symbol-cluster ({conf:.0%}): [{_fmt(symc.lower_bound)}, {_fmt(symc.upper_bound)}]  (n_symbols={symc.n_symbols})", flush=True)
        expc = cluster_bootstrap_ic(base, feature_col=FEATURE, target_col=PARENT_TARGET, cluster_key_fn=lambda r: r["expiration"], n_resamples=500, seed=9004, confidence_level=conf, min_universe_size=3)
        print(f"  expiration-cluster ({conf:.0%}): [{_fmt(expc.lower_bound)}, {_fmt(expc.upper_bound)}]  (n_clusters={expc.n_symbols})", flush=True)
        yearc = cluster_bootstrap_ic(base, feature_col=FEATURE, target_col=PARENT_TARGET, cluster_key_fn=lambda r: r["timestamp"].year, n_resamples=500, seed=9005, confidence_level=conf, min_universe_size=3)
        print(f"  year-cluster ({conf:.0%}): [{_fmt(yearc.lower_bound)}, {_fmt(yearc.upper_bound)}]  (n_clusters={yearc.n_symbols})", flush=True)
        if conf == 0.90:
            all_ci_positive = all(
                lo is not None and lo > 0
                for lo in (block_report.mean_trade_return_ci.lower if block_report.mean_trade_return_ci else None,
                           symc.lower_bound, expc.lower_bound, yearc.lower_bound)
            )
    print(f"  ALL clustered 90% CIs exclude zero: {all_ci_positive}", flush=True)

    # ---- outlier check (mandatory carry-forward from Phase 21/22 convention) ----
    print(f"\n{'=' * 100}\nOUTLIER CHECK (carried forward from the Phase 19-22 convention)\n{'=' * 100}", flush=True)
    target_vals = [r[PARENT_TARGET] for r in base]
    attribution = compute_outlier_attribution(target_vals)
    print(f"  outlier attribution on {PARENT_TARGET}: top_1%_share={_fmt(attribution.top_1pct_share)}  top_5%_share={_fmt(attribution.top_5pct_share)}", flush=True)
    winsorized_5pct = winsorize(target_vals, fraction=0.05)
    w_rows = [dict(r, **{PARENT_TARGET: t}) for r, t in zip(base, winsorized_5pct)]
    w_effect = pooled_ic(w_rows, FEATURE, PARENT_TARGET)
    print(f"  winsorize 5%: IC={_fmt(w_effect)}  (full sample IC={_fmt(overlap_ic)})", flush=True)
    outlier_dependent = w_effect is not None and overlap_ic is not None and ((w_effect > 0) != (overlap_ic > 0) or abs(w_effect) < abs(overlap_ic) * 0.3)
    print(f"  OUTLIER_DEPENDENT: {outlier_dependent}", flush=True)
    flags["outlier_dependent"] = outlier_dependent

    # ============================================================== PART 20: PBO / DSR
    print(f"\n{'=' * 100}\nPART 20 — PBO / DSR (P22 original vs P23 recomputation)\n{'=' * 100}", flush=True)
    print("  P22 ORIGINAL: PBO=0.700  DSR=0.9991 (observed SR=4.9827, expected max SR under 4 trials=1.2587) -- kept in this report, not hidden.", flush=True)
    if len(ic_series) >= 8:
        n_periods = 6
        all_days = sorted({r["timestamp"] for r in base})
        day_start, day_end = all_days[0], all_days[-1]
        total_days = (day_end - day_start).days + 1
        variants = [FEATURE, "option_vol_ratio_5_20", "underlying_range_expansion_5", "option_momentum_5"]
        period_matrix = []
        for v in variants:
            v_points = compute_ic_series(base, v, PARENT_TARGET, min_universe_size=3)
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
        print(f"  P23 RECOMPUTATION: {pbo.render()}", flush=True)
        print(f"  P23 RECOMPUTATION: DSR: {dsr.render()}", flush=True)

    # ============================================================== PART 21: MULTIPLE TESTING
    print(f"\n{'#' * 100}\nPART 21 — MULTIPLE-TESTING CORRECTION ({len(raw_p_values)} raw p-values, P23-INV family)\n{'#' * 100}", flush=True)
    for method in (bonferroni_correction, holm_bonferroni_correction, benjamini_hochberg_fdr):
        report = method(raw_p_values, alpha=0.05)
        print(f"  {report.method}: n_significant={report.n_significant}/{report.n_tests}", flush=True)

    # ============================================================== PART 27 (first vocabulary): FINAL CLASSIFICATION
    print(f"\n{'#' * 100}\nFINAL CLASSIFICATION (Part 27)\n{'#' * 100}", flush=True)
    print(f"  flags: {flags}", flush=True)
    if flags["underlying_inherited"]:
        classification = "UNDERLYING_INHERITED"
    elif flags["outlier_dependent"]:
        classification = "OUTLIER_DEPENDENT"
    elif flags["expiration_dependent"]:
        classification = "EXPIRATION_DEPENDENT"
    elif flags["moneyness_dependent"]:
        classification = "MONEYNESS_DEPENDENT"
    elif flags["overlap_dependent"]:
        classification = "OVERLAP_DEPENDENT"
    elif flags["non_directional_only"]:
        classification = "NON_DIRECTIONAL_ONLY"
    elif not all_ci_positive:
        classification = "FRAGILE_DISCOVERY"
    else:
        classification = "ROBUST_DISCOVERY_CANDIDATE"
    print(f"  ==> P22-OPT-013 INVESTIGATION CLASSIFICATION: {classification}", flush=True)
    print("  IMPORTANT: this does NOT mean validated, profitable, or ready for trading.", flush=True)

    gate_store = DiscoveryDevelopmentGateStore(Path("logs/research_data/phase23_gate_transitions.jsonl"))
    gate_store.transition(hypothesis_id=INV_ID, to_stage=DiscoveryDevelopmentStage.IDEA, reason="Phase 23 investigation", evidence_summary="")
    gate_store.transition(hypothesis_id=INV_ID, to_stage=DiscoveryDevelopmentStage.PREREGISTERED, reason="preregistered step 2", evidence_summary="")
    gate_store.transition(hypothesis_id=INV_ID, to_stage=DiscoveryDevelopmentStage.DISCOVERY_TESTED, reason="Phase 23 investigation completed", evidence_summary=classification)
    if classification == "ROBUST_DISCOVERY_CANDIDATE":
        gate_store.transition(hypothesis_id=INV_ID, to_stage=DiscoveryDevelopmentStage.DISCOVERY_SUPPORTED, reason=classification, evidence_summary=classification)
    else:
        gate_store.transition(hypothesis_id=INV_ID, to_stage=DiscoveryDevelopmentStage.NOT_READY, reason=f"classified {classification}", evidence_summary=classification)

    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))
    dims_fp = ExperimentDimensions(
        feature_definition=FEATURE, parameter_range={"controls": control_cols, "targets": [t for _, t in TARGET_VALIDATION_FAMILY]},
        universe_name=universe.name, target_definition=PARENT_TARGET, execution_model="n/a-discovery-only",
        cost_model="assumption-only-1x-2x-3x-5x", validation_methodology="Phase 23 adversarial investigation",
    )
    exp_store.record(
        data_version="phase23-panel-v1", feature_version="phase23-investigation-v1", symbols=list(universe.symbols), timeframe="day",
        strategy_version="1.0", prediction_horizon=5, train_period=("2021-12-01", "2023-06-15"),
        parameters={"n_raw_p_values": len(raw_p_values)}, metrics={"survives_all_controls": int(bool(survives_all_controls))},
        strategy_family="p22_opt_013_investigation", classification=classification,
        tags=("phase23-investigation", universe.name, "mark-to-market-historical-research"),
        notes=f"flags={flags}", hypothesis_id=INV_ID, universe_name=universe.name,
        experiment_fingerprint=compute_experiment_fingerprint(dims_fp), research_family_id="P23-INVESTIGATION-2026-09",
    )
    print("\nSTEP 3 COMPLETE.", flush=True)


if __name__ == "__main__":
    main()
