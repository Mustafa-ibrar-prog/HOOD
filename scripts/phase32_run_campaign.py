#!/usr/bin/env python3
"""Phase 32 — runs the real `bucketed_options_alpha` campaign against
the real, certified free dataset, end to end: audit density -> select a
bucket scheme -> build the causal bucket panel -> evaluate all 14
hypotheses -> multiple-testing correction -> classify -> gate-check ->
tradeability -> Phase 31 comparison.

Reuses `scripts.phase31_run_campaign.build_real_store` directly (same
real ingestion directory list, no re-fetch, no new download).

Writes a full JSON result to logs/research_data/phase32_results.json and
prints a human-readable summary to stdout.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.phase31_run_campaign import build_real_store  # noqa: E402
from src.options.phase31_panel_builder import build_panel_rows  # noqa: E402
from src.options.phase32_campaign import Phase32Report, run_campaign  # noqa: E402
from src.options.phase32_density_audit import (  # noqa: E402
    build_density_report,
    compute_bucket_density,
    count_duplicate_observations,
    count_impossible_prices,
)
from src.options.phase32_bucket_definitions import COARSE_SCHEME, FINE_SCHEME  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = REPO_ROOT / "logs/research_data/phase32_results.json"
HYPOTHESIS_REGISTRY_PATH = REPO_ROOT / "logs/research_data/phase32_hypotheses.jsonl"
PREREGISTRATION_PATH = REPO_ROOT / "logs/research_data/phase32_preregistration.jsonl"


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
    print("=" * 100, "\nPHASE 32 -- BUCKETED OPTIONS ALPHA DISCOVERY -- REAL CAMPAIGN RUN\n", "=" * 100, sep="", flush=True)
    store = build_real_store()

    print("\nBuilding the real contract-day panel (Phase 31's builder, reused unmodified)...", flush=True)
    contract_day_rows = build_panel_rows(store, max_contracts_per_underlying=6000)
    print(f"Real contract-day rows: {len(contract_day_rows)}", flush=True)

    print("\n" + "=" * 100 + "\nDENSITY AUDIT (Part 2)\n" + "=" * 100, flush=True)
    density = build_density_report(contract_day_rows)
    print(f"underlying/date cells: {len(density)}", flush=True)
    dup = count_duplicate_observations(contract_day_rows)
    impossible = count_impossible_prices(contract_day_rows)
    print(f"duplicate observations: {dup}", flush=True)
    print(f"impossible prices: {impossible}", flush=True)
    fine_cells = compute_bucket_density(contract_day_rows, FINE_SCHEME)
    coarse_cells = compute_bucket_density(contract_day_rows, COARSE_SCHEME)
    print(f"FINE scheme bucket cells: {len(fine_cells)}", flush=True)
    print(f"COARSE scheme bucket cells: {len(coarse_cells)}", flush=True)

    print("\nRunning the bucketed campaign (this may take a few minutes)...", flush=True)
    report = run_campaign(
        store,
        max_contracts_per_underlying=6000,
        n_placebo_trials=25,
        n_bootstrap_resamples=100,
        hypothesis_registry_path=HYPOTHESIS_REGISTRY_PATH,
        preregistration_store_path=PREREGISTRATION_PATH,
    )

    print(f"\nScheme selected: {report.scheme_selection.chosen_scheme.name}", flush=True)
    print(f"Reason: {report.scheme_selection.reason}", flush=True)
    print(f"Bucket-day rows: {report.n_bucket_rows} (from {report.n_contract_day_rows} real contract-day rows)", flush=True)
    print(f"Underlyings with bucket coverage: {report.underlyings}", flush=True)

    print("\n" + "=" * 100 + "\nCLASSIFICATIONS\n" + "=" * 100, flush=True)
    for h in report.hypotheses:
        r = report.results[h.hypothesis_id]
        ic = r.base_evidence.cross_sectional.report.ic_summary.average_ic if (r.base_evidence.cross_sectional.applicable and r.base_evidence.cross_sectional.report) else None
        print(f"\n{h.hypothesis_id} ({h.name}): {r.classification.value.upper()}  tradeability={r.tradeability.value.upper()}", flush=True)
        print(f"  feature={r.base_evidence.feature_col} target={r.base_evidence.target_col} horizon={r.base_evidence.primary_horizon}d  "
              f"IC={ic}  BH_sig={r.base_evidence.bh_significant} (p_adj={r.base_evidence.bh_adjusted_p})", flush=True)
        print(f"  reason: {r.classification_reason}", flush=True)
        print(f"  gate: {'PASSED' if r.gate.passed else 'FAILED'} (failing: {r.gate.failing_criteria})", flush=True)

    mtc = report.multiple_testing
    print("\n" + "=" * 100 + "\nMULTIPLE TESTING SUMMARY\n" + "=" * 100, flush=True)
    print(f"  Bonferroni significant: {mtc['bonferroni'].n_significant}/14", flush=True)
    print(f"  Holm significant: {mtc['holm'].n_significant}/14", flush=True)
    print(f"  Benjamini-Hochberg significant: {mtc['benjamini_hochberg'].n_significant}/14", flush=True)

    print("\n" + "=" * 100 + "\nPHASE 31 COMPARISON\n" + "=" * 100, flush=True)
    for k, v in report.phase31_comparison.items():
        print(f"  {k}: {v}", flush=True)

    supported = [h.hypothesis_id for h in report.hypotheses if report.results[h.hypothesis_id].classification.value == "discovery_supported"]
    promising = [h.hypothesis_id for h in report.hypotheses if report.results[h.hypothesis_id].classification.value == "promising"]
    gate_passed = [h.hypothesis_id for h in report.hypotheses if report.results[h.hypothesis_id].gate.passed]
    print(f"\nDISCOVERY_SUPPORTED: {supported}", flush=True)
    print(f"PROMISING: {promising}", flush=True)
    print(f"GATE PASSED (all 12 criteria): {gate_passed}", flush=True)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    serializable = {
        "n_contract_day_rows": report.n_contract_day_rows,
        "n_bucket_rows": report.n_bucket_rows,
        "underlyings": list(report.underlyings),
        "scheme_selection": {
            "chosen_scheme": report.scheme_selection.chosen_scheme.name,
            "fine_cells_meeting_threshold": report.scheme_selection.fine_cells_meeting_threshold,
            "coarse_cells_meeting_threshold": report.scheme_selection.coarse_cells_meeting_threshold,
            "reason": report.scheme_selection.reason,
        },
        "density": {
            "n_underlying_date_cells": len(density), "duplicate_observations": dup, "impossible_prices": impossible,
            "n_fine_bucket_cells": len(fine_cells), "n_coarse_bucket_cells": len(coarse_cells),
        },
        "classifications": {hid: {"classification": r.classification.value, "reason": r.classification_reason, "tradeability": r.tradeability.value} for hid, r in report.results.items()},
        "gate_results": {
            hid: {"passed": r.gate.passed, "failing_criteria": list(r.gate.failing_criteria),
                  "criteria": [{"number": c.number, "name": c.name, "passed": c.passed, "detail": c.detail} for c in r.gate.criteria]}
            for hid, r in report.results.items()
        },
        "multiple_testing": {
            method: {"n_tests": r.n_tests, "n_significant": r.n_significant, "alpha": r.alpha,
                      "results": [{"label": x.label, "raw_p": x.raw_p_value, "adjusted_p": x.adjusted_p_value, "significant": x.significant_at_alpha} for x in r.results]}
            for method, r in mtc.items()
        },
        "phase31_comparison": report.phase31_comparison,
        "evidence_summary": {
            hid: {
                "feature_col": r.base_evidence.feature_col, "target_col": r.base_evidence.target_col, "primary_horizon": r.base_evidence.primary_horizon,
                "average_ic": (r.base_evidence.cross_sectional.report.ic_summary.average_ic if (r.base_evidence.cross_sectional.applicable and r.base_evidence.cross_sectional.report) else None),
                "ic_p_value": (r.base_evidence.cross_sectional.report.ic_p_value if (r.base_evidence.cross_sectional.applicable and r.base_evidence.cross_sectional.report) else None),
                "quantile_spread": (r.base_evidence.cross_sectional.report.quantile_report.spread_q5_minus_q1 if (r.base_evidence.cross_sectional.applicable and r.base_evidence.cross_sectional.report) else None),
                "cross_sectional_applicable": r.base_evidence.cross_sectional.applicable, "cross_sectional_reason": r.base_evidence.cross_sectional.reason,
                "pooled_time_series": (_to_plain(r.pooled_time_series) if r.pooled_time_series else None),
                "n_symbols_eligible": r.symbol_balanced.n_symbols_eligible,
                "symbol_balanced_spearman": r.symbol_balanced.symbol_balanced_spearman,
                "dominated_by_single_symbol": r.symbol_balanced.dominated_by_single_symbol,
                "dominant_symbol": r.symbol_balanced.dominant_symbol,
                "weighting_materially_disagree": r.weighting_comparison.materially_disagree,
                "underlying_control_classification": (r.base_evidence.underlying_control.classification if r.base_evidence.underlying_control else None),
                "underlying_control_delta_r_squared": (r.base_evidence.underlying_control.delta_r_squared if r.base_evidence.underlying_control else None),
                "robustness_fragile": r.base_evidence.robustness.fragile,
                "bootstrap_ci": ([r.base_evidence.bootstrap.lower_bound, r.base_evidence.bootstrap.upper_bound] if r.base_evidence.bootstrap else None),
                "outlier_dependent": r.outlier_removal.outlier_dependent,
                "placebo_shuffled_signal_p": (r.base_evidence.placebo_results.get("shuffled_signal_placebo").empirical_p_value if r.base_evidence.placebo_results.get("shuffled_signal_placebo") else None),
                "bucket_affordability_median_premium": r.bucket_affordability.median_premium_usd,
                "bucket_affordability_p25": r.bucket_affordability.p25_premium_usd,
                "bucket_affordability_p75": r.bucket_affordability.p75_premium_usd,
                "bucket_affordability_pct_affordable": r.bucket_affordability.pct_affordable,
                "bh_significant": r.base_evidence.bh_significant, "bh_adjusted_p": r.base_evidence.bh_adjusted_p,
            }
            for hid, r in report.results.items()
        },
    }
    with RESULTS_PATH.open("w") as f:
        json.dump(serializable, f, indent=2, default=str)
    print(f"\nFull results written to {RESULTS_PATH}", flush=True)
    print("\nPHASE 32 CAMPAIGN COMPLETE. No trade placed. No strategy created. No data purchased.", flush=True)


if __name__ == "__main__":
    main()
