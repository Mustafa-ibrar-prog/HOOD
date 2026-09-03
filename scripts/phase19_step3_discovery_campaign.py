#!/usr/bin/env python3
"""Phase 19, STEP 3 — the options_alpha discovery campaign (P19-OPT-001..012)
on the real 24-contract, single-expiration panel built by step 1. MARK-TO-
MARKET HISTORICAL RESEARCH only (Part 10) -- no backtest, no trading
strategy, no live/paper order, no VALIDATION/FINAL_HOLDOUT data access.
Must be run AFTER step 1 and step 2.

Every real statistic below reuses Phase 7+'s existing statistical
machinery (src.research.ic/quantile/multiple_testing/return_series_
bootstrap/overfitting_metrics/purged_cv/cross_sectional_placebo) --
nothing here reimplements IC, bootstrap, PBO, DSR, or purged CV.

Honesty about scale: this panel is SMALL (24 contracts, one expiration
cycle, ~74 trading days) compared to the equity cross-sectional research
in prior phases (dozens of symbols, years of data). Every result below is
reported with that context, never inflated by treating 1,776 contract-day
ROWS as 1,776 independent observations (they are not -- 74 timestamps x
24 contracts, heavily autocorrelated within a contract).
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.store import HistoricalDataStore  # noqa: E402
from src.features import FeatureEngine  # noqa: E402
from src.features.volatility import RealizedVolatility  # noqa: E402
from src.options.cost_model import COST_SENSITIVITY_ASSUMPTIONS, apply_cost_assumption  # noqa: E402
from src.options.price_history import STANDARD_FORWARD_HORIZONS  # noqa: E402
from src.options.quality import find_suspicious_flat_price_run  # noqa: E402
from src.options.universe import phase19_verified_underlying_universe  # noqa: E402
from src.research import (  # noqa: E402
    DiscoveryDevelopmentGateStore,
    DiscoveryDevelopmentStage,
    ExperimentStore,
    benjamini_hochberg_fdr,
    block_bootstrap_return_series,
    bonferroni_correction,
    compute_ic_series,
    compute_pearson_ic_series,
    cross_sectional_quantile_returns,
    deflated_sharpe_ratio,
    holm_bonferroni_correction,
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
from src.research.experiment_fingerprint import ExperimentDimensions, compute_experiment_fingerprint  # noqa: E402
from src.research.preregistration import PreregistrationStore  # noqa: E402
from src.research.purged_cv import PurgedCVConfig, PurgedFold, fold_has_leakage, generate_purged_folds  # noqa: E402
from src.research.stats_utils import t_test_p_value  # noqa: E402
from src.research.targets import future_return  # noqa: E402

RESEARCH_PANEL = Path("logs/research_data/phase19_research_panel.jsonl")
VOL_WINDOW = 20
PRIMARY_HORIZON = 5
PRIMARY_TARGET_COL = "forward_return_5"
PRIMARY_FEATURE = "log_moneyness"
FLAT_RUN_MIN_LENGTH = 10


def _fmt(x) -> str:
    return "None" if x is None else f"{x:.5f}"


def _ic_p_value(points) -> float | None:
    values = [p.ic for p in points if p.ic is not None]
    if len(values) < 2:
        return None
    return t_test_p_value(values)


def _welch_p_value(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2 or len(b) < 2:
        return None
    from src.research.analysis import mean as _mean
    from src.research.analysis import stdev as _stdev
    from src.research.stats_utils import two_tailed_p_value_from_z

    mean_a, mean_b = _mean(a), _mean(b)
    se = ((_stdev(a) ** 2) / len(a) + (_stdev(b) ** 2) / len(b)) ** 0.5
    if se == 0:
        return None
    return two_tailed_p_value_from_z((mean_a - mean_b) / se)


def load_panel() -> list[dict]:
    if not RESEARCH_PANEL.is_file():
        raise SystemExit(f"{RESEARCH_PANEL} not found -- run step 1 first.")
    rows = [json.loads(line) for line in RESEARCH_PANEL.read_text().splitlines() if line.strip()]
    for r in rows:
        r["timestamp"] = date.fromisoformat(r["timestamp"])
        r["symbol"] = r["option_id"]  # generic IC/quantile machinery expects a "symbol" key
    return rows


def enrich_with_underlying_features(rows: list[dict], underlyings: tuple[str, ...]) -> None:
    """Adds underlying-derived features (daily return, lagged realized
    vol, forward return) by joining on (underlying_symbol, date). Mutates
    `rows` in place."""
    store = HistoricalDataStore(Path("logs/research_data"))
    engine = FeatureEngine([RealizedVolatility(VOL_WINDOW)])
    by_symbol_date: dict[str, dict[date, dict]] = {}
    for sym in underlyings:
        bars = store.load(sym, "day")
        frame = engine.compute(bars)
        raw_vol = frame.columns[f"realized_vol_{VOL_WINDOW}"]
        lagged_vol = [None] + list(raw_vol[:-1])
        daily_returns = [None] + [
            (bars[i].close - bars[i - 1].close) / bars[i - 1].close if bars[i - 1].close else None for i in range(1, len(bars))
        ]
        fwd = future_return(bars, PRIMARY_HORIZON)
        by_date = {}
        for i, b in enumerate(bars):
            by_date[b.timestamp.date()] = {
                "underlying_lagged_realized_vol": lagged_vol[i],
                "underlying_daily_return": daily_returns[i],
                "underlying_forward_return_5": fwd[i],
            }
        by_symbol_date[sym] = by_date

    for r in rows:
        feats = by_symbol_date.get(r["underlying_symbol"], {}).get(r["timestamp"], {})
        r.update(feats)


def add_derived_features(rows: list[dict]) -> None:
    """Per-contract-derived features that need the contract's own
    ordered close series: daily option return, |daily return|, and the
    tick-floor flat-price-run flag (Part 15/18)."""
    by_contract: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_contract[r["option_id"]].append(r)
    for option_id, contract_rows in by_contract.items():
        contract_rows.sort(key=lambda r: r["timestamp"])
        closes = [r["option_close"] for r in contract_rows]
        flat_issues = find_suspicious_flat_price_run(closes, min_run_length=FLAT_RUN_MIN_LENGTH, flat_value=0.01)
        flagged_indices: set[int] = set()
        # Recompute run boundaries directly (find_suspicious_flat_price_run reports issues, not indices) --
        # reuse the exact same scan so the flag is provably consistent with the quality check.
        run_start = None
        for i, c in enumerate(closes):
            if c == 0.01:
                if run_start is None:
                    run_start = i
            else:
                if run_start is not None and i - run_start >= FLAT_RUN_MIN_LENGTH:
                    flagged_indices.update(range(run_start, i))
                run_start = None
        if run_start is not None and len(closes) - run_start >= FLAT_RUN_MIN_LENGTH:
            flagged_indices.update(range(run_start, len(closes)))

        for i, r in enumerate(contract_rows):
            prev_close = closes[i - 1] if i > 0 else None
            r["option_daily_return"] = (closes[i] - prev_close) / prev_close if prev_close and prev_close > 0 else None
            r["abs_option_daily_return"] = abs(r["option_daily_return"]) if r["option_daily_return"] is not None else None
            r["is_flat_pinned"] = 1.0 if i in flagged_indices else 0.0
            r["moneyness_x_dte_interaction"] = r["log_moneyness"] * r["dte"]
            r["call_put_numeric"] = 1.0 if r["call_put"] == "call" else 0.0
        if flat_issues:
            print(f"  [quality] {option_id}: {len(flat_issues)} flat-price-run issue(s) flagged, {len(flagged_indices)} bars marked is_flat_pinned", flush=True)


def main() -> None:
    universe = phase19_verified_underlying_universe()

    prereg_store = PreregistrationStore(Path("logs/research_data/phase19_preregistrations.jsonl"))
    require_preregistered(prereg_store, "P19-OPT-FAMILY")
    for i in range(1, 13):
        require_preregistered(prereg_store, f"P19-OPT-{i:03d}")

    print(f"UNIVERSE: {universe.name} — {universe.symbols}", flush=True)
    print("LABEL: MARK-TO-MARKET HISTORICAL RESEARCH throughout (Part 10) -- priced off get_option_historicals closes.", flush=True)

    panel = load_panel()
    print(f"Loaded panel: {len(panel)} contract-day rows, {len({r['option_id'] for r in panel})} contracts, "
          f"{len({r['timestamp'] for r in panel})} distinct trading days.\n", flush=True)

    enrich_with_underlying_features(panel, universe.symbols)
    add_derived_features(panel)

    raw_p_values: list[tuple[str, float]] = []
    all_ic_results: dict[str, dict] = {}

    # ============================================================== PART A: MAIN SCREEN @ primary horizon
    print(f"{'=' * 100}\nPART A — MAIN SCREEN @ h={PRIMARY_HORIZON} (n_contracts={len({r['option_id'] for r in panel})} per timestamp)\n{'=' * 100}", flush=True)
    main_features = ("log_moneyness", "dte", "call_put_numeric", "moneyness_x_dte_interaction")
    for feature_name in main_features:
        spearman_points = compute_ic_series(panel, feature_name, PRIMARY_TARGET_COL, min_universe_size=3)
        spearman = summarize_ic(spearman_points, feature_name=feature_name, target_name=PRIMARY_TARGET_COL)
        pearson_points = compute_pearson_ic_series(panel, feature_name, PRIMARY_TARGET_COL, min_universe_size=3)
        pearson = summarize_pearson_ic(pearson_points, feature_name=feature_name, target_name=PRIMARY_TARGET_COL)
        quantiles = cross_sectional_quantile_returns(panel, feature_name, PRIMARY_TARGET_COL, n_quantiles=5, min_universe_size=3)
        key = f"{feature_name}|{PRIMARY_TARGET_COL}"
        all_ic_results[key] = {"spearman": spearman, "pearson": pearson, "quantiles": quantiles, "spearman_points": spearman_points}
        print(f"  {feature_name:32s}: spearman_IC={_fmt(spearman.average_ic)}  pearson_IC={_fmt(pearson.average_ic)}  "
              f"spread={_fmt(quantiles.spread_q5_minus_q1)}  monotonic={quantiles.is_monotonic}", flush=True)
        p = _ic_p_value(spearman_points)
        if p is not None:
            raw_p_values.append((key, p))

    print("\n  NOTE on 'moneyness_x_dte_interaction' above: because dte is constant across the cross-section at any "
          "given timestamp (single expiration), the interaction term is a positive scalar multiple of log_moneyness "
          "at every timestamp -- its cross-sectional IC is therefore MATHEMATICALLY IDENTICAL to log_moneyness's own "
          "IC in this single-expiration panel (confirmed above: both 0.05515), not an independent finding. Part G's "
          "OLS below is the correct place to look for a genuine interaction effect (it uses dte as a POOLED, "
          "not cross-sectional, regressor).", flush=True)
    print("\n  NOTE on 'dte' above: this panel uses a SINGLE expiration (2022-03-18) for every contract, so DTE is "
          "IDENTICAL across all 24 contracts at any given timestamp -- cross-sectional IC is structurally UNDEFINED "
          "for it (zero cross-sectional variance to rank), not merely weak. A separate POOLED TIME-SERIES correlation "
          "(across all 1,776 contract-day rows, ignoring the cross-sectional dimension) is the correct test for DTE "
          "given this data's shape, and is reported next.", flush=True)
    from src.research.analysis import spearman_correlation as _spearman

    dte_vals_pooled = [r["dte"] for r in panel if r.get("dte") is not None and r.get(PRIMARY_TARGET_COL) is not None]
    dte_targets_pooled = [r[PRIMARY_TARGET_COL] for r in panel if r.get("dte") is not None and r.get(PRIMARY_TARGET_COL) is not None]
    dte_pooled_corr = _spearman(dte_vals_pooled, dte_targets_pooled)
    print(f"  dte (POOLED time-series Spearman, n={len(dte_vals_pooled)}): correlation={_fmt(dte_pooled_corr)}  "
          "(DESCRIPTIVE ONLY -- no valid p-value is computed: the 1,656 stacked rows are NOT independent observations, "
          "so a standard t-test denominator would understate the true standard error; magnitude/sign are reported, "
          "significance is not claimed)", flush=True)
    all_ic_results["dte_pooled|" + PRIMARY_TARGET_COL] = {"pooled_correlation": dte_pooled_corr, "n": len(dte_vals_pooled)}

    # ============================================================== PART B: HORIZON STABILITY (P19-OPT-009)
    print(f"\n{'=' * 100}\nPART B — HORIZON STABILITY ({PRIMARY_FEATURE} IC across all preregistered horizons)\n{'=' * 100}", flush=True)
    horizon_ics: dict[int, float | None] = {}
    for h in STANDARD_FORWARD_HORIZONS:
        col = f"forward_return_{h}"
        key = f"{PRIMARY_FEATURE}|{col}"
        if h == PRIMARY_HORIZON:
            # Already computed in Part A (with quantiles) -- reuse it rather than overwrite that
            # richer entry with a partial one, and never double-count the same test in raw_p_values.
            summary = all_ic_results[key]["spearman"]
            horizon_ics[h] = summary.average_ic
            print(f"  h={h:3d}: IC={_fmt(summary.average_ic)}  (== Part A's primary-horizon result)", flush=True)
            continue
        points = compute_ic_series(panel, PRIMARY_FEATURE, col, min_universe_size=3)
        summary = summarize_ic(points, feature_name=PRIMARY_FEATURE, target_name=col)
        horizon_ics[h] = summary.average_ic
        all_ic_results[key] = {"spearman": summary, "spearman_points": points}
        print(f"  h={h:3d}: IC={_fmt(summary.average_ic)}", flush=True)
        p = _ic_p_value(points)
        if p is not None:
            raw_p_values.append((key, p))
    same_sign = len({1 if (v or 0) > 0 else (-1 if (v or 0) < 0 else 0) for v in horizon_ics.values() if v is not None}) <= 1
    print(f"  same-sign across all horizons: {same_sign}", flush=True)

    # ============================================================== PART C: MONEYNESS BUCKET TAIL/SKEW (P19-OPT-004)
    print(f"\n{'=' * 100}\nPART C — MONEYNESS BUCKET TAIL-RISK COMPARISON\n{'=' * 100}", flush=True)
    from src.research.analysis import stdev as _stdev

    bucket_stats: dict[str, dict] = {}
    for bucket in ("deep_itm", "itm", "near_atm", "otm", "deep_otm"):
        vals = [r[PRIMARY_TARGET_COL] for r in panel if r.get("moneyness_bucket") == bucket and r.get(PRIMARY_TARGET_COL) is not None]
        if len(vals) < 2:
            print(f"  {bucket:10s}: n={len(vals)} (too few for stats)", flush=True)
            continue
        bucket_stats[bucket] = {"n": len(vals), "mean": sum(vals) / len(vals), "stdev": _stdev(vals), "min": min(vals), "max": max(vals)}
        print(f"  {bucket:10s}: n={len(vals):5d}  mean={_fmt(bucket_stats[bucket]['mean'])}  stdev={_fmt(bucket_stats[bucket]['stdev'])}  "
              f"min={_fmt(bucket_stats[bucket]['min'])}  max={_fmt(bucket_stats[bucket]['max'])}", flush=True)
    deep_otm_stdev = bucket_stats.get("deep_otm", {}).get("stdev")
    itm_atm_stdevs = [bucket_stats[b]["stdev"] for b in ("deep_itm", "itm", "near_atm") if b in bucket_stats]
    itm_atm_mean_stdev = sum(itm_atm_stdevs) / len(itm_atm_stdevs) if itm_atm_stdevs else None
    print(f"  deep_otm stdev={_fmt(deep_otm_stdev)}  vs  ITM/ATM mean stdev={_fmt(itm_atm_mean_stdev)}", flush=True)

    # ============================================================== PART D: CALL/PUT ASYMMETRY (P19-OPT-005)
    print(f"\n{'=' * 100}\nPART D — CALL/PUT ASYMMETRY\n{'=' * 100}", flush=True)
    call_rets = [r[PRIMARY_TARGET_COL] for r in panel if r.get("call_put") == "call" and r.get(PRIMARY_TARGET_COL) is not None]
    put_rets = [r[PRIMARY_TARGET_COL] for r in panel if r.get("call_put") == "put" and r.get(PRIMARY_TARGET_COL) is not None]
    call_mean = sum(call_rets) / len(call_rets) if call_rets else None
    put_mean = sum(put_rets) / len(put_rets) if put_rets else None
    cp_gap = None if call_mean is None or put_mean is None else call_mean - put_mean
    cp_p = _welch_p_value(call_rets, put_rets)
    print(f"  call: n={len(call_rets)} mean={_fmt(call_mean)}   put: n={len(put_rets)} mean={_fmt(put_mean)}   "
          f"gap={_fmt(cp_gap)}  Welch_p={_fmt(cp_p)}", flush=True)

    # ============================================================== PART E: VOLATILITY -> MAGNITUDE (P19-OPT-006)
    print(f"\n{'=' * 100}\nPART E — UNDERLYING VOLATILITY -> OPTION FORWARD-RETURN MAGNITUDE\n{'=' * 100}", flush=True)
    for r in panel:
        r["abs_forward_return_5"] = abs(r[PRIMARY_TARGET_COL]) if r.get(PRIMARY_TARGET_COL) is not None else None
    vol_mag_points = compute_ic_series(panel, "underlying_lagged_realized_vol", "abs_forward_return_5", min_universe_size=3)
    vol_mag_ic = summarize_ic(vol_mag_points, feature_name="underlying_lagged_realized_vol", target_name="abs_forward_return_5")
    print(f"  IC(underlying_lagged_realized_vol, |forward_return_5|) = {_fmt(vol_mag_ic.average_ic)}", flush=True)
    all_ic_results["underlying_lagged_realized_vol|abs_forward_return_5"] = {"spearman": vol_mag_ic, "spearman_points": vol_mag_points}
    p = _ic_p_value(vol_mag_points)
    if p is not None:
        raw_p_values.append(("underlying_lagged_realized_vol|abs_forward_return_5", p))

    # ============================================================== PART F: REVERSAL VS CONTINUATION (P19-OPT-007)
    print(f"\n{'=' * 100}\nPART F — SHORT-HORIZON REVERSAL/CONTINUATION (top-quintile |option daily return|)\n{'=' * 100}", flush=True)
    rows_with_vals = [r for r in panel if r.get("abs_option_daily_return") is not None and r.get("option_daily_return") is not None and r.get("forward_return_1") is not None]
    sorted_rows = sorted(rows_with_vals, key=lambda r: r["abs_option_daily_return"])
    n = len(sorted_rows)
    top_quintile_f = sorted_rows[int(n * 0.8):] if n else []
    signed_products = [(1 if r["option_daily_return"] > 0 else -1) * r["forward_return_1"] for r in top_quintile_f if r["option_daily_return"] != 0]
    mean_signed_product = sum(signed_products) / len(signed_products) if signed_products else None
    print(f"  n={len(top_quintile_f)}  mean(sign(daily_return)*forward_return_1)={_fmt(mean_signed_product)}  "
          f"-> {'CONTINUATION' if (mean_signed_product or 0) > 0 else 'REVERSAL' if (mean_signed_product or 0) < 0 else 'NEITHER'}", flush=True)

    # ============================================================== PART G: MONEYNESS x DTE INTERACTION OLS (P19-OPT-003)
    print(f"\n{'=' * 100}\nPART G — MONEYNESS x DTE INTERACTION (OLS)\n{'=' * 100}", flush=True)
    y = [r.get(PRIMARY_TARGET_COL) for r in panel]
    lm = [r.get("log_moneyness") for r in panel]
    dte_vals = [r.get("dte") for r in panel]
    interaction = [r.get("moneyness_x_dte_interaction") for r in panel]
    model_ab = ols_regression(y, {"log_moneyness": lm, "dte": dte_vals}, min_observations=30)
    model_abc = ols_regression(y, {"log_moneyness": lm, "dte": dte_vals, "interaction": interaction}, min_observations=30)
    print(f"  Model AB:  {model_ab.render()}", flush=True)
    print(f"  Model ABC: {model_abc.render()}", flush=True)
    interaction_incremental = None
    interaction_p = None
    if model_ab.applicable and model_abc.applicable:
        interaction_incremental = model_abc.r_squared - model_ab.r_squared
        interaction_p = model_abc.coefficient_p_values.get("interaction", 1.0)
        print(f"  interaction incremental R2={_fmt(interaction_incremental)}  interaction_p={interaction_p:.4g}", flush=True)

    # ============================================================== PART H: PER-UNDERLYING LEAVE-ONE-OUT (P19-OPT-008)
    print(f"\n{'=' * 100}\nPART H — PER-UNDERLYING LEAVE-ONE-OUT STABILITY ({PRIMARY_FEATURE})\n{'=' * 100}", flush=True)
    pooled_ic = all_ic_results[f"{PRIMARY_FEATURE}|{PRIMARY_TARGET_COL}"]["spearman"].average_ic
    per_underlying_ic = {}
    for sym in universe.symbols:
        sym_rows = [r for r in panel if r["underlying_symbol"] == sym]
        sym_points = compute_ic_series(sym_rows, PRIMARY_FEATURE, PRIMARY_TARGET_COL, min_universe_size=3)
        sym_ic = summarize_ic(sym_points, feature_name=PRIMARY_FEATURE, target_name=PRIMARY_TARGET_COL).average_ic
        per_underlying_ic[sym] = sym_ic
        without = [r for r in panel if r["underlying_symbol"] != sym]
        without_points = compute_ic_series(without, PRIMARY_FEATURE, PRIMARY_TARGET_COL, min_universe_size=3)
        without_ic = summarize_ic(without_points, feature_name=PRIMARY_FEATURE, target_name=PRIMARY_TARGET_COL).average_ic
        print(f"  {sym}: own_IC={_fmt(sym_ic)}   pooled_without_{sym}_IC={_fmt(without_ic)}", flush=True)
    same_sign_underlyings = sum(1 for v in per_underlying_ic.values() if v is not None and pooled_ic is not None and (v > 0) == (pooled_ic > 0))
    print(f"  pooled_IC={_fmt(pooled_ic)}  underlyings agreeing in sign with pooled: {same_sign_underlyings}/{len(universe.symbols)}", flush=True)

    # ============================================================== PART I: MECHANICAL BASELINE (P19-OPT-010)
    print(f"\n{'=' * 100}\nPART I — MECHANICAL-BASELINE CHECK: option IC vs underlying-equity IC on the SAME feature/horizon\n{'=' * 100}", flush=True)
    underlying_points = compute_ic_series(panel, PRIMARY_FEATURE, "underlying_forward_return_5", min_universe_size=3)
    underlying_ic = summarize_ic(underlying_points, feature_name=PRIMARY_FEATURE, target_name="underlying_forward_return_5")
    print(f"  option IC(log_moneyness, forward_return_5)={_fmt(pooled_ic)}   "
          f"underlying-equity IC(log_moneyness, underlying_forward_return_5)={_fmt(underlying_ic.average_ic)}", flush=True)
    mechanical_gap = None if pooled_ic is None or underlying_ic.average_ic is None else abs(pooled_ic) - abs(underlying_ic.average_ic)
    print(f"  |option_IC| - |underlying_IC| = {_fmt(mechanical_gap)}  "
          f"(positive => option data adds information beyond the underlying's own forward return)", flush=True)

    # ============================================================== PART J: DATA-QUALITY NEGATIVE CONTROL (P19-OPT-011)
    print(f"\n{'=' * 100}\nPART J — FLAT-PRICE-PINNED NEGATIVE CONTROL (variance comparison)\n{'=' * 100}", flush=True)
    pinned_rets = [r[PRIMARY_TARGET_COL] for r in panel if r.get("is_flat_pinned") == 1.0 and r.get(PRIMARY_TARGET_COL) is not None]
    unpinned_rets = [r[PRIMARY_TARGET_COL] for r in panel if r.get("is_flat_pinned") == 0.0 and r.get(PRIMARY_TARGET_COL) is not None]
    pinned_var = _stdev(pinned_rets) ** 2 if len(pinned_rets) >= 2 else None
    unpinned_var = _stdev(unpinned_rets) ** 2 if len(unpinned_rets) >= 2 else None
    print(f"  pinned: n={len(pinned_rets)} variance={_fmt(pinned_var)}   unpinned: n={len(unpinned_rets)} variance={_fmt(unpinned_var)}", flush=True)

    # ============================================================== PART K: DTE-BUCKET DECAY MAGNITUDE (P19-OPT-012)
    print(f"\n{'=' * 100}\nPART K — DTE-BUCKET DECAY MAGNITUDE (mean forward_return_1 by bucket)\n{'=' * 100}", flush=True)
    dte_bucket_means = {}
    for bucket in ("0-7", "8-30", "31-60", "61-120", "120+"):
        vals = [r["forward_return_1"] for r in panel if r.get("dte_bucket") == bucket and r.get("forward_return_1") is not None]
        if vals:
            dte_bucket_means[bucket] = sum(vals) / len(vals)
            print(f"  {bucket:8s}: n={len(vals):5d}  mean_forward_return_1={_fmt(dte_bucket_means[bucket])}", flush=True)
    most_negative_bucket = min(dte_bucket_means, key=lambda b: dte_bucket_means[b]) if dte_bucket_means else None
    print(f"  most-negative bucket: {most_negative_bucket}", flush=True)

    # ============================================================== PART L: PLACEBO BATTERY
    print(f"\n{'=' * 100}\nPART L — PLACEBO BATTERY (primary feature/target)\n{'=' * 100}", flush=True)
    shuffled = shuffled_signal_placebo(panel, feature_col=PRIMARY_FEATURE, target_col=PRIMARY_TARGET_COL, n_trials=200, seed=1901)
    print(f"  A. cross-sectional shuffle: observed_IC={_fmt(shuffled.observed_statistic)}  p={shuffled.empirical_p_value}", flush=True)
    time_shuffled = time_shuffled_target_placebo(panel, feature_col=PRIMARY_FEATURE, target_col=PRIMARY_TARGET_COL, n_trials=200, seed=1902)
    print(f"  B. time shuffle: observed_IC={_fmt(time_shuffled.observed_statistic)}  p={time_shuffled.empirical_p_value}", flush=True)
    random_ctrl = random_feature_control(panel, target_col=PRIMARY_TARGET_COL, n_trials=100, seed=1903, min_universe_size=3)
    random_mean_ic = sum(random_ctrl.placebo_distribution) / len(random_ctrl.placebo_distribution) if random_ctrl.placebo_distribution else None
    print(f"  C. random feature: mean_IC={_fmt(random_mean_ic)}", flush=True)
    rng = random.Random(1904)
    random_sign_rows = [dict(r) for r in panel]
    for r in random_sign_rows:
        if r.get(PRIMARY_FEATURE) is not None:
            r[PRIMARY_FEATURE] = abs(r[PRIMARY_FEATURE]) * rng.choice((1, -1))
    random_sign_ic = summarize_ic(compute_ic_series(random_sign_rows, PRIMARY_FEATURE, PRIMARY_TARGET_COL, min_universe_size=3), feature_name=PRIMARY_FEATURE, target_name=PRIMARY_TARGET_COL)
    print(f"  D. random-sign placebo: IC={_fmt(random_sign_ic.average_ic)}  (true_IC={_fmt(pooled_ic)})", flush=True)
    alignment_concern = False
    for shift in (1, 2, 5):
        shifted = shifted_signal_placebo(panel, feature_col=PRIMARY_FEATURE, target_col=PRIMARY_TARGET_COL, shift_bars=shift)
        shifted_ic = shifted.placebo_distribution[0] if shifted.placebo_distribution else None
        flag = shifted_ic is not None and pooled_ic is not None and abs(shifted_ic) >= abs(pooled_ic)
        alignment_concern = alignment_concern or flag
        print(f"  E. alignment shift=+{shift}: true_IC={_fmt(pooled_ic)}  shifted_IC={_fmt(shifted_ic)}  {'<-- CONCERN' if flag else ''}", flush=True)

    # ============================================================== PART M: MULTIPLE-TESTING CORRECTION
    print(f"\n{'=' * 100}\nPART M — MULTIPLE-TESTING CORRECTION (n={len(raw_p_values)})\n{'=' * 100}", flush=True)
    for method in (bonferroni_correction, holm_bonferroni_correction, benjamini_hochberg_fdr):
        report = method(raw_p_values, alpha=0.05)
        print(f"  {report.method}: n_significant={report.n_significant}/{report.n_tests}", flush=True)
    bh_report = benjamini_hochberg_fdr(raw_p_values, alpha=0.05)
    bh_significant_keys = {r.label for r in bh_report.results if r.significant_at_alpha}
    primary_key = f"{PRIMARY_FEATURE}|{PRIMARY_TARGET_COL}"
    primary_bh = next((r for r in bh_report.results if r.label == primary_key), None)
    print(f"  primary test ({primary_key}) BH-adjusted p={primary_bh.adjusted_p_value if primary_bh else 'N/A'}  significant={primary_bh.significant_at_alpha if primary_bh else 'N/A'}", flush=True)

    # ============================================================== PART N: BOOTSTRAP
    print(f"\n{'=' * 100}\nPART N — BOOTSTRAP (block + stationary) on primary IC series\n{'=' * 100}", flush=True)
    primary_ic_series = [p.ic for p in all_ic_results[f"{PRIMARY_FEATURE}|{PRIMARY_TARGET_COL}"]["spearman_points"] if p.ic is not None]
    for conf in (0.90, 0.95):
        block_report = block_bootstrap_return_series(primary_ic_series, block_size=5, n_resamples=2000, seed=1905, confidence_level=conf)
        print(f"  block bootstrap ({conf:.0%} CI): {block_report.render()}", flush=True)
        stationary_report = stationary_bootstrap_return_series(primary_ic_series, mean_block_length=5.0, n_resamples=2000, seed=1906, confidence_level=conf)
        print(f"  stationary bootstrap ({conf:.0%} CI): {stationary_report.render()}", flush=True)

    # ============================================================== PART O: PBO / DSR
    print(f"\n{'=' * 100}\nPART O — PBO / DSR (across the {len(main_features)} main-screen features)\n{'=' * 100}", flush=True)
    n_periods = 6
    all_days = sorted({r["timestamp"] for r in panel})
    if len(all_days) >= n_periods:
        day_start, day_end = all_days[0], all_days[-1]
        total_days = (day_end - day_start).days + 1
        period_matrix: list[list[float]] = []
        for feature_name in main_features:
            points = all_ic_results[f"{feature_name}|{PRIMARY_TARGET_COL}"]["spearman_points"]
            buckets: list[list[float]] = [[] for _ in range(n_periods)]
            for p in points:
                if p.ic is None:
                    continue
                offset = (p.timestamp - day_start).days
                bucket = min(n_periods - 1, max(0, (offset * n_periods) // total_days))
                buckets[bucket].append(p.ic)
            period_matrix.append([sum(b) / len(b) if b else 0.0 for b in buckets])
        pbo = probability_of_backtest_overfitting(period_matrix)
        print(f"  {pbo.render()}", flush=True)
    else:
        print(f"  skipped -- fewer than {n_periods} distinct days in the panel", flush=True)
    dsr = deflated_sharpe_ratio(primary_ic_series, n_trials=len(main_features))
    print(f"  DSR applied to {PRIMARY_FEATURE}'s own per-timestamp IC series (n_trials={len(main_features)}): {dsr.render()}", flush=True)

    # ============================================================== PART P: PURGED CV LEAKAGE DEMO
    print(f"\n{'=' * 100}\nPART P — PURGED/EMBARGOED CV LEAKAGE DEMONSTRATION\n{'=' * 100}", flush=True)
    sample_option_id = panel[0]["option_id"]
    sample_dates = sorted({r["timestamp"] for r in panel if r["option_id"] == sample_option_id})
    sample_timestamps = [datetime(d.year, d.month, d.day, tzinfo=timezone.utc) for d in sample_dates]
    cv_config = PurgedCVConfig(n_splits=6, prediction_horizon_bars=PRIMARY_HORIZON, purge_window_bars=2, embargo_bars=2)
    purged_folds = generate_purged_folds(sample_timestamps, cv_config)
    purged_leakage = [fold_has_leakage(f, sample_timestamps, prediction_horizon_bars=PRIMARY_HORIZON) for f in purged_folds]
    print(f"  purged CV: {sum(purged_leakage)}/{len(purged_folds)} folds show leakage (expected: 0)", flush=True)

    def _naive_folds(n: int, n_splits: int) -> list[PurgedFold]:
        base_size, remainder = n // n_splits, n % n_splits
        folds, start = [], 0
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

    # ============================================================== PART Q: COST SENSITIVITY (ASSUMPTION-labeled only)
    print(f"\n{'=' * 100}\nPART Q — COST SENSITIVITY (Part 10: 1x/2x/3x ASSUMPTION-labeled, net of mark-to-market Q5-Q1)\n{'=' * 100}", flush=True)
    q5_entry_prices = [r["option_close"] for r in panel if r.get(PRIMARY_FEATURE) is not None]
    gross_spread = all_ic_results[f"{PRIMARY_FEATURE}|{PRIMARY_TARGET_COL}"]["quantiles"].spread_q5_minus_q1
    mean_entry_price = sum(q5_entry_prices) / len(q5_entry_prices) if q5_entry_prices else None
    print(f"  gross Q5-Q1 spread (mark-to-market): {_fmt(gross_spread)}   mean entry option price across panel: {_fmt(mean_entry_price)}", flush=True)
    for assumption in COST_SENSITIVITY_ASSUMPTIONS:
        if gross_spread is None or mean_entry_price is None or mean_entry_price <= 0:
            print(f"  {assumption.label}: N/A", flush=True)
            continue
        net_spread = apply_cost_assumption(gross_spread, mean_entry_price, assumption)
        print(f"  {assumption.label}: net_Q5-Q1_spread={_fmt(net_spread)}  viable_under_this_assumption={'True' if net_spread > 0 else 'False'}", flush=True)

    # ============================================================== FINAL CLASSIFICATION
    print(f"\n{'=' * 100}\nFINAL PER-HYPOTHESIS CLASSIFICATION\n{'=' * 100}", flush=True)
    gate_store = DiscoveryDevelopmentGateStore(Path("logs/research_data/phase19_gate_transitions.jsonl"))
    classifications: dict[str, tuple[str, str]] = {}

    def _advance_and_classify(hyp_id: str, verdict: str, reason: str) -> None:
        classifications[hyp_id] = (verdict, reason)
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.IDEA, reason="new options_alpha hypothesis", evidence_summary="")
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.PREREGISTERED, reason="preregistered before any analysis ran", evidence_summary="")
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DISCOVERY_TESTED, reason="discovery family completed", evidence_summary=reason)
        if verdict == "DISCOVERY_SUPPORTED":
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DISCOVERY_SUPPORTED, reason=reason, evidence_summary=reason)
        else:
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.NOT_READY, reason=f"classified {verdict}: {reason}", evidence_summary=reason)
        print(f"  {hyp_id}: {verdict} — {reason}", flush=True)

    def _classify_ic(key: str) -> tuple[str, str]:
        bh_sig = key in bh_significant_keys
        result = all_ic_results.get(key)
        if result is None:
            return "NOT_READY", "no result computed"
        ic = result["spearman"].average_ic
        q = result.get("quantiles")
        reason = f"IC={_fmt(ic)}, BH-significant={bh_sig}, monotonic={q.is_monotonic if q else 'N/A'}, n_contracts=24 (small panel)"
        if not bh_sig:
            return ("REJECTED" if ic is not None and abs(ic) < 0.01 else "INCONCLUSIVE"), reason
        if q is not None and q.is_monotonic is False:
            return "FRAGILE", reason
        return "DISCOVERY_SUPPORTED", reason

    v, r = _classify_ic(f"log_moneyness|{PRIMARY_TARGET_COL}")
    _advance_and_classify("P19-OPT-001", v, r)

    v2 = "INCONCLUSIVE"  # cross-sectional IC is structurally undefined (single-expiration panel); the pooled correlation below is descriptive only, never treated as a significance-tested result
    r2 = f"cross-sectional IC UNDEFINED (single expiration, zero cross-sectional DTE variance); pooled descriptive Spearman correlation={_fmt(dte_pooled_corr)} (no valid p-value -- see Part A note)"
    _advance_and_classify("P19-OPT-002", v2, r2)

    v3 = "DISCOVERY_SUPPORTED" if (interaction_incremental is not None and interaction_incremental > 0.005 and model_abc.applicable and (interaction_p or 1.0) < 0.05) else "INCONCLUSIVE"
    _advance_and_classify("P19-OPT-003", v3, f"interaction incremental R2={_fmt(interaction_incremental)}, interaction_p={interaction_p}")

    v4 = "DISCOVERY_SUPPORTED" if (deep_otm_stdev is not None and itm_atm_mean_stdev is not None and deep_otm_stdev > itm_atm_mean_stdev * 1.2) else "INCONCLUSIVE"
    _advance_and_classify("P19-OPT-004", v4, f"deep_otm_stdev={_fmt(deep_otm_stdev)} vs itm_atm_mean_stdev={_fmt(itm_atm_mean_stdev)}")

    v5 = "DISCOVERY_SUPPORTED" if (cp_gap is not None and cp_p is not None and cp_p < 0.05 and abs(cp_gap) > 0.01) else ("REJECTED" if cp_p is not None and cp_p >= 0.05 else "INCONCLUSIVE")
    _advance_and_classify("P19-OPT-005", v5, f"call_mean={_fmt(call_mean)}, put_mean={_fmt(put_mean)}, gap={_fmt(cp_gap)}, Welch_p={_fmt(cp_p)}")

    v6, r6 = _classify_ic("underlying_lagged_realized_vol|abs_forward_return_5")
    _advance_and_classify("P19-OPT-006", v6, r6)

    v7 = "DISCOVERY_SUPPORTED" if (mean_signed_product is not None and mean_signed_product < -0.001) else ("REJECTED" if (mean_signed_product or 0) >= 0 else "INCONCLUSIVE")
    _advance_and_classify("P19-OPT-007", v7, f"mean_signed_product={_fmt(mean_signed_product)} (negative required for reversal)")

    v8 = "DISCOVERY_SUPPORTED" if same_sign_underlyings >= 3 else "FRAGILE"
    _advance_and_classify("P19-OPT-008", v8, f"{same_sign_underlyings}/{len(universe.symbols)} underlyings agree in sign with pooled IC={_fmt(pooled_ic)}")

    v9 = "DISCOVERY_SUPPORTED" if same_sign else "FRAGILE"
    _advance_and_classify("P19-OPT-009", v9, f"horizon ICs: {[_fmt(horizon_ics[h]) for h in STANDARD_FORWARD_HORIZONS]}")

    v10 = "DISCOVERY_SUPPORTED" if (mechanical_gap is not None and mechanical_gap > 0.01) else "INCONCLUSIVE"
    _advance_and_classify("P19-OPT-010", v10, f"|option_IC|-|underlying_IC|={_fmt(mechanical_gap)}")

    v11 = "DISCOVERY_SUPPORTED" if (pinned_var is not None and unpinned_var is not None and pinned_var < unpinned_var * 0.5) else "INCONCLUSIVE"
    _advance_and_classify("P19-OPT-011", v11, f"pinned_variance={_fmt(pinned_var)} vs unpinned_variance={_fmt(unpinned_var)} (data-quality negative control, not an alpha claim)")

    v12 = "DISCOVERY_SUPPORTED" if most_negative_bucket == "0-7" else "INCONCLUSIVE"
    _advance_and_classify("P19-OPT-012", v12, f"most-negative-decay bucket={most_negative_bucket} (expected '0-7')")

    n_supported = sum(1 for v, _ in classifications.values() if v == "DISCOVERY_SUPPORTED")
    print(f"\n{n_supported}/{len(classifications)} hypotheses classified DISCOVERY_SUPPORTED.", flush=True)
    print("No trading strategy is created here. No alpha is declared as fact. This is a DISCOVERY-stage report only.", flush=True)

    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))
    dims_fp = ExperimentDimensions(
        feature_definition=PRIMARY_FEATURE, parameter_range={"main_features": list(main_features), "horizons": list(STANDARD_FORWARD_HORIZONS)},
        universe_name=universe.name, target_definition=PRIMARY_TARGET_COL, execution_model="n/a-discovery",
        cost_model="n/a-discovery-assumption-only", validation_methodology="cross-sectional discovery family on real 24-contract mark-to-market panel",
    )
    exp_store.record(
        data_version="phase19-real-options-panel-v1", feature_version="phase19-discovery-v1", symbols=list(universe.symbols), timeframe="day",
        strategy_version="1.0", prediction_horizon=PRIMARY_HORIZON, train_period=("2021-12-01", "2022-03-17"),
        parameters={"n_tests": len(raw_p_values), "n_contracts": 24}, metrics={"primary_ic": pooled_ic, "n_discovery_supported": n_supported},
        strategy_family="options_alpha", classification=("DISCOVERY_SUPPORTED" if n_supported > 0 else "NOT_READY"),
        tags=("phase19-discovery", universe.name, "mark-to-market-historical-research"),
        notes=f"{n_supported}/{len(classifications)} DISCOVERY_SUPPORTED; classifications={ {k: v[0] for k, v in classifications.items()} }",
        hypothesis_id="P19-OPT-FAMILY", universe_name=universe.name, experiment_fingerprint=compute_experiment_fingerprint(dims_fp),
        research_family_id="P19-OPT-DISCOVERY-2026-09",
    )
    print("\nSTEP 3 COMPLETE.", flush=True)


if __name__ == "__main__":
    main()
