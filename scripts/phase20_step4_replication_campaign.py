#!/usr/bin/env python3
"""Phase 20, STEP 4 — Parts 9-20: the replication campaign. Re-runs the
5 Phase 19 DISCOVERY_SUPPORTED hypotheses (as P19-OPT-XXX-EXPANDED) on
the expanded 120-contract, 12-underlying, 3-expiration panel. Reuses
Phase 7+'s statistical machinery end to end; nothing here reimplements
IC, bootstrap, PBO, DSR, or purged CV. MARK-TO-MARKET HISTORICAL
RESEARCH only (Part 20) -- no backtest, no trading strategy, no
live/paper order, no VALIDATION/FINAL_HOLDOUT access.

Must run AFTER step 1 (panel) and step 3 (preregistration).

Classification vocabulary (Part 23's explicit requirement): a surviving
finding is EXPANDED_DISCOVERY_SUPPORTED -- NEVER "VALIDATED". This
phase does not promote anything to trading-ready status.
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.store import HistoricalDataStore  # noqa: E402
from src.options.cost_model import COST_SENSITIVITY_ASSUMPTIONS, apply_cost_assumption  # noqa: E402
from src.options.mechanical_baseline import compare_option_vs_underlying_signal  # noqa: E402
from src.options.price_history import STANDARD_FORWARD_HORIZONS  # noqa: E402
from src.options.universe import phase20_verified_underlying_universe  # noqa: E402
from src.research import (  # noqa: E402
    DiscoveryDevelopmentGateStore,
    DiscoveryDevelopmentStage,
    ExperimentStore,
    benjamini_hochberg_fdr,
    block_bootstrap_return_series,
    bonferroni_correction,
    compute_ic_series,
    holm_bonferroni_correction,
    label_bars_by_regime,
    require_preregistered,
    shuffled_signal_placebo,
    stationary_bootstrap_return_series,
    summarize_ic,
    time_shuffled_target_placebo,
)
from src.research.analysis import stdev as _stdev  # noqa: E402
from src.research.experiment_fingerprint import ExperimentDimensions, compute_experiment_fingerprint  # noqa: E402
from src.research.preregistration import PreregistrationStore  # noqa: E402
from src.research.stats_utils import t_test_p_value  # noqa: E402

RESEARCH_PANEL = Path("logs/research_data/phase20_research_panel.jsonl")
PRIMARY_TARGET_COL = "forward_return_5"
PRIMARY_FEATURE = "log_moneyness"
EXPERIMENT_FAMILY_ID = "P20-REPL-2026-09"


def _fmt(x) -> str:
    return "None" if x is None else f"{x:.5f}"


def _welch_p_value(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2 or len(b) < 2:
        return None
    from src.research.analysis import mean as _mean
    from src.research.stats_utils import two_tailed_p_value_from_z

    mean_a, mean_b = _mean(a), _mean(b)
    se = ((_stdev(a) ** 2) / len(a) + (_stdev(b) ** 2) / len(b)) ** 0.5
    if se == 0:
        return None
    return two_tailed_p_value_from_z((mean_a - mean_b) / se)


def load_panel() -> list[dict]:
    rows = [json.loads(line) for line in RESEARCH_PANEL.read_text().splitlines() if line.strip()]
    for r in rows:
        r["timestamp"] = date.fromisoformat(r["timestamp"])
        r["symbol"] = r["option_id"]
    return rows


def main() -> None:
    universe = phase20_verified_underlying_universe()
    sector_by_symbol = {m.symbol: m.sector for m in universe.members}

    prereg_store = PreregistrationStore(Path("logs/research_data/phase20_preregistrations.jsonl"))
    expanded_ids = ("P19-OPT-004-EXPANDED", "P19-OPT-005-EXPANDED", "P19-OPT-008-EXPANDED", "P19-OPT-009-EXPANDED", "P19-OPT-012-EXPANDED")
    for hid in expanded_ids:
        require_preregistered(prereg_store, hid)

    panel = load_panel()
    print(f"Loaded expanded panel: {len(panel)} rows, {len({r['option_id'] for r in panel})} contracts, "
          f"{len({r['underlying_symbol'] for r in panel})} underlyings, {len({r['expiration'] for r in panel})} expirations.\n", flush=True)

    raw_p_values: list[tuple[str, float]] = []

    # ============================================================== PRIMARY IC (needed by 008/009 EXPANDED)
    print(f"{'=' * 100}\nPRIMARY: pooled cross-sectional IC({PRIMARY_FEATURE}, {PRIMARY_TARGET_COL}) on the expanded panel\n{'=' * 100}", flush=True)
    primary_points = compute_ic_series(panel, PRIMARY_FEATURE, PRIMARY_TARGET_COL, min_universe_size=3)
    primary_summary = summarize_ic(primary_points, feature_name=PRIMARY_FEATURE, target_name=PRIMARY_TARGET_COL)
    pooled_ic = primary_summary.average_ic
    print(f"  pooled_IC={_fmt(pooled_ic)}  (Phase 19's original 4-underlying/1-expiration pooled_IC was 0.05515, FRAGILE classification)", flush=True)
    p = t_test_p_value([pt.ic for pt in primary_points if pt.ic is not None])
    if p is not None:
        raw_p_values.append((f"{PRIMARY_FEATURE}|{PRIMARY_TARGET_COL}|pooled", p))

    # ============================================================== P19-OPT-004-EXPANDED: MONEYNESS BUCKET TAIL RISK
    print(f"\n{'=' * 100}\nP19-OPT-004-EXPANDED — Deep-OTM tail-risk replication\n{'=' * 100}", flush=True)
    bucket_stats: dict[str, dict] = {}
    for bucket in ("deep_itm", "itm", "near_atm", "otm", "deep_otm"):
        vals = [r[PRIMARY_TARGET_COL] for r in panel if r.get("moneyness_bucket") == bucket and r.get(PRIMARY_TARGET_COL) is not None]
        if len(vals) < 2:
            continue
        bucket_stats[bucket] = {"n": len(vals), "mean": sum(vals) / len(vals), "stdev": _stdev(vals)}
        print(f"  {bucket:10s}: n={len(vals):5d}  mean={_fmt(bucket_stats[bucket]['mean'])}  stdev={_fmt(bucket_stats[bucket]['stdev'])}", flush=True)
    deep_otm_stdev = bucket_stats.get("deep_otm", {}).get("stdev")
    itm_atm_stdevs = [bucket_stats[b]["stdev"] for b in ("deep_itm", "itm", "near_atm") if b in bucket_stats]
    itm_atm_mean_stdev = sum(itm_atm_stdevs) / len(itm_atm_stdevs) if itm_atm_stdevs else None
    print(f"  deep_otm_stdev={_fmt(deep_otm_stdev)}  vs  ITM/ATM_mean_stdev={_fmt(itm_atm_mean_stdev)}  "
          f"(original: 0.51533 vs 0.39650)", flush=True)

    # ============================================================== P19-OPT-005-EXPANDED: CALL/PUT ASYMMETRY
    print(f"\n{'=' * 100}\nP19-OPT-005-EXPANDED — Call/put asymmetry replication\n{'=' * 100}", flush=True)
    call_rets = [r[PRIMARY_TARGET_COL] for r in panel if r.get("call_put") == "call" and r.get(PRIMARY_TARGET_COL) is not None]
    put_rets = [r[PRIMARY_TARGET_COL] for r in panel if r.get("call_put") == "put" and r.get(PRIMARY_TARGET_COL) is not None]
    call_mean = sum(call_rets) / len(call_rets) if call_rets else None
    put_mean = sum(put_rets) / len(put_rets) if put_rets else None
    cp_gap = None if call_mean is None or put_mean is None else call_mean - put_mean
    cp_p = _welch_p_value(call_rets, put_rets)
    print(f"  call: n={len(call_rets)} mean={_fmt(call_mean)}   put: n={len(put_rets)} mean={_fmt(put_mean)}   "
          f"gap={_fmt(cp_gap)}  Welch_p={_fmt(cp_p)}  (original gap: -0.27192)", flush=True)
    if cp_p is not None:
        raw_p_values.append(("call_put_asymmetry|expanded", cp_p))

    # ============================================================== P19-OPT-008-EXPANDED: PER-UNDERLYING STABILITY (12 underlyings)
    print(f"\n{'=' * 100}\nP19-OPT-008-EXPANDED — Per-underlying stability replication ({len(universe.symbols)} underlyings)\n{'=' * 100}", flush=True)
    per_underlying_ic = {}
    for sym in universe.symbols:
        sym_rows = [r for r in panel if r["underlying_symbol"] == sym]
        sym_points = compute_ic_series(sym_rows, PRIMARY_FEATURE, PRIMARY_TARGET_COL, min_universe_size=3)
        sym_ic = summarize_ic(sym_points, feature_name=PRIMARY_FEATURE, target_name=PRIMARY_TARGET_COL).average_ic
        per_underlying_ic[sym] = sym_ic
        print(f"  {sym}: IC={_fmt(sym_ic)}", flush=True)
    same_sign_underlyings = sum(1 for v in per_underlying_ic.values() if v is not None and pooled_ic is not None and (v > 0) == (pooled_ic > 0))
    print(f"  pooled_IC={_fmt(pooled_ic)}  underlyings agreeing in sign: {same_sign_underlyings}/{len(universe.symbols)}  "
          f"(original: 4/4)", flush=True)

    print("\n  Leave-one-sector-out:", flush=True)
    sectors = sorted({s for s in sector_by_symbol.values() if s})
    for sector in sectors:
        without = [r for r in panel if sector_by_symbol.get(r["underlying_symbol"]) != sector]
        without_ic = summarize_ic(compute_ic_series(without, PRIMARY_FEATURE, PRIMARY_TARGET_COL, min_universe_size=3), feature_name=PRIMARY_FEATURE, target_name=PRIMARY_TARGET_COL).average_ic
        print(f"    without sector={sector}: IC={_fmt(without_ic)}", flush=True)

    # ============================================================== P19-OPT-009-EXPANDED: HORIZON STABILITY
    print(f"\n{'=' * 100}\nP19-OPT-009-EXPANDED — Horizon stability replication\n{'=' * 100}", flush=True)
    horizon_ics = {}
    for h in STANDARD_FORWARD_HORIZONS:
        col = f"forward_return_{h}"
        points = compute_ic_series(panel, PRIMARY_FEATURE, col, min_universe_size=3)
        summary = summarize_ic(points, feature_name=PRIMARY_FEATURE, target_name=col)
        horizon_ics[h] = summary.average_ic
        print(f"  h={h:3d}: IC={_fmt(summary.average_ic)}", flush=True)
        if h != 5:
            p = t_test_p_value([pt.ic for pt in points if pt.ic is not None])
            if p is not None:
                raw_p_values.append((f"{PRIMARY_FEATURE}|forward_return_{h}|expanded", p))
    same_sign_horizons = len({1 if (v or 0) > 0 else (-1 if (v or 0) < 0 else 0) for v in horizon_ics.values() if v is not None}) <= 1
    print(f"  same-sign across all horizons: {same_sign_horizons}  (original: True)", flush=True)

    # ============================================================== P19-OPT-012-EXPANDED: DTE-BUCKET DECAY
    print(f"\n{'=' * 100}\nP19-OPT-012-EXPANDED — Expiration-proximity decay replication\n{'=' * 100}", flush=True)
    dte_bucket_means = {}
    for bucket in ("0-7", "8-30", "31-60", "61-120", "120+"):
        vals = [r["forward_return_1"] for r in panel if r.get("dte_bucket") == bucket and r.get("forward_return_1") is not None]
        if vals:
            dte_bucket_means[bucket] = sum(vals) / len(vals)
            print(f"  {bucket:8s}: n={len(vals):6d}  mean_forward_return_1={_fmt(dte_bucket_means[bucket])}", flush=True)
    most_negative_bucket = min(dte_bucket_means, key=lambda b: dte_bucket_means[b]) if dte_bucket_means else None
    print(f"  most-negative bucket: {most_negative_bucket}  (original: '0-7')", flush=True)

    # ============================================================== MULTIPLE TESTING (SEPARATE Phase 20 family)
    print(f"\n{'=' * 100}\nMULTIPLE-TESTING CORRECTION — Phase 20 replication family (n={len(raw_p_values)}, SEPARATE from Phase 19's)\n{'=' * 100}", flush=True)
    for method in (bonferroni_correction, holm_bonferroni_correction, benjamini_hochberg_fdr):
        report = method(raw_p_values, alpha=0.05)
        print(f"  {report.method}: n_significant={report.n_significant}/{report.n_tests}", flush=True)
    bh_report = benjamini_hochberg_fdr(raw_p_values, alpha=0.05)
    bh_significant_keys = {r.label for r in bh_report.results if r.significant_at_alpha}
    print(f"  Family accounting: 5 hypotheses x (variants across underlyings/horizons/moneyness-buckets tested above), "
          f"{len(universe.symbols)} underlyings, {len({r['expiration'] for r in panel})} expirations, 5 moneyness buckets, "
          f"{len(raw_p_values)} raw p-values in this family.", flush=True)

    # ============================================================== BOOTSTRAP
    print(f"\n{'=' * 100}\nBOOTSTRAP — primary IC series (block + stationary)\n{'=' * 100}", flush=True)
    ic_series = [pt.ic for pt in primary_points if pt.ic is not None]
    for conf in (0.90, 0.95):
        block_report = block_bootstrap_return_series(ic_series, block_size=5, n_resamples=2000, seed=2001, confidence_level=conf)
        print(f"  block bootstrap ({conf:.0%} CI): {block_report.render()}", flush=True)
        stationary_report = stationary_bootstrap_return_series(ic_series, mean_block_length=5.0, n_resamples=2000, seed=2002, confidence_level=conf)
        print(f"  stationary bootstrap ({conf:.0%} CI): {stationary_report.render()}", flush=True)

    # ============================================================== PLACEBO
    print(f"\n{'=' * 100}\nPLACEBO BATTERY\n{'=' * 100}", flush=True)
    shuffled = shuffled_signal_placebo(panel, feature_col=PRIMARY_FEATURE, target_col=PRIMARY_TARGET_COL, n_trials=200, seed=2003)
    print(f"  cross-sectional shuffle: observed_IC={_fmt(shuffled.observed_statistic)}  p={shuffled.empirical_p_value}", flush=True)
    time_shuffled = time_shuffled_target_placebo(panel, feature_col=PRIMARY_FEATURE, target_col=PRIMARY_TARGET_COL, n_trials=200, seed=2004)
    print(f"  time shuffle: observed_IC={_fmt(time_shuffled.observed_statistic)}  p={time_shuffled.empirical_p_value}", flush=True)

    # ============================================================== MECHANICAL BASELINE (Part 11/12)
    print(f"\n{'=' * 100}\nMECHANICAL BASELINE — option signal vs underlying-equity signal\n{'=' * 100}", flush=True)
    baseline = compare_option_vs_underlying_signal(panel, feature_col=PRIMARY_FEATURE, option_target_col=PRIMARY_TARGET_COL, underlying_target_col="underlying_forward_return_5")
    print(f"  {baseline.render()}  (original single-expiration gap was -0.04901, INHERITED_FROM_UNDERLYING)", flush=True)

    # ============================================================== TIME / REGIME STABILITY (Part 17)
    print(f"\n{'=' * 100}\nTIME AND REGIME STABILITY\n{'=' * 100}", flush=True)
    years = sorted({r["timestamp"].year for r in panel})
    for year in years:
        year_rows = [r for r in panel if r["timestamp"].year == year]
        year_ic = summarize_ic(compute_ic_series(year_rows, PRIMARY_FEATURE, PRIMARY_TARGET_COL, min_universe_size=3), feature_name=PRIMARY_FEATURE, target_name=PRIMARY_TARGET_COL).average_ic
        print(f"  {year}: IC={_fmt(year_ic)}  n_rows={len(year_rows)}", flush=True)

    equity_store = HistoricalDataStore(Path("logs/research_data"))
    regime_by_symbol_date: dict[str, dict[date, str]] = {}
    for sym in universe.symbols:
        bars = equity_store.load(sym, "day")
        labels = label_bars_by_regime(bars)
        regime_by_symbol_date[sym] = {ts.date(): label for ts, label in labels.items()}
    regime_buckets: dict[str, list[float]] = defaultdict(list)
    for r in panel:
        label = regime_by_symbol_date.get(r["underlying_symbol"], {}).get(r["timestamp"], "unknown")
        target = r.get(PRIMARY_TARGET_COL)
        if target is not None:
            regime_buckets[label].append(target)
    print("\n  By market regime (causal per-underlying trend/volatility label):", flush=True)
    for label in sorted(regime_buckets):
        vals = regime_buckets[label]
        if len(vals) < 5:
            continue
        print(f"    {label:16s}: n={len(vals):5d}  mean_forward_return_5={_fmt(sum(vals) / len(vals))}", flush=True)

    # ============================================================== COST SENSITIVITY (Part 20)
    print(f"\n{'=' * 100}\nCOST SENSITIVITY (Part 20: MARK-TO-MARKET HISTORICAL RESEARCH only, ASSUMPTION-labeled)\n{'=' * 100}", flush=True)
    entry_prices = [r["option_close"] for r in panel if r.get(PRIMARY_TARGET_COL) is not None]
    mean_entry_price = sum(entry_prices) / len(entry_prices) if entry_prices else None
    # Use the deep_otm - itm mean gap as the diagnostic spread, mirroring Phase 19's quantile-spread pattern
    gross_gap = (bucket_stats.get("deep_otm", {}).get("mean") or 0) - (bucket_stats.get("itm", {}).get("mean") or 0)
    print(f"  mean entry option price across panel: {_fmt(mean_entry_price)}   diagnostic deep_otm-itm gap: {_fmt(gross_gap)}", flush=True)
    for assumption in COST_SENSITIVITY_ASSUMPTIONS:
        if mean_entry_price is None or mean_entry_price <= 0:
            continue
        net = apply_cost_assumption(gross_gap, mean_entry_price, assumption)
        print(f"  {assumption.label}: net_gap={_fmt(net)}  viable_under_this_assumption={'True' if net > 0 else 'False'}", flush=True)

    # ============================================================== FINAL CLASSIFICATION (Part 23: never "VALIDATED")
    print(f"\n{'=' * 100}\nFINAL PER-HYPOTHESIS REPLICATION CLASSIFICATION\n{'=' * 100}", flush=True)
    gate_store = DiscoveryDevelopmentGateStore(Path("logs/research_data/phase20_gate_transitions.jsonl"))
    classifications: dict[str, tuple[str, str]] = {}

    def _advance_and_classify(hyp_id: str, verdict: str, reason: str) -> None:
        assert verdict in ("EXPANDED_DISCOVERY_SUPPORTED", "EXPANDED_WEAKENED", "EXPANDED_REJECTED", "EXPANDED_INCONCLUSIVE")
        classifications[hyp_id] = (verdict, reason)
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.IDEA, reason="replication run", evidence_summary="")
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.PREREGISTERED, reason="preregistered before any replication analysis ran", evidence_summary="")
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DISCOVERY_TESTED, reason="replication family completed", evidence_summary=reason)
        if verdict == "EXPANDED_DISCOVERY_SUPPORTED":
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DISCOVERY_SUPPORTED, reason=reason, evidence_summary=reason)
        else:
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.NOT_READY, reason=f"classified {verdict}: {reason}", evidence_summary=reason)
        print(f"  {hyp_id}: {verdict} — {reason}", flush=True)

    v4 = "EXPANDED_DISCOVERY_SUPPORTED" if (deep_otm_stdev is not None and itm_atm_mean_stdev is not None and deep_otm_stdev > itm_atm_mean_stdev * 1.2) else "EXPANDED_WEAKENED"
    _advance_and_classify("P19-OPT-004-EXPANDED", v4, f"deep_otm_stdev={_fmt(deep_otm_stdev)} vs itm_atm_mean_stdev={_fmt(itm_atm_mean_stdev)}")

    v5 = "EXPANDED_DISCOVERY_SUPPORTED" if (cp_gap is not None and cp_p is not None and cp_p < 0.05 and abs(cp_gap) > 0.01) else ("EXPANDED_REJECTED" if cp_p is not None and cp_p >= 0.05 else "EXPANDED_INCONCLUSIVE")
    _advance_and_classify("P19-OPT-005-EXPANDED", v5, f"call_mean={_fmt(call_mean)}, put_mean={_fmt(put_mean)}, gap={_fmt(cp_gap)}, Welch_p={_fmt(cp_p)}")

    v8 = "EXPANDED_DISCOVERY_SUPPORTED" if same_sign_underlyings >= len(universe.symbols) * 0.75 else "EXPANDED_WEAKENED"
    _advance_and_classify("P19-OPT-008-EXPANDED", v8, f"{same_sign_underlyings}/{len(universe.symbols)} underlyings agree in sign with pooled IC={_fmt(pooled_ic)} (original: 4/4)")

    v9 = "EXPANDED_DISCOVERY_SUPPORTED" if same_sign_horizons else "EXPANDED_WEAKENED"
    _advance_and_classify("P19-OPT-009-EXPANDED", v9, f"horizon ICs: {[_fmt(horizon_ics[h]) for h in STANDARD_FORWARD_HORIZONS]}")

    v12 = "EXPANDED_DISCOVERY_SUPPORTED" if most_negative_bucket == "0-7" else "EXPANDED_WEAKENED"
    _advance_and_classify("P19-OPT-012-EXPANDED", v12, f"most-negative-decay bucket={most_negative_bucket} (expected '0-7')")

    n_supported = sum(1 for v, _ in classifications.values() if v == "EXPANDED_DISCOVERY_SUPPORTED")
    print(f"\n{n_supported}/{len(classifications)} replication runs classified EXPANDED_DISCOVERY_SUPPORTED.", flush=True)
    print("No hypothesis is declared VALIDATED. No trading strategy is created here.", flush=True)

    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))
    dims_fp = ExperimentDimensions(
        feature_definition=PRIMARY_FEATURE, parameter_range={"expanded_ids": list(expanded_ids), "horizons": list(STANDARD_FORWARD_HORIZONS)},
        universe_name=universe.name, target_definition=PRIMARY_TARGET_COL, execution_model="n/a-replication",
        cost_model="n/a-replication-assumption-only", validation_methodology="replication of Phase 19 DISCOVERY_SUPPORTED hypotheses on the expanded panel",
    )
    exp_store.record(
        data_version="phase20-expanded-options-panel-v1", feature_version="phase20-replication-v1", symbols=list(universe.symbols), timeframe="day",
        strategy_version="1.0", prediction_horizon=5, train_period=("2021-12-01", "2023-06-15"),
        parameters={"n_tests": len(raw_p_values), "n_contracts": 120}, metrics={"primary_ic": pooled_ic, "n_expanded_discovery_supported": n_supported},
        strategy_family="options_alpha_replication", classification=("EXPANDED_DISCOVERY_SUPPORTED" if n_supported > 0 else "EXPANDED_WEAKENED"),
        tags=("phase20-replication", universe.name, "mark-to-market-historical-research"),
        notes=f"{n_supported}/{len(classifications)} EXPANDED_DISCOVERY_SUPPORTED; classifications={ {k: v[0] for k, v in classifications.items()} }",
        hypothesis_id="P20-REPL-FAMILY", universe_name=universe.name, experiment_fingerprint=compute_experiment_fingerprint(dims_fp),
        research_family_id=EXPERIMENT_FAMILY_ID,
    )
    print("\nSTEP 4 COMPLETE.", flush=True)


if __name__ == "__main__":
    main()
