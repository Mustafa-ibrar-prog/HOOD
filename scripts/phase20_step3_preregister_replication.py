#!/usr/bin/env python3
"""Phase 20, STEP 3 — Part 9: preregisters the 5 replication runs
(P19-OPT-XXX-EXPANDED) for every Phase 19 hypothesis that was classified
DISCOVERY_SUPPORTED (004, 005, 008, 009, 012). Each new record's
`parent_hypothesis_id` points at the ORIGINAL, frozen Phase 19
hypothesis -- the original is never edited (this script only READS it to
assert it still exists unmodified) and no P19-OPT-* definition changes.
Must run AFTER scripts/phase20_step1_ingest_expanded_panel.py and
BEFORE scripts/phase20_step4_replication_campaign.py.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.options.universe import phase20_verified_underlying_universe  # noqa: E402
from src.research import Hypothesis, HypothesisRegistry  # noqa: E402
from src.research.preregistration import PreregistrationRecord, PreregistrationStore  # noqa: E402

PARENT_IDS = ("P19-OPT-004", "P19-OPT-005", "P19-OPT-008", "P19-OPT-009", "P19-OPT-012")

EXPANDED = {
    "P19-OPT-004-EXPANDED": ("Deep-OTM tail-risk replication", "P19-OPT-004", "Does the deep-OTM > ITM/ATM forward-return dispersion finding survive a 12-underlying, 3-expiration panel?", ("moneyness_bucket",)),
    "P19-OPT-005-EXPANDED": ("Call/put asymmetry replication", "P19-OPT-005", "Does the call/put mean forward-return asymmetry survive the expanded panel?", ("call_put",)),
    "P19-OPT-008-EXPANDED": ("Per-underlying moneyness-IC stability replication", "P19-OPT-008", "Does log_moneyness's cross-sectional IC keep a consistent sign across all 12 underlyings (not just 4)?", ("log_moneyness",)),
    "P19-OPT-009-EXPANDED": ("Horizon stability replication", "P19-OPT-009", "Does log_moneyness's IC keep a consistent sign across horizons 1/3/5/10/20 on the expanded, multi-expiration panel?", ("log_moneyness",)),
    "P19-OPT-012-EXPANDED": ("Expiration-proximity decay replication", "P19-OPT-012", "Does the 0-7 DTE bucket remain the most-negative-mean-forward-return bucket on the expanded panel?", ("dte_bucket",)),
}


def main() -> None:
    universe = phase20_verified_underlying_universe()
    hyp_registry = HypothesisRegistry(Path("logs/research_data/hypotheses.jsonl"))
    prereg_store = PreregistrationStore(Path("logs/research_data/phase20_preregistrations.jsonl"))

    print("READ-ONLY confirmation — every Phase 19 DISCOVERY_SUPPORTED hypothesis exists, unmodified:\n", flush=True)
    for parent_id in PARENT_IDS:
        parent = hyp_registry.get(parent_id)
        if parent is None:
            raise RuntimeError(f"{parent_id} not found — Phase 19 must have run first. Refusing to invent context.")
        print(f"  {parent.hypothesis_id} v{parent.version} — {parent.name} (family={parent.family!r}, parent_hypothesis_id={parent.parent_hypothesis_id})", flush=True)

    print(f"\nUNIVERSE: {universe.name} — {universe.symbols}\n", flush=True)

    for hyp_id, (name, parent_id, statement, features) in EXPANDED.items():
        hypothesis = Hypothesis(
            hypothesis_id=hyp_id, name=name, version="1.0", description=statement, economic_intuition=statement,
            mathematical_definition=f"replication of {parent_id} on the Phase 20 expanded panel (12 underlyings, 3 expirations, 120 contracts); features: {features}",
            required_data=("real option OHLC bars (get_option_historicals)", "real underlying OHLC bars (HistoricalDataStore)"),
            required_features=features, prediction_horizon_bars=5,
            test_methodology="identical methodology to the parent hypothesis, applied to the expanded panel -- see "
                              "scripts/phase20_step4_replication_campaign.py for the exact statistics computed "
                              "(bootstrap, multiple-testing, symbol/sector leave-one-out, PBO/DSR where applicable, "
                              "placebo battery, mechanical-baseline comparison, cost sensitivity)",
            expected_direction="unsigned",
            assumptions=(
                f"this is a REPLICATION of {parent_id}, not a new discovery -- the original hypothesis definition is frozen and unmodified",
                "the expanded panel is still small in absolute terms (120 contracts, 3 expirations) relative to a "
                "fully mature options research dataset -- explicitly not claimed to be exhaustive",
                "contract-day observations from the same underlying/contract are NOT independent -- every stability "
                "check below explicitly accounts for this (leave-one-symbol-out, leave-one-sector-out, not just a "
                "naive larger n)",
                f"universe={universe.name}: real, verified via a real get_option_instruments probe per member",
            ),
            family="options_alpha_replication", target_definition="forward_return_5",
            holding_period_bars=None, entry_rule="N/A — replication research only, no trading strategy this phase", exit_rule="N/A",
            universe=universe.symbols, expected_mechanism=f"replication of {parent_id}'s mechanism on a materially broader universe",
            falsification_criteria=(
                "the finding does not replicate in the same direction on the expanded panel",
                "the finding is concentrated in one underlying or one sector (leave-one-out swings the result)",
                "the finding does not survive multiple-testing correction within the Phase 20 replication family",
                "the finding is fully explained by the mechanical-baseline (underlying-equity) comparison",
                "the effect disappears under 1x/2x/3x ASSUMPTION-labeled cost sensitivity",
            ),
            parent_hypothesis_id=parent_id, development_version=None,
        )
        if hyp_registry.get(hyp_id) is None:
            hyp_registry.register(hypothesis)
        print(f"Registered: {hyp_id} — {name} (parent={parent_id})", flush=True)

        record = PreregistrationRecord(
            hypothesis_id=hyp_id, hypothesis_version="1.0", rationale=statement, expected_direction="unsigned",
            target_definition="forward_return_5", features=features, universe_name=universe.name, time_horizon_bars=5,
            parameter_ranges={"parent_hypothesis_id": parent_id, "horizons": [1, 3, 5, 10, 20]},
            validation_methodology="see Hypothesis.test_methodology",
            cost_assumptions="1x/2x/3x ASSUMPTION-labeled spread/slippage/commission sensitivity (src.options.cost_model) -- never presented as an observed cost",
            success_criteria=("see scripts/phase20_step4_replication_campaign.py's per-hypothesis classification logic",),
            falsification_criteria=hypothesis.falsification_criteria, registered_at=datetime.now(timezone.utc),
        )
        if prereg_store.get(hyp_id, "1.0") is None:
            prereg_store.register(record)

    print(f"\n{len(EXPANDED)} replication hypotheses registered under family='options_alpha_replication', "
          f"experiment family='P20-REPL-2026-09' (Part 19: kept SEPARATE from Phase 19's discovery family).", flush=True)
    print("\nSTEP 3 COMPLETE — no replication analysis has run yet.", flush=True)


if __name__ == "__main__":
    main()
