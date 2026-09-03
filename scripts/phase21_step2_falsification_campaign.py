#!/usr/bin/env python3
"""Phase 21, STEP 2 — Parts 5-23: the adversarial falsification
campaign. Tests the 2 Phase 20 survivors (P19-OPT-009-EXPANDED,
P19-OPT-005-EXPANDED) plus the mechanical-baseline negative control,
using ONLY the existing Phase 19/20 discovery data. Every original
P19-OPT-* definition (frozen, verified by step 1) is read but never
modified. MARK-TO-MARKET HISTORICAL RESEARCH only. No strategy is
created, no order is placed, no VALIDATION/FINAL_HOLDOUT data is
touched.

Assumes the goal stated in Part 1: this is NOT a hunt for another
positive result. Every check below is run and reported even when it
weakens or kills a candidate.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.store import HistoricalDataStore  # noqa: E402
from src.options.cost_model import CostAssumption, apply_cost_assumption  # noqa: E402
from src.options.dependence_bootstrap import SymbolClusterBootstrapReport, symbol_cluster_bootstrap_ic  # noqa: E402
from src.options.mechanical_baseline import compare_option_vs_underlying_signal  # noqa: E402
from src.options.outlier_treatment import compute_outlier_attribution, top_observations, winsorize  # noqa: E402
from src.options.placebo_extensions import (  # noqa: E402
    block_preserving_shuffle_gap_placebo,
    block_preserving_shuffle_placebo,
    random_group_gap_control,
    shifted_group_gap_placebo,
    sign_flipped_target_diagnostic,
    sign_flipped_target_gap_diagnostic,
    shuffled_group_gap_placebo,
    symbol_identity_shuffle_gap_placebo,
    symbol_identity_shuffle_placebo,
    time_shuffled_target_gap_placebo,
    within_symbol_time_shuffle_gap_placebo,
    within_symbol_time_shuffle_placebo,
)
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
from src.research.return_series_bootstrap import block_bootstrap_return_series, stationary_bootstrap_return_series  # noqa: E402
from src.research.stats_utils import t_test_p_value, two_tailed_p_value_from_z  # noqa: E402

RESEARCH_PANEL = Path("logs/research_data/phase20_research_panel.jsonl")
TARGET_COL = "forward_return_5"
CANDIDATES = {
    "P19-OPT-009-EXPANDED": {"parent": "P19-OPT-009", "feature": "log_moneyness", "metric": "ic"},
    "P19-OPT-005-EXPANDED": {"parent": "P19-OPT-005", "feature": "call_put", "metric": "gap"},
}
FIVE_X_ASSUMPTION = CostAssumption("5x ASSUMPTION (extreme/illiquid stress case)", spread_pct_of_mid=0.18, slippage_pct=0.07, commission_per_contract=0.65, rationale="ASSUMPTION: Part 17's mandated 5x stress case -- not calibrated to any observed spread (none exist historically)")


def _fmt(x) -> str:
    return "None" if x is None else f"{x:.5f}"


def _welch_p_value(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2 or len(b) < 2:
        return None
    mean_a, mean_b = _mean(a), _mean(b)
    se = ((_stdev(a) ** 2) / len(a) + (_stdev(b) ** 2) / len(b)) ** 0.5
    if se == 0:
        return None
    return two_tailed_p_value_from_z((mean_a - mean_b) / se)


def pooled_ic(rows: list[dict], feature_col: str, target_col: str = TARGET_COL) -> float | None:
    points = compute_ic_series(rows, feature_col, target_col, min_universe_size=3)
    return summarize_ic(points, feature_name=feature_col, target_name=target_col).average_ic


def call_put_gap(rows: list[dict], target_col: str = TARGET_COL) -> tuple[float | None, float | None, float | None, float | None]:
    calls = [r[target_col] for r in rows if r.get("call_put") == "call" and r.get(target_col) is not None]
    puts = [r[target_col] for r in rows if r.get("call_put") == "put" and r.get(target_col) is not None]
    if not calls or not puts:
        return None, None, None, None
    call_mean, put_mean = _mean(calls), _mean(puts)
    return call_mean, put_mean, call_mean - put_mean, _welch_p_value(calls, puts)


def effect(candidate: str, rows: list[dict]) -> float | None:
    cfg = CANDIDATES[candidate]
    if cfg["metric"] == "ic":
        return pooled_ic(rows, cfg["feature"])
    return call_put_gap(rows)[2]


def effect_p_value(candidate: str, rows: list[dict]) -> float | None:
    cfg = CANDIDATES[candidate]
    if cfg["metric"] == "ic":
        points = compute_ic_series(rows, cfg["feature"], TARGET_COL, min_universe_size=3)
        return t_test_p_value([p.ic for p in points if p.ic is not None])
    return call_put_gap(rows)[3]


def load_panel() -> list[dict]:
    rows = [json.loads(line) for line in RESEARCH_PANEL.read_text().splitlines() if line.strip()]
    for r in rows:
        r["timestamp"] = date.fromisoformat(r["timestamp"])
        r["symbol"] = r["option_id"]
    return rows


def main() -> None:
    universe = phase20_verified_underlying_universe()
    prereg_store = PreregistrationStore(Path("logs/research_data/phase20_preregistrations.jsonl"))
    for cand_id in CANDIDATES:
        require_preregistered(prereg_store, cand_id)

    panel = load_panel()
    print(f"Loaded panel: {len(panel)} rows, {len({r['option_id'] for r in panel})} contracts, "
          f"{len({r['underlying_symbol'] for r in panel})} underlyings. MARK_TO_MARKET_HISTORICAL_RESEARCH only.\n", flush=True)

    raw_p_values: dict[str, list[tuple[str, float]]] = {c: [] for c in CANDIDATES}
    results: dict[str, dict] = {c: {} for c in CANDIDATES}

    for cand_id, cfg in CANDIDATES.items():
        print(f"\n{'#' * 100}\nCANDIDATE: {cand_id} (parent={cfg['parent']}, feature={cfg['feature']}, metric={cfg['metric']})\n{'#' * 100}", flush=True)
        pooled_effect = effect(cand_id, panel)
        pooled_p = effect_p_value(cand_id, panel)
        print(f"  POOLED effect on full panel: {_fmt(pooled_effect)}  p={_fmt(pooled_p)}", flush=True)
        results[cand_id]["pooled_effect"] = pooled_effect
        if pooled_p is not None:
            raw_p_values[cand_id].append((f"{cand_id}|pooled", pooled_p))

        # ============================================================== PART 5: TEMPORAL FALSIFICATION
        print(f"\n{'=' * 90}\nPART 5 — TEMPORAL FALSIFICATION\n{'=' * 90}", flush=True)
        years = sorted({r["timestamp"].year for r in panel})
        year_effects = {}
        for year in years:
            year_rows = [r for r in panel if r["timestamp"].year == year]
            e = effect(cand_id, year_rows)
            p = effect_p_value(cand_id, year_rows)
            year_effects[year] = e
            print(f"    {year}: effect={_fmt(e)}  p={_fmt(p)}  n={len(year_rows)}", flush=True)
            if p is not None:
                raw_p_values[cand_id].append((f"{cand_id}|year={year}", p))
        quarters = sorted({(r["timestamp"].year, (r["timestamp"].month - 1) // 3 + 1) for r in panel})
        print("    By quarter:", flush=True)
        quarter_effects = {}
        for y, q in quarters:
            q_rows = [r for r in panel if r["timestamp"].year == y and (r["timestamp"].month - 1) // 3 + 1 == q]
            if len(q_rows) < 30:
                print(f"      {y}Q{q}: INSUFFICIENT_SAMPLE (n={len(q_rows)})", flush=True)
                continue
            e = effect(cand_id, q_rows)
            quarter_effects[(y, q)] = e
            print(f"      {y}Q{q}: effect={_fmt(e)}  n={len(q_rows)}", flush=True)

        equity_store = HistoricalDataStore(Path("logs/research_data"))
        regime_by_symbol_date: dict[str, dict[date, str]] = {}
        for sym in universe.symbols:
            bars = equity_store.load(sym, "day")
            labels = label_bars_by_regime(bars)
            regime_by_symbol_date[sym] = {ts.date(): label for ts, label in labels.items()}
        regime_buckets: dict[str, list[dict]] = defaultdict(list)
        for r in panel:
            label = regime_by_symbol_date.get(r["underlying_symbol"], {}).get(r["timestamp"], "unknown")
            regime_buckets[label].append(r)
        print("    By regime:", flush=True)
        for label in sorted(regime_buckets):
            rows = regime_buckets[label]
            if len(rows) < 30:
                continue
            e = effect(cand_id, rows)
            print(f"      {label:16s}: effect={_fmt(e)}  n={len(rows)}", flush=True)

        rolling_effects = []
        sorted_dates = sorted({r["timestamp"] for r in panel})
        window_days = 60
        for i in range(0, len(sorted_dates), 20):
            start_d = sorted_dates[i]
            end_d = start_d + __import__("datetime").timedelta(days=window_days)
            window_rows = [r for r in panel if start_d <= r["timestamp"] <= end_d]
            if len(window_rows) < 30:
                continue
            e = effect(cand_id, window_rows)
            if e is not None:
                rolling_effects.append(e)
        year_vals = [v for v in year_effects.values() if v is not None]
        signs = [1 if v > 0 else (-1 if v < 0 else 0) for v in year_vals]
        sign_consistency = (max(signs.count(1), signs.count(-1)) / len(signs)) if signs else None
        print(f"\n    SUMMARY: sign_consistency(years)={_fmt(sign_consistency)}  "
              f"effect_dispersion(stdev of yearly effects)={_fmt(_stdev(year_vals) if len(year_vals) > 1 else None)}  "
              f"worst_year_effect={_fmt(min(year_vals) if year_vals else None)}  best_year_effect={_fmt(max(year_vals) if year_vals else None)}  "
              f"fraction_years_positive={_fmt(signs.count(1) / len(signs) if signs else None)}  "
              f"rolling_windows_computed={len(rolling_effects)}  rolling_effect_stdev={_fmt(_stdev(rolling_effects) if len(rolling_effects) > 1 else None)}", flush=True)
        results[cand_id]["sign_consistency_years"] = sign_consistency
        results[cand_id]["year_effects"] = year_effects

        # ============================================================== PART 6: SYMBOL FALSIFICATION
        print(f"\n{'=' * 90}\nPART 6 — SYMBOL FALSIFICATION (leave-one-underlying-out)\n{'=' * 90}", flush=True)
        per_symbol_effects = {}
        for sym in universe.symbols:
            sym_rows = [r for r in panel if r["underlying_symbol"] == sym]
            e = effect(cand_id, sym_rows)
            per_symbol_effects[sym] = e
        for sym in universe.symbols:
            without = [r for r in panel if r["underlying_symbol"] != sym]
            without_effect = effect(cand_id, without)
            print(f"    own={sym}: effect={_fmt(per_symbol_effects[sym])}   without_{sym}: effect={_fmt(without_effect)}", flush=True)
        sym_vals = [v for v in per_symbol_effects.values() if v is not None]
        pos_frac = sum(1 for v in sym_vals if v > 0) / len(sym_vals) if sym_vals else None
        neg_frac = sum(1 for v in sym_vals if v < 0) / len(sym_vals) if sym_vals else None
        print(f"    median_per_symbol_effect={_fmt(sorted(sym_vals)[len(sym_vals) // 2] if sym_vals else None)}  "
              f"mean_per_symbol_effect={_fmt(_mean(sym_vals) if sym_vals else None)}  "
              f"positive_symbol_fraction={_fmt(pos_frac)}  negative_symbol_fraction={_fmt(neg_frac)}", flush=True)
        single_symbol_driven = pos_frac is not None and (pos_frac >= 0.9 or neg_frac >= 0.9) is False and max(pos_frac, neg_frac or 0) < 0.6
        results[cand_id]["symbol_positive_fraction"] = pos_frac

        # ============================================================== PART 7: EXPIRATION FALSIFICATION
        print(f"\n{'=' * 90}\nPART 7 — EXPIRATION FALSIFICATION\n{'=' * 90}", flush=True)
        expirations = sorted({r["expiration"] for r in panel})
        for exp in expirations:
            exp_rows = [r for r in panel if r["expiration"] == exp]
            if len(exp_rows) < 30:
                print(f"    {exp}: INSUFFICIENT_SAMPLE (n={len(exp_rows)})", flush=True)
                continue
            e = effect(cand_id, exp_rows)
            print(f"    {exp}: effect={_fmt(e)}  n={len(exp_rows)}", flush=True)
        for exp in expirations:
            without = [r for r in panel if r["expiration"] != exp]
            e = effect(cand_id, without)
            print(f"    without {exp}: effect={_fmt(e)}", flush=True)

        # ============================================================== PART 8: MONEYNESS FALSIFICATION
        print(f"\n{'=' * 90}\nPART 8 — MONEYNESS FALSIFICATION\n{'=' * 90}", flush=True)
        buckets = ("deep_itm", "itm", "near_atm", "otm", "deep_otm")
        bucket_effects = {}
        for b in buckets:
            b_rows = [r for r in panel if r.get("moneyness_bucket") == b]
            if len(b_rows) < 30:
                print(f"    {b:10s}: INSUFFICIENT_SAMPLE (n={len(b_rows)})", flush=True)
                continue
            e = effect(cand_id, b_rows)
            bucket_effects[b] = e
            print(f"    {b:10s}: effect={_fmt(e)}  n={len(b_rows)}", flush=True)
        for b in bucket_effects:
            without = [r for r in panel if r.get("moneyness_bucket") != b]
            e = effect(cand_id, without)
            print(f"    without {b}: effect={_fmt(e)}", flush=True)
        b_vals = [v for v in bucket_effects.values() if v is not None]
        b_signs = [1 if v > 0 else -1 for v in b_vals]
        print(f"    sign_consistency(buckets)={_fmt(max(b_signs.count(1), b_signs.count(-1)) / len(b_signs) if b_signs else None)}", flush=True)

        # ============================================================== PART 9: CALL/PUT FALSIFICATION
        print(f"\n{'=' * 90}\nPART 9 — CALL/PUT FALSIFICATION\n{'=' * 90}", flush=True)
        if cfg["feature"] == "call_put":
            print("    (this candidate IS the call/put relationship -- see PART 5-8 above, which already implicitly "
                  "test it; the diagnostic below controls for underlying direction instead)", flush=True)
            call_rows = [r for r in panel if r["call_put"] == "call"]
            put_rows = [r for r in panel if r["call_put"] == "put"]
            underlying_up = [r for r in panel if (r.get("underlying_daily_return") or 0) > 0]
            underlying_down = [r for r in panel if (r.get("underlying_daily_return") or 0) < 0]
            gap_up = call_put_gap(underlying_up)[2]
            gap_down = call_put_gap(underlying_down)[2]
            print(f"    call/put gap when underlying_daily_return>0: {_fmt(gap_up)}  n={len(underlying_up)}", flush=True)
            print(f"    call/put gap when underlying_daily_return<0: {_fmt(gap_down)}  n={len(underlying_down)}", flush=True)
            print(f"    gap survives controlling for underlying direction: "
                  f"{gap_up is not None and gap_down is not None and (gap_up > 0) == (gap_down > 0) == (pooled_effect > 0 if pooled_effect else None)}", flush=True)
        else:
            call_rows = [r for r in panel if r["call_put"] == "call"]
            put_rows = [r for r in panel if r["call_put"] == "put"]
            call_effect = effect(cand_id, call_rows)
            put_effect = effect(cand_id, put_rows)
            print(f"    calls only: effect={_fmt(call_effect)}  n={len(call_rows)}", flush=True)
            print(f"    puts only:  effect={_fmt(put_effect)}  n={len(put_rows)}", flush=True)
            if call_effect is not None and put_effect is not None:
                if (call_effect > 0) == (put_effect > 0):
                    print(f"    survives in both, same sign", flush=True)
                else:
                    print(f"    SIGN REVERSES between calls and puts", flush=True)

        # ============================================================== PART 10: OUTLIER FALSIFICATION
        print(f"\n{'=' * 90}\nPART 10 — OUTLIER FALSIFICATION (mandatory)\n{'=' * 90}", flush=True)
        target_vals = [r[TARGET_COL] for r in panel if r.get(TARGET_COL) is not None]
        attribution = compute_outlier_attribution(target_vals)
        print(f"    outlier attribution on pooled {TARGET_COL} (n={len(target_vals)}): "
              f"top_1%_share={_fmt(attribution.top_1pct_share)}  top_5%_share={_fmt(attribution.top_5pct_share)}  "
              f"top_10%_share={_fmt(attribution.top_10pct_share)}", flush=True)
        top5 = top_observations(target_vals, n=5)
        top10 = top_observations(target_vals, n=10)
        print(f"    top 5 |{TARGET_COL}| observations: {[f'{o.value:.3f}' for o in top5]}", flush=True)
        print(f"    top 10 |{TARGET_COL}| observations: {[f'{o.value:.3f}' for o in top10]}", flush=True)

        def _rows_with_target_replaced(source_rows, new_targets):
            return [dict(r, **{TARGET_COL: t}) for r, t in zip(source_rows, new_targets)]

        rows_with_target = [r for r in panel if r.get(TARGET_COL) is not None]
        raw_targets = [r[TARGET_COL] for r in rows_with_target]
        full_effect = effect(cand_id, rows_with_target)
        print(f"    1. full sample: effect={_fmt(full_effect)}", flush=True)
        # Exact: keep-mask via the actual top-1%-positive/negative INDICES (not value membership, which is
        # ambiguous under duplicate values).
        top1pos_idx = {o.index for o in top_observations(raw_targets, n=max(1, len(raw_targets) // 100), by="positive")}
        top1neg_idx = {o.index for o in top_observations(raw_targets, n=max(1, len(raw_targets) // 100), by="negative")}
        rows_no_top1pos = [r for i, r in enumerate(rows_with_target) if i not in top1pos_idx]
        rows_no_top1neg = [r for i, r in enumerate(rows_with_target) if i not in top1neg_idx]
        print(f"    2. remove top 1% positive: effect={_fmt(effect(cand_id, rows_no_top1pos))}  (n={len(rows_no_top1pos)})", flush=True)
        print(f"    3. remove top 1% negative: effect={_fmt(effect(cand_id, rows_no_top1neg))}  (n={len(rows_no_top1neg)})", flush=True)

        for frac in (0.01, 0.025, 0.05):
            winsorized_targets = winsorize(raw_targets, fraction=frac)
            winsorized_rows = _rows_with_target_replaced(rows_with_target, winsorized_targets)
            w_effect = effect(cand_id, winsorized_rows)
            print(f"    winsorize {frac:.1%}: effect={_fmt(w_effect)}", flush=True)
            if frac == 0.05:
                results[cand_id]["winsorized_5pct_effect"] = w_effect

        outlier_dependent = full_effect is not None and results[cand_id].get("winsorized_5pct_effect") is not None and (
            (full_effect > 0) != (results[cand_id]["winsorized_5pct_effect"] > 0)
            or abs(results[cand_id]["winsorized_5pct_effect"]) < abs(full_effect) * 0.3
        )
        print(f"    OUTLIER_DEPENDENT: {outlier_dependent}", flush=True)
        results[cand_id]["outlier_dependent"] = outlier_dependent

        # ============================================================== PART 11: UNDERLYING CONTROL
        print(f"\n{'=' * 90}\nPART 11 — UNDERLYING CONTROL (Model A/B/C)\n{'=' * 90}", flush=True)
        if cfg["feature"] == "log_moneyness":
            baseline = compare_option_vs_underlying_signal(panel, feature_col="log_moneyness", option_target_col=TARGET_COL, underlying_target_col="underlying_forward_return_5")
            print(f"    Model A (feature -> underlying_forward_return_5): IC={_fmt(baseline.underlying_ic)}", flush=True)
            print(f"    Model B (feature -> option forward_return_5):     IC={_fmt(baseline.option_ic)}", flush=True)
            print(f"    gap={_fmt(baseline.gap)}  -> {baseline.classification}", flush=True)

            from src.research.regression import ols_regression
            y = [r.get(TARGET_COL) for r in panel]
            underlying_ret = [r.get("underlying_forward_return_5") for r in panel]
            feature_vals = [r.get("log_moneyness") for r in panel]
            model_u = ols_regression(y, {"underlying_ret": underlying_ret}, min_observations=30)
            model_uf = ols_regression(y, {"underlying_ret": underlying_ret, "feature": feature_vals}, min_observations=30)
            incremental_r2 = None
            feature_p = None
            if model_u.applicable and model_uf.applicable:
                incremental_r2 = model_uf.r_squared - model_u.r_squared
                feature_p = model_uf.coefficient_p_values.get("feature")
            print(f"    Model C: option_target ~ underlying_ret + feature -- incremental R2 from adding feature={_fmt(incremental_r2)}  "
                  f"feature_p={_fmt(feature_p)}", flush=True)
            if baseline.classification == "option_adds_information" and incremental_r2 is not None and incremental_r2 > 0.005 and (feature_p or 1.0) < 0.05:
                underlying_control_verdict = "TRUE_OPTION_SPECIFIC_INFORMATION"
            elif baseline.classification == "inherited_from_underlying" or incremental_r2 is None or incremental_r2 <= 0.005:
                underlying_control_verdict = "INHERITED_FROM_UNDERLYING"
            else:
                underlying_control_verdict = "UNCERTAIN"
            print(f"    VERDICT: {underlying_control_verdict}", flush=True)
        else:
            call_gap_up = call_put_gap([r for r in panel if (r.get("underlying_daily_return") or 0) > 0])[2]
            call_gap_down = call_put_gap([r for r in panel if (r.get("underlying_daily_return") or 0) < 0])[2]
            print(f"    call/put gap conditional on underlying direction: up_days={_fmt(call_gap_up)}  down_days={_fmt(call_gap_down)}", flush=True)
            if call_gap_up is not None and call_gap_down is not None and (call_gap_up > 0) == (call_gap_down > 0):
                underlying_control_verdict = "INHERITED_FROM_UNDERLYING"
            else:
                underlying_control_verdict = "UNCERTAIN"
            print(f"    VERDICT: {underlying_control_verdict}  (a call/put asymmetry that persists in BOTH up-days and "
                  f"down-days with the SAME sign is, by construction, consistent with mechanical option "
                  f"asymmetry/skew rather than a direction-dependent option-specific signal)", flush=True)
        results[cand_id]["underlying_control_verdict"] = underlying_control_verdict

        # ============================================================== PART 12: MECHANICAL LEVERAGE CONTROL
        print(f"\n{'=' * 90}\nPART 12 — MECHANICAL OPTION LEVERAGE CONTROL\n{'=' * 90}", flush=True)
        print("    HISTORICAL_GREEKS_UNAVAILABLE -- no delta-adjusted exposure can be computed for any historical date "
              "(Phase 18/19/20 confirmed: get_option_quotes against an expired contract returns empty; no historical "
              "Greeks exist to reconstruct from, and none are reconstructed/assumed here).", flush=True)
        dollar_returns = [(r["option_close"] - r["option_open"]) * 100 for r in panel if r.get("option_close") is not None and r.get("option_open") is not None]
        print(f"    dollar P&L per contract (open->close, same-day, n={len(dollar_returns)}): mean=${_fmt(_mean(dollar_returns) if dollar_returns else None)}  "
              f"stdev=${_fmt(_stdev(dollar_returns) if len(dollar_returns) > 1 else None)}", flush=True)
        mae_vals = [(r["option_open"] - r["option_low"]) / r["option_open"] for r in panel if r.get("option_open") and r["option_open"] > 0]
        mfe_vals = [(r["option_high"] - r["option_open"]) / r["option_open"] for r in panel if r.get("option_open") and r["option_open"] > 0]
        print(f"    same-day MAE: mean={_fmt(_mean(mae_vals) if mae_vals else None)}   same-day MFE: mean={_fmt(_mean(mfe_vals) if mfe_vals else None)}  "
              f"(intraday path proxy, NOT a multi-day trade MAE/MFE -- see src.options.return_normalization for the causal multi-bar version)", flush=True)

        # ============================================================== PART 13: PLACEBO TESTING
        # IMPORTANT: the statistic tested must MATCH the candidate's own primary metric. For the IC-metric
        # candidate that is the IC-based battery (src.research.cross_sectional_placebo, reused). For the
        # gap-metric candidate, an IC of a binary-encoded call/put feature is a DIFFERENT statistic from the
        # candidate's real pooled effect (a group-mean gap) -- so the gap-metric candidate uses the dedicated
        # `*_group_gap_*` mirror battery from src.options.placebo_extensions, which computes the actual gap
        # statistic under each of the same 7 randomizations (see that module's docstring).
        print(f"\n{'=' * 90}\nPART 13 — PLACEBO TESTING (7 types)\n{'=' * 90}", flush=True)
        feat_col = cfg["feature"] if cfg["feature"] != "call_put" else "call_put_numeric"
        if cfg["metric"] == "ic":
            shuffled = shuffled_signal_placebo(panel, feature_col=feat_col, target_col=TARGET_COL, n_trials=200, seed=4001)
            print(f"    1. cross-sectional feature shuffle: observed={_fmt(shuffled.observed_statistic)}  p={shuffled.empirical_p_value}", flush=True)
            time_shuf = within_symbol_time_shuffle_placebo(panel, feature_col=feat_col, target_col=TARGET_COL, n_trials=200, seed=4002)
            print(f"    2. time shuffle (within-symbol): observed={_fmt(time_shuf.observed_statistic)}  p={time_shuf.empirical_p_value}", flush=True)
            sym_shuf = symbol_identity_shuffle_placebo(panel, feature_col=feat_col, target_col=TARGET_COL, n_trials=200, seed=4003)
            print(f"    3. symbol shuffle: observed={_fmt(sym_shuf.observed_statistic)}  p={sym_shuf.empirical_p_value}", flush=True)
            random_sig = random_feature_control(panel, target_col=TARGET_COL, n_trials=100, seed=4004, min_universe_size=3)
            random_sig_mean = _mean(random_sig.placebo_distribution) if random_sig.placebo_distribution else None
            print(f"    4. randomized signal: mean_placebo_IC={_fmt(random_sig_mean)}", flush=True)
            rand_target = time_shuffled_target_placebo(panel, feature_col=feat_col, target_col=TARGET_COL, n_trials=200, seed=4005)
            print(f"    5. randomized target: observed={_fmt(rand_target.observed_statistic)}  p={rand_target.empirical_p_value}", flush=True)
            block_shuf = block_preserving_shuffle_placebo(panel, feature_col=feat_col, target_col=TARGET_COL, block_size=5, n_trials=200, seed=4006)
            print(f"    6. block-preserving shuffle: observed={_fmt(block_shuf.observed_statistic)}  p={block_shuf.empirical_p_value}", flush=True)
            sign_flip = sign_flipped_target_diagnostic(panel, feature_col=feat_col, target_col=TARGET_COL)
            print(f"    7. sign-flipped target (diagnostic): observed={_fmt(sign_flip.observed_statistic)}  "
                  f"flipped={_fmt(sign_flip.placebo_distribution[0] if sign_flip.placebo_distribution else None)}  "
                  f"(sanity check: should equal -observed exactly)", flush=True)
        else:
            shuffled = shuffled_group_gap_placebo(panel, target_col=TARGET_COL, n_trials=200, seed=4001)
            print(f"    1. cross-sectional call/put-label shuffle: observed={_fmt(shuffled.observed_statistic)}  p={shuffled.empirical_p_value}", flush=True)
            time_shuf = within_symbol_time_shuffle_gap_placebo(panel, target_col=TARGET_COL, n_trials=200, seed=4002)
            print(f"    2. time shuffle (within-underlying): observed={_fmt(time_shuf.observed_statistic)}  p={time_shuf.empirical_p_value}", flush=True)
            sym_shuf = symbol_identity_shuffle_gap_placebo(panel, target_col=TARGET_COL, n_trials=200, seed=4003)
            print(f"    3. symbol shuffle: observed={_fmt(sym_shuf.observed_statistic)}  p={sym_shuf.empirical_p_value}", flush=True)
            random_sig = random_group_gap_control(panel, target_col=TARGET_COL, n_trials=100, seed=4004)
            random_sig_mean = _mean(random_sig.placebo_distribution) if random_sig.placebo_distribution else None
            print(f"    4. randomized signal (random group label): mean_placebo_gap={_fmt(random_sig_mean)}", flush=True)
            rand_target = time_shuffled_target_gap_placebo(panel, target_col=TARGET_COL, n_trials=200, seed=4005)
            print(f"    5. randomized target: observed={_fmt(rand_target.observed_statistic)}  p={rand_target.empirical_p_value}", flush=True)
            block_shuf = block_preserving_shuffle_gap_placebo(panel, target_col=TARGET_COL, block_size=5, n_trials=200, seed=4006)
            print(f"    6. block-preserving shuffle: observed={_fmt(block_shuf.observed_statistic)}  p={block_shuf.empirical_p_value}", flush=True)
            sign_flip = sign_flipped_target_gap_diagnostic(panel, target_col=TARGET_COL)
            print(f"    7. sign-flipped target (diagnostic): observed={_fmt(sign_flip.observed_statistic)}  "
                  f"flipped={_fmt(sign_flip.placebo_distribution[0] if sign_flip.placebo_distribution else None)}  "
                  f"(sanity check: should equal -observed exactly)", flush=True)
        placebo_ps = [p.empirical_p_value for p in (shuffled, time_shuf, sym_shuf, rand_target, block_shuf) if p.empirical_p_value is not None]
        for name, p in (("shuffle", shuffled.empirical_p_value), ("time_shuffle", time_shuf.empirical_p_value), ("symbol_shuffle", sym_shuf.empirical_p_value), ("random_target", rand_target.empirical_p_value), ("block_shuffle", block_shuf.empirical_p_value)):
            if p is not None:
                raw_p_values[cand_id].append((f"{cand_id}|placebo_{name}", p))
        clearly_distinguishable = all(p is not None and p < 0.10 for p in placebo_ps) if placebo_ps else False
        print(f"    clearly distinguishable from ALL placebo distributions (p<0.10 each): {clearly_distinguishable}", flush=True)
        results[cand_id]["placebo_clearly_distinguishable"] = clearly_distinguishable

        # ============================================================== PART 14: TEMPORAL SHIFT TEST
        print(f"\n{'=' * 90}\nPART 14 — TEMPORAL SHIFT TEST\n{'=' * 90}", flush=True)
        shift_results = {}
        for shift in (1, 2, 5, 10):
            if cfg["metric"] == "ic":
                shifted = shifted_signal_placebo(panel, feature_col=feat_col, target_col=TARGET_COL, shift_bars=shift)
            else:
                shifted = shifted_group_gap_placebo(panel, target_col=TARGET_COL, shift_bars=shift)
            shifted_val = shifted.placebo_distribution[0] if shifted.placebo_distribution else None
            shift_results[shift] = shifted_val
            flag = shifted_val is not None and pooled_effect is not None and abs(shifted_val) >= abs(pooled_effect)
            print(f"    shift=+{shift}: true={_fmt(pooled_effect)}  shifted={_fmt(shifted_val)}  {'<-- shifted >= true (investigate)' if flag else ''}", flush=True)
        results[cand_id]["shift_results"] = shift_results

        # ============================================================== PART 15: DEPENDENCE-AWARE BOOTSTRAP
        print(f"\n{'=' * 90}\nPART 15/21 — DEPENDENCE-AWARE BOOTSTRAP\n{'=' * 90}", flush=True)
        if cfg["metric"] == "ic":
            points = compute_ic_series(panel, feat_col, TARGET_COL, min_universe_size=3)
            ic_series = [p.ic for p in points if p.ic is not None]
            for conf in (0.90, 0.95):
                block_report = block_bootstrap_return_series(ic_series, block_size=5, n_resamples=2000, seed=5001, confidence_level=conf)
                stationary_report = stationary_bootstrap_return_series(ic_series, mean_block_length=5.0, n_resamples=2000, seed=5002, confidence_level=conf)
                print(f"    time-block bootstrap ({conf:.0%} CI): {block_report.render()}", flush=True)
                print(f"    stationary bootstrap ({conf:.0%} CI): {stationary_report.render()}", flush=True)
        symcluster: SymbolClusterBootstrapReport | None = None
        if cfg["metric"] == "ic":
            for conf in (0.90, 0.95):
                symcluster = symbol_cluster_bootstrap_ic(panel, feature_col=feat_col, target_col=TARGET_COL, n_resamples=1000, seed=5003, confidence_level=conf)
                print(f"    {symcluster.render()}", flush=True)
                results[cand_id][f"symbol_cluster_ci_{int(conf*100)}"] = (symcluster.lower_bound, symcluster.upper_bound)
        else:
            print("    (mean-gap metric -- symbol-cluster bootstrap applied to the call/put gap directly below)", flush=True)
            import random as _random
            by_symbol_rows: dict[str, list[dict]] = defaultdict(list)
            for r in panel:
                by_symbol_rows[r["underlying_symbol"]].append(r)
            syms = list(by_symbol_rows.keys())
            gap_resamples = []
            rng = _random.Random(5004)
            for _ in range(1000):
                chosen = [rng.choice(syms) for _ in syms]
                resample_rows = [row for s in chosen for row in by_symbol_rows[s]]
                g = call_put_gap(resample_rows)[2]
                if g is not None:
                    gap_resamples.append(g)
            if gap_resamples:
                ordered = sorted(gap_resamples)
                for conf in (0.90, 0.95):
                    alpha = 1 - conf
                    lo = ordered[int(len(ordered) * (alpha / 2))]
                    hi = ordered[min(len(ordered) - 1, int(len(ordered) * (1 - alpha / 2)))]
                    print(f"    symbol-cluster bootstrap of call/put gap ({conf:.0%} CI): point={_fmt(pooled_effect)}  [{_fmt(lo)}, {_fmt(hi)}]  (n_symbols={len(syms)})", flush=True)
                    results[cand_id][f"symbol_cluster_ci_{int(conf*100)}"] = (lo, hi)

        # ============================================================== PART 16: EFFECT SIZE
        print(f"\n{'=' * 90}\nPART 16 — EFFECT SIZE OVER P-VALUE\n{'=' * 90}", flush=True)
        print(f"    pooled effect={_fmt(pooled_effect)}  pooled_p={_fmt(pooled_p)}  n_rows={len(panel)}  n_symbols={len(universe.symbols)}", flush=True)
        print(f"    economic magnitude context: mean option premium in panel=${_fmt(_mean([r['option_close'] for r in panel]))}", flush=True)

        # ============================================================== PART 17: COST SENSITIVITY
        print(f"\n{'=' * 90}\nPART 17 — COST SENSITIVITY (1x/2x/3x/5x ASSUMPTION-labeled)\n{'=' * 90}", flush=True)
        from src.options.cost_model import COST_SENSITIVITY_ASSUMPTIONS
        mean_entry = _mean([r["option_close"] for r in panel])
        gross = pooled_effect if pooled_effect is not None else 0.0
        cost_survives = []
        for assumption in list(COST_SENSITIVITY_ASSUMPTIONS) + [FIVE_X_ASSUMPTION]:
            net = apply_cost_assumption(abs(gross), mean_entry, assumption) if mean_entry > 0 else None
            survives = net is not None and net > 0
            cost_survives.append(survives)
            print(f"    {assumption.label}: net_effect_magnitude={_fmt(net)}  survives={survives}", flush=True)
        cost_fragile = not cost_survives[0]  # fails even the gentlest 1x assumption
        print(f"    COST_FRAGILE: {cost_fragile}", flush=True)
        results[cand_id]["cost_fragile"] = cost_fragile

        # ============================================================== PART 18: ECONOMIC SIGNIFICANCE
        print(f"\n{'=' * 90}\nPART 18 — ECONOMIC SIGNIFICANCE (for a ~$1,000 account, aspirational only)\n{'=' * 90}", flush=True)
        contracts_affordable = int(1000 / (mean_entry * 100)) if mean_entry > 0 else 0
        print(f"    mean option premium=${_fmt(mean_entry)}/share (${_fmt(mean_entry*100)}/contract) -> "
              f"~{contracts_affordable} contract(s) affordable on a $1,000 account (before any position-sizing discipline)", flush=True)
        print(f"    NOTE: this is a feasibility check, not a target -- Part 18 explicitly forbids forcing the research "
              f"toward a $20-50/day figure.", flush=True)

        # ============================================================== PART 20: PBO / DSR
        print(f"\n{'=' * 90}\nPART 20 — PBO / DSR\n{'=' * 90}", flush=True)
        if cfg["metric"] == "ic" and len(ic_series) >= 8:
            n_periods = 6
            all_days = sorted({r["timestamp"] for r in panel})
            day_start, day_end = all_days[0], all_days[-1]
            total_days = (day_end - day_start).days + 1
            variants = [feat_col, "underlying_lagged_realized_vol", "dte", "moneyness_ratio"]
            period_matrix = []
            for v in variants:
                v_points = compute_ic_series(panel, v, TARGET_COL, min_universe_size=3)
                buckets: list[list[float]] = [[] for _ in range(n_periods)]
                for p in v_points:
                    if p.ic is None:
                        continue
                    offset = (p.timestamp - day_start).days
                    bucket = min(n_periods - 1, max(0, (offset * n_periods) // total_days))
                    buckets[bucket].append(p.ic)
                period_matrix.append([sum(b) / len(b) if b else 0.0 for b in buckets])
            pbo = probability_of_backtest_overfitting(period_matrix)
            print(f"    {pbo.render()}", flush=True)
            dsr = deflated_sharpe_ratio(ic_series, n_trials=len(variants))
            print(f"    DSR: {dsr.render()}", flush=True)
        else:
            print("    PBO/DSR require a per-timestamp IC series with enough independent periods -- not computed for "
                  "the call/put mean-gap metric (it is not a per-timestamp IC series); see Part 20's own instruction "
                  "not to force these metrics when their assumptions are invalid.", flush=True)

    # ============================================================== PART 19: MULTIPLE TESTING (whole Phase 21 family)
    print(f"\n{'#' * 100}\nPART 19 — MULTIPLE-TESTING CORRECTION (complete Phase 21 family)\n{'#' * 100}", flush=True)
    all_p_values = [p for cand_ps in raw_p_values.values() for p in cand_ps]
    print(f"  total raw p-values across both candidates: {len(all_p_values)}", flush=True)
    for method in (bonferroni_correction, holm_bonferroni_correction, benjamini_hochberg_fdr):
        report = method(all_p_values, alpha=0.05)
        print(f"  {report.method}: n_significant={report.n_significant}/{report.n_tests}", flush=True)

    # ============================================================== PART 22/23: ROBUSTNESS SCORECARD + FINAL CLASSIFICATION
    print(f"\n{'#' * 100}\nPART 22/23 — ROBUSTNESS SCORECARD & FINAL CLASSIFICATION\n{'#' * 100}", flush=True)
    gate_store = DiscoveryDevelopmentGateStore(Path("logs/research_data/phase21_gate_transitions.jsonl"))
    final_classifications = {}
    for cand_id, r in results.items():
        scorecard = {
            "statistical_significance": r.get("pooled_effect") is not None,
            "temporal_stability": (r.get("sign_consistency_years") or 0) >= 0.67,
            "symbol_stability": (r.get("symbol_positive_fraction") or 0) >= 0.6 or (r.get("symbol_positive_fraction") or 1) <= 0.4,
            "outlier_stability": not r.get("outlier_dependent", True),
            "placebo_separation": r.get("placebo_clearly_distinguishable", False),
            "underlying_control": r.get("underlying_control_verdict") == "TRUE_OPTION_SPECIFIC_INFORMATION",
            "cost_sensitivity": not r.get("cost_fragile", True),
        }
        print(f"\n  {cand_id} scorecard:", flush=True)
        for dim, passed in scorecard.items():
            print(f"    {dim}: {'PASS' if passed else 'FAIL'}", flush=True)
        n_pass = sum(scorecard.values())

        if r.get("underlying_control_verdict") == "INHERITED_FROM_UNDERLYING":
            final = "INHERITED_FROM_UNDERLYING"
        elif r.get("cost_fragile") or r.get("outlier_dependent"):
            final = "FRAGILE"
        elif not r.get("placebo_clearly_distinguishable"):
            final = "INCONCLUSIVE"
        elif n_pass >= 6:
            final = "ROBUST_DISCOVERY_CANDIDATE"
        elif n_pass >= 4:
            final = "FRAGILE"
        else:
            final = "REJECTED"
        final_classifications[cand_id] = final
        print(f"  {cand_id}: {n_pass}/7 scorecard dimensions passed -> FINAL CLASSIFICATION: {final}", flush=True)

        gate_store.transition(hypothesis_id=cand_id, to_stage=DiscoveryDevelopmentStage.IDEA, reason="Phase 21 falsification", evidence_summary="")
        gate_store.transition(hypothesis_id=cand_id, to_stage=DiscoveryDevelopmentStage.PREREGISTERED, reason="already preregistered in Phase 20", evidence_summary="")
        gate_store.transition(hypothesis_id=cand_id, to_stage=DiscoveryDevelopmentStage.DISCOVERY_TESTED, reason="Phase 21 falsification family completed", evidence_summary=final)
        if final == "ROBUST_DISCOVERY_CANDIDATE":
            gate_store.transition(hypothesis_id=cand_id, to_stage=DiscoveryDevelopmentStage.DISCOVERY_SUPPORTED, reason=final, evidence_summary=final)
        else:
            gate_store.transition(hypothesis_id=cand_id, to_stage=DiscoveryDevelopmentStage.NOT_READY, reason=f"classified {final}", evidence_summary=final)

    n_robust = sum(1 for v in final_classifications.values() if v == "ROBUST_DISCOVERY_CANDIDATE")
    print(f"\n{n_robust}/{len(final_classifications)} candidates classified ROBUST_DISCOVERY_CANDIDATE "
          f"(NOTE: this does NOT mean validated -- see Part 23's explicit definition).", flush=True)
    print("No strategy is created. No order is placed. No parameter was tuned to improve these results.", flush=True)

    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))
    dims_fp = ExperimentDimensions(
        feature_definition="log_moneyness+call_put", parameter_range={"candidates": list(CANDIDATES.keys())},
        universe_name=universe.name, target_definition=TARGET_COL, execution_model="n/a-falsification-only",
        cost_model="assumption-only-1x-2x-3x-5x", validation_methodology="Phase 21 adversarial falsification battery",
    )
    exp_store.record(
        data_version="phase20-expanded-options-panel-v1", feature_version="phase21-falsification-v1", symbols=list(universe.symbols), timeframe="day",
        strategy_version="1.0", prediction_horizon=5, train_period=("2021-12-01", "2023-06-15"),
        parameters={"n_candidates": len(CANDIDATES), "n_p_values": len(all_p_values)}, metrics={"n_robust_discovery_candidate": n_robust},
        strategy_family="options_alpha_falsification", classification=("ROBUST_DISCOVERY_CANDIDATE" if n_robust > 0 else "NOT_ROBUST"),
        tags=("phase21-falsification", universe.name, "mark-to-market-historical-research"),
        notes=f"final_classifications={final_classifications}",
        hypothesis_id="P21-FALSIFICATION-FAMILY", universe_name=universe.name, experiment_fingerprint=compute_experiment_fingerprint(dims_fp),
        research_family_id="P21-FALSIFICATION-2026-09",
    )
    print("\nSTEP 2 COMPLETE.", flush=True)


if __name__ == "__main__":
    main()
