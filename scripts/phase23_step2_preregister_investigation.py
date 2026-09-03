#!/usr/bin/env python3
"""Phase 23, Parts 4/5/7/11 — preregisters the COMPLETE Phase 23 test
matrix BEFORE any result is computed: the control hierarchy (Part 4),
the target-validation family (Part 5), the 2022-concentration
decomposition candidates (Part 11), and the tradeable-transformation
grid (Part 7). Two new investigations, both with
parent_hypothesis_id="P22-OPT-013" (a CHILD reference -- P22-OPT-013
itself is never edited or re-registered):

  P23-INV-P22-OPT-013      -- the adversarial investigation (mechanism,
                               controls, target falsification, directional
                               analysis, concentration, bootstrap, PBO/DSR)
  P23-OPT-013-TRADEABLE    -- the simple rule-based tradeable transformation

Every parameter below (control order, target list, decomposition
candidates, threshold grid, holding-period grid) is fixed here, before
Part 23's own explicit instruction is honored: no parameter may be
chosen, added, or tuned after seeing a result.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.options.universe import phase20_verified_underlying_universe  # noqa: E402
from src.research import Hypothesis, HypothesisRegistry  # noqa: E402
from src.research.experiment_fingerprint import ExperimentDimensions, compute_experiment_fingerprint  # noqa: E402
from src.research.preregistration import PreregistrationRecord, PreregistrationStore  # noqa: E402

PARENT_ID = "P22-OPT-013"

# Part 4: control hierarchy, CUMULATIVE (each control is added on top of every control before it) -- fixed order,
# not reordered after seeing which controls "work."
CONTROL_HIERARCHY = (
    ("control_1_underlying_forward_return", "underlying_forward_return_5"),
    ("control_2_underlying_abs_forward_return", "abs_underlying_forward_return_5"),
    ("control_3_underlying_realized_vol", "underlying_lagged_realized_vol"),
    ("control_4_underlying_vol_expansion", "underlying_vol_ratio_5_20"),
    ("control_5_underlying_range_expansion", "underlying_range_expansion_5"),
    ("control_6_option_trailing_return", "option_momentum_5"),
    ("control_7_option_trailing_volatility", "option_vol_ratio_5_20"),
    ("control_8_option_recent_range_level", "option_true_range_proxy_10"),
    ("control_9_moneyness_distance_from_atm", "abs_log_moneyness"),
    ("control_10_dte", "dte"),
)

# Part 5: target-validation family -- A-J, fixed before any result.
TARGET_VALIDATION_FAMILY = (
    ("A", "forward_return_1", "forward close-to-close option return, 1 bar"),
    ("B", "forward_return_3", "forward close-to-close option return, 3 bars"),
    ("C", "forward_return_5", "forward close-to-close option return, 5 bars"),
    ("D", "forward_return_10", "forward close-to-close option return, 10 bars"),
    ("E", "forward_return_20", "forward close-to-close option return, 20 bars"),
    ("F", "mfe_5", "maximum favorable excursion, 5 bars (the Phase 22 parent target)"),
    ("G", "mae_5", "maximum adverse excursion, 5 bars"),
    ("H", "mfe_minus_mae_5", "MFE minus MAE, 5 bars"),
    ("I", "forward_return_5", "future option return CONDITIONAL on a positive forward_return_5 outcome (subsample where forward_return_5 > 0)"),
    ("J", "target_positive_indicator_5", "probability of a positive forward_return_5 (binary 0/1, Spearman IC as a point-biserial-style rank correlation)"),
)

# Part 11: 2022-concentration decomposition candidates -- fixed BEFORE the decomposition is run, so no
# post-hoc-favorable explanation can be selectively reported.
DECOMPOSITION_CANDIDATES = (
    ("A", "specific market/volatility regime (bull/bear x high/low-vol bucket)"),
    ("B", "specific expiration (2022-03-18 or 2022-06-17 vs 2023-06-16)"),
    ("C", "specific symbols (leave-one-out / top-contributor concentration)"),
    ("D", "specific option characteristics (moneyness bucket, call/put)"),
    ("E", "specific data availability (differential row counts / coverage by year)"),
    ("F", "random variation (no single structural explanation dominates)"),
)

# Part 7: the tradeable-transformation grid -- SMALL, bounded, fixed before any P&L is computed.
THRESHOLD_GRID = (1.25, 1.50, 1.75, 2.00, 2.50)
HOLDING_PERIOD_GRID = (1, 3, 5, 10)
ENTRY_TIMING_VARIANTS = ("next_bar_open", "next_bar_close")  # Part 8 -- same-bar close is EXCLUDED as an executable fill; see Part 8's own prohibition


def main() -> None:
    universe = phase20_verified_underlying_universe()
    hyp_registry = HypothesisRegistry(Path("logs/research_data/hypotheses.jsonl"))
    prereg_store = PreregistrationStore(Path("logs/research_data/phase23_preregistrations.jsonl"))

    parent = hyp_registry.get(PARENT_ID)
    if parent is None:
        raise RuntimeError(f"{PARENT_ID} not found -- Phase 22 must have run first.")
    print(f"PARENT CONFIRMED (read-only): {PARENT_ID} -- {parent.name}\n", flush=True)

    print("CONTROL HIERARCHY (Part 4, cumulative, fixed order):", flush=True)
    for name, col in CONTROL_HIERARCHY:
        print(f"  {name}: {col}", flush=True)
    print("\nTARGET-VALIDATION FAMILY (Part 5, fixed before any result):", flush=True)
    for letter, col, desc in TARGET_VALIDATION_FAMILY:
        print(f"  Target {letter} [{col}]: {desc}", flush=True)
    print("\n2022-CONCENTRATION DECOMPOSITION CANDIDATES (Part 11, fixed before any result):", flush=True)
    for letter, desc in DECOMPOSITION_CANDIDATES:
        print(f"  {letter}: {desc}", flush=True)
    print(f"\nTRADEABLE-TRANSFORMATION GRID (Part 7, tightly bounded): "
          f"thresholds={THRESHOLD_GRID}  holding_periods={HOLDING_PERIOD_GRID}  "
          f"({len(THRESHOLD_GRID)}x{len(HOLDING_PERIOD_GRID)}={len(THRESHOLD_GRID) * len(HOLDING_PERIOD_GRID)} combinations)  "
          f"entry_timing_variants={ENTRY_TIMING_VARIANTS}", flush=True)

    investigations = {
        "P23-INV-P22-OPT-013": (
            "Adversarial investigation of P22-OPT-013",
            "Mechanism decomposition, cumulative control hierarchy, target-validation family, directional "
            "(call/put/underlying-direction) analysis, non-overlapping-sampling test, signal-clustering analysis, "
            "2022-concentration decomposition, symbol/expiration/moneyness/call-put concentration and leave-one-out, "
            "clustered bootstrap (symbol/expiration/year), PBO/DSR, multiple testing -- all against the FROZEN "
            "P22-OPT-013 definition (option_range_expansion_5 -> mfe_5). The goal is to break the discovery, not "
            "to improve it.",
            ("option_range_expansion_5",) + tuple(col for _, col in CONTROL_HIERARCHY),
        ),
        "P23-OPT-013-TRADEABLE": (
            "Tradeable rule-based transformation of P22-OPT-013",
            "IF option_range_expansion_5 > threshold THEN enter long the option at the NEXT executable price "
            "(never same-bar close -- Part 8's explicit prohibition on an impossible fill using the same bar's own "
            "high/low that produced the signal); exit after `holding_period` bars. A small, preregistered "
            f"{len(THRESHOLD_GRID)}x{len(HOLDING_PERIOD_GRID)} grid, evaluated once, not optimized.",
            ("option_range_expansion_5",),
        ),
    }

    for inv_id, (name, statement, features) in investigations.items():
        hypothesis = Hypothesis(
            hypothesis_id=inv_id, name=name, version="1.0", description=statement, economic_intuition=statement,
            mathematical_definition=f"parent={PARENT_ID}; features={features}",
            required_data=("Phase 19/20/22 real option+underlying OHLC (already gathered, no new MCP fetch)",),
            required_features=features, prediction_horizon_bars=5,
            test_methodology="see scripts/phase23_step3_investigation_campaign.py / phase23_step4_tradeable_transformation.py",
            expected_direction="unsigned",
            assumptions=(
                "P22-OPT-013 (the parent) is frozen and never re-registered or edited this phase",
                "all data is MARK_TO_MARKET_HISTORICAL_RESEARCH -- no historical bid/ask/volume/OI/IV/Greeks exist "
                "for this connector; none are fabricated this phase",
                "the control hierarchy, target-validation family, decomposition candidates, and tradeable grid are "
                "all fixed BEFORE any Phase 23 result is computed -- no post-hoc addition/removal",
            ),
            family="p22_opt_013_investigation", target_definition="varies (see control/target lists)",
            holding_period_bars=None, entry_rule="N/A — discovery-stage only, no live/paper order this phase", exit_rule="N/A",
            universe=universe.symbols, expected_mechanism=statement,
            falsification_criteria=(
                "the effect fails to survive the cumulative control hierarchy (incremental R2 <= 0.005 after all "
                "10 controls) -> UNDERLYING_INHERITED",
                "the effect materially weakens under non-overlapping sampling -> OVERLAP_DEPENDENT",
                "removing one expiration destroys the effect -> EXPIRATION_DEPENDENT",
                "only one moneyness bucket drives the effect -> MONEYNESS_DEPENDENT",
                "the tradeable transformation fails realistic next-bar execution or 1x cost sensitivity -> "
                "TRADEABLE_SIGNAL_FRAGILE or TRADEABLE_SIGNAL_REJECTED",
            ),
            parent_hypothesis_id=PARENT_ID, development_version=None,
        )
        if hyp_registry.get(inv_id) is None:
            hyp_registry.register(hypothesis)
        print(f"\nRegistered: {inv_id} (parent={PARENT_ID}) — {name}", flush=True)

        record = PreregistrationRecord(
            hypothesis_id=inv_id, hypothesis_version="1.0", rationale=statement, expected_direction="unsigned",
            target_definition="varies", features=features, universe_name=universe.name, time_horizon_bars=5,
            parameter_ranges={
                "control_hierarchy": [c for _, c in CONTROL_HIERARCHY],
                "target_validation_family": [t for _, t, _ in TARGET_VALIDATION_FAMILY],
                "decomposition_candidates": [d for d, _ in DECOMPOSITION_CANDIDATES],
                "threshold_grid": list(THRESHOLD_GRID), "holding_period_grid": list(HOLDING_PERIOD_GRID),
                "entry_timing_variants": list(ENTRY_TIMING_VARIANTS),
            },
            validation_methodology="see Hypothesis.test_methodology",
            cost_assumptions="1x/2x/3x/5x ASSUMPTION-labeled -- never presented as an observed cost",
            success_criteria=("see scripts/phase23_step3/step4's classification logic",),
            falsification_criteria=hypothesis.falsification_criteria, registered_at=datetime.now(timezone.utc),
        )
        if prereg_store.get(inv_id, "1.0") is None:
            prereg_store.register(record)

        dims = ExperimentDimensions(
            feature_definition=str(features), parameter_range={"parent": PARENT_ID},
            universe_name=universe.name, target_definition="varies", execution_model="n/a-discovery-only" if inv_id.startswith("P23-INV") else "next-bar-execution-research-only",
            cost_model="assumption-only-1x-2x-3x-5x", validation_methodology=hypothesis.test_methodology,
        )
        print(f"  experiment fingerprint: {compute_experiment_fingerprint(dims)}", flush=True)

    print("\nSTEP 2 COMPLETE — full Phase 23 test matrix preregistered. No adversarial analysis has run yet.", flush=True)


if __name__ == "__main__":
    main()
