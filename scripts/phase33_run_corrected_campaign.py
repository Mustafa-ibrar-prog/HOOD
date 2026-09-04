#!/usr/bin/env python3
"""Phase 33, Part A/24 — runs the CORRECTED `bucketed_options_alpha`
campaign against the real, certified free dataset, through the repaired
multiple-testing accounting machinery (`phase33_test_registry.py` +
`phase33_corrected_campaign.py`), and compares the result against Phase
32's already-published, real-data classifications
(`logs/research_data/phase32_results.json`, committed as
`docs/phase32_bucketed_options_alpha.md`'s source of truth).

Reuses `scripts.phase31_run_campaign.build_real_store` directly (same
real ingestion directory list, no re-fetch, no new download) and
`phase31_panel_builder.build_panel_rows` directly, exactly as
`scripts/phase32_run_campaign.py` did.

The `previous_results` comparison is built from the ALREADY-COMPUTED,
ALREADY-PUBLISHED Phase 32 JSON output rather than re-running Phase 32's
original (uncorrected) campaign a second time -- the published
classifications ARE "Phase 32's conclusions" that Part A's "if any Phase
32 conclusion changes, document exactly why" refers to, and reusing them
avoids a second, redundant full real-data evaluation pass (14 hypotheses
x placebo/bootstrap resampling) that would produce bit-identical results
anyway since `evaluate_one_bucket_hypothesis` is deterministic given the
same real data and the same trial counts.

Writes a full JSON result to
logs/research_data/phase33_corrected_results.json and prints a
human-readable summary to stdout.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.phase31_run_campaign import build_real_store  # noqa: E402
from src.options.phase31_classification import DiscoveryClassification  # noqa: E402
from src.options.phase33_corrected_campaign import CorrectedPhase32Report, run_corrected_campaign  # noqa: E402
from src.options.phase33_test_registry import DIAGNOSTIC_FAMILY, PLACEBO_FAMILY, PRIMARY_FAMILY  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
PHASE32_RESULTS_PATH = REPO_ROOT / "logs/research_data/phase32_results.json"
RESULTS_PATH = REPO_ROOT / "logs/research_data/phase33_corrected_results.json"
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


@dataclass(frozen=True)
class _PublishedResult:
    """A minimal stand-in exposing only what `run_corrected_campaign`'s
    `previous_results` comparison actually reads (`.classification`) --
    built from Phase 32's already-published JSON, not a fabricated
    re-evaluation."""

    classification: DiscoveryClassification


def _load_phase32_published_results() -> dict[str, _PublishedResult]:
    if not PHASE32_RESULTS_PATH.is_file():
        print(f"WARNING: {PHASE32_RESULTS_PATH} not found -- running without a previous-results comparison.", flush=True)
        return {}
    data = json.loads(PHASE32_RESULTS_PATH.read_text())
    out = {}
    for hid, c in data["classifications"].items():
        out[hid] = _PublishedResult(classification=DiscoveryClassification(c["classification"]))
    return out


def main() -> None:
    print("=" * 100, "\nPHASE 33 PART A -- CORRECTED MULTIPLE-TESTING CAMPAIGN -- REAL DATA RUN\n", "=" * 100, sep="", flush=True)
    store = build_real_store()
    previous_results = _load_phase32_published_results()
    print(f"Loaded {len(previous_results)} published Phase 32 classifications for comparison.", flush=True)

    print("\nRunning the corrected bucketed campaign (this may take a few minutes)...", flush=True)
    report: CorrectedPhase32Report = run_corrected_campaign(
        store,
        max_contracts_per_underlying=6000,
        n_placebo_trials=25,
        n_bootstrap_resamples=100,
        hypothesis_registry_path=HYPOTHESIS_REGISTRY_PATH,
        preregistration_store_path=PREREGISTRATION_PATH,
        previous_results=previous_results,
    )

    print(f"\nScheme selected: {report.scheme_selection.chosen_scheme.name}", flush=True)
    print(f"Bucket-day rows: {report.n_bucket_rows} (from {report.n_contract_day_rows} real contract-day rows)", flush=True)

    print("\n" + "=" * 100 + "\nTEST REGISTRY ACCOUNTING (Part A's core fix)\n" + "=" * 100, flush=True)
    all_records = report.registry.all()
    print(f"Total registered inferential test records: {len(all_records)}", flush=True)
    print(f"  PRIMARY_FAMILY ({PRIMARY_FAMILY}): {len(report.registry.by_family(PRIMARY_FAMILY))} records, "
          f"{report.primary_correction.n_with_p_value} testable -- Bonferroni sig={report.primary_correction.bonferroni.n_significant if report.primary_correction.bonferroni else 0}, "
          f"Holm sig={report.primary_correction.holm.n_significant if report.primary_correction.holm else 0}, "
          f"BH sig={report.primary_correction.benjamini_hochberg.n_significant if report.primary_correction.benjamini_hochberg else 0}", flush=True)
    print(f"  DIAGNOSTIC_FAMILY ({DIAGNOSTIC_FAMILY}): {len(report.registry.by_family(DIAGNOSTIC_FAMILY))} records (no p-value forced -- descriptive only)", flush=True)
    print(f"  PLACEBO_FAMILY ({PLACEBO_FAMILY}): {len(report.registry.by_family(PLACEBO_FAMILY))} records, "
          f"{report.placebo_correction.n_with_p_value} testable -- BH sig={report.placebo_correction.benjamini_hochberg.n_significant if report.placebo_correction.benjamini_hochberg else 0}", flush=True)

    old_primary_count = 14  # Phase 32's original: exactly one p-value (cross-sectional IC) per hypothesis
    print(f"\nPhase 32's ORIGINAL correction family size: {old_primary_count} (cross-sectional IC only, one per hypothesis)", flush=True)
    print(f"Phase 33's CORRECTED primary family size: {report.primary_correction.n_registered} registered "
          f"({report.primary_correction.n_with_p_value} testable)", flush=True)

    print("\n" + "=" * 100 + "\nCORRECTED CLASSIFICATIONS\n" + "=" * 100, flush=True)
    for h in report.hypotheses:
        r = report.results[h.hypothesis_id]
        print(f"\n{h.hypothesis_id} ({h.name}): {r.classification.value.upper()}  tradeability={r.tradeability.value.upper()}", flush=True)
        print(f"  BH_sig={r.base_evidence.bh_significant} (p_adj={r.base_evidence.bh_adjusted_p})", flush=True)
        print(f"  reason: {r.classification_reason}", flush=True)
        print(f"  gate: {'PASSED' if r.gate.passed else 'FAILED'} (failing: {r.gate.failing_criteria})", flush=True)

    print("\n" + "=" * 100 + "\nCHANGED CONCLUSIONS (vs Phase 32's published results)\n" + "=" * 100, flush=True)
    if report.changed_conclusions:
        for hid, why in report.changed_conclusions.items():
            print(f"  {hid}: {why}", flush=True)
    else:
        print("  No hypothesis's classification changed. The correction fix widened the corrected family "
              "(more conservative or equal thresholds) but did not flip any conclusion on this real dataset.", flush=True)

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
        "scheme_selection": {"chosen_scheme": report.scheme_selection.chosen_scheme.name, "reason": report.scheme_selection.reason},
        "registry_accounting": {
            "total_records": len(all_records),
            "primary_family": {
                "n_registered": report.primary_correction.n_registered,
                "n_with_p_value": report.primary_correction.n_with_p_value,
                "bonferroni_n_significant": report.primary_correction.bonferroni.n_significant if report.primary_correction.bonferroni else 0,
                "holm_n_significant": report.primary_correction.holm.n_significant if report.primary_correction.holm else 0,
                "bh_n_significant": report.primary_correction.benjamini_hochberg.n_significant if report.primary_correction.benjamini_hochberg else 0,
            },
            "diagnostic_family_n_records": len(report.registry.by_family(DIAGNOSTIC_FAMILY)),
            "placebo_family": {
                "n_registered": report.placebo_correction.n_registered,
                "n_with_p_value": report.placebo_correction.n_with_p_value,
                "bh_n_significant": report.placebo_correction.benjamini_hochberg.n_significant if report.placebo_correction.benjamini_hochberg else 0,
            },
            "old_phase32_primary_family_size_for_comparison": old_primary_count,
        },
        "all_registered_records": [_to_plain(r) for r in all_records],
        "classifications": {
            hid: {"classification": r.classification.value, "reason": r.classification_reason, "tradeability": r.tradeability.value,
                  "bh_significant": r.base_evidence.bh_significant, "bh_adjusted_p": r.base_evidence.bh_adjusted_p,
                  "gate_passed": r.gate.passed}
            for hid, r in report.results.items()
        },
        "changed_conclusions": report.changed_conclusions,
    }
    with RESULTS_PATH.open("w") as f:
        json.dump(serializable, f, indent=2, default=str)
    print(f"\nFull results written to {RESULTS_PATH}", flush=True)
    print("\nPHASE 33 PART A CAMPAIGN COMPLETE. No trade placed. No strategy created. No data purchased.", flush=True)


if __name__ == "__main__":
    main()
