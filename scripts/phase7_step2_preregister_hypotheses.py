#!/usr/bin/env python3
"""Phase 7, Part 12-14 — STEP 2: generates the 12 controlled,
economically-motivated hypotheses, PRINTS the full preregistered list
(Part 14's explicit requirement — before any experiment runs), then
writes each one to both the HypothesisRegistry (shared with Phases 4-6,
same file) and a dedicated PreregistrationStore. This must run BEFORE
scripts/phase7_step3_discovery_campaign.py — the campaign script calls
require_preregistered() and will refuse to run against any hypothesis
that skipped this step.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import us_diversified_universe  # noqa: E402
from src.research import HypothesisRegistry, generate_hypotheses, preregistration_from_hypothesis  # noqa: E402
from src.research.preregistration import PreregistrationStore  # noqa: E402


def main() -> None:
    universe = us_diversified_universe()
    hypotheses = generate_hypotheses(universe.symbols, benchmark_symbol="SPY")

    print(f"PHASE 7 PREREGISTERED HYPOTHESIS LIST ({len(hypotheses)} hypotheses, one per mechanism family)\n", flush=True)
    for h in hypotheses:
        print(f"[{h.hypothesis_id}] {h.name}  (family={h.family})", flush=True)
        print(f"  economic_intuition: {h.economic_intuition}", flush=True)
        print(f"  mathematical_definition: {h.mathematical_definition}", flush=True)
        print(f"  expected_direction: {h.expected_direction}  prediction_horizon_bars: {h.prediction_horizon_bars}", flush=True)
        print(f"  falsification_criteria: {h.falsification_criteria}", flush=True)
        print(flush=True)

    hyp_registry = HypothesisRegistry(Path("logs/research_data/hypotheses.jsonl"))
    prereg_store = PreregistrationStore(Path("logs/research_data/phase7_preregistrations.jsonl"))

    for h in hypotheses:
        if hyp_registry.get(h.hypothesis_id) is None:
            hyp_registry.register(h)
        record = preregistration_from_hypothesis(
            h, universe_name=universe.name, validation_methodology="cross-sectional IC/quantile analysis on DISCOVERY_DATA only — no backtest at this stage",
            cost_assumptions="not applicable at the discovery (IC-only) stage — no trades are simulated",
            success_criteria=(
                "average IC magnitude clearly distinguishable from a random-signal control (baseline_comparison.adds_information_beyond_random)",
                "shuffled-signal placebo empirical p-value < 0.10",
                "IC sign matches the hypothesis's pre-declared expected_direction",
            ),
        )
        if prereg_store.get(h.hypothesis_id, h.version) is None:
            prereg_store.register(record)

    print(f"Registered {len(hyp_registry.load_all())} total hypotheses in HypothesisRegistry (cumulative across all phases).", flush=True)
    print(f"Preregistered {len(prereg_store.load_all())} total records in PreregistrationStore.", flush=True)


if __name__ == "__main__":
    main()
