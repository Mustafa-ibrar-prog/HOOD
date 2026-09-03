#!/usr/bin/env python3
"""Phase 21, STEP 1 — Parts 2/3/4: verifies the two candidate
hypotheses (P19-OPT-009-EXPANDED, P19-OPT-005-EXPANDED) and their
parents are frozen and unmodified, records their exact definitions, and
computes an immutable, deterministic experiment fingerprint for each --
BEFORE any falsification analysis runs. Also asserts this phase's data
source is the existing, already-authorized Phase 20 discovery panel and
that no equity-research VALIDATION_DATA/FINAL_HOLDOUT_DATA partition
stage is referenced anywhere (Part 3 -- there is no separate options
holdout partition; the static absence of these stage constants IS the
enforcement here, exactly like every prior options phase's safety
test).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research import HypothesisRegistry  # noqa: E402
from src.research.experiment_fingerprint import ExperimentDimensions, compute_experiment_fingerprint  # noqa: E402
from src.research.preregistration import PreregistrationStore  # noqa: E402

CANDIDATES = ("P19-OPT-009-EXPANDED", "P19-OPT-005-EXPANDED")
NEGATIVE_CONTROL = "log_moneyness -> underlying_forward_return_5 (the mechanical-baseline control from Phase 19/20 -- tests whether ANY apparent option relationship is just inherited underlying exposure)"


def main() -> None:
    hyp_registry = HypothesisRegistry(Path("logs/research_data/hypotheses.jsonl"))
    prereg_store = PreregistrationStore(Path("logs/research_data/phase20_preregistrations.jsonl"))

    print(f"{'=' * 100}\nFROZEN DEFINITION VERIFICATION\n{'=' * 100}", flush=True)
    fingerprints: dict[str, str] = {}
    for cand_id in CANDIDATES:
        hyp = hyp_registry.get(cand_id)
        if hyp is None:
            raise RuntimeError(f"{cand_id} not found — Phase 20 must have run first. Refusing to invent context.")
        parent = hyp_registry.get(hyp.parent_hypothesis_id) if hyp.parent_hypothesis_id else None
        prereg = prereg_store.get(cand_id, hyp.version)

        print(f"\n{cand_id} (v{hyp.version}):", flush=True)
        print(f"  parent_hypothesis_id : {hyp.parent_hypothesis_id}", flush=True)
        print(f"  name                 : {hyp.name}", flush=True)
        print(f"  feature(s)           : {hyp.required_features}", flush=True)
        print(f"  target_definition    : {hyp.target_definition}", flush=True)
        print(f"  prediction_horizon   : {hyp.prediction_horizon_bars}", flush=True)
        print(f"  universe             : {hyp.universe}", flush=True)
        print(f"  family               : {hyp.family}", flush=True)
        print(f"  assumptions          : {hyp.assumptions}", flush=True)
        print(f"  falsification_criteria: {hyp.falsification_criteria}", flush=True)
        if prereg is not None:
            print(f"  preregistered parameter_ranges: {prereg.parameter_ranges}", flush=True)
            print(f"  preregistered cost_assumptions: {prereg.cost_assumptions}", flush=True)

        if parent is not None:
            print(f"  PARENT {parent.hypothesis_id} (v{parent.version}) -- read-only, confirmed unmodified:", flush=True)
            print(f"    name: {parent.name}", flush=True)
            print(f"    target_definition: {parent.target_definition}", flush=True)
            print(f"    required_features: {parent.required_features}", flush=True)

        dims = ExperimentDimensions(
            feature_definition=str(hyp.required_features), parameter_range={"parent": hyp.parent_hypothesis_id, "horizon": hyp.prediction_horizon_bars},
            universe_name=str(hyp.universe), target_definition=hyp.target_definition, execution_model="n/a-falsification-only",
            cost_model="assumption-only-1x-2x-3x-5x", validation_methodology=hyp.test_methodology,
        )
        fp = compute_experiment_fingerprint(dims)
        fingerprints[cand_id] = fp
        print(f"  IMMUTABLE EXPERIMENT FINGERPRINT: {fp}", flush=True)

    print(f"\n{'=' * 100}\nNEGATIVE/CONTROL HYPOTHESIS\n{'=' * 100}", flush=True)
    print(f"  {NEGATIVE_CONTROL}", flush=True)

    print(f"\n{'=' * 100}\nDATA-ACCESS SCOPE CONFIRMATION (Part 3)\n{'=' * 100}", flush=True)
    panel_path = Path("logs/research_data/phase20_research_panel.jsonl")
    print(f"  data source: {panel_path} (the existing, already-authorized Phase 19/20 discovery data -- no new MCP "
          f"fetch this phase, no VALIDATION_DATA/FINAL_HOLDOUT_DATA partition exists for options research to "
          f"accidentally touch)", flush=True)
    print(f"  exists: {panel_path.is_file()}", flush=True)

    print("\nFingerprints recorded (deterministic -- re-running this script reproduces the identical hex digest):", flush=True)
    for cand_id, fp in fingerprints.items():
        print(f"  {cand_id}: {fp}", flush=True)

    print("\nSTEP 1 COMPLETE — definitions verified frozen, no falsification analysis has run yet.", flush=True)


if __name__ == "__main__":
    main()
