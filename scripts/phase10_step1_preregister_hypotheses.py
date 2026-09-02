#!/usr/bin/env python3
"""Phase 10, Parts 1-7 & 21 — STEP 1: preregisters the NEW
VOLATILITY_PERSISTENCE hypothesis family (P10-VP-001..010) and the
COMPLETE discovery test family (features x targets x horizons x regimes)
before any analysis runs — same discipline as Phase 9's Step 1.

Explicitly NOT a continuation or parameter variation of P7-VOLANOM-A,
P7-VOLANOM-A-DEV1, or P9-VOLCLUST-A (read-only lookups only, asserted
below; parent_hypothesis_id=None for every P10 hypothesis).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import us_diversified_universe  # noqa: E402
from src.research import Hypothesis, HypothesisRegistry  # noqa: E402
from src.research.preregistration import PreregistrationRecord, PreregistrationStore  # noqa: E402

# --- preregistered feature set (Part 4) — compact, one canonical parameterization per concept --
FEATURE_SET = (
    "realized_vol_5", "realized_vol_10", "realized_vol_20", "realized_vol_60",
    "volatility_zscore_20", "volatility_percentile_60", "short_long_vol_ratio",
    "volatility_change_5", "volatility_change_10", "volatility_acceleration",
    "volatility_persistence_score", "volatility_regime", "volatility_regime_duration",
    "volatility_shock", "volatility_compression", "volatility_expansion",
)

# --- preregistered target set (Part 5) ----------------------------------------------------------
TARGET_SET = (
    "future_realized_volatility", "future_realized_variance",
    "future_volatility_change", "future_volatility_direction",
    "future_absolute_return", "future_absolute_cumulative_return", "future_max_absolute_move",
    "future_max_drawdown", "future_return", "future_risk_adjusted_return",
)
PRIMARY_TARGET = "future_realized_volatility"

# --- preregistered horizon set (Part 6) ---------------------------------------------------------
HORIZON_SET = (1, 3, 5, 10, 20)
PRIMARY_HORIZON = 5  # continuity with Phase 7/9's own primary horizon choice, NOT selected after seeing any Phase 10 result

# --- preregistered volatility-regime states (Part 9) — exact quartile cut points ----------------
VOL_REGIME_STATES = ("LOW", "NORMAL", "HIGH", "EXTREME")  # VolatilityRegimeState(window=20, lookback=100): quartiles of the trailing 100-bar volatility-percentile distribution

# --- preregistered mean-reversion / compression / expansion thresholds (Parts 10-11) ------------
VOLATILITY_SHOCK_ZSCORE_THRESHOLD = 2.0
VOLATILITY_COMPRESSION_PERCENTILE_THRESHOLD = 0.20
VOLATILITY_EXPANSION_PERCENTILE_THRESHOLD = 0.80

# --- the existing 5-regime taxonomy reused from Phase 7/9 (bull/bear x high/low vol) for the -----
# --- regime cross-check table (distinct from the volatility-only LOW/NORMAL/HIGH/EXTREME above) -
REGIME_SET = ("bull_high_vol", "bull_low_vol", "bear_high_vol", "bear_low_vol", "unknown")

HYPOTHESES = {
    "P10-VP-001": dict(
        name="Volatility Persistence (recent -> future realized volatility)",
        statement="Recent realized volatility (realized_vol_20) predicts future realized volatility. Research Question A. "
                   "This is the EXPECTED, well-known baseline relationship (volatility clustering) — the discovery question is "
                   "whether it is statistically robust and temporally clean here, not whether it exists at all.",
        features=("realized_vol_20",), target=PRIMARY_TARGET, horizon=PRIMARY_HORIZON,
    ),
    "P10-VP-002": dict(
        name="Volatility Regime Persistence",
        statement="Volatility regime membership (LOW/NORMAL/HIGH/EXTREME, VolatilityRegimeState) persists over time — measured via "
                   "regime transition probabilities and expected episode duration. Research Question B.",
        features=("volatility_regime",), target=None, horizon=None,
    ),
    "P10-VP-003": dict(
        name="Volatility Mean Reversion After a Shock",
        statement="Extreme volatility shocks (VolatilityZScore(20) > 2.0, the preregistered 'volatility_shock' threshold) mean-revert "
                   "toward normal volatility over the following 1/3/5/10/20 bars. Research Question D.",
        features=("volatility_shock", "volatility_zscore_20", "realized_vol_20"), target=PRIMARY_TARGET, horizon=None,
    ),
    "P10-VP-004": dict(
        name="Volatility Momentum (acceleration -> continued expansion)",
        statement="Volatility acceleration (the 2nd difference of realized_vol_20) predicts CONTINUED volatility expansion, not just "
                   "the level of future volatility. Research Question E.",
        features=("volatility_acceleration",), target="future_volatility_change", horizon=PRIMARY_HORIZON,
    ),
    "P10-VP-005": dict(
        name="Volatility Term Structure",
        statement="short_long_vol_ratio (realized_vol_5 / realized_vol_20) predicts future volatility DIRECTION (rising vs falling), "
                   "where available data supports a short-vs-long-run volatility comparison. Research Question F.",
        features=("short_long_vol_ratio",), target="future_volatility_direction", horizon=PRIMARY_HORIZON,
    ),
    "P10-VP-006": dict(
        name="Volatility Regime -> Future Return Magnitude",
        statement="Volatility regime (LOW/NORMAL/HIGH/EXTREME) predicts future absolute-return magnitude — i.e. identifies "
                   "environments of larger or smaller absolute moves. Research Question I.",
        features=("volatility_regime",), target="future_absolute_return", horizon=PRIMARY_HORIZON,
    ),
    "P10-VP-007": dict(
        name="Volatility Regime -> Conditional Return Distribution",
        statement="Volatility regime changes the conditional DISTRIBUTION of future returns (mean/median/Sharpe-like/downside "
                   "deviation/win rate), tested separately from whether it predicts DIRECTION. Research Question G.",
        features=("volatility_regime",), target="future_return", horizon=PRIMARY_HORIZON,
    ),
    "P10-VP-008": dict(
        name="Volatility Regime -> Future Drawdown Risk",
        statement="Volatility regime predicts future maximum-drawdown magnitude — potentially useful as RISK MANAGEMENT "
                   "information even if it cannot produce excess return. Research Question H.",
        features=("volatility_regime",), target="future_max_drawdown", horizon=PRIMARY_HORIZON,
    ),
    "P10-VP-009": dict(
        name="Volatility Compression -> Subsequent Expansion",
        statement="Volatility compression (bottom quintile of the trailing 60-bar realized-vol percentile distribution) predicts "
                   "subsequent volatility EXPANSION. Research Questions E/F.",
        features=("volatility_compression",), target="future_volatility_direction", horizon=None,
    ),
    "P10-VP-010": dict(
        name="Volatility Expansion -> Subsequent Contraction",
        statement="Volatility expansion (top quintile of the trailing 60-bar realized-vol percentile distribution) predicts "
                   "subsequent volatility CONTRACTION — the mirror image of P10-VP-009.",
        features=("volatility_expansion",), target="future_volatility_direction", horizon=None,
    ),
}


def main() -> None:
    universe = us_diversified_universe()
    hyp_registry = HypothesisRegistry(Path("logs/research_data/hypotheses.jsonl"))
    prereg_store = PreregistrationStore(Path("logs/research_data/phase10_preregistrations.jsonl"))

    # --- read-only confirmation: prior phases' hypotheses remain untouched, never re-registered --
    for prior_id in ("P7-VOLANOM-A", "P7-VOLANOM-A-DEV1", "P9-VOLCLUST-A"):
        prior = hyp_registry.get(prior_id)
        if prior is None:
            raise RuntimeError(f"{prior_id} not found — Phases 7-9 must have run first. Refusing to invent context.")
        print(f"Prior hypothesis (READ-ONLY, unmodified): {prior.hypothesis_id} — {prior.name}", flush=True)
    print(flush=True)

    for hyp_id, spec in HYPOTHESES.items():
        hypothesis = Hypothesis(
            hypothesis_id=hyp_id, name=spec["name"], version="1.0",
            description=spec["statement"], economic_intuition=spec["statement"],
            mathematical_definition=f"features: {spec['features']}; target: {spec['target']}; horizon: {spec['horizon']}",
            required_data=("daily OHLCV",), required_features=spec["features"], prediction_horizon_bars=spec["horizon"] or PRIMARY_HORIZON,
            test_methodology="cross-sectional IC (Spearman + Pearson) / quantile / regime-transition / mean-reversion / "
                              "compression-expansion / incremental-information (OLS) / temporal-alignment / autocorrelation / "
                              "placebo analysis on DISCOVERY_DATA only — no backtest, no trading strategy this phase",
            expected_direction="positive", assumptions=(
                "this is a NEW hypothesis family (VOLATILITY_PERSISTENCE), explicitly NOT a continuation or parameter variation "
                "of P7-VOLANOM-A, P7-VOLANOM-A-DEV1, or P9-VOLCLUST-A",
                "volatility predicting volatility is EXPECTED (well-known clustering) — the real question is incremental "
                "information and economic value, not existence of raw persistence",
            ),
            family="volatility_persistence", target_definition=spec["target"] or PRIMARY_TARGET,
            holding_period_bars=None, entry_rule="N/A — discovery-stage only, no trading strategy this phase", exit_rule="N/A",
            universe=universe.symbols, expected_mechanism="volatility clustering / information arrival / liquidity conditions / "
                                                            "market-wide risk repricing / behavioral feedback (ECONOMIC_RATIONALE, not CAUSAL_PROOF)",
            falsification_criteria=(
                "IC (Spearman or Pearson) not reliably in the expected direction across DISCOVERY_DATA",
                "shifted-alignment IC is >= true-alignment IC (TEMPORAL_ALIGNMENT_CONCERN)",
                "the relationship does not survive shuffled-signal, shifted-signal, or time-shuffled-target placebo tests",
                "no incremental information beyond simple lagged realized volatility (Part 8)",
                "the relationship is concentrated in one symbol or one sector (leave-one-out)",
            ),
            parent_hypothesis_id=None, development_version=None,  # NEW family — no parent hypothesis
        )
        if hyp_registry.get(hyp_id) is None:
            hyp_registry.register(hypothesis)
        print(f"Registered: {hyp_id} — {spec['name']}", flush=True)

        record = PreregistrationRecord(
            hypothesis_id=hyp_id, hypothesis_version="1.0", rationale=spec["statement"], expected_direction="positive",
            target_definition=spec["target"] or PRIMARY_TARGET, features=spec["features"], universe_name=universe.name,
            time_horizon_bars=spec["horizon"] or PRIMARY_HORIZON,
            parameter_ranges={"features": list(spec["features"]), "target": spec["target"], "horizon": spec["horizon"]},
            validation_methodology="see Hypothesis.test_methodology", cost_assumptions="not applicable at the discovery stage — no trades are simulated",
            success_criteria=("see scripts/phase10_step2_discovery_campaign.py's per-hypothesis classification logic",),
            falsification_criteria=hypothesis.falsification_criteria, registered_at=datetime.now(timezone.utc),
        )
        if prereg_store.get(hyp_id, "1.0") is None:
            prereg_store.register(record)

    print(f"\n{len(HYPOTHESES)} hypotheses registered under family='volatility_persistence', none derived from a prior phase's hypothesis.\n", flush=True)

    # --- the SHARED, complete discovery family (Part 21: corrected as ONE family) ----------------
    print("PREREGISTERED SHARED DISCOVERY FAMILY (Part 21 — corrected as ONE family across ALL hypotheses):", flush=True)
    print(f"  features ({len(FEATURE_SET)}): {FEATURE_SET}", flush=True)
    print(f"  targets ({len(TARGET_SET)}): {TARGET_SET}  (primary={PRIMARY_TARGET})", flush=True)
    print(f"  horizons ({len(HORIZON_SET)}): {HORIZON_SET}  (primary={PRIMARY_HORIZON})", flush=True)
    print(f"  volatility-regime states ({len(VOL_REGIME_STATES)}): {VOL_REGIME_STATES}", flush=True)
    print(f"  regime cross-check taxonomy ({len(REGIME_SET)}, reused from Phase 7/9): {REGIME_SET}", flush=True)
    n_main_screen = len(FEATURE_SET) * len(TARGET_SET)  # all features x all targets @ primary horizon
    n_horizon_table = len(FEATURE_SET) * (len(HORIZON_SET) - 1)  # all features x remaining horizons @ primary target
    n_regime_tests = len(FEATURE_SET) * len(REGIME_SET)  # all features @ primary target/horizon, by regime
    total = n_main_screen + n_horizon_table + n_regime_tests
    print(f"  planned test count: {n_main_screen} (main screen) + {n_horizon_table} (horizon table) + {n_regime_tests} (regime) = {total} total", flush=True)

    family_record = PreregistrationRecord(
        hypothesis_id="P10-VOLPERSIST", hypothesis_version="1.0",
        rationale="Shared discovery family manifest for the VOLATILITY_PERSISTENCE campaign (Part 21) — the complete "
                   "feature x target x horizon x regime test matrix, fixed before any analysis ran, so multiple-testing "
                   "correction accounts for everything tested, not just whichever result looks interesting afterward.",
        expected_direction="positive", target_definition=PRIMARY_TARGET, features=FEATURE_SET, universe_name=universe.name,
        time_horizon_bars=PRIMARY_HORIZON,
        parameter_ranges={"feature_set": list(FEATURE_SET), "target_set": list(TARGET_SET), "horizon_set": list(HORIZON_SET),
                           "vol_regime_states": list(VOL_REGIME_STATES), "regime_set": list(REGIME_SET), "planned_test_count": total,
                           "volatility_shock_zscore_threshold": VOLATILITY_SHOCK_ZSCORE_THRESHOLD,
                           "volatility_compression_percentile_threshold": VOLATILITY_COMPRESSION_PERCENTILE_THRESHOLD,
                           "volatility_expansion_percentile_threshold": VOLATILITY_EXPANSION_PERCENTILE_THRESHOLD},
        validation_methodology="cross-sectional IC (Spearman + Pearson), quantile, temporal-alignment, autocorrelation, regime, "
                                "regime-transition, mean-reversion, compression/expansion, symbol/sector robustness, baseline "
                                "comparison, incremental-information (OLS), placebo battery — DISCOVERY_DATA only",
        cost_assumptions="not applicable at the discovery stage — no trades are simulated",
        success_criteria=("see scripts/phase10_step2_discovery_campaign.py's per-hypothesis classification logic",),
        falsification_criteria=("volatility predicting volatility alone is NOT sufficient evidence of alpha — see phase philosophy",),
        registered_at=datetime.now(timezone.utc),
    )
    if prereg_store.get(family_record.hypothesis_id, family_record.hypothesis_version) is None:
        prereg_store.register(family_record)
    print(f"\nPreregistered family manifest: {family_record.hypothesis_id} v{family_record.hypothesis_version}", flush=True)
    print("\nSTEP 1 COMPLETE — no discovery analysis has run yet.", flush=True)


if __name__ == "__main__":
    main()
