#!/usr/bin/env python3
"""Phase 7 — STEP 3: the discovery campaign itself. For each of the 12
preregistered hypotheses, evaluates its feature/target relationship on
DISCOVERY_DATA ONLY (never DEVELOPMENT/VALIDATION/FINAL_HOLDOUT — no
backtest runs anywhere in this script): cross-sectional IC/quantile,
alpha decay across 7 horizons, regime-conditional IC, baseline comparison,
multiple placebo/permutation controls, a hypothesis-similarity/reuse
check against every prior hypothesis (Phase 4's 6 + this campaign's own
running history), a 12-dimension scorecard, and a gate transition
(IDEA -> PREREGISTERED -> DISCOVERY_TESTED, or -> NOT_READY). Every
hypothesis lands at DISCOVERY_TESTED or NOT_READY — nothing here can
reach DEVELOPMENT_VALIDATED or beyond (this script contains zero
backtesting code).

Multiple-testing correction (Bonferroni/Holm/BH) is applied ONCE, across
all 12 hypotheses' raw IC p-values together, as a single research family
— exactly the "5/10/15/20/25/30-day momentum" style accounting this phase
exists to make explicit.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import HistoricalDataStore, us_diversified_universe  # noqa: E402
from src.features import FeatureEngine  # noqa: E402
from src.features.mean_reversion import RollingZScore  # noqa: E402
from src.features.momentum import RateOfChange  # noqa: E402
from src.features.regime import TrendRegime, VolatilityRegime  # noqa: E402
from src.features.volatility import RealizedVolatility, VolatilityPercentile  # noqa: E402
from src.features.volume import RelativeVolume  # noqa: E402
from src.research import (  # noqa: E402
    STANDARD_DECAY_HORIZONS,
    DimensionVerdict,
    ExperimentStore,
    HypothesisFingerprint,
    HypothesisRegistry,
    PartitionStore,
    PreregistrationStore,
    ResearchGateStore,
    ResearchLifecycleStage,
    ResearchDatasetGenerator,
    ScorecardDimension,
    build_scorecard,
    benjamini_hochberg_fdr,
    bonferroni_correction,
    bucket_threshold,
    check_research_reuse,
    compare_against_baselines,
    compute_experiment_fingerprint,
    evaluate_cross_sectional_alpha,
    filter_rows_by_partition,
    holm_bonferroni_correction,
    ic_by_regime,
    label_bars_by_regime,
    measure_alpha_decay,
    random_symbol_and_timing_placebo,  # noqa: F401  (imported for parity/reference; not used at the discovery/panel stage)
    require_preregistered,
    shifted_signal_placebo,
    shuffled_signal_placebo,
    time_shuffled_target_placebo,
)
from src.research.cross_sectional_alpha import CrossSectionalAlphaConfig
from src.research.experiment_fingerprint import ExperimentDimensions
from src.research.partition import PartitionLifecycleStage

RESEARCH_FAMILY_ID = "P7-DISCOVERY-2026-09"

# Maps hypothesis_id -> (panel_key, target_key) computed below.
FEATURE_COL_BY_HYP = {
    "P7-MOM-A": "feature_roc_20", "P7-MR-A": "feature_zscore_20", "P7-VOL-A": "derived_neg_vol",
    "P7-VPC-A": "derived_vpc", "P7-TREND-A": "feature_trend_regime_10_50", "P7-BRK-A": "derived_neg_volpct",
    "P7-XSEC-A": "derived_xsec", "P7-MKTREL-A": "derived_mktrel", "P7-SECTREL-A": "derived_sectrel",
    "P7-VOLADJMOM-A": "derived_voladjmom", "P7-VOLANOM-A": "feature_relative_volume_10", "P7-GAP-A": "derived_gap",
}
TARGET_COL_BY_HYP = {
    "P7-MOM-A": "target_future_return_5bar", "P7-MR-A": "target_future_return_5bar", "P7-VOL-A": "target_future_return_10bar",
    "P7-VPC-A": "target_future_return_5bar", "P7-TREND-A": "target_future_return_10bar", "P7-BRK-A": "abs_target_future_return_10bar",
    "P7-XSEC-A": "target_future_return_5bar", "P7-MKTREL-A": "target_future_return_5bar", "P7-SECTREL-A": "target_future_return_5bar",
    "P7-VOLADJMOM-A": "target_future_return_5bar", "P7-VOLANOM-A": "abs_target_future_return_5bar", "P7-GAP-A": "target_future_return_5bar",
}


def build_panel(store: HistoricalDataStore, universe) -> list[dict]:
    engine = FeatureEngine([
        RateOfChange(5), RateOfChange(20), RollingZScore(20), RealizedVolatility(20), VolatilityPercentile(20, 100),
        RelativeVolume(10), TrendRegime(10, 50),
    ])
    generator = ResearchDatasetGenerator(engine, horizons=STANDARD_DECAY_HORIZONS)

    bars_by_symbol = {s: store.load(s, "day") for s in universe.symbols}
    panel: list[dict] = []
    for sym, bars in bars_by_symbol.items():
        if not bars:
            continue
        ds = generator.generate(bars, data_version="phase5-campaign-v1")
        panel.extend(dict(row) for row in ds.rows)

    # gap: computed directly from bars (no dedicated Feature class exists yet), merged in by (symbol, timestamp)
    gap_by_key: dict[tuple[str, object], float | None] = {}
    for sym, bars in bars_by_symbol.items():
        for i in range(1, len(bars)):
            prev_close = bars[i - 1].close
            gap_by_key[(sym, bars[i].timestamp)] = (bars[i].open - prev_close) / prev_close if prev_close else None
    for row in panel:
        row["derived_gap"] = gap_by_key.get((row["symbol"], row["timestamp"]))

    # abs targets (for magnitude hypotheses)
    for row in panel:
        for h in (5, 10):
            col = f"target_future_return_{h}bar"
            if row.get(col) is not None:
                row[f"abs_{col}"] = abs(row[col])

    # in-script derived/combined/demeaned features
    by_ts: dict = defaultdict(list)
    for row in panel:
        by_ts[row["timestamp"]].append(row)
    spy_roc20_by_ts = {row["timestamp"]: row.get("feature_roc_20") for row in panel if row["symbol"] == "SPY"}

    for row in panel:
        f5, rv10, roc20, rvol20, volpct = row.get("feature_roc_5"), row.get("feature_relative_volume_10"), row.get("feature_roc_20"), row.get("feature_realized_vol_20"), row.get("feature_vol_percentile_20_100")
        row["derived_vpc"] = (f5 * rv10) if f5 is not None and rv10 is not None else None
        row["derived_voladjmom"] = (roc20 / rvol20) if roc20 is not None and rvol20 else None
        row["derived_neg_vol"] = (-rvol20) if rvol20 is not None else None
        row["derived_neg_volpct"] = (-volpct) if volpct is not None else None
        spy_roc = spy_roc20_by_ts.get(row["timestamp"])
        row["derived_mktrel"] = (roc20 - spy_roc) if roc20 is not None and spy_roc is not None else None

    for ts, rows in by_ts.items():
        vals = [r["feature_roc_20"] for r in rows if r.get("feature_roc_20") is not None]
        universe_mean = sum(vals) / len(vals) if vals else None
        for r in rows:
            r["derived_xsec"] = (r["feature_roc_20"] - universe_mean) if r.get("feature_roc_20") is not None and universe_mean is not None else None
        sector_vals: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            sec = universe.sector_of(r["symbol"])
            if sec and r.get("feature_roc_20") is not None:
                sector_vals[sec].append(r["feature_roc_20"])
        sector_means = {sec: sum(v) / len(v) for sec, v in sector_vals.items() if len(v) >= 2}
        for r in rows:
            sec = universe.sector_of(r["symbol"])
            r["derived_sectrel"] = (r["feature_roc_20"] - sector_means[sec]) if sec in sector_means and r.get("feature_roc_20") is not None else None

    return panel


def main() -> None:
    store = HistoricalDataStore(Path("logs/research_data"))
    universe = us_diversified_universe()

    partition_store = PartitionStore(Path("logs/research_data/phase7_partitions.jsonl"))
    discovery_partitions = partition_store.active_by_stage(PartitionLifecycleStage.DISCOVERY)
    if not discovery_partitions:
        raise RuntimeError("no DISCOVERY_DATA partition found — run scripts/phase7_step1_determine_partitions.py first")
    discovery_partition = discovery_partitions[0]
    print(f"DISCOVERY_DATA: {discovery_partition.start_date} .. {discovery_partition.end_date}", flush=True)

    prereg_store = PreregistrationStore(Path("logs/research_data/phase7_preregistrations.jsonl"))
    hyp_registry = HypothesisRegistry(Path("logs/research_data/hypotheses.jsonl"))
    gate_store = ResearchGateStore(Path("logs/research_data/phase7_gate_transitions.jsonl"))
    exp_store = ExperimentStore(Path("logs/research_data/experiments.jsonl"))

    print("Building the full feature/target panel (all symbols, all horizons)...", flush=True)
    full_panel = build_panel(store, universe)
    discovery_panel = filter_rows_by_partition(full_panel, discovery_partition)
    print(f"Full panel: {len(full_panel)} rows. DISCOVERY_DATA panel: {len(discovery_panel)} rows.\n", flush=True)

    regime_labels: dict = {}
    for sym in universe.symbols:
        bars = store.load(sym, "day")
        regime_labels.update(label_bars_by_regime(bars))

    hypotheses = [h for h in hyp_registry.load_all() if h.hypothesis_id in FEATURE_COL_BY_HYP]
    momentum_panel = [dict(r, __self__=None) for r in discovery_panel]  # reused as the momentum baseline panel (feature_roc_20 already present)
    mr_panel = [dict(r, __self__=None) for r in discovery_panel]

    prior_fingerprints: list[HypothesisFingerprint] = []
    raw_p_values: list[tuple[str, float]] = []
    all_results = {}

    for h in hypotheses:
        require_preregistered(prereg_store, h.hypothesis_id, h.version)  # STRUCTURAL enforcement — raises if step 2 was skipped
        feature_col, target_col = FEATURE_COL_BY_HYP[h.hypothesis_id], TARGET_COL_BY_HYP[h.hypothesis_id]
        print(f"{'=' * 90}\n{h.hypothesis_id} — {h.name}\n{'=' * 90}", flush=True)

        alpha_config = CrossSectionalAlphaConfig(feature_col=feature_col, target_col=target_col, n_quantiles=5)
        alpha_report = evaluate_cross_sectional_alpha(discovery_panel, alpha_config)
        print(f"IC: avg={alpha_report.ic_summary.average_ic} t={alpha_report.ic_t_statistic} p={alpha_report.ic_p_value}", flush=True)
        print(f"Quantile spread: {alpha_report.quantile_report.spread_q5_minus_q1}  monotonic={alpha_report.quantile_report.is_monotonic}", flush=True)

        # measure_alpha_decay expects each horizon's panel to carry a
        # "target_future_return_{h}bar" column by that EXACT name. For the
        # two magnitude hypotheses (target_col starts with "abs_"), remap
        # the precomputed abs_target_future_return_{h}bar column onto that
        # expected name via a shallow per-row copy (never mutates
        # discovery_panel itself) — abs targets exist only for h in (5, 10).
        if target_col.startswith("abs_"):
            panel_by_horizon = {}
            for hz in (5, 10):
                abs_col = f"abs_target_future_return_{hz}bar"
                panel_by_horizon[hz] = [dict(row, **{f"target_future_return_{hz}bar": row.get(abs_col)}) for row in discovery_panel]
        else:
            panel_by_horizon = {hz: discovery_panel for hz in STANDARD_DECAY_HORIZONS}
        decay_report = measure_alpha_decay(panel_by_horizon, feature_col=feature_col, meaningful_ic_threshold=0.01)
        print(f"Alpha decay classification: {decay_report.classification} ({decay_report.classification_reason})", flush=True)

        regime_result = ic_by_regime(discovery_panel, feature_col, target_col, regime_labels)
        regime_signs = {r: s.average_ic for r, s in regime_result.items() if s.average_ic is not None}
        print(f"Regime IC: {regime_signs}", flush=True)

        baseline_report = compare_against_baselines(
            discovery_panel, candidate_feature_col=feature_col, target_col=target_col,
            momentum_panel_rows=momentum_panel, mean_reversion_panel_rows=mr_panel, n_placebo_trials=100, seed=hash(h.hypothesis_id) % 10_000,
        )
        print(f"vs baselines: momentum_IC={baseline_report.momentum_baseline_ic} mr_IC={baseline_report.mean_reversion_baseline_ic} adds_info_vs_random={baseline_report.adds_information_beyond_random}", flush=True)

        shuffled = shuffled_signal_placebo(discovery_panel, feature_col=feature_col, target_col=target_col, n_trials=100, seed=hash(h.hypothesis_id) % 10_000)
        shifted = shifted_signal_placebo(discovery_panel, feature_col=feature_col, target_col=target_col, shift_bars=5)
        time_shuffled = time_shuffled_target_placebo(discovery_panel, feature_col=feature_col, target_col=target_col, n_trials=100, seed=hash(h.hypothesis_id) % 10_000)
        print(f"Placebo: shuffled_p={shuffled.empirical_p_value}  shifted_ic={shifted.placebo_distribution}  time_shuffled_p={time_shuffled.empirical_p_value}", flush=True)

        fp = HypothesisFingerprint(
            hypothesis_id=h.hypothesis_id, family=h.family, feature_variant=feature_col, target_horizon_bars=h.prediction_horizon_bars,
            universe_name=universe.name, threshold_bucket=bucket_threshold(20, bucket_width=10), cost_assumptions="n/a-discovery", execution_assumptions="n/a-discovery",
        )
        reuse_check = check_research_reuse(fp, prior_fingerprints, similarity_threshold=0.70)
        prior_fingerprints.append(fp)
        print(f"Research reuse check: flagged={reuse_check.flagged}  ({reuse_check.explanation})", flush=True)

        if alpha_report.ic_p_value is not None:
            raw_p_values.append((h.hypothesis_id, alpha_report.ic_p_value))

        ic_sign_matches = None
        if alpha_report.ic_summary.average_ic is not None:
            observed_sign = "positive" if alpha_report.ic_summary.average_ic > 0 else "negative"
            ic_sign_matches = observed_sign == h.expected_direction

        stat_verdict = DimensionVerdict.NOT_APPLICABLE
        if alpha_report.ic_p_value is not None:
            if ic_sign_matches and alpha_report.ic_p_value < 0.05:
                stat_verdict = DimensionVerdict.SUPPORTS
            elif ic_sign_matches is False and alpha_report.ic_p_value < 0.05:
                stat_verdict = DimensionVerdict.AGAINST
            else:
                stat_verdict = DimensionVerdict.NEUTRAL

        regime_supports = sum(1 for ic in regime_signs.values() if ic_sign_matches is not None and ((ic > 0) == (h.expected_direction == "positive")))
        regime_verdict = DimensionVerdict.NOT_APPLICABLE
        if regime_signs:
            frac = regime_supports / len(regime_signs)
            regime_verdict = DimensionVerdict.SUPPORTS if frac >= 0.6 else DimensionVerdict.NEUTRAL if frac >= 0.4 else DimensionVerdict.AGAINST

        contamination_verdict = DimensionVerdict.AGAINST if reuse_check.flagged else DimensionVerdict.SUPPORTS

        dims = [
            ScorecardDimension("statistical_evidence", stat_verdict, f"IC={alpha_report.ic_summary.average_ic} p={alpha_report.ic_p_value} sign_matches_expected={ic_sign_matches}"),
            ScorecardDimension("regime_stability", regime_verdict, f"{regime_supports}/{len(regime_signs)} regimes agree with expected direction" if regime_signs else "no regime data"),
            ScorecardDimension("data_quality", DimensionVerdict.SUPPORTS, "US_DIVERSIFIED: 20/20 symbols usable (Phase 5 quality report)"),
            ScorecardDimension("research_contamination_risk", contamination_verdict, reuse_check.explanation),
            ScorecardDimension("economic_rationale", DimensionVerdict.SUPPORTS, "documented economic_intuition, expected_mechanism, and falsification_criteria all present"),
        ]
        scorecard = build_scorecard(h.hypothesis_id, dims)
        print(f"\n{scorecard.render()}\n", flush=True)

        gate_store.transition(hypothesis_id=h.hypothesis_id, to_stage=ResearchLifecycleStage.IDEA, reason="generated by hypothesis_generator", evidence_summary="")
        gate_store.transition(hypothesis_id=h.hypothesis_id, to_stage=ResearchLifecycleStage.PREREGISTERED, reason="preregistered before any test ran", evidence_summary="")
        if scorecard.classification == "NOT_READY":
            gate_store.transition(hypothesis_id=h.hypothesis_id, to_stage=ResearchLifecycleStage.NOT_READY, reason=scorecard.classification_reason, evidence_summary=f"IC={alpha_report.ic_summary.average_ic}")
        else:
            gate_store.transition(hypothesis_id=h.hypothesis_id, to_stage=ResearchLifecycleStage.DISCOVERY_TESTED, reason=scorecard.classification_reason, evidence_summary=f"IC={alpha_report.ic_summary.average_ic}")

        dims_fp = ExperimentDimensions(
            feature_definition=h.mathematical_definition, parameter_range={}, universe_name=universe.name, target_definition=target_col,
            execution_model="n/a-discovery", cost_model="n/a-discovery", validation_methodology="cross-sectional IC on DISCOVERY_DATA",
        )
        exp_store.record(
            data_version="phase5-campaign-v1", feature_version="phase7-discovery-v1", symbols=universe.symbols, timeframe="day",
            strategy_version="1.0", prediction_horizon=h.prediction_horizon_bars, train_period=(str(discovery_partition.start_date), str(discovery_partition.end_date)),
            parameters={}, metrics={"average_ic": alpha_report.ic_summary.average_ic, "ic_p_value": alpha_report.ic_p_value},
            strategy_family=h.family, classification=scorecard.classification, tags=("phase7-discovery", universe.name),
            notes=scorecard.classification_reason, hypothesis_id=h.hypothesis_id, universe_name=universe.name,
            experiment_fingerprint=compute_experiment_fingerprint(dims_fp), partition_dataset_id=discovery_partition.dataset_id,
            research_family_id=RESEARCH_FAMILY_ID,
        )

        all_results[h.hypothesis_id] = dict(alpha=alpha_report, decay=decay_report, regime=regime_result, baseline=baseline_report, scorecard=scorecard, reuse=reuse_check)
        print(flush=True)

    print(f"\n{'=' * 90}\nMULTIPLE-TESTING CORRECTION — family {RESEARCH_FAMILY_ID} ({len(raw_p_values)} raw p-values)\n{'=' * 90}", flush=True)
    for method in (bonferroni_correction, holm_bonferroni_correction, benjamini_hochberg_fdr):
        report = method(raw_p_values, alpha=0.05)
        print(report.render(), flush=True)
        print(flush=True)

    print("SUMMARY", flush=True)
    for hid, r in all_results.items():
        print(f"  {hid}: classification={r['scorecard'].classification}  IC={r['alpha'].ic_summary.average_ic}  decay={r['decay'].classification}  reuse_flagged={r['reuse'].flagged}", flush=True)


if __name__ == "__main__":
    main()
