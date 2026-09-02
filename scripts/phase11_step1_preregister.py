#!/usr/bin/env python3
"""Phase 11, Parts 1-8, 28 — STEP 1: preregisters the NEW
VOLATILITY_CONDITIONED_EXPOSURE hypothesis family (P11-VCE-001..006),
freezes the benchmark definitions, exposure mechanisms, target-volatility
candidates, and rebalance frequencies, and preregisters the COMPLETE
variant grid (Part 28) — all BEFORE any backtest runs.

Explicitly NOT a continuation of P7-VOLANOM-A, P7-VOLANOM-A-DEV1,
P9-VOLCLUST-A, or any P10-VP-* hypothesis (read-only lookups only,
asserted below; parent_hypothesis_id=None for every P11 hypothesis).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import us_diversified_universe  # noqa: E402
from src.research import Hypothesis, HypothesisRegistry  # noqa: E402
from src.research.exposure_mechanisms import EXPOSURE_MAX, EXPOSURE_MIN, MECHANISMS, REBALANCE_FREQUENCIES, TARGET_VOL_CANDIDATES  # noqa: E402
from src.research.preregistration import PreregistrationRecord, PreregistrationStore  # noqa: E402

# --- benchmark definitions (Part 3, 10) — the underlying return engine is DELIBERATELY neutral --
BENCHMARKS = {
    "BUY_AND_HOLD_SPY": "Buys SPY at the first available open, holds unconditionally for the whole period (src.research.baseline.buy_and_hold_curve) — the frictionless, zero-turnover reference.",
    "STATIC_100PCT_EQUAL_WEIGHT_UNIVERSE": "Equal-weight (1/20) allocation across the full US_DIVERSIFIED universe, rebalanced back to equal weight on the same schedule as every exposure mechanism (STATIC mechanism, exposure=100% always) — the 'always fully invested' comparison.",
    "RANDOM_EXPOSURE": "Same rebalance timestamps/bounds as the real mechanism being evaluated, but each rebalance's exposure is drawn independently from that mechanism's OWN empirical exposure distribution (Part 25).",
    "SHUFFLED_VOLATILITY": "Same rebalance timestamps and exact same multiset of exposure values as the real mechanism, but temporally SHUFFLED (Part 26) — tests whether TIMING carries information.",
}

# --- exposure grid (Part 4, 17-19) — FROZEN before any backtest ran -----------------------------
def _build_grid() -> list[dict]:
    grid = []
    for freq in REBALANCE_FREQUENCIES:
        grid.append({"mechanism": "STATIC", "target_annual_vol": None, "rebalance_frequency": freq})
        for tv in TARGET_VOL_CANDIDATES:
            grid.append({"mechanism": "VOL_TARGET", "target_annual_vol": tv, "rebalance_frequency": freq})
        grid.append({"mechanism": "REGIME", "target_annual_vol": None, "rebalance_frequency": freq})
        grid.append({"mechanism": "COMPRESSION_EXPANSION", "target_annual_vol": None, "rebalance_frequency": freq})
    return grid


GRID = _build_grid()

HYPOTHESES = {
    "P11-VCE-001": "Volatility-targeted exposure can reduce realized portfolio volatility while preserving a meaningful fraction of return (the 'return retention ratio', Part 12).",
    "P11-VCE-002": "Reducing exposure during HIGH/EXTREME volatility regimes (the REGIME mechanism) improves risk-adjusted performance (Sharpe/Sortino/Calmar) versus static 100% exposure.",
    "P11-VCE-003": "Increasing exposure during LOW-volatility regimes improves risk-adjusted performance AFTER ACCOUNTING FOR COSTS versus static 100% exposure.",
    "P11-VCE-004": "Compression/expansion states (the COMPRESSION_EXPANSION mechanism) can improve exposure timing relative to a static or randomized comparison.",
    "P11-VCE-005": "Volatility-forecast-based position sizing (the VOL_TARGET mechanism) improves DRAWDOWN-adjusted performance (Calmar, max drawdown, recovery time) versus static exposure.",
    "P11-VCE-006": "Volatility-conditioned exposure (the BEST-performing preregistered mechanism, selected on DISCOVERY_DATA only) provides superior risk-adjusted performance versus static exposure, out-of-sample on DEVELOPMENT_DATA.",
}


def main() -> None:
    universe = us_diversified_universe()
    hyp_registry = HypothesisRegistry(Path("logs/research_data/hypotheses.jsonl"))
    prereg_store = PreregistrationStore(Path("logs/research_data/phase11_preregistrations.jsonl"))

    print("READ-ONLY confirmation — none of these are modified this phase:", flush=True)
    for prior_id in ("P7-VOLANOM-A", "P7-VOLANOM-A-DEV1", "P9-VOLCLUST-A"):
        prior = hyp_registry.get(prior_id)
        if prior is None:
            raise RuntimeError(f"{prior_id} not found — prior phases must have run first. Refusing to invent context.")
        print(f"  {prior.hypothesis_id} — {prior.name}", flush=True)
    p10_found = 0
    for i in range(1, 11):
        p10_id = f"P10-VP-{i:03d}"
        if hyp_registry.get(p10_id) is not None:
            p10_found += 1
    print(f"  {p10_found}/10 P10-VP-* hypotheses confirmed present and untouched\n", flush=True)

    print("CORE OBJECTIVE: this is RISK/EXPOSURE research, not directional alpha research.", flush=True)
    print("CRITICAL DISTINCTION preserved throughout: A. volatility forecasting != B. exposure management != C. excess-return alpha.\n", flush=True)

    for hyp_id, statement in HYPOTHESES.items():
        hypothesis = Hypothesis(
            hypothesis_id=hyp_id, name=statement[:80], version="1.0", description=statement, economic_intuition=statement,
            mathematical_definition="exposure = mechanism(volatility features), applied to a NEUTRAL benchmark return engine (never a directional alpha strategy)",
            required_data=("daily OHLCV",), required_features=("realized_vol_20_ann", "volatility_regime", "volatility_compression", "volatility_expansion"),
            prediction_horizon_bars=5, test_methodology="event-driven backtest (Phase 3 BacktestEngine, unmodified) on DISCOVERY_DATA+DEVELOPMENT_DATA; "
                                                          "block/stationary bootstrap on returns, PBO, Deflated Sharpe Ratio, cost/execution stress, "
                                                          "randomized-exposure and shuffled-volatility placebo controls",
            expected_direction="positive", assumptions=(
                "this is a NEW hypothesis family (VOLATILITY_CONDITIONED_EXPOSURE), explicitly NOT a continuation of P7-VOLANOM-A/"
                "P7-VOLANOM-A-DEV1/P9-VOLCLUST-A/any P10-VP-* hypothesis",
                "a successful result here is about the DISTRIBUTION of returns (volatility, drawdown, tail risk), not necessarily higher raw return",
                "evidence that volatility can be forecast does not by itself establish that exposure management improves outcomes, and evidence that "
                "exposure management improves outcomes does not by itself establish tradeable excess-return alpha (Part 31)",
            ),
            family="volatility_conditioned_exposure", target_definition="risk-adjusted return distribution (Sharpe/Sortino/Calmar/drawdown/tail risk) vs static exposure",
            holding_period_bars=None, entry_rule="volatility-conditioned exposure fraction applied to a neutral benchmark (Part 3) — never a directional signal",
            exit_rule="N/A — continuous rebalancing, not discrete entry/exit",
            universe=universe.symbols, expected_mechanism="lower realized volatility / smaller drawdowns from reduced exposure during elevated-volatility "
                                                            "periods, at the cost of turnover/transaction costs and some foregone return",
            falsification_criteria=(
                "risk-adjusted metrics (Sharpe/Sortino/Calmar) do not improve versus static exposure, after realistic costs",
                "the mechanism only outperforms randomized/shuffled exposure controls before costs, not after",
                "drawdown/tail-risk metrics are not meaningfully improved (Phase 10 already found weak direct drawdown-prediction information)",
                "the result does not replicate out-of-sample on DEVELOPMENT_DATA after being selected on DISCOVERY_DATA",
            ),
            parent_hypothesis_id=None, development_version=None,
        )
        if hyp_registry.get(hyp_id) is None:
            hyp_registry.register(hypothesis)
        print(f"Registered: {hyp_id} — {statement[:90]}...", flush=True)

        record = PreregistrationRecord(
            hypothesis_id=hyp_id, hypothesis_version="1.0", rationale=statement, expected_direction="positive",
            target_definition="risk-adjusted return distribution vs static exposure", features=hypothesis.required_features,
            universe_name=universe.name, time_horizon_bars=5,
            parameter_ranges={"exposure_min": EXPOSURE_MIN, "exposure_max": EXPOSURE_MAX, "mechanisms": list(MECHANISMS),
                               "target_vol_candidates": list(TARGET_VOL_CANDIDATES), "rebalance_frequencies": list(REBALANCE_FREQUENCIES)},
            validation_methodology="event-driven backtest, bootstrap, PBO, DSR, cost/execution stress, placebo controls — DISCOVERY_DATA+DEVELOPMENT_DATA only",
            cost_assumptions="PerShareCommission + FixedPercentSlippage + FixedPercentSpreadModel at 1x, stress-tested at 2x/3x (Part 16)",
            success_criteria=("see scripts/phase11_step2_exposure_grid.py and phase11_step3_regime_yearly_symbol_and_report.py's classification logic",),
            falsification_criteria=hypothesis.falsification_criteria, registered_at=datetime.now(timezone.utc),
        )
        if prereg_store.get(hyp_id, "1.0") is None:
            prereg_store.register(record)

    print(f"\n{len(HYPOTHESES)} hypotheses registered under family='volatility_conditioned_exposure', none derived from any prior phase's hypothesis.\n", flush=True)

    print(f"{'=' * 90}\nFROZEN BENCHMARK DEFINITIONS (Part 3, 10)\n{'=' * 90}", flush=True)
    for name, desc in BENCHMARKS.items():
        print(f"  {name}: {desc}", flush=True)

    print(f"\n{'=' * 90}\nFROZEN EXPOSURE MECHANISM GRID (Part 4, 17-19) — {len(GRID)} variants, none selected/discarded before running\n{'=' * 90}", flush=True)
    for i, v in enumerate(GRID):
        label = f"VOL_TARGET({v['target_annual_vol']:.0%})" if v["mechanism"] == "VOL_TARGET" else v["mechanism"]
        print(f"  [{i:2d}] {label:22s} rebalance={v['rebalance_frequency']}", flush=True)
    print(f"\n  Exposure bounds (Part 6, fixed, never optimized): [{EXPOSURE_MIN:.0%}, {EXPOSURE_MAX:.0%}] — NO LEVERAGE anywhere in this phase.", flush=True)
    print(f"  Plus 2 placebo controls (RANDOM_EXPOSURE, SHUFFLED_VOLATILITY) applied to the WINNING variant only (Parts 25-26) — "
          f"not part of the {len(GRID)}-variant search space used for PBO/DSR trial counting, but reported alongside it.", flush=True)

    family_record = PreregistrationRecord(
        hypothesis_id="P11-VCE-FAMILY", hypothesis_version="1.0",
        rationale="Shared discovery/development family manifest for the VOLATILITY_CONDITIONED_EXPOSURE campaign (Part 28) — the complete "
                   "mechanism x target-vol x rebalance-frequency variant grid, fixed before any backtest ran, so multiple-testing / PBO / DSR "
                   "trial counting reflects everything actually searched.",
        expected_direction="positive", target_definition="risk-adjusted return distribution vs static exposure",
        features=("realized_vol_20_ann", "volatility_regime", "volatility_compression", "volatility_expansion"),
        universe_name=universe.name, time_horizon_bars=5,
        parameter_ranges={"grid": GRID, "n_variants": len(GRID), "benchmarks": list(BENCHMARKS.keys())},
        validation_methodology="event-driven backtest (Phase 3 engine) + bootstrap + PBO + DSR + cost/execution stress + placebo controls",
        cost_assumptions="PerShareCommission + FixedPercentSlippage + FixedPercentSpreadModel, stress-tested 1x/2x/3x",
        success_criteria=("see step 2/3 scripts' classification logic",),
        falsification_criteria=("a mechanism that only 'wins' before costs, or only on DISCOVERY_DATA and not DEVELOPMENT_DATA, is not development-supported",),
        registered_at=datetime.now(timezone.utc),
    )
    if prereg_store.get(family_record.hypothesis_id, family_record.hypothesis_version) is None:
        prereg_store.register(family_record)
    print(f"\nPreregistered family manifest: {family_record.hypothesis_id} v{family_record.hypothesis_version}", flush=True)
    print("\nSTEP 1 COMPLETE — no backtest has run yet.", flush=True)


if __name__ == "__main__":
    main()
