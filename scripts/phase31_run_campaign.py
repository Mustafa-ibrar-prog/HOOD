#!/usr/bin/env python3
"""Phase 31 — runs the real `options_alpha_round2` campaign against the
real, certified free dataset (Phase 26+27's combined QuantConnect/Lean
sample), end to end: preregister -> build the real panel -> evaluate all
16 hypotheses -> multiple-testing correction -> classify -> gate-check.

Reuses the EXACT same real ingestion directory list
`scripts/phase27_step1_build_expanded_dataset.py` uses (no re-fetch, no
new download -- the raw files are already on disk from Phase 26/27).

Writes a full JSON result to logs/research_data/phase31_results.json and
prints a human-readable summary to stdout.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.options.phase26_ingest import RAW_EXTRACTED_DIR as P26_EXTRACTED  # noqa: E402
from src.options.phase27_ingest import PHASE27_RAW_EXTRACTED_DIR as P27_EXTRACTED  # noqa: E402
from src.options.phase27_ingest import build_expanded_store_from_directories  # noqa: E402
from src.options.phase31_campaign import run_campaign  # noqa: E402

TODAY = date(2026, 9, 4)
REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = REPO_ROOT / "logs/research_data/phase31_results.json"
HYPOTHESIS_REGISTRY_PATH = REPO_ROOT / "logs/research_data/phase31_hypotheses.jsonl"
PREREGISTRATION_PATH = REPO_ROOT / "logs/research_data/phase31_preregistration.jsonl"


def build_real_store():
    retrieval_ts = datetime.now(timezone.utc)
    store, conflicts = build_expanded_store_from_directories(
        quote_dirs=[
            P26_EXTRACTED / "aapl_2014_quote", P26_EXTRACTED / "aapl_2015_quote", P26_EXTRACTED / "spy_20230803_quote",
            P27_EXTRACTED / "foxa_2013_quote", P27_EXTRACTED / "goog_2015_quote", P27_EXTRACTED / "nwsa_2013_quote", P27_EXTRACTED / "twx_2014_quote",
            P27_EXTRACTED / "goog_min_20151223_quote", P27_EXTRACTED / "goog_min_20151224_quote", P27_EXTRACTED / "goog_min_20151228_quote",
            P27_EXTRACTED / "foxa_min_20130702_quote", P27_EXTRACTED / "nwsa_min_20130628_quote",
            P27_EXTRACTED / "twx_min_20140605_quote", P27_EXTRACTED / "twx_min_20140606_quote",
            P27_EXTRACTED / "aapl_min_20140606_quote", P27_EXTRACTED / "aapl_min_20140609_quote",
        ],
        trade_dirs=[
            P26_EXTRACTED / "aapl_2014_trade", P26_EXTRACTED / "aapl_2015_trade", P26_EXTRACTED / "spy_20230803_trade",
            P27_EXTRACTED / "foxa_2013_trade", P27_EXTRACTED / "goog_2015_trade", P27_EXTRACTED / "nwsa_2013_trade", P27_EXTRACTED / "twx_2014_trade",
            P27_EXTRACTED / "goog_min_20151223_trade", P27_EXTRACTED / "goog_min_20151224_trade", P27_EXTRACTED / "goog_min_20151228_trade",
            P27_EXTRACTED / "foxa_min_20130702_trade", P27_EXTRACTED / "nwsa_min_20130628_trade",
            P27_EXTRACTED / "twx_min_20140605_trade", P27_EXTRACTED / "twx_min_20140606_trade",
            P27_EXTRACTED / "aapl_min_20140606_trade", P27_EXTRACTED / "aapl_min_20140609_trade",
        ],
        oi_dirs=[
            P26_EXTRACTED / "aapl_2014_oi",
            P27_EXTRACTED / "goog_2015_oi", P27_EXTRACTED / "twx_2014_oi",
            P27_EXTRACTED / "goog_min_20151223_oi", P27_EXTRACTED / "goog_min_20151224_oi",
            P27_EXTRACTED / "twx_min_20140605_oi", P27_EXTRACTED / "twx_min_20140606_oi",
            P27_EXTRACTED / "aapl_min_20140606_oi", P27_EXTRACTED / "aapl_min_20140609_oi",
        ],
        equity_files={
            "AAPL": P26_EXTRACTED / "aapl_equity" / "aapl.csv", "SPY": P26_EXTRACTED / "spy_equity" / "spy.csv",
            "GOOG": P27_EXTRACTED / "goog_equity" / "goog.csv", "FOXA": P27_EXTRACTED / "foxa_equity" / "foxa.csv",
            "NWSA": P27_EXTRACTED / "nwsa_equity" / "nwsa.csv",
        },
        retrieval_timestamp=retrieval_ts, today=TODAY,
    )
    print(f"Real store built: {len(store.contracts)} contracts, {len(conflicts)} merge conflicts.", flush=True)
    return store


def _to_jsonable(obj):
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, "value") and hasattr(type(obj), "__members__"):  # enum
        return obj.value
    if callable(obj) and not isinstance(obj, (int, float, str, bool)) and obj.__class__.__name__ not in ("NoneType",):
        try:
            json.dumps(obj)
        except TypeError:
            return repr(obj)
    return obj


def main() -> None:
    print("=" * 100, "\nPHASE 31 -- OPTIONS ALPHA DISCOVERY ROUND 2 -- REAL CAMPAIGN RUN\n", "=" * 100, sep="", flush=True)
    store = build_real_store()

    print("\nRunning campaign (this builds the real panel, evaluates all 16 hypotheses, and applies "
          "multiple-testing correction) -- this may take several minutes...", flush=True)
    report = run_campaign(
        store,
        max_contracts_per_underlying=80,
        n_placebo_trials=25,
        n_bootstrap_resamples=100,
        hypothesis_registry_path=HYPOTHESIS_REGISTRY_PATH,
        preregistration_store_path=PREREGISTRATION_PATH,
    )

    print(f"\nPanel rows: {report.n_panel_rows}", flush=True)
    print(f"Underlyings with daily coverage in the panel: {report.underlyings}", flush=True)

    print("\n" + "=" * 100 + "\nCLASSIFICATIONS\n" + "=" * 100, flush=True)
    for h in report.hypotheses:
        cls, reason = report.classifications[h.hypothesis_id]
        gate = report.gates[h.hypothesis_id]
        ev = report.evidence[h.hypothesis_id]
        ic = ev.cross_sectional.report.ic_summary.average_ic if (ev.cross_sectional.applicable and ev.cross_sectional.report) else None
        print(f"\n{h.hypothesis_id} ({h.name}): {cls.value.upper()}", flush=True)
        print(f"  feature={ev.feature_col} target={ev.target_col} horizon={ev.primary_horizon}d  IC={ic}  "
              f"BH_sig={ev.bh_significant} (p_adj={ev.bh_adjusted_p})", flush=True)
        print(f"  reason: {reason}", flush=True)
        print(f"  gate: {'PASSED' if gate.passed else 'FAILED'} (failing: {gate.failing_criteria})", flush=True)

    bh = report.multiple_testing["benjamini_hochberg"]
    bonf = report.multiple_testing["bonferroni"]
    holm = report.multiple_testing["holm"]
    print("\n" + "=" * 100 + "\nMULTIPLE TESTING SUMMARY\n" + "=" * 100, flush=True)
    print(f"  Bonferroni significant: {bonf.n_significant}/16", flush=True)
    print(f"  Holm significant: {holm.n_significant}/16", flush=True)
    print(f"  Benjamini-Hochberg significant: {bh.n_significant}/16", flush=True)

    supported = [h.hypothesis_id for h in report.hypotheses if report.classifications[h.hypothesis_id][0].value == "discovery_supported"]
    promising = [h.hypothesis_id for h in report.hypotheses if report.classifications[h.hypothesis_id][0].value == "promising"]
    print(f"\nDISCOVERY_SUPPORTED: {supported}", flush=True)
    print(f"PROMISING: {promising}", flush=True)
    gate_passed = [h.hypothesis_id for h in report.hypotheses if report.gates[h.hypothesis_id].passed]
    print(f"GATE PASSED (all 12 criteria): {gate_passed}", flush=True)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    serializable = {
        "n_panel_rows": report.n_panel_rows,
        "underlyings": list(report.underlyings),
        "hypotheses": [asdict(h) if False else {"hypothesis_id": h.hypothesis_id, "name": h.name} for h in report.hypotheses],
        "classifications": {hid: {"classification": cls.value, "reason": reason} for hid, (cls, reason) in report.classifications.items()},
        "gate_results": {
            hid: {"passed": g.passed, "failing_criteria": list(g.failing_criteria),
                  "criteria": [{"number": c.number, "name": c.name, "passed": c.passed, "detail": c.detail} for c in g.criteria]}
            for hid, g in report.gates.items()
        },
        "multiple_testing": {
            method: {"n_tests": r.n_tests, "n_significant": r.n_significant, "alpha": r.alpha,
                      "results": [{"label": x.label, "raw_p": x.raw_p_value, "adjusted_p": x.adjusted_p_value, "significant": x.significant_at_alpha} for x in r.results]}
            for method, r in report.multiple_testing.items()
        },
        "evidence_summary": {
            hid: {
                "feature_col": ev.feature_col, "target_col": ev.target_col, "primary_horizon": ev.primary_horizon,
                "average_ic": (ev.cross_sectional.report.ic_summary.average_ic if (ev.cross_sectional.applicable and ev.cross_sectional.report) else None),
                "ic_p_value": (ev.cross_sectional.report.ic_p_value if (ev.cross_sectional.applicable and ev.cross_sectional.report) else None),
                "quantile_spread": (ev.cross_sectional.report.quantile_report.spread_q5_minus_q1 if (ev.cross_sectional.applicable and ev.cross_sectional.report) else None),
                "is_monotonic": (ev.cross_sectional.report.quantile_report.is_monotonic if (ev.cross_sectional.applicable and ev.cross_sectional.report) else None),
                "cross_sectional_applicable": ev.cross_sectional.applicable, "cross_sectional_reason": ev.cross_sectional.reason,
                "time_series_applicable": ev.time_series.applicable, "time_series_n_contracts_eligible": ev.time_series.n_contracts_eligible,
                "time_series_pooled_spearman": ev.time_series.pooled_spearman_mean, "time_series_sign_stable_fraction": ev.time_series.sign_stable_fraction,
                "underlying_control_classification": (ev.underlying_control.classification if ev.underlying_control else None),
                "underlying_control_delta_r_squared": (ev.underlying_control.delta_r_squared if ev.underlying_control else None),
                "underlying_control_option_ic": (ev.underlying_control.option_ic if ev.underlying_control else None),
                "underlying_control_underlying_ic": (ev.underlying_control.underlying_ic if ev.underlying_control else None),
                "robustness_fragile": ev.robustness.fragile,
                "robustness_sign_flips_underlyings": ev.robustness.sign_flips_across_underlyings,
                "robustness_sign_flips_years": ev.robustness.sign_flips_across_years,
                "temporal_alignment_concerns": [{"shift": t.shift, "true_ic": t.true_ic, "shifted_ic": t.shifted_ic, "concern": t.concern} for t in ev.temporal_alignment],
                "bootstrap_ci": ([ev.bootstrap.lower_bound, ev.bootstrap.upper_bound] if ev.bootstrap else None),
                "placebo_shuffled_signal_empirical_p": (ev.placebo_results.get("shuffled_signal_placebo").empirical_p_value if ev.placebo_results.get("shuffled_signal_placebo") else None),
                "affordability_avg_premium_usd": ev.affordability.average_premium_usd,
                "affordability_pct_affordable": ev.affordability.pct_affordable_with_account,
                "liquidity_pct_quote_available": ev.liquidity.pct_quote_available,
                "liquidity_avg_spread_pct": ev.liquidity.average_spread_pct,
                "cost_sensitivity": [{"multiplier": c.multiplier, "net_effect": c.net_effect, "survives": c.survives} for c in ev.cost_sensitivity],
                "outlier_trimmed_ic": ev.outlier_trimmed_ic,
                "bh_significant": ev.bh_significant, "bh_adjusted_p": ev.bh_adjusted_p,
            }
            for hid, ev in report.evidence.items()
        },
    }
    with RESULTS_PATH.open("w") as f:
        json.dump(serializable, f, indent=2, default=str)
    print(f"\nFull results written to {RESULTS_PATH}", flush=True)
    print("\nPHASE 31 CAMPAIGN COMPLETE. No trade placed. No strategy created. No data purchased.", flush=True)


if __name__ == "__main__":
    main()
