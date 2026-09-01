#!/usr/bin/env python3
"""Phase 8, Part 1 — STEP 1: formal development preregistration for
P7-VOLANOM-A-DEV1, the tradeable translation of P7-VOLANOM-A's frozen
discovery finding. Must run BEFORE any Phase 8 backtest — later scripts
call require_preregistered() and refuse to run without this.

DOES NOT modify P7-VOLANOM-A (read-only lookup, asserted below). Creates
a NEW hypothesis_id (P7-VOLANOM-A-DEV1) with parent_hypothesis_id =
"P7-VOLANOM-A", exactly per the "create a development version rather than
modifying the original" instruction.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import us_diversified_universe  # noqa: E402
from src.research import Hypothesis, HypothesisRegistry, PartitionLifecycleStage, PartitionStore  # noqa: E402
from src.research.preregistration import PreregistrationRecord, PreregistrationStore  # noqa: E402

# --- the small, preregistered parameter grid (Part 5) ---------------------------------------
# baseline_lookback: RelativeVolume's own trailing window. 10 EXACTLY matches
#   P7-VOLANOM-A's discovery feature (RelativeVolume(10)); 20 is tested as a
#   neighboring "monthly" baseline for parameter robustness (Part 20).
# anomaly_threshold: how many multiples of the trailing average volume counts
#   as "unusual." 1.5x/2x/3x are round, economically motivated multiples
#   chosen for spacing, not fit to any prior result.
# holding_period_bars: 3/5/10 bracket the discovery hypothesis's own
#   prediction_horizon_bars=5.
# Full cross product: 2 x 3 x 3 = 18 variants. Small, multi-dimensional,
# never touched or reordered after this point.
BASELINE_LOOKBACK_GRID = (10, 20)
ANOMALY_THRESHOLD_GRID = (1.5, 2.0, 3.0)
HOLDING_PERIOD_GRID = (3, 5, 10)


def main() -> None:
    universe = us_diversified_universe()
    hyp_registry = HypothesisRegistry(Path("logs/research_data/hypotheses.jsonl"))

    parent = hyp_registry.get("P7-VOLANOM-A")
    if parent is None:
        raise RuntimeError("P7-VOLANOM-A is not in the hypothesis registry — Phase 7 must have run first. Refusing to invent a parent record.")
    print(f"Parent hypothesis (READ-ONLY, unmodified): {parent.hypothesis_id} v{parent.version}", flush=True)
    print(f"  mathematical_definition: {parent.mathematical_definition}", flush=True)
    print(f"  expected_direction: {parent.expected_direction}  (magnitude-based, NOT directional — see translation note below)", flush=True)

    partition_store = PartitionStore(Path("logs/research_data/phase7_partitions.jsonl"))
    discovery = partition_store.active_by_stage(PartitionLifecycleStage.DISCOVERY)[0]
    development = partition_store.active_by_stage(PartitionLifecycleStage.DEVELOPMENT)[0]
    dev_start, dev_end = discovery.start_date, development.end_date
    print(f"\nDevelopment period (DISCOVERY_DATA + DEVELOPMENT_DATA only): {dev_start} .. {dev_end}", flush=True)
    print(f"VALIDATION_DATA and FINAL_HOLDOUT_DATA are NOT used this phase.", flush=True)

    translation_note = (
        "TRANSLATION CHOICE (recorded before any backtest ran): P7-VOLANOM-A's discovery "
        "hypothesis tests whether RelativeVolume predicts |future_return| (magnitude, not "
        "direction) — it explicitly says 'not directional.' Phase 8 requires a tradeable, "
        "long-only mechanism. The least-biased translation, which adds no new filter and does "
        "not silently retest the already-tested P7-VPC-A (volume-confirmed momentum), is to go "
        "LONG UNCONDITIONALLY whenever RelativeVolume exceeds the threshold, regardless of the "
        "bar's own return sign. A near-zero or negative result is an EXPECTED, non-failure "
        "outcome under this translation — it would mean the magnitude relationship does not "
        "carry a directional (buyable) edge, exactly consistent with what the discovery "
        "hypothesis always claimed it was testing."
    )
    print(f"\n{translation_note}\n", flush=True)

    dev_hypothesis = Hypothesis(
        hypothesis_id="P7-VOLANOM-A-DEV1", name="Volume Anomaly — Long-Only Development Translation", version="1.0",
        description="Tradeable, long-only translation of P7-VOLANOM-A's discovery-stage magnitude finding: go long unconditionally when RelativeVolume(baseline_lookback) exceeds anomaly_threshold, hold exactly holding_period_bars, exit.",
        economic_intuition=parent.economic_intuition,
        mathematical_definition="signal = 1[RelativeVolume(baseline_lookback) > anomaly_threshold]; LONG unconditionally on signal; FLAT after exactly holding_period_bars",
        required_data=("daily OHLCV",), required_features=(f"relative_volume_{{baseline_lookback}}",),
        prediction_horizon_bars=5, test_methodology="event-driven backtest (Phase 3 BacktestEngine, unmodified) on DISCOVERY_DATA+DEVELOPMENT_DATA only",
        expected_direction="positive", assumptions=(translation_note,),
        family="volume_anomaly", target_definition="realized net trade P&L (not an IC target — this is now a real backtest)",
        holding_period_bars=None,  # varies per parameter-grid variant — see parameters on each individual experiment record instead
        entry_rule="LONG when RelativeVolume(baseline_lookback) > anomaly_threshold and no existing position in that symbol",
        exit_rule="FLAT exactly holding_period_bars bars after entry — no stop-loss, no take-profit, no early exit",
        universe=universe.symbols, expected_mechanism="unconditional long exposure to 'something unusual is happening' events, testing whether the magnitude effect carries ANY net directional edge",
        falsification_criteria=(
            "net expectancy is not clearly positive across the development period",
            "the effect does not survive shuffled-signal or randomized-entry-timing placebo",
            "the effect does not survive 2x transaction costs",
            "the effect is concentrated in 1-2 symbols (leave-one-symbol-out reverses the sign)",
            "the shift-placebo investigation shows the relationship persists similarly under deliberately wrong alignment (Phase 7's caution)",
        ),
        parent_hypothesis_id="P7-VOLANOM-A", development_version="DEV1",
    )
    if hyp_registry.get(dev_hypothesis.hypothesis_id) is None:
        hyp_registry.register(dev_hypothesis)
    print(f"Registered development hypothesis: {dev_hypothesis.hypothesis_id} (parent={dev_hypothesis.parent_hypothesis_id})", flush=True)

    param_grid = {"baseline_lookback": list(BASELINE_LOOKBACK_GRID), "anomaly_threshold": list(ANOMALY_THRESHOLD_GRID), "holding_period_bars": list(HOLDING_PERIOD_GRID)}
    n_variants = len(BASELINE_LOOKBACK_GRID) * len(ANOMALY_THRESHOLD_GRID) * len(HOLDING_PERIOD_GRID)
    print(f"\nPreregistered parameter grid ({n_variants} variants, full cross product, never touched using Phase 7 IC results or Phase 5/6 MR-002 experience):", flush=True)
    print(f"  {json.dumps(param_grid, indent=2)}", flush=True)

    prereg_store = PreregistrationStore(Path("logs/research_data/phase8_preregistrations.jsonl"))
    record = PreregistrationRecord(
        hypothesis_id=dev_hypothesis.hypothesis_id, hypothesis_version=dev_hypothesis.version, rationale=translation_note,
        expected_direction="positive", target_definition="realized net trade P&L (long-only, fixed holding period)",
        features=(f"relative_volume_<baseline_lookback>",), universe_name=universe.name, time_horizon_bars=5,
        parameter_ranges=param_grid, validation_methodology="event-driven backtest on DISCOVERY_DATA+DEVELOPMENT_DATA only; VALIDATION_DATA/FINAL_HOLDOUT_DATA untouched",
        cost_assumptions="Phase 5/6 real models: NextBarExecutionModel(delay=1), FixedPercentSlippage(0.001), PerShareCommission(0.005), FixedPercentSpreadModel(0.001), equal-dollar FixedQuantitySizer",
        success_criteria=(
            "clearly positive net expectancy across the full development period",
            "survives 2x transaction costs",
            "survives execution stress (extra delay, higher slippage)",
            "no single symbol required for a positive result (leave-one-out)",
            "beats random-signal and shuffled-volume-signal baselines",
            "shift-placebo investigation does not show the effect persisting equally under deliberately wrong alignment",
        ),
        falsification_criteria=dev_hypothesis.falsification_criteria,
        registered_at=datetime.now(timezone.utc),
    )
    if prereg_store.get(record.hypothesis_id, record.hypothesis_version) is None:
        prereg_store.register(record)
    print(f"\nPreregistered in PreregistrationStore: {record.hypothesis_id} v{record.hypothesis_version}", flush=True)
    print("\nSTEP 1 COMPLETE — no backtest has run yet.", flush=True)


if __name__ == "__main__":
    main()
