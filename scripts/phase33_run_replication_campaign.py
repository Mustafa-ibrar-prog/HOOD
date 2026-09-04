#!/usr/bin/env python3
"""Phase 33, Parts C-N/24 — runs the real P22-OPT-013 coarse-grained
replication campaign against the real, certified free dataset.

Reuses `scripts.phase31_run_campaign.build_real_store` directly (same
real ingestion directory list, no re-fetch, no new download).

Writes a full JSON result to
logs/research_data/phase33_replication_results.json and prints a
human-readable summary to stdout.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.phase31_run_campaign import build_real_store  # noqa: E402
from src.options.phase33_replication_campaign import ReplicationReport, run_replication_campaign  # noqa: E402
from src.options.phase33_replication_hypotheses import PRIMARY_HYPOTHESIS_ID  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = REPO_ROOT / "logs/research_data/phase33_replication_results.json"
HYPOTHESIS_REGISTRY_PATH = REPO_ROOT / "logs/research_data/phase33_replication_hypotheses.jsonl"
PREREGISTRATION_PATH = REPO_ROOT / "logs/research_data/phase33_replication_preregistration.jsonl"


def _to_plain(obj):
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_plain(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    if hasattr(obj, "value") and hasattr(type(obj), "__members__"):
        return obj.value
    return obj


def main() -> None:
    print("=" * 100, "\nPHASE 33 PARTS C-N -- P22-OPT-013 COARSE-GRAINED REPLICATION -- REAL DATA RUN\n", "=" * 100, sep="", flush=True)
    store = build_real_store()

    print("\nRunning the replication campaign (this may take a few minutes)...", flush=True)
    report: ReplicationReport = run_replication_campaign(
        store,
        max_contracts_per_underlying=6000,
        n_placebo_trials=25,
        n_bootstrap_resamples=100,
        hypothesis_registry_path=HYPOTHESIS_REGISTRY_PATH,
        preregistration_store_path=PREREGISTRATION_PATH,
    )

    print(f"\nScheme selected: {report.scheme_selection.chosen_scheme.name}", flush=True)
    print(f"Contract-day rows: {report.n_contract_day_rows}", flush=True)
    print(f"Bucket-day rows: {report.n_bucket_rows}", flush=True)
    print(f"Bucket-day rows with a real range-expansion value: {report.n_rows_with_range_expansion}", flush=True)

    print("\n" + "=" * 100 + "\nEXPIRATION / YEAR CONCENTRATION (Part G/H)\n" + "=" * 100, flush=True)
    ec, yc = report.expiration_concentration, report.year_concentration
    print(f"Expirations: n_rows={ec.n_rows} n_distinct={ec.n_distinct} top={ec.top_value} top_share={ec.top_share}", flush=True)
    print(f"Years: n_rows={yc.n_rows} n_distinct={yc.n_distinct} top={yc.top_value} top_share={yc.top_share}", flush=True)
    print(f"Full year counts: {yc.counts}", flush=True)
    print(f"Full expiration counts: {ec.counts}", flush=True)

    print("\n" + "=" * 100 + "\nPER-HYPOTHESIS RESULTS (Parts D/E/F/G/K)\n" + "=" * 100, flush=True)
    for h in report.hypotheses:
        r = report.results[h.hypothesis_id]
        ev = r.base_result.base_evidence
        ic = ev.cross_sectional.report.ic_summary.average_ic if (ev.cross_sectional.applicable and ev.cross_sectional.report) else None
        pooled = r.base_result.pooled_time_series
        print(f"\n{h.hypothesis_id} ({h.name})  [{'PRIMARY' if r.is_primary else 'secondary'}]", flush=True)
        print(f"  target={h.target_definition}  classification={r.classification.value.upper()}  tradeability={r.tradeability.value.upper()}", flush=True)
        print(f"  cross_sectional_IC={ic}  pooled_spearman={(pooled.spearman_correlation if pooled else None)}  BH_sig={ev.bh_significant} (p_adj={ev.bh_adjusted_p})", flush=True)
        print(f"  underlying_control={getattr(ev.underlying_control, 'classification', None)}  robustness_fragile={ev.robustness.fragile}", flush=True)
        print(f"  dte_balanced={r.dte_balanced.group_balanced_spearman}  moneyness_balanced={r.moneyness_balanced.group_balanced_spearman}  call_put_balanced={r.call_put_balanced.group_balanced_spearman}", flush=True)
        print(f"  non_overlap: before_IC={r.non_overlap.cross_sectional_before_ic} after_IC={r.non_overlap.cross_sectional_after_ic} after_p={r.non_overlap.cross_sectional_after_p} n_after={r.non_overlap.n_rows_after}", flush=True)
        print(f"  outlier_dependent={r.base_result.outlier_removal.outlier_dependent}", flush=True)
        print(f"  reason: {r.classification_reason}", flush=True)
        print(f"  gate: {'PASSED' if r.gate.passed else 'FAILED'} (failing: {r.gate.failing_criteria})", flush=True)

    print("\n" + "=" * 100 + "\nMULTIPLE-TESTING REGISTRY (Part I)\n" + "=" * 100, flush=True)
    print(f"Total registered records: {len(report.registry.all())}", flush=True)
    print(f"PRIMARY: n_registered={report.primary_correction.n_registered} n_testable={report.primary_correction.n_with_p_value} "
          f"BH_sig={report.primary_correction.benjamini_hochberg.n_significant if report.primary_correction.benjamini_hochberg else 0}", flush=True)
    print(f"PLACEBO: n_registered={report.placebo_correction.n_registered} n_testable={report.placebo_correction.n_with_p_value} "
          f"BH_sig={report.placebo_correction.benjamini_hochberg.n_significant if report.placebo_correction.benjamini_hochberg else 0}", flush=True)

    print("\n" + "=" * 100 + "\nFINAL VERDICT (Part L/N)\n" + "=" * 100, flush=True)
    v = report.verdict
    print(f"did_replicate: {v.did_replicate}", flush=True)
    print(f"survived_underlying_control: {v.survived_underlying_control}", flush=True)
    print(f"survived_multiple_testing: {v.survived_multiple_testing}", flush=True)
    print(f"survived_outlier_removal: {v.survived_outlier_removal}", flush=True)
    print(f"survived_non_overlap: {v.survived_non_overlap}", flush=True)
    print(f"survived_concentration: {v.survived_concentration}", flush=True)
    print(f"is_directional: {v.is_directional}", flush=True)
    print(f"is_economically_tradeable: {v.is_economically_tradeable}", flush=True)
    print(f"passes_promising_gate: {v.passes_promising_gate}", flush=True)
    print(f"reason: {v.reason}", flush=True)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    serializable = {
        "n_contract_day_rows": report.n_contract_day_rows,
        "n_bucket_rows": report.n_bucket_rows,
        "n_rows_with_range_expansion": report.n_rows_with_range_expansion,
        "scheme_selection": {"chosen_scheme": report.scheme_selection.chosen_scheme.name, "reason": report.scheme_selection.reason},
        "expiration_concentration": _to_plain(ec),
        "year_concentration": _to_plain(yc),
        "classifications": {
            hid: {
                "classification": r.classification.value, "reason": r.classification_reason, "tradeability": r.tradeability.value,
                "is_primary": r.is_primary, "target": next(h.target_definition for h in report.hypotheses if h.hypothesis_id == hid),
                "bh_significant": r.base_result.base_evidence.bh_significant, "bh_adjusted_p": r.base_result.base_evidence.bh_adjusted_p,
                "gate_passed": r.gate.passed, "gate_failing_criteria": list(r.gate.failing_criteria),
                "underlying_control_classification": getattr(r.base_result.base_evidence.underlying_control, "classification", None),
                "robustness_fragile": r.base_result.base_evidence.robustness.fragile,
                "outlier_dependent": r.base_result.outlier_removal.outlier_dependent,
                "dte_balanced_spearman": r.dte_balanced.group_balanced_spearman,
                "moneyness_balanced_spearman": r.moneyness_balanced.group_balanced_spearman,
                "call_put_balanced_spearman": r.call_put_balanced.group_balanced_spearman,
                "non_overlap_ic_before": r.non_overlap.cross_sectional_before_ic,
                "non_overlap_ic_after": r.non_overlap.cross_sectional_after_ic,
                "non_overlap_p_after": r.non_overlap.cross_sectional_after_p,
                "bucket_affordability_pct_affordable": r.base_result.bucket_affordability.pct_affordable,
                "bucket_affordability_median_premium": r.base_result.bucket_affordability.median_premium_usd,
            }
            for hid, r in report.results.items()
        },
        "registry_accounting": {
            "total_records": len(report.registry.all()),
            "primary_n_registered": report.primary_correction.n_registered,
            "primary_n_testable": report.primary_correction.n_with_p_value,
            "primary_bh_significant": report.primary_correction.benjamini_hochberg.n_significant if report.primary_correction.benjamini_hochberg else 0,
            "placebo_n_registered": report.placebo_correction.n_registered,
            "placebo_n_testable": report.placebo_correction.n_with_p_value,
        },
        "all_registered_records": [_to_plain(r) for r in report.registry.all()],
        "verdict": _to_plain(v),
    }
    with RESULTS_PATH.open("w") as f:
        json.dump(serializable, f, indent=2, default=str)
    print(f"\nFull results written to {RESULTS_PATH}", flush=True)
    print("\nPHASE 33 REPLICATION CAMPAIGN COMPLETE. No trade placed. No strategy created. No data purchased.", flush=True)


if __name__ == "__main__":
    main()
