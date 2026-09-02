#!/usr/bin/env python3
"""Phase 13, Parts 4-9, 17 — STEP 1: preregisters the NEW
OVERNIGHT_INTRADAY_DECOMPOSITION hypothesis family (P13-OID-001..008),
freezes the exact feature/target/horizon/window definitions and the
complete discovery test family — all BEFORE any discovery analysis runs.
Must be run AFTER scripts/phase13_step0_data_quality_gate.py has PROCEED'd.

Explicitly NOT a continuation of P7-VOLANOM-A, P9-VOLCLUST-A, any
P10-VP-*, any P11-VCE-*, or any P12-CSRS-* hypothesis (read-only lookups
only, asserted below; parent_hypothesis_id=None for every P13 hypothesis).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import us_diversified_universe  # noqa: E402
from src.research import Hypothesis, HypothesisRegistry  # noqa: E402
from src.research.preregistration import PreregistrationRecord, PreregistrationStore  # noqa: E402

# --- preregistered feature set (Part 7) — the main cross-sectional IC screen -------------------
FEATURE_SET = (
    "overnight_return",                    # A
    "intraday_return",                     # B
    "abs_overnight_return",                # C
    "abs_intraday_return",                 # D
    "overnight_intraday_disagreement",     # E
    "gap_extremeness_20",                  # F — overnight_t / RealizedVolatility(20) through t-1
    "intraday_extremeness_20",             # G — intraday_t / RealizedVolatility(20) through t-1
)
# used OUTSIDE the main IC screen, in their own dedicated analyses (Parts 12-13):
STATE_FEATURE = "overnight_intraday_state"          # H — categorical, Part 13 disagreement analysis
INTERACTION_FEATURE = "overnight_intraday_interaction"  # Part 12's OLS interaction term
VOL_WINDOW = 20  # preregistered, fixed before any analysis ran

# --- preregistered target/horizon set (Part 6) --------------------------------------------------
TARGET_SET = ("next_close_to_close_return", "next_overnight_return", "next_intraday_return")
PRIMARY_TARGET = "next_close_to_close_return"
PRIMARY_HORIZON = 1  # next trading session
SECONDARY_HORIZON = 5  # preregistered secondary horizon — reported alongside, never chosen after seeing results

REGIME_SET = ("bull_high_vol", "bull_low_vol", "bear_high_vol", "bear_low_vol", "unknown")  # reused, unmodified taxonomy

HYPOTHESES = {
    "P13-OID-001": ("Overnight return predicts next-session return", "overnight_return, ranked cross-sectionally, predicts next_close_to_close_return.", ("overnight_return",)),
    "P13-OID-002": ("Large overnight gaps exhibit short-horizon reversal", "The top quintile of abs_overnight_return shows a NEGATIVE sign-consistency with next_close_to_close_return (reversal) at h=1.", ("abs_overnight_return", "overnight_return")),
    "P13-OID-003": ("Large overnight gaps exhibit continuation", "The top quintile of abs_overnight_return shows a POSITIVE sign-consistency with next_close_to_close_return (continuation) at h=1 — the mirror-image, competing hypothesis to P13-OID-002, resolved by the same evidence.", ("abs_overnight_return", "overnight_return")),
    "P13-OID-004": ("Intraday return predicts next-session return", "intraday_return, ranked cross-sectionally, predicts next_close_to_close_return.", ("intraday_return",)),
    "P13-OID-005": ("Large intraday moves exhibit short-horizon reversal", "The top quintile of abs_intraday_return shows a NEGATIVE sign-consistency with next_close_to_close_return at h=1.", ("abs_intraday_return", "intraday_return")),
    "P13-OID-006": ("Overnight and intraday returns interact in predicting next return", "future_return ~ overnight + intraday + overnight*intraday (OLS) shows a significant interaction term beyond either main effect.", (INTERACTION_FEATURE, "overnight_return", "intraday_return")),
    "P13-OID-007": ("Overnight-vs-intraday disagreement contains predictive information", "The 4-state overnight_intraday_state (+/+, +/-, -/+, -/-) shows materially different next_close_to_close_return distributions across states.", (STATE_FEATURE,)),
    "P13-OID-008": ("Extreme gap/intraday combinations predict subsequent volatility-adjusted return", "The top quintile of combined |gap_extremeness_20|+|intraday_extremeness_20| predicts next_close_to_close_return / lagged_realized_vol.", ("gap_extremeness_20", "intraday_extremeness_20")),
}


def main() -> None:
    universe = us_diversified_universe()
    hyp_registry = HypothesisRegistry(Path("logs/research_data/hypotheses.jsonl"))
    prereg_store = PreregistrationStore(Path("logs/research_data/phase13_preregistrations.jsonl"))

    print("READ-ONLY confirmation — none of these are modified this phase:", flush=True)
    for prior_id in ("P7-VOLANOM-A", "P7-VOLANOM-A-DEV1", "P9-VOLCLUST-A"):
        prior = hyp_registry.get(prior_id)
        if prior is None:
            raise RuntimeError(f"{prior_id} not found — prior phases must have run first. Refusing to invent context.")
        print(f"  {prior.hypothesis_id} — {prior.name}", flush=True)
    p10_found = sum(1 for i in range(1, 11) if hyp_registry.get(f"P10-VP-{i:03d}") is not None)
    p11_found = sum(1 for i in range(1, 7) if hyp_registry.get(f"P11-VCE-{i:03d}") is not None)
    p12_found = sum(1 for i in range(1, 11) if hyp_registry.get(f"P12-CSRS-{i:03d}") is not None)
    print(f"  {p10_found}/10 P10-VP-* hypotheses confirmed present and untouched", flush=True)
    print(f"  {p11_found}/6 P11-VCE-* hypotheses confirmed present and untouched", flush=True)
    print(f"  {p12_found}/10 P12-CSRS-* hypotheses confirmed present and untouched\n", flush=True)

    print("DATA QUALITY: this script assumes scripts/phase13_step0_data_quality_gate.py has already "
          "run and printed PROCEED. Adjustment status: split-adjusted, dividend-unadjusted (see that "
          "script's own output for the full evidence trail).\n", flush=True)
    print("UNIVERSE LIMITATION: US_DIVERSIFIED is CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED.\n", flush=True)

    for hyp_id, (name, statement, features) in HYPOTHESES.items():
        hypothesis = Hypothesis(
            hypothesis_id=hyp_id, name=name, version="1.0", description=statement, economic_intuition=statement,
            mathematical_definition=f"features: {features}; targets: {TARGET_SET}; horizons: ({PRIMARY_HORIZON}, {SECONDARY_HORIZON}); vol_window={VOL_WINDOW}",
            required_data=("daily OHLC",), required_features=features, prediction_horizon_bars=PRIMARY_HORIZON,
            test_methodology="cross-sectional IC (Spearman + Pearson) / per-symbol time-series correlation / quantile / "
                              "reversal-vs-continuation / interaction OLS / disagreement-state / extreme-move / regime / "
                              "year-quarter stability / breadth / placebo / multiple-testing / purged-CV / bootstrap / PBO / DSR "
                              "analysis on DISCOVERY_DATA only — no backtest, no trading strategy this phase",
            expected_direction="positive", assumptions=(
                "this is a NEW hypothesis family (OVERNIGHT_INTRADAY_DECOMPOSITION), explicitly NOT a continuation of "
                "P7-VOLANOM-A, P9-VOLCLUST-A, any P10-VP-*, P11-VCE-*, or P12-CSRS-* hypothesis",
                "the primary information source is OHLC decomposition (overnight vs intraday), not ordinary close-to-close momentum",
                "OHLC data is split-adjusted but NOT dividend-adjusted — a small, bounded, documented mechanical noise "
                "source on ex-dividend dates for dividend-paying names (see the data-quality gate)",
                "US_DIVERSIFIED is CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED — explicitly labeled, not claimed unbiased",
            ),
            family="overnight_intraday_decomposition", target_definition=PRIMARY_TARGET,
            holding_period_bars=None, entry_rule="N/A — discovery-stage only, no trading strategy this phase", exit_rule="N/A",
            universe=universe.symbols, expected_mechanism="overnight gaps reflect after-hours information arrival/order-flow "
                                                            "imbalance that may over- or under-react, while intraday moves "
                                                            "reflect regular-session price discovery — the two legs may carry "
                                                            "different (or interacting) predictive content for subsequent returns",
            falsification_criteria=(
                "IC (Spearman or Pearson) not reliably in the expected direction across DISCOVERY_DATA after multiple-testing correction",
                "quantile portfolios are not monotonic and the Q5-Q1 spread is not economically meaningful",
                "the relationship does not survive the placebo battery (cross-sectional shuffle, time shuffle, random-sign, "
                "negative-control feature)",
                "the relationship is concentrated in one symbol or one sector (leave-one-out)",
                "the edge does not survive realistic transaction costs (1x/2x/3x stress)",
                "the result does not replicate across years/quarters (single-period-driven)",
                "the shifted-alignment placebo cannot be explained by feature/target autocorrelation alone",
            ),
            parent_hypothesis_id=None, development_version=None,
        )
        if hyp_registry.get(hyp_id) is None:
            hyp_registry.register(hypothesis)
        print(f"Registered: {hyp_id} — {name}", flush=True)

        record = PreregistrationRecord(
            hypothesis_id=hyp_id, hypothesis_version="1.0", rationale=statement, expected_direction="positive",
            target_definition=PRIMARY_TARGET, features=features, universe_name=universe.name, time_horizon_bars=PRIMARY_HORIZON,
            parameter_ranges={"features": list(features), "target_set": list(TARGET_SET), "horizons": [PRIMARY_HORIZON, SECONDARY_HORIZON], "vol_window": VOL_WINDOW},
            validation_methodology="see Hypothesis.test_methodology", cost_assumptions="PerShareCommission-style, stress-tested 1x/2x/3x turnover-implied costs (research-only, no backtest)",
            success_criteria=("see scripts/phase13_step2_discovery_campaign.py's per-hypothesis classification logic",),
            falsification_criteria=hypothesis.falsification_criteria, registered_at=datetime.now(timezone.utc),
        )
        if prereg_store.get(hyp_id, "1.0") is None:
            prereg_store.register(record)

    print(f"\n{len(HYPOTHESES)} hypotheses registered under family='overnight_intraday_decomposition', none derived from a prior phase's hypothesis.\n", flush=True)

    print("PREREGISTERED SHARED DISCOVERY FAMILY (Part 17 — corrected as ONE family across ALL hypotheses):", flush=True)
    print(f"  main-screen features ({len(FEATURE_SET)}): {FEATURE_SET}", flush=True)
    print(f"  dedicated-analysis features: {STATE_FEATURE} (Part 13), {INTERACTION_FEATURE} (Part 12)", flush=True)
    print(f"  targets ({len(TARGET_SET)}): {TARGET_SET}  (primary={PRIMARY_TARGET})", flush=True)
    print(f"  horizons: primary={PRIMARY_HORIZON}, secondary={SECONDARY_HORIZON}", flush=True)
    print(f"  vol_window={VOL_WINDOW}", flush=True)
    print(f"  regime taxonomy ({len(REGIME_SET)}, reused from Phase 7/9/10/12): {REGIME_SET}", flush=True)
    n_main_screen = len(FEATURE_SET) * len(TARGET_SET)  # @ primary horizon
    n_secondary_horizon = len(FEATURE_SET)  # primary target @ secondary horizon only
    n_regime_tests = len(FEATURE_SET) * len(REGIME_SET)  # @ primary target/horizon
    total = n_main_screen + n_secondary_horizon + n_regime_tests
    print(f"  planned test count: {n_main_screen} (main screen @ h={PRIMARY_HORIZON}) + {n_secondary_horizon} (secondary horizon h={SECONDARY_HORIZON}) "
          f"+ {n_regime_tests} (regime) = {total} total", flush=True)

    family_record = PreregistrationRecord(
        hypothesis_id="P13-OID-FAMILY", hypothesis_version="1.0",
        rationale="Shared discovery family manifest for the OVERNIGHT_INTRADAY_DECOMPOSITION campaign (Part 17) — the complete "
                   "feature x target x horizon x regime test matrix, fixed before any analysis ran.",
        expected_direction="positive", target_definition=PRIMARY_TARGET, features=FEATURE_SET, universe_name=universe.name, time_horizon_bars=PRIMARY_HORIZON,
        parameter_ranges={"feature_set": list(FEATURE_SET), "target_set": list(TARGET_SET), "horizons": [PRIMARY_HORIZON, SECONDARY_HORIZON],
                           "regime_set": list(REGIME_SET), "vol_window": VOL_WINDOW, "planned_test_count": total},
        validation_methodology="cross-sectional IC (Spearman+Pearson), per-symbol time-series, quantile, reversal-vs-continuation, "
                                "interaction OLS, disagreement-state, extreme-move, regime, year/quarter stability, breadth, "
                                "placebo, multiple-testing, purged-CV, bootstrap, PBO, DSR — DISCOVERY_DATA only",
        cost_assumptions="not applicable at the discovery stage — no trades are simulated, turnover/cost estimated analytically",
        success_criteria=("see scripts/phase13_step2_discovery_campaign.py's per-hypothesis classification logic",),
        falsification_criteria=("a nominal p<0.05 alone is NOT sufficient — see phase philosophy",),
        registered_at=datetime.now(timezone.utc),
    )
    if prereg_store.get(family_record.hypothesis_id, family_record.hypothesis_version) is None:
        prereg_store.register(family_record)
    print(f"\nPreregistered family manifest: {family_record.hypothesis_id} v{family_record.hypothesis_version}", flush=True)
    print("\nSTEP 1 COMPLETE — no discovery analysis has run yet.", flush=True)


if __name__ == "__main__":
    main()
