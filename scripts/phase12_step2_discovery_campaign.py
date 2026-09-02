#!/usr/bin/env python3
"""Phase 12 — STEP 2: the full discovery-stage investigation of the
CROSS_SECTIONAL_RELATIVE_STRENGTH hypothesis family (P12-CSRS-001..010)
on DISCOVERY_DATA only. No backtest, no trading strategy, no
DEVELOPMENT_DATA/VALIDATION_DATA/FINAL_HOLDOUT_DATA access anywhere.

Covers Parts 7-23: cross-sectional IC (Spearman+Pearson), quantile
portfolios (incl. cumulative return/drawdown/turnover), incremental-
information (OLS), factor-neutrality correlation matrix, alpha decay
(horizon table), regime analysis, year/quarter stability, breadth/
concentration, placebo battery, multiple-testing correction, purged-CV
leakage demonstration, bootstrap, PBO, and DSR.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import HistoricalDataStore, run_universe_quality_report, us_diversified_universe  # noqa: E402
from src.features import FeatureEngine  # noqa: E402
from src.features.momentum import RateOfChange  # noqa: E402
from src.features.relative_strength import RelativeStrengthAcceleration, RelativeStrengthPersistence, VolatilityAdjustedMomentum  # noqa: E402
from src.research import (  # noqa: E402
    DiscoveryDevelopmentGateStore,
    DiscoveryDevelopmentStage,
    ExperimentStore,
    PartitionLifecycleStage,
    PartitionStore,
    analyze_feature,
    benjamini_hochberg_fdr,
    block_bootstrap_return_series,
    bonferroni_correction,
    compute_experiment_fingerprint,
    compute_ic_series,
    compute_pearson_ic_series,
    cross_sectional_quantile_returns,
    cumulative_residual_momentum,
    deflated_sharpe_ratio,
    effective_number_of_trials,
    filter_rows_by_partition,
    holm_bonferroni_correction,
    ic_by_regime,
    label_bars_by_regime,
    market_residual_returns,
    market_sector_residual_returns,
    ols_regression,
    probability_of_backtest_overfitting,
    random_feature_control,
    require_preregistered,
    sector_residual_returns,
    shifted_signal_placebo,
    shuffled_signal_placebo,
    stationary_bootstrap_return_series,
    summarize_ic,
    summarize_pearson_ic,
)
from src.research.analysis import pearson_correlation  # noqa: E402
from src.research.experiment_fingerprint import ExperimentDimensions  # noqa: E402
from src.research.preregistration import PreregistrationStore  # noqa: E402
from src.research.purged_cv import PurgedCVConfig, PurgedFold, fold_has_leakage, generate_purged_folds  # noqa: E402
from src.research.stats_utils import t_test_p_value  # noqa: E402
from src.research.targets import future_return  # noqa: E402

BETA_WINDOW = 60
RESIDUAL_MOMENTUM_WINDOW = 20
HORIZON_SET = (1, 5, 20)
PRIMARY_HORIZON = 5
REGIME_SET = ("bull_high_vol", "bull_low_vol", "bear_high_vol", "bear_low_vol", "unknown")
FEATURE_SET = (
    "return_5d", "return_20d", "return_60d", "market_residual_mom_20d", "sector_residual_mom_20d",
    "market_sector_residual_mom_20d", "vol_adj_momentum_20d", "relative_strength_persistence", "relative_strength_acceleration",
)
PRIMARY_FEATURE = "return_20d"
COST_RATES_BPS = (10, 20, 30)  # one-way, 1x/2x/3x stress (Part 14) — a documented analytical assumption, no live backtest this phase


def _fmt(x) -> str:
    return "None" if x is None else f"{x:.4f}"


def _ic_p_value(points) -> float | None:
    values = [p.ic for p in points if p.ic is not None]
    if len(values) < 2:
        return None
    return t_test_p_value(values)


def build_panel(store, universe, usable: list[str]) -> tuple[list[dict], dict, dict]:
    """One row per (symbol, timestamp) with every preregistered feature
    and every target x horizon column."""
    bars_by_symbol = {s: store.load(s, "day") for s in usable}
    spy_bars = bars_by_symbol["SPY"]
    sectors = universe.by_sector()
    sector_of = {sym: sec for sec, syms in sectors.items() for sym in syms}

    raw_engine = FeatureEngine([RateOfChange(5), RateOfChange(20), RateOfChange(60), VolatilityAdjustedMomentum(20, 20), RelativeStrengthPersistence(20, 20), RelativeStrengthAcceleration(20)])

    panel: list[dict] = []
    for sym in usable:
        bars = bars_by_symbol[sym]
        if not bars or len(bars) != len(spy_bars):
            continue  # residual construction requires aligned lengths (same trading calendar) — this codebase's stored bars are already calendar-aligned per symbol; skip defensively rather than crash
        frame = raw_engine.compute(bars)

        peer_symbols = [p for p in sectors.get(sector_of.get(sym, ""), ()) if p != sym]
        peer_bars = {p: bars_by_symbol[p] for p in peer_symbols if p in bars_by_symbol and len(bars_by_symbol[p]) == len(bars)}

        market_resid = market_residual_returns(bars, spy_bars, beta_window=BETA_WINDOW)
        sector_resid = sector_residual_returns(bars, peer_bars)
        market_sector_resid = market_sector_residual_returns(bars, spy_bars, peer_bars, beta_window=BETA_WINDOW)
        market_resid_mom = cumulative_residual_momentum(market_resid, window=RESIDUAL_MOMENTUM_WINDOW)
        sector_resid_mom = cumulative_residual_momentum(sector_resid, window=RESIDUAL_MOMENTUM_WINDOW)
        market_sector_resid_mom = cumulative_residual_momentum(market_sector_resid, window=RESIDUAL_MOMENTUM_WINDOW)

        target_columns: dict[str, list] = {f"future_return_{h}": future_return(bars, h) for h in HORIZON_SET}

        for i, ts in enumerate(frame.timestamps):
            row = {"timestamp": ts, "symbol": sym, "sector": sector_of.get(sym, "unclassified")}
            row["return_5d"] = frame.columns["roc_5"][i]
            row["return_20d"] = frame.columns["roc_20"][i]
            row["return_60d"] = frame.columns["roc_60"][i]
            row["vol_adj_momentum_20d"] = frame.columns["vol_adj_momentum_20"][i]
            row["relative_strength_persistence"] = frame.columns["relative_strength_persistence"][i]
            row["relative_strength_acceleration"] = frame.columns["relative_strength_acceleration"][i]
            row["market_residual_mom_20d"] = market_resid_mom[i]
            row["sector_residual_mom_20d"] = sector_resid_mom[i]
            row["market_sector_residual_mom_20d"] = market_sector_resid_mom[i]
            row["negative_control"] = (hash(sym) % 1000) / 1000.0  # Part 19D — constant per symbol, zero genuine economic content
            for col_name, series in target_columns.items():
                row[col_name] = series[i]
            panel.append(row)
    return panel, bars_by_symbol, sector_of


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    universe = us_diversified_universe()

    prereg_store = PreregistrationStore(Path("logs/research_data/phase12_preregistrations.jsonl"))
    require_preregistered(prereg_store, "P12-CSRS-FAMILY")
    for i in range(1, 11):
        require_preregistered(prereg_store, f"P12-CSRS-{i:03d}")

    partition_store = PartitionStore(Path("logs/research_data/phase7_partitions.jsonl"))
    discovery = partition_store.active_by_stage(PartitionLifecycleStage.DISCOVERY)[0]
    print(f"DISCOVERY_DATA: {discovery.start_date} .. {discovery.end_date}", flush=True)
    print("UNIVERSE LIMITATION: US_DIVERSIFIED is CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED.\n", flush=True)

    quality = run_universe_quality_report(store, universe, "day", min_bars_required=100)
    usable = [q.symbol for q in quality if q.available]
    print(f"Universe: {universe.name}  usable={len(usable)}/{len(universe.symbols)}", flush=True)
    if "SPY" not in usable:
        raise RuntimeError("SPY (the market proxy) is not usable — cannot construct market-residual features.")

    print("Building the full feature/target panel (9 features x 3 horizons)...", flush=True)
    full_panel, bars_by_symbol_full, sector_of = build_panel(store, universe, usable)
    discovery_panel = filter_rows_by_partition(full_panel, discovery)
    print(f"Full panel: {len(full_panel)} rows. DISCOVERY_DATA panel: {len(discovery_panel)} rows.\n", flush=True)

    regime_labels: dict = {}
    for sym in usable:
        regime_labels.update(label_bars_by_regime(bars_by_symbol_full[sym]))

    raw_p_values: list[tuple[str, float]] = []
    all_ic_results: dict[str, dict] = {}

    # ============================================================== PART A: MAIN SCREEN (27 tests)
    print(f"{'=' * 100}\nPART A — MAIN SCREEN: {len(FEATURE_SET)} features x {len(HORIZON_SET)} horizons\n{'=' * 100}", flush=True)
    for feature_name in FEATURE_SET:
        row_str = []
        for h in HORIZON_SET:
            target_col = f"future_return_{h}"
            spearman_points = compute_ic_series(discovery_panel, feature_name, target_col, min_universe_size=3)
            spearman = summarize_ic(spearman_points, feature_name=feature_name, target_name=target_col)
            pearson_points = compute_pearson_ic_series(discovery_panel, feature_name, target_col, min_universe_size=3)
            pearson = summarize_pearson_ic(pearson_points, feature_name=feature_name, target_name=target_col)
            quantiles = cross_sectional_quantile_returns(discovery_panel, feature_name, target_col, n_quantiles=5, min_universe_size=3)
            key = f"{feature_name}|h{h}"
            all_ic_results[key] = {"spearman": spearman, "pearson": pearson, "quantiles": quantiles, "spearman_points": spearman_points}
            row_str.append(f"h{h}:spear={_fmt(spearman.average_ic)}/pear={_fmt(pearson.average_ic)}")
            p = _ic_p_value(spearman_points)
            if p is not None:
                raw_p_values.append((key, p))
        print(f"  {feature_name:32s}: " + "  ".join(row_str), flush=True)

    print(f"\nQuantile detail (primary horizon h={PRIMARY_HORIZON}):", flush=True)
    for feature_name in FEATURE_SET:
        q = all_ic_results[f"{feature_name}|h{PRIMARY_HORIZON}"]["quantiles"]
        print(f"  {feature_name:32s}: spread={_fmt(q.spread_q5_minus_q1)}  monotonic={q.is_monotonic}  n_ts={q.timestamps_used}", flush=True)
        for qr in q.quantiles:
            print(f"      Q{qr.quantile}: n={qr.sample_count:5d} mean={qr.mean_return:.5f} hit_rate={qr.hit_rate:.2%} vol={qr.volatility:.5f} "
                  f"sharpe_like={_fmt(qr.mean_return / qr.volatility if qr.volatility else None)}", flush=True)

    # ============================================================== PART B: REGIME TABLE (45 tests)
    print(f"\n{'=' * 100}\nPART B — REGIME TABLE (all features @ primary horizon)\n{'=' * 100}", flush=True)
    regime_table: dict[str, dict] = {}
    primary_target_col = f"future_return_{PRIMARY_HORIZON}"
    for feature_name in FEATURE_SET:
        regime_result = ic_by_regime(discovery_panel, feature_name, primary_target_col, regime_labels, min_universe_size=3)
        regime_table[feature_name] = regime_result
        print(f"  {feature_name:32s}: " + "; ".join(f"{r}={_fmt(s.average_ic)}(n={sum(1 for p in s.points if p.ic is not None)})" for r, s in regime_result.items()), flush=True)
        for regime_name, summary in regime_result.items():
            p_val = _ic_p_value(summary.points)
            if p_val is not None:
                raw_p_values.append((f"{feature_name}|h{PRIMARY_HORIZON}|regime={regime_name}", p_val))

    print(f"\nTotal raw p-values collected across the complete preregistered family: {len(raw_p_values)}", flush=True)

    # ============================================================== PART 11: INCREMENTAL INFORMATION
    print(f"\n{'=' * 100}\nPART 11 — INCREMENTAL_PREDICTIVE_INFORMATION vs raw momentum (OLS, h={PRIMARY_HORIZON})\n{'=' * 100}", flush=True)
    y = [r.get(primary_target_col) for r in discovery_panel]
    raw_mom = [r.get(PRIMARY_FEATURE) for r in discovery_panel]
    model_a = ols_regression(y, {"raw_momentum": raw_mom}, min_observations=30)
    print(f"  Model A (future_return ~ {PRIMARY_FEATURE}): {model_a.render()}", flush=True)
    incremental_by_feature: dict[str, float | None] = {}
    incremental_significant: dict[str, bool] = {}
    for feature_name in ("market_residual_mom_20d", "sector_residual_mom_20d", "market_sector_residual_mom_20d", "vol_adj_momentum_20d"):
        candidate = [r.get(feature_name) for r in discovery_panel]
        model_b = ols_regression(y, {"candidate": candidate}, min_observations=30)
        model_c = ols_regression(y, {"raw_momentum": raw_mom, "candidate": candidate}, min_observations=30)
        if model_a.applicable and model_c.applicable:
            incremental = model_c.r_squared - model_a.r_squared
            incremental_by_feature[feature_name] = incremental
            p_candidate = model_c.coefficient_p_values.get("candidate", 1.0)
            incremental_significant[feature_name] = incremental > 0.005 and p_candidate < 0.05
            print(f"  {feature_name:32s}: R2_A={model_a.r_squared:.5f}  R2_C={model_c.r_squared:.5f}  delta_R2={incremental:.5f}  "
                  f"candidate_p={p_candidate:.4g}  {'<-- INCREMENTAL' if incremental_significant[feature_name] else ''}", flush=True)
        else:
            incremental_by_feature[feature_name] = None
            incremental_significant[feature_name] = False
            print(f"  {feature_name:32s}: NOT_APPLICABLE", flush=True)

    # ============================================================== PART 12: FACTOR NEUTRALITY / CORRELATION MATRIX
    print(f"\n{'=' * 100}\nPART 12 — FACTOR NEUTRALITY: correlation matrix (pooled panel values)\n{'=' * 100}", flush=True)
    corr_features = ("return_20d", "market_residual_mom_20d", "sector_residual_mom_20d", "market_sector_residual_mom_20d", "vol_adj_momentum_20d")
    print("  " + " ".join(f"{f[:14]:>14s}" for f in corr_features), flush=True)
    for f1 in corr_features:
        row_vals = []
        for f2 in corr_features:
            paired = [(r[f1], r[f2]) for r in discovery_panel if r.get(f1) is not None and r.get(f2) is not None]
            if len(paired) < 2:
                row_vals.append(None)
                continue
            xs, ys = [p[0] for p in paired], [p[1] for p in paired]
            row_vals.append(pearson_correlation(xs, ys))
        print(f"  {f1[:20]:20s} " + " ".join(f"{_fmt(v):>14s}" for v in row_vals), flush=True)

    # ============================================================== PART 13: QUANTILE PORTFOLIO TIME SERIES (cumulative return, drawdown, turnover)
    print(f"\n{'=' * 100}\nPART 13 — QUANTILE PORTFOLIO TIME SERIES (primary feature/horizon)\n{'=' * 100}", flush=True)
    by_ts: dict = defaultdict(list)
    for row in discovery_panel:
        f, t = row.get(PRIMARY_FEATURE), row.get(primary_target_col)
        if f is not None and t is not None:
            by_ts[row["timestamp"]].append((row["symbol"], f, t))
    quantile_membership: dict = {}  # ts -> {quantile: set(symbols)}
    quantile_return_series: dict = defaultdict(list)  # quantile -> [(ts, mean_return)]
    for ts in sorted(by_ts):
        triples = by_ts[ts]
        if len(triples) < 3:
            continue
        ranked = sorted(triples, key=lambda t: t[1])
        n = len(ranked)
        buckets: dict[int, list] = defaultdict(list)
        members: dict[int, set] = defaultdict(set)
        for i, (sym, _f, t) in enumerate(ranked):
            bucket = min(4, (i * 5) // n)
            buckets[bucket].append(t)
            members[bucket].add(sym)
        quantile_membership[ts] = members
        for q in range(5):
            if buckets[q]:
                quantile_return_series[q].append((ts, sum(buckets[q]) / len(buckets[q])))

    # Compounding EVERY daily row of an h-bar FORWARD return would treat heavily overlapping
    # windows (each future_return_h observation shares h-1 days with its neighbor) as if they were
    # independent sequential periods, wildly overstating cumulative return. The methodologically
    # correct way to turn a series of overlapping h-bar forward returns into a valid compounded
    # curve is to sample every h-th observation (PRIMARY_HORIZON apart) — genuinely disjoint periods.
    for q in range(5):
        series = quantile_return_series[q][::PRIMARY_HORIZON]
        if not series:
            continue
        cum = 1.0
        peak = 1.0
        max_dd = 0.0
        for _ts, ret in series:
            cum *= 1 + ret
            peak = max(peak, cum)
            max_dd = min(max_dd, (cum - peak) / peak)
        print(f"  Q{q + 1}: n_non_overlapping_periods={len(series):4d}  cumulative_return={(cum - 1) * 100:+7.2f}%  max_drawdown={max_dd * 100:+6.2f}%", flush=True)

    ts_sorted = sorted(quantile_membership.keys())
    turnover_by_quantile: dict[int, list[float]] = defaultdict(list)
    for prev_ts, cur_ts in zip(ts_sorted, ts_sorted[1:]):
        for q in range(5):
            prev_members = quantile_membership[prev_ts].get(q, set())
            cur_members = quantile_membership[cur_ts].get(q, set())
            if not prev_members and not cur_members:
                continue
            changed = len(prev_members.symmetric_difference(cur_members))
            denom = max(1, len(prev_members) + len(cur_members))
            turnover_by_quantile[q].append(changed / denom)
    print("\n  Per-bar turnover (fraction of quantile membership changing day to day):", flush=True)
    for q in range(5):
        vals = turnover_by_quantile.get(q, [])
        avg_turnover = sum(vals) / len(vals) if vals else None
        print(f"  Q{q + 1}: avg_daily_turnover={_fmt(avg_turnover)}", flush=True)

    # ============================================================== PART 14: TURNOVER AND COSTS
    print(f"\n{'=' * 100}\nPART 14 — TURNOVER AND ESTIMATED TRANSACTION COSTS (Q5-Q1 long-only diagnostic, 1x/2x/3x)\n{'=' * 100}", flush=True)
    q5_turnover_series = turnover_by_quantile.get(4, [])
    avg_q5_turnover = sum(q5_turnover_series) / len(q5_turnover_series) if q5_turnover_series else 0.0
    gross_spread = all_ic_results[f"{PRIMARY_FEATURE}|h{PRIMARY_HORIZON}"]["quantiles"].spread_q5_minus_q1
    print(f"  avg Q5 daily turnover: {avg_q5_turnover:.3f}   gross Q5-Q1 spread (h={PRIMARY_HORIZON}): {_fmt(gross_spread)}", flush=True)
    for mult, bps in zip((1, 2, 3), COST_RATES_BPS):
        cost_drag = avg_q5_turnover * (bps / 10_000) * 2  # round-trip: buy + sell
        net_spread = None if gross_spread is None else gross_spread - cost_drag
        print(f"  {mult}x ({bps}bps one-way): estimated cost_drag={cost_drag:.5f}  net_Q5-Q1_spread={_fmt(net_spread)}  "
              f"viable={'True' if (net_spread or -1) > 0 else 'False'}", flush=True)

    # ============================================================== PART 17: TIME STABILITY (year)
    print(f"\n{'=' * 100}\nPART 17 — TIME STABILITY (year, primary feature/horizon)\n{'=' * 100}", flush=True)
    years = sorted({r["timestamp"].year for r in discovery_panel})
    for year in years:
        year_rows = [r for r in discovery_panel if r["timestamp"].year == year]
        year_ic = summarize_ic(compute_ic_series(year_rows, PRIMARY_FEATURE, primary_target_col, min_universe_size=3), feature_name=PRIMARY_FEATURE, target_name=primary_target_col)
        year_q = cross_sectional_quantile_returns(year_rows, PRIMARY_FEATURE, primary_target_col, n_quantiles=5, min_universe_size=3)
        print(f"  {year}: IC={_fmt(year_ic.average_ic)}  spread={_fmt(year_q.spread_q5_minus_q1)}  monotonic={year_q.is_monotonic}  n_ts={year_q.timestamps_used}", flush=True)

    print("\n  By quarter:", flush=True)
    quarters = sorted({(r["timestamp"].year, (r["timestamp"].month - 1) // 3 + 1) for r in discovery_panel})
    for year, q in quarters:
        q_rows = [r for r in discovery_panel if r["timestamp"].year == year and (r["timestamp"].month - 1) // 3 + 1 == q]
        if len(q_rows) < 30:
            continue
        q_ic = summarize_ic(compute_ic_series(q_rows, PRIMARY_FEATURE, primary_target_col, min_universe_size=3), feature_name=PRIMARY_FEATURE, target_name=primary_target_col)
        print(f"  {year}Q{q}: IC={_fmt(q_ic.average_ic)}  n_rows={len(q_rows)}", flush=True)

    # ============================================================== PART 18: BREADTH / CONCENTRATION
    print(f"\n{'=' * 100}\nPART 18 — CROSS-SECTIONAL BREADTH (primary feature/horizon)\n{'=' * 100}", flush=True)
    pooled_ic = all_ic_results[f"{PRIMARY_FEATURE}|h{PRIMARY_HORIZON}"]["spearman"].average_ic
    per_symbol_positive = 0
    for sym in usable:
        sym_rows = [r for r in discovery_panel if r["symbol"] == sym]
        result = analyze_feature(sym_rows, PRIMARY_FEATURE, primary_target_col, n_quantiles=3)
        if result.spearman_correlation is not None and result.spearman_correlation > 0:
            per_symbol_positive += 1
        print(f"  {sym}: n={result.sample_count}  spearman={_fmt(result.spearman_correlation)}", flush=True)
    print(f"\n  symbols with positive per-symbol IC: {per_symbol_positive}/{len(usable)}", flush=True)

    print("\n  Leave-one-symbol-out:", flush=True)
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
    print(f"  max swing: {loo_swings[0][2]:.4f}  sign_flips_without: {sign_flips}", flush=True)

    print("\n  Leave-one-sector-out:", flush=True)
    for sector_name, sector_symbols in universe.by_sector().items():
        rows_without = [r for r in discovery_panel if r["symbol"] not in sector_symbols]
        without_ic = summarize_ic(compute_ic_series(rows_without, PRIMARY_FEATURE, primary_target_col, min_universe_size=3), feature_name=PRIMARY_FEATURE, target_name=primary_target_col).average_ic
        print(f"  without sector={sector_name}: IC={_fmt(without_ic)}", flush=True)

    # ============================================================== PART 19: PLACEBO TESTS
    print(f"\n{'=' * 100}\nPART 19 — PLACEBO BATTERY (primary feature/horizon)\n{'=' * 100}", flush=True)
    random_ctrl = random_feature_control(discovery_panel, target_col=primary_target_col, n_trials=100, seed=601, min_universe_size=3)
    random_mean_ic = sum(random_ctrl.placebo_distribution) / len(random_ctrl.placebo_distribution) if random_ctrl.placebo_distribution else None
    print(f"  A. random ranking placebo: mean_IC={_fmt(random_mean_ic)}", flush=True)
    shuffled = shuffled_signal_placebo(discovery_panel, feature_col=PRIMARY_FEATURE, target_col=primary_target_col, n_trials=200, seed=602)
    print(f"  B. feature-shuffling placebo: observed_IC={_fmt(shuffled.observed_statistic)}  p={shuffled.empirical_p_value}", flush=True)
    alignment_concern = False
    for shift in (1, 5, 10):
        shifted = shifted_signal_placebo(discovery_panel, feature_col=PRIMARY_FEATURE, target_col=primary_target_col, shift_bars=shift)
        shifted_ic = shifted.placebo_distribution[0] if shifted.placebo_distribution else None
        flag = shifted_ic is not None and pooled_ic is not None and abs(shifted_ic) >= abs(pooled_ic)
        alignment_concern = alignment_concern or flag
        print(f"  C. time-shift placebo shift=+{shift}: true_IC={_fmt(pooled_ic)}  shifted_IC={_fmt(shifted_ic)}  {'<-- CONCERN' if flag else ''}", flush=True)
    negctrl_points = compute_ic_series(discovery_panel, "negative_control", primary_target_col, min_universe_size=3)
    negctrl_ic = summarize_ic(negctrl_points, feature_name="negative_control", target_name=primary_target_col)
    print(f"  D. negative-control feature (symbol-hash, no genuine content): IC={_fmt(negctrl_ic.average_ic)}", flush=True)
    survives_placebo = (shuffled.empirical_p_value is not None and shuffled.empirical_p_value < 0.10) and not alignment_concern and abs(negctrl_ic.average_ic or 0) < abs(pooled_ic or 1)

    # ============================================================== PART 20: MULTIPLE TESTING
    print(f"\n{'=' * 100}\nPART 20 — MULTIPLE-TESTING CORRECTION (complete family, n={len(raw_p_values)})\n{'=' * 100}", flush=True)
    for method in (bonferroni_correction, holm_bonferroni_correction, benjamini_hochberg_fdr):
        report = method(raw_p_values, alpha=0.05)
        print(f"  {report.method}: n_significant={report.n_significant}/{report.n_tests}", flush=True)
    bh_report = benjamini_hochberg_fdr(raw_p_values, alpha=0.05)
    bh_significant_keys = {r.label for r in bh_report.results if r.significant_at_alpha}
    primary_key = f"{PRIMARY_FEATURE}|h{PRIMARY_HORIZON}"
    primary_bh = next((r for r in bh_report.results if r.label == primary_key), None)
    print(f"\n  Primary test ({primary_key}) BH-adjusted p={primary_bh.adjusted_p_value if primary_bh else 'N/A'}  significant={primary_bh.significant_at_alpha if primary_bh else 'N/A'}", flush=True)

    complete_rows = [r for r in discovery_panel[:2000] if all(r.get(name) is not None for name in FEATURE_SET)][:500]
    feature_value_series = {name: [r[name] for r in complete_rows] for name in FEATURE_SET}
    eff_trials = effective_number_of_trials(list(feature_value_series.values()))
    print(f"  {eff_trials.render()}", flush=True)

    # ============================================================== PART 21: PURGED / EMBARGOED CV DEMO
    print(f"\n{'=' * 100}\nPART 21 — PURGED/EMBARGOED CV LEAKAGE DEMONSTRATION\n{'=' * 100}", flush=True)
    sample_symbol = "SPY"
    sample_bars = bars_by_symbol_full[sample_symbol]
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
            train_idx = tuple(i for i in range(n) if i not in test_idx)  # NO purge, NO embargo — the naive, leaky baseline
            folds.append(PurgedFold(fold_index=k, test_indices=test_idx, train_indices=train_idx, purged_count=0, embargoed_count=0))
            start += size
        return folds

    naive_folds = _naive_folds(len(sample_timestamps), 6)
    naive_leakage = [fold_has_leakage(f, sample_timestamps, prediction_horizon_bars=PRIMARY_HORIZON) for f in naive_folds]
    print(f"  naive (unpurged) CV: {sum(naive_leakage)}/{len(naive_folds)} folds show leakage (expected: > 0)", flush=True)

    # ============================================================== PART 22: PBO / DSR
    print(f"\n{'=' * 100}\nPART 22 — PBO / DSR (across the {len(FEATURE_SET)} preregistered features, primary horizon)\n{'=' * 100}", flush=True)
    n_periods = 8
    period_matrix: list[list[float]] = []
    disc_start, disc_end = discovery.start_date, discovery.end_date
    total_days = (disc_end - disc_start).days + 1
    for feature_name in FEATURE_SET:
        points = all_ic_results[f"{feature_name}|h{PRIMARY_HORIZON}"]["spearman_points"]
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

    best_feature_idx = max(range(len(FEATURE_SET)), key=lambda i: abs(all_ic_results[f"{FEATURE_SET[i]}|h{PRIMARY_HORIZON}"]["spearman"].average_ic or 0))
    best_feature = FEATURE_SET[best_feature_idx]
    best_ic_series = [p.ic for p in all_ic_results[f"{best_feature}|h{PRIMARY_HORIZON}"]["spearman_points"] if p.ic is not None]
    dsr = deflated_sharpe_ratio(best_ic_series, n_trials=len(FEATURE_SET))
    print(f"  DSR applied to {best_feature}'s own per-timestamp IC series (n_trials={len(FEATURE_SET)}, the searched feature count): {dsr.render()}", flush=True)
    print("  NOTE: DSR's formula only needs a return-like series with defined mean/skew/kurtosis — applying it to an IC series "
          "(rather than a P&L return series) is a documented adaptation, consistent with this project's Phase 9-11 precedent "
          "of reusing the SAME statistical machinery on the right unit of analysis for a new context.", flush=True)

    # ============================================================== PART 23: BOOTSTRAP
    print(f"\n{'=' * 100}\nPART 23 — BOOTSTRAP (block + stationary) on {PRIMARY_FEATURE}'s own IC series and Q5-Q1 spread series\n{'=' * 100}", flush=True)
    primary_ic_series = [p.ic for p in all_ic_results[f"{PRIMARY_FEATURE}|h{PRIMARY_HORIZON}"]["spearman_points"] if p.ic is not None]
    for conf in (0.90, 0.95):
        block_report = block_bootstrap_return_series(primary_ic_series, block_size=5, n_resamples=2000, seed=701, confidence_level=conf)
        print(f"  IC series, block bootstrap ({conf:.0%} CI): {block_report.render()}", flush=True)
    q5_minus_q1_series = [ret2 - ret1 for (ts1, ret1), (ts2, ret2) in zip(quantile_return_series[0], quantile_return_series[4]) if ts1 == ts2]
    if q5_minus_q1_series:
        for conf in (0.90, 0.95):
            spread_report = stationary_bootstrap_return_series(q5_minus_q1_series, mean_block_length=5.0, n_resamples=2000, seed=702, confidence_level=conf)
            print(f"  Q5-Q1 spread series, stationary bootstrap ({conf:.0%} CI): {spread_report.render()}", flush=True)

    # ============================================================== FINAL CLASSIFICATION (Part 24) & GATE (Part 30)
    print(f"\n{'=' * 100}\nFINAL PER-HYPOTHESIS CLASSIFICATION\n{'=' * 100}", flush=True)
    gate_store = DiscoveryDevelopmentGateStore(Path("logs/research_data/phase12_gate_transitions.jsonl"))
    classifications: dict[str, tuple[str, str]] = {}

    def _advance_and_classify(hyp_id: str, verdict: str, reason: str) -> None:
        classifications[hyp_id] = (verdict, reason)
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.IDEA, reason="new CROSS_SECTIONAL_RELATIVE_STRENGTH hypothesis", evidence_summary="")
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.PREREGISTERED, reason="preregistered before any analysis ran", evidence_summary="")
        gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DISCOVERY_TESTED, reason="discovery family completed", evidence_summary=reason)
        if verdict == "DISCOVERY_SUPPORTED":
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.DISCOVERY_SUPPORTED, reason=reason, evidence_summary=reason)
        else:
            gate_store.transition(hypothesis_id=hyp_id, to_stage=DiscoveryDevelopmentStage.NOT_READY, reason=f"classified {verdict}: {reason}", evidence_summary=reason)
        print(f"  {hyp_id}: {verdict} — {reason}", flush=True)

    def _classify_feature(feature_name: str, h: int = PRIMARY_HORIZON) -> tuple[str, str]:
        key = f"{feature_name}|h{h}"
        bh_sig = key in bh_significant_keys
        q = all_ic_results[key]["quantiles"]
        ic = all_ic_results[key]["spearman"].average_ic
        reason = f"IC={_fmt(ic)}, BH-significant={bh_sig}, monotonic={q.is_monotonic}, spread={_fmt(q.spread_q5_minus_q1)}, breadth={per_symbol_positive}/{len(usable)}, survives_placebo={survives_placebo}"
        if not bh_sig:
            return "REJECTED" if ic is not None and abs(ic) < 0.01 else "INCONCLUSIVE", reason
        if not q.is_monotonic or not survives_placebo:
            return "FRAGILE", reason
        if per_symbol_positive < len(usable) * 0.5:
            return "FRAGILE", reason
        return "DISCOVERY_SUPPORTED", reason

    v, r = _classify_feature("return_5d")
    v20, r20 = _classify_feature("return_20d")
    v60, r60 = _classify_feature("return_60d")
    _advance_and_classify("P12-CSRS-001", v20, f"[using return_20d as the representative raw-momentum window] {r20}")
    v, r = _classify_feature("market_residual_mom_20d")
    v_incr = incremental_significant.get("market_residual_mom_20d", False)
    _advance_and_classify("P12-CSRS-002", v if v_incr else ("FRAGILE" if v == "DISCOVERY_SUPPORTED" else v), f"{r}; incremental_vs_raw={v_incr}")
    v, r = _classify_feature("sector_residual_mom_20d")
    v_incr = incremental_significant.get("sector_residual_mom_20d", False)
    _advance_and_classify("P12-CSRS-003", v if v_incr else ("FRAGILE" if v == "DISCOVERY_SUPPORTED" else v), f"{r}; incremental_vs_raw={v_incr}")
    v, r = _classify_feature("market_sector_residual_mom_20d")
    v_incr = incremental_significant.get("market_sector_residual_mom_20d", False)
    _advance_and_classify("P12-CSRS-004", v if v_incr else ("FRAGILE" if v == "DISCOVERY_SUPPORTED" else v), f"{r}; incremental_vs_raw={v_incr}")
    v, r = _classify_feature("vol_adj_momentum_20d")
    _advance_and_classify("P12-CSRS-005", v, r)
    v, r = _classify_feature("relative_strength_persistence")
    _advance_and_classify("P12-CSRS-006", v, r)
    # P12-CSRS-007: reversal hypothesis — success means NEGATIVE, BH-significant IC at h=1 for return_5d
    key_rev = "return_5d|h1"
    ic_rev = all_ic_results[key_rev]["spearman"].average_ic
    bh_sig_rev = key_rev in bh_significant_keys
    verdict_rev = "DISCOVERY_SUPPORTED" if (bh_sig_rev and ic_rev is not None and ic_rev < -0.01) else ("REJECTED" if ic_rev is not None and ic_rev >= 0 else "INCONCLUSIVE")
    _advance_and_classify("P12-CSRS-007", verdict_rev, f"return_5d IC at h=1 = {_fmt(ic_rev)}, BH-significant={bh_sig_rev} (reversal requires NEGATIVE IC)")
    _advance_and_classify("P12-CSRS-008", v20, f"[return_20d @ h={PRIMARY_HORIZON}] {r20}")
    v60_20, r60_20 = _classify_feature("return_60d", h=20)
    _advance_and_classify("P12-CSRS-009", v60_20, f"[return_60d @ h=20] {r60_20}")
    v, r = _classify_feature("relative_strength_acceleration")
    _advance_and_classify("P12-CSRS-010", v, r)

    n_supported = sum(1 for v, _ in classifications.values() if v == "DISCOVERY_SUPPORTED")
    print(f"\n{n_supported}/{len(classifications)} hypotheses classified DISCOVERY_SUPPORTED.", flush=True)
    print("Per Part 30: this phase STOPS after the discovery report. No development-stage backtest is created here, "
          "regardless of classification outcome.", flush=True)

    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))
    dims_fp = ExperimentDimensions(feature_definition=PRIMARY_FEATURE, parameter_range={"feature_set": list(FEATURE_SET), "horizon_set": list(HORIZON_SET), "beta_window": BETA_WINDOW}, universe_name=universe.name, target_definition="future_return", execution_model="n/a-discovery", cost_model="n/a-discovery", validation_methodology="cross-sectional discovery family on DISCOVERY_DATA")
    exp_store.record(
        data_version="phase5-campaign-v1", feature_version="phase12-discovery-v1", symbols=usable, timeframe="day",
        strategy_version="1.0", prediction_horizon=PRIMARY_HORIZON, train_period=(str(discovery.start_date), str(discovery.end_date)),
        parameters={"n_tests": len(raw_p_values)}, metrics={"primary_ic": pooled_ic, "n_discovery_supported": n_supported},
        strategy_family="cross_sectional_relative_strength", classification=("DISCOVERY_SUPPORTED" if n_supported > 0 else "NOT_READY"),
        tags=("phase12-discovery", universe.name), notes=f"{n_supported}/{len(classifications)} DISCOVERY_SUPPORTED; classifications={ {k: v[0] for k, v in classifications.items()} }",
        hypothesis_id="P12-CSRS-FAMILY", universe_name=universe.name, experiment_fingerprint=compute_experiment_fingerprint(dims_fp),
        research_family_id="P12-CSRS-DISCOVERY-2026-09",
    )
    print("\nSTEP 2 COMPLETE.", flush=True)


if __name__ == "__main__":
    main()
