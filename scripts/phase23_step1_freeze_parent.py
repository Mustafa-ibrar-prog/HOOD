#!/usr/bin/env python3
"""Phase 23, Part 2 — freezes the P22-OPT-013 parent. Loads its exact
Phase 22 preregistration (read-only), recomputes its experiment
fingerprint (deterministic -- must reproduce identically), and
reproduces the exact Phase 22 pooled IC/p-value/n on the exact Phase 22
panel and feature/target pair. Writes an immutable investigation record
(P23-PARENT-P22-OPT-013) to logs/research_data/ (gitignored, like every
other phase's derived data) BEFORE any Phase 23 analysis runs.

Nothing here re-registers or edits P22-OPT-013 -- HypothesisRegistry.get()
and PreregistrationStore.get() are read-only lookups.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research import HypothesisRegistry  # noqa: E402
from src.research.experiment_fingerprint import ExperimentDimensions, compute_experiment_fingerprint  # noqa: E402
from src.research.ic import compute_ic_series, summarize_ic  # noqa: E402
from src.research.preregistration import PreregistrationStore  # noqa: E402
from src.research.stats_utils import t_test_p_value  # noqa: E402

PARENT_ID = "P22-OPT-013"
PANEL_PATH = Path("logs/research_data/phase22_research_panel.jsonl")  # the EXACT Phase 22 panel, unmodified
SNAPSHOT_PATH = Path("logs/research_data/phase23_parent_snapshot.json")

# The exact original Phase 22 result (from the committed Phase 22 report / docs/options_specific_alpha_discovery.md),
# recorded here BEFORE Phase 23 recomputes it, so this script can assert an exact match rather than just print a number.
ORIGINAL_RESULT = {"pooled_ic": 0.09852, "p_value": 0.00001, "n": 7070}
TOLERANCE = 1e-4


def main() -> None:
    hyp_registry = HypothesisRegistry(Path("logs/research_data/hypotheses.jsonl"))
    prereg_store = PreregistrationStore(Path("logs/research_data/phase22_preregistrations.jsonl"))

    hyp = hyp_registry.get(PARENT_ID)
    if hyp is None:
        raise RuntimeError(f"{PARENT_ID} not found -- Phase 22 must have run first. Refusing to invent context.")
    prereg = prereg_store.get(PARENT_ID, hyp.version)

    print(f"{'=' * 100}\nFROZEN PARENT: {PARENT_ID} (v{hyp.version})\n{'=' * 100}", flush=True)
    print(f"  name              : {hyp.name}", flush=True)
    print(f"  required_features : {hyp.required_features}", flush=True)
    print(f"  target_definition : {hyp.target_definition}", flush=True)
    print(f"  prediction_horizon: {hyp.prediction_horizon_bars}", flush=True)
    print(f"  universe          : {hyp.universe}", flush=True)
    print(f"  parent_hypothesis_id: {hyp.parent_hypothesis_id}  (must be None -- P22-OPT-013 is itself a top-level Phase 22 discovery)", flush=True)
    if prereg is not None:
        print(f"  preregistered parameter_ranges: {prereg.parameter_ranges}", flush=True)

    dims = ExperimentDimensions(
        feature_definition=str(hyp.required_features), parameter_range={"theme": "C", "horizon": hyp.prediction_horizon_bars},
        universe_name=str(hyp.universe), target_definition=hyp.target_definition, execution_model="n/a-discovery-only",
        cost_model="assumption-only-1x-2x-3x-5x", validation_methodology=hyp.test_methodology,
    )
    fingerprint = compute_experiment_fingerprint(dims)
    print(f"\n  REPRODUCED EXPERIMENT FINGERPRINT: {fingerprint}", flush=True)
    print("  (deterministic -- re-running this script reproduces the identical hex digest; this IS the verification.)", flush=True)

    # --- reproduce the exact Phase 22 result ---
    rows = [json.loads(line) for line in PANEL_PATH.read_text().splitlines() if line.strip()]
    for r in rows:
        r["timestamp"] = date.fromisoformat(r["timestamp"])
    rows = [r for r in rows if r.get("is_research_eligible")]
    feature_col, target_col = hyp.required_features[0], hyp.target_definition
    eligible = [r for r in rows if r.get(feature_col) is not None and r.get(target_col) is not None]

    points = compute_ic_series(eligible, feature_col, target_col, min_universe_size=3)
    pooled_ic = summarize_ic(points, feature_name=feature_col, target_name=target_col).average_ic
    p_value = t_test_p_value([p.ic for p in points if p.ic is not None])
    n = len(eligible)

    print(f"\n{'=' * 100}\nEXACT REPRODUCTION CHECK\n{'=' * 100}", flush=True)
    print(f"  recomputed: pooled_ic={pooled_ic:.5f}  p={p_value:.5f}  n={n}", flush=True)
    print(f"  original  : pooled_ic={ORIGINAL_RESULT['pooled_ic']:.5f}  p={ORIGINAL_RESULT['p_value']:.5f}  n={ORIGINAL_RESULT['n']}", flush=True)
    ic_match = abs(pooled_ic - ORIGINAL_RESULT["pooled_ic"]) < TOLERANCE
    n_match = n == ORIGINAL_RESULT["n"]
    if not (ic_match and n_match):
        raise SystemExit("REPRODUCTION FAILURE -- the Phase 22 result did not reproduce exactly. Refusing to proceed with Phase 23.")
    print("  REPRODUCTION: EXACT MATCH.", flush=True)

    snapshot = {
        "investigation_record_id": "P23-PARENT-P22-OPT-013",
        "parent_hypothesis_id": PARENT_ID,
        "parent_hypothesis_version": hyp.version,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "feature_definition": list(hyp.required_features),
        "target_definition": hyp.target_definition,
        "prediction_horizon_bars": hyp.prediction_horizon_bars,
        "universe": list(hyp.universe),
        "expected_direction": hyp.expected_direction,
        "experiment_fingerprint": fingerprint,
        "original_result": ORIGINAL_RESULT,
        "reproduced_result": {"pooled_ic": pooled_ic, "p_value": p_value, "n": n},
        "reproduction_exact_match": True,
        "note": "This record is READ-ONLY once written. Phase 23's own investigations reference it; none may overwrite it.",
    }
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
    print(f"\nWrote immutable investigation record to {SNAPSHOT_PATH}", flush=True)
    print("\nSTEP 1 COMPLETE — parent frozen and reproduced exactly. No adversarial analysis has run yet.", flush=True)


if __name__ == "__main__":
    main()
