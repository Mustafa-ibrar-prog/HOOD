#!/usr/bin/env python3
"""Phase 12, Parts 3-9, 26 — STEP 1: preregisters the NEW
CROSS_SECTIONAL_RELATIVE_STRENGTH hypothesis family (P12-CSRS-001..010),
freezes the exact feature/target/horizon/window definitions and the
complete discovery test family, and documents sector-data availability —
all BEFORE any discovery analysis runs.

Explicitly NOT a continuation of P7-VOLANOM-A, P9-VOLCLUST-A, any
P10-VP-* hypothesis, or any P11-VCE-* hypothesis (read-only lookups only,
asserted below; parent_hypothesis_id=None for every P12 hypothesis).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import us_diversified_universe  # noqa: E402
from src.research import Hypothesis, HypothesisRegistry  # noqa: E402
from src.research.preregistration import PreregistrationRecord, PreregistrationStore  # noqa: E402

# --- preregistered feature set (Part 6) — compact, one canonical window per derived concept -----
FEATURE_SET = (
    "return_5d",                        # raw momentum, short window (RateOfChange(5), Phase 2, unmodified)
    "return_20d",                       # raw momentum, medium window (RateOfChange(20))
    "return_60d",                       # raw momentum, long window (RateOfChange(60))
    "market_residual_mom_20d",          # cumulative 20d market-residual return (causal rolling beta, window=60)
    "sector_residual_mom_20d",          # cumulative 20d sector-residual return (equal-weight peer subtraction)
    "market_sector_residual_mom_20d",   # cumulative 20d market+sector residual return (sequential)
    "vol_adj_momentum_20d",             # RateOfChange(20) / RealizedVolatility(20)
    "relative_strength_persistence",    # rolling fraction of trailing 20 bars with RateOfChange(20) > 0
    "relative_strength_acceleration",   # 2nd discrete difference of RateOfChange(20)
)
BETA_WINDOW = 60  # preregistered rolling-beta estimation window (Part 6B) — fixed before any analysis ran
RESIDUAL_MOMENTUM_WINDOW = 20  # the canonical window every residual/derived feature uses (Part 6, "do not expand the grid")

# --- preregistered target/horizon set (Part 9) --------------------------------------------------
TARGET = "future_return"  # Phase 2's future_return(bars, horizon), UNMODIFIED
HORIZON_SET = (1, 5, 20)
PRIMARY_HORIZON = 5  # continuity with every prior phase's own primary-horizon convention, fixed before seeing any result

REGIME_SET = ("bull_high_vol", "bull_low_vol", "bear_high_vol", "bear_low_vol", "unknown")  # reused from Phase 7/9/10, unmodified taxonomy

HYPOTHESES = {
    "P12-CSRS-001": ("Raw cross-sectional momentum", "Raw trailing return (return_5d/20d/60d), ranked cross-sectionally, predicts future return.", ("return_5d", "return_20d", "return_60d")),
    "P12-CSRS-002": ("Market-residual momentum", "Momentum of the stock's return AFTER removing its causally-estimated market-beta exposure (market_residual_mom_20d) contains information beyond raw momentum.", ("market_residual_mom_20d",)),
    "P12-CSRS-003": ("Sector-residual momentum", "Momentum of the stock's return AFTER removing its sector's equal-weight peer return (sector_residual_mom_20d) contains information beyond raw momentum.", ("sector_residual_mom_20d",)),
    "P12-CSRS-004": ("Market + sector residual momentum", "Momentum after removing BOTH market and sector effects (market_sector_residual_mom_20d) contains information beyond raw momentum AND beyond either residual alone.", ("market_sector_residual_mom_20d",)),
    "P12-CSRS-005": ("Volatility-adjusted relative strength", "Momentum scaled by trailing realized volatility (vol_adj_momentum_20d) predicts future return better than raw momentum.", ("vol_adj_momentum_20d",)),
    "P12-CSRS-006": ("Relative-strength persistence", "A stock whose own momentum sign has been persistently positive (relative_strength_persistence) predicts future return.", ("relative_strength_persistence",)),
    "P12-CSRS-007": ("Short-horizon cross-sectional reversal", "return_5d predicts future return NEGATIVELY at short horizons (reversal, not momentum) — tested via return_5d's own IC sign at h=1.", ("return_5d",)),
    "P12-CSRS-008": ("Medium-horizon cross-sectional momentum", "return_20d predicts future return positively at medium horizons.", ("return_20d",)),
    "P12-CSRS-009": ("Long-horizon cross-sectional momentum", "return_60d predicts future return positively at longer horizons.", ("return_60d",)),
    "P12-CSRS-010": ("Relative-strength acceleration", "A stock whose own momentum is itself accelerating (relative_strength_acceleration) predicts future return.", ("relative_strength_acceleration",)),
}


def main() -> None:
    universe = us_diversified_universe()
    hyp_registry = HypothesisRegistry(Path("logs/research_data/hypotheses.jsonl"))
    prereg_store = PreregistrationStore(Path("logs/research_data/phase12_preregistrations.jsonl"))

    print("READ-ONLY confirmation — none of these are modified this phase:", flush=True)
    for prior_id in ("P7-VOLANOM-A", "P7-VOLANOM-A-DEV1", "P9-VOLCLUST-A"):
        prior = hyp_registry.get(prior_id)
        if prior is None:
            raise RuntimeError(f"{prior_id} not found — prior phases must have run first. Refusing to invent context.")
        print(f"  {prior.hypothesis_id} — {prior.name}", flush=True)
    p10_found = sum(1 for i in range(1, 11) if hyp_registry.get(f"P10-VP-{i:03d}") is not None)
    p11_found = sum(1 for i in range(1, 7) if hyp_registry.get(f"P11-VCE-{i:03d}") is not None)
    print(f"  {p10_found}/10 P10-VP-* hypotheses confirmed present and untouched", flush=True)
    print(f"  {p11_found}/6 P11-VCE-* hypotheses confirmed present and untouched\n", flush=True)

    # --- sector-data availability (Part 4) -----------------------------------------------------
    sectors = universe.by_sector()
    print(f"SECTOR DATA: {universe.name} sector classifications sourced from src/data/universe.py "
          f"(Phase 5's built-in universe definition — hard-coded, real GICS-like sector labels, NOT invented for this phase). "
          f"{len(sectors)} sectors: {dict(sectors)}\n", flush=True)
    print("UNIVERSE LIMITATION: US_DIVERSIFIED is CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED — a fixed, currently-listed "
          "20-symbol universe, NOT a point-in-time-unbiased historical universe. Explicitly labeled, not claimed otherwise.\n", flush=True)

    for hyp_id, (name, statement, features) in HYPOTHESES.items():
        hypothesis = Hypothesis(
            hypothesis_id=hyp_id, name=name, version="1.0", description=statement, economic_intuition=statement,
            mathematical_definition=f"features: {features}; target: {TARGET}; horizons: {HORIZON_SET}; beta_window={BETA_WINDOW}",
            required_data=("daily OHLCV",), required_features=features, prediction_horizon_bars=PRIMARY_HORIZON,
            test_methodology="cross-sectional IC (Spearman + Pearson) / quantile / incremental-information (vs raw momentum) / "
                              "regime / year-quarter stability / breadth / placebo / multiple-testing / purged-CV leakage demo / "
                              "bootstrap / PBO / DSR analysis on DISCOVERY_DATA only — no backtest, no trading strategy this phase",
            expected_direction="positive", assumptions=(
                "this is a NEW hypothesis family (CROSS_SECTIONAL_RELATIVE_STRENGTH), explicitly NOT a continuation of "
                "P7-VOLANOM-A, P9-VOLCLUST-A, any P10-VP-* hypothesis, or any P11-VCE-* hypothesis",
                "the central question is whether residual momentum adds INCREMENTAL information beyond raw momentum, "
                "market exposure, and sector exposure — not merely whether raw momentum exists",
                "US_DIVERSIFIED is CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED — explicitly labeled, not claimed unbiased",
            ),
            family="cross_sectional_relative_strength", target_definition=TARGET,
            holding_period_bars=None, entry_rule="N/A — discovery-stage only, no trading strategy this phase", exit_rule="N/A",
            universe=universe.symbols, expected_mechanism="slow information diffusion / behavioral underreaction to firm-specific "
                                                            "(not market- or sector-wide) news, producing short-to-medium-term "
                                                            "continuation in returns net of common factor exposure",
            falsification_criteria=(
                "IC (Spearman or Pearson) not reliably in the expected direction across DISCOVERY_DATA after multiple-testing correction",
                "quantile portfolios are not monotonic Q1<Q2<Q3<Q4<Q5 (or the reverse for the reversal hypothesis)",
                "the relationship does not survive placebo tests (random ranking, feature-shuffle, time-shift, negative-control feature)",
                "no incremental information beyond raw momentum (residual features only) — a residual IC no better than raw momentum's own IC",
                "the relationship is concentrated in one symbol or one sector (leave-one-out)",
                "the edge does not survive realistic transaction costs (1x/2x/3x stress)",
                "the result does not replicate across years/quarters (single-period-driven)",
            ),
            parent_hypothesis_id=None, development_version=None,
        )
        if hyp_registry.get(hyp_id) is None:
            hyp_registry.register(hypothesis)
        print(f"Registered: {hyp_id} — {name}", flush=True)

        record = PreregistrationRecord(
            hypothesis_id=hyp_id, hypothesis_version="1.0", rationale=statement, expected_direction="positive",
            target_definition=TARGET, features=features, universe_name=universe.name, time_horizon_bars=PRIMARY_HORIZON,
            parameter_ranges={"features": list(features), "horizon_set": list(HORIZON_SET), "beta_window": BETA_WINDOW, "residual_momentum_window": RESIDUAL_MOMENTUM_WINDOW},
            validation_methodology="see Hypothesis.test_methodology", cost_assumptions="PerShareCommission-style, stress-tested 1x/2x/3x turnover-implied costs (research-only, no backtest)",
            success_criteria=("see scripts/phase12_step2_discovery_campaign.py's per-hypothesis classification logic",),
            falsification_criteria=hypothesis.falsification_criteria, registered_at=datetime.now(timezone.utc),
        )
        if prereg_store.get(hyp_id, "1.0") is None:
            prereg_store.register(record)

    print(f"\n{len(HYPOTHESES)} hypotheses registered under family='cross_sectional_relative_strength', none derived from a prior phase's hypothesis.\n", flush=True)

    print("PREREGISTERED SHARED DISCOVERY FAMILY (Part 20 — corrected as ONE family across ALL hypotheses):", flush=True)
    print(f"  features ({len(FEATURE_SET)}): {FEATURE_SET}", flush=True)
    print(f"  target: {TARGET}  horizons ({len(HORIZON_SET)}): {HORIZON_SET}  (primary={PRIMARY_HORIZON})", flush=True)
    print(f"  beta_window={BETA_WINDOW}  residual_momentum_window={RESIDUAL_MOMENTUM_WINDOW}", flush=True)
    print(f"  regime taxonomy ({len(REGIME_SET)}, reused from Phase 7/9/10): {REGIME_SET}", flush=True)
    n_main_screen = len(FEATURE_SET) * len(HORIZON_SET)
    n_regime_tests = len(FEATURE_SET) * len(REGIME_SET)
    total = n_main_screen + n_regime_tests
    print(f"  planned test count: {n_main_screen} (main screen: features x horizons) + {n_regime_tests} (regime) = {total} total", flush=True)

    family_record = PreregistrationRecord(
        hypothesis_id="P12-CSRS-FAMILY", hypothesis_version="1.0",
        rationale="Shared discovery family manifest for the CROSS_SECTIONAL_RELATIVE_STRENGTH campaign (Part 20) — the complete "
                   "feature x horizon x regime test matrix, fixed before any analysis ran.",
        expected_direction="positive", target_definition=TARGET, features=FEATURE_SET, universe_name=universe.name, time_horizon_bars=PRIMARY_HORIZON,
        parameter_ranges={"feature_set": list(FEATURE_SET), "horizon_set": list(HORIZON_SET), "regime_set": list(REGIME_SET),
                           "beta_window": BETA_WINDOW, "residual_momentum_window": RESIDUAL_MOMENTUM_WINDOW, "planned_test_count": total},
        validation_methodology="cross-sectional IC (Spearman+Pearson), quantile, incremental-information, regime, year/quarter "
                                "stability, breadth, placebo, multiple-testing, purged-CV, bootstrap, PBO, DSR — DISCOVERY_DATA only",
        cost_assumptions="not applicable at the discovery stage — no trades are simulated, turnover/cost estimated analytically",
        success_criteria=("see scripts/phase12_step2_discovery_campaign.py's per-hypothesis classification logic",),
        falsification_criteria=("raw momentum existing alone is NOT sufficient — see phase philosophy: incremental information is the bar",),
        registered_at=datetime.now(timezone.utc),
    )
    if prereg_store.get(family_record.hypothesis_id, family_record.hypothesis_version) is None:
        prereg_store.register(family_record)
    print(f"\nPreregistered family manifest: {family_record.hypothesis_id} v{family_record.hypothesis_version}", flush=True)
    print("\nSTEP 1 COMPLETE — no discovery analysis has run yet.", flush=True)


if __name__ == "__main__":
    main()
