#!/usr/bin/env python3
"""Phase 9, Parts 1-4, 16 — STEP 1: preregisters P9-VOLCLUST-A, a NEW
economic hypothesis (related to, but NOT a parameter variation of,
P7-VOLANOM-A) — before any discovery analysis runs. Also preregisters the
COMPLETE discovery family (features x targets x horizons x regimes) so
Part 16's multiple-testing accounting corrects everything tested, not
just the final "interesting" result.

Does NOT modify P7-VOLANOM-A or P7-VOLANOM-A-DEV1 (read-only lookups,
asserted below).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import us_diversified_universe  # noqa: E402
from src.research import Hypothesis, HypothesisRegistry  # noqa: E402
from src.research.preregistration import PreregistrationRecord, PreregistrationStore  # noqa: E402

# --- preregistered feature set (Part 3-4) — SMALL, not hundreds of correlated variants -------
FEATURE_SET = (
    "relative_volume_10",           # RelativeVolume(10) — exact P7-VOLANOM-A feature, unmodified
    "relative_volume_20",           # RelativeVolume(20) — a second, slower baseline
    "log_relative_volume_10",       # log(volume / rolling_mean(volume))
    "volume_zscore_20",             # volume z-score
    "volume_percentile_10_100",     # volume percentile/rank (reuses existing VolumePercentile)
    "volume_change_5",              # volume change (reuses existing VolumeChange)
    "volume_acceleration_10",       # change in RelativeVolume itself (second-derivative-ish)
    "volume_frac_above_10_1.5_10",  # rolling fraction of trailing 10 bars with RelativeVolume(10) > 1.5 — PERSISTENT cluster indicator
    "volume_streak_10_1.5",         # consecutive abnormal-volume streak length
    "volume_rolling_mean_10_10",    # rolling mean of RelativeVolume(10) — smooths one-day shocks
    "volume_rolling_std_10_10",     # rolling stdev of RelativeVolume(10)
)

# --- preregistered target set (Part 2) --------------------------------------------------------
TARGET_SET = ("future_realized_volatility", "future_realized_variance", "future_absolute_cumulative_return", "future_max_absolute_move")
PRIMARY_TARGET = "future_realized_volatility"

# --- preregistered horizon set (Part 9) -------------------------------------------------------
HORIZON_SET = (1, 2, 3, 5, 10, 20)
PRIMARY_HORIZON = 5  # matches P7-VOLANOM-A's own horizon, for continuity — NOT chosen after seeing any Phase 9 result

REGIME_SET = ("bull_high_vol", "bull_low_vol", "bear_high_vol", "bear_low_vol", "unknown")


def main() -> None:
    universe = us_diversified_universe()
    hyp_registry = HypothesisRegistry(Path("logs/research_data/hypotheses.jsonl"))

    parent = hyp_registry.get("P7-VOLANOM-A")
    dev = hyp_registry.get("P7-VOLANOM-A-DEV1")
    if parent is None or dev is None:
        raise RuntimeError("P7-VOLANOM-A and/or P7-VOLANOM-A-DEV1 not found — Phases 7-8 must have run first. Refusing to invent context.")
    print(f"Parent (READ-ONLY, unmodified): {parent.hypothesis_id} — {parent.mathematical_definition}", flush=True)
    print(f"Sibling (READ-ONLY, unmodified): {dev.hypothesis_id} — classification recorded in Phase 8 as INCONCLUSIVE, NOT reused here\n", flush=True)

    statement = (
        "Periods of unusually high trading volume may be associated with elevated subsequent realized return "
        "magnitude/volatility, because volume clustering reflects changing market activity, information arrival, "
        "liquidity conditions, or regime transitions. This is NOT 'higher volume -> higher stock price' — direction "
        "is explicitly NOT being predicted. Related to P7-VOLANOM-A (which found a magnitude relationship using a "
        "single feature and single target) but this is a NEW economic hypothesis, not a parameter variation of it: "
        "P7-VOLANOM-A tested one feature (RelativeVolume(10)) against one target (|future_return|) with no "
        "distinction between a one-day shock and a persistent cluster; P9-VOLCLUST-A tests whether PERSISTENCE of "
        "abnormal volume specifically (not just its instantaneous level) carries information, against a properly "
        "constructed family of volatility/magnitude targets, and explicitly tests whether that information is "
        "INCREMENTAL to what past realized volatility already tells us."
    )

    hypothesis = Hypothesis(
        hypothesis_id="P9-VOLCLUST-A", name="Volume Clustering vs Future Volatility/Magnitude", version="1.0",
        description=statement, economic_intuition=statement,
        mathematical_definition=f"features: {FEATURE_SET}; targets: {TARGET_SET}; horizons: {HORIZON_SET}",
        required_data=("daily OHLCV",), required_features=FEATURE_SET, prediction_horizon_bars=PRIMARY_HORIZON,
        test_methodology="cross-sectional IC (Spearman AND Pearson)/quantile/regime/temporal-alignment/autocorrelation/incremental-information analysis on DISCOVERY_DATA only — no backtest, no trading strategy this phase",
        expected_direction="positive", assumptions=(
            "direction of future RETURN is explicitly not being predicted — only magnitude/volatility",
            "a successful discovery result does NOT by itself imply the information has economic/tradable value (Part 19) — that is a SEPARATE question for a later phase",
        ),
        family="volume_clustering", target_definition=PRIMARY_TARGET,
        holding_period_bars=None, entry_rule="N/A — discovery-stage only, no trading strategy this phase", exit_rule="N/A",
        universe=universe.symbols, expected_mechanism="volume clustering reflects information arrival/liquidity/regime-transition dynamics that elevate near-term realized volatility, independent of directional bias",
        falsification_criteria=(
            "IC (Spearman or Pearson) not reliably positive across DISCOVERY_DATA for the primary target/horizon",
            "shifted-alignment IC is >= true-alignment IC (TEMPORAL_ALIGNMENT_CONCERN) for the primary feature/target",
            "the relationship does not survive shuffled-signal, shifted-signal, time-shuffled-target, or random-feature placebo tests",
            "volume features add no incremental explanatory power (R^2) beyond lagged realized volatility alone (Part 14)",
            "the relationship is concentrated in one symbol or one sector (leave-one-out)",
            "the relationship does not generalize across regimes",
        ),
        parent_hypothesis_id="P7-VOLANOM-A", development_version=None,  # explicitly a NEW hypothesis, not a development version of the parent
    )
    if hyp_registry.get(hypothesis.hypothesis_id) is None:
        hyp_registry.register(hypothesis)
    print(f"Registered: {hypothesis.hypothesis_id} (parent={hypothesis.parent_hypothesis_id}, NOT a parameter variation)\n", flush=True)

    print("PREREGISTERED DISCOVERY FAMILY (Part 16 — corrected as ONE family, not just the final result):", flush=True)
    print(f"  features ({len(FEATURE_SET)}): {FEATURE_SET}", flush=True)
    print(f"  targets ({len(TARGET_SET)}): {TARGET_SET}  (primary={PRIMARY_TARGET})", flush=True)
    print(f"  horizons ({len(HORIZON_SET)}): {HORIZON_SET}  (primary={PRIMARY_HORIZON})", flush=True)
    print(f"  regimes ({len(REGIME_SET)}): {REGIME_SET}", flush=True)
    n_main_screen = len(FEATURE_SET) * len(TARGET_SET)  # all features x all targets @ primary horizon
    n_horizon_table = len(FEATURE_SET) * (len(HORIZON_SET) - 1)  # all features x remaining horizons @ primary target (primary horizon already in the main screen)
    n_regime_tests = len(FEATURE_SET) * len(REGIME_SET)  # all features @ primary target/horizon, by regime
    total = n_main_screen + n_horizon_table + n_regime_tests
    print(f"  planned test count: {n_main_screen} (main screen) + {n_horizon_table} (horizon table) + {n_regime_tests} (regime) = {total} total", flush=True)

    prereg_store = PreregistrationStore(Path("logs/research_data/phase9_preregistrations.jsonl"))
    record = PreregistrationRecord(
        hypothesis_id="P9-VOLCLUST-A", hypothesis_version="1.0", rationale=statement, expected_direction="positive",
        target_definition=PRIMARY_TARGET, features=FEATURE_SET, universe_name=universe.name, time_horizon_bars=PRIMARY_HORIZON,
        parameter_ranges={"feature_set": list(FEATURE_SET), "target_set": list(TARGET_SET), "horizon_set": list(HORIZON_SET), "regime_set": list(REGIME_SET), "planned_test_count": total},
        validation_methodology="cross-sectional IC (Spearman + Pearson), quantile, temporal-alignment, autocorrelation, regime, symbol/sector robustness, baseline comparison, incremental-information (OLS), placebo battery — DISCOVERY_DATA only",
        cost_assumptions="not applicable at the discovery stage — no trades are simulated",
        success_criteria=(
            "primary feature/target/horizon IC (Spearman AND Pearson) reliably positive and statistically significant after multiple-testing correction",
            "no TEMPORAL_ALIGNMENT_CONCERN for the primary feature/target",
            "survives the full placebo battery",
            "volume features show genuine INCREMENTAL_PREDICTIVE_INFORMATION beyond lagged realized volatility",
            "relationship generalizes across symbols/sectors/regimes, not concentrated in one",
        ),
        falsification_criteria=hypothesis.falsification_criteria, registered_at=datetime.now(timezone.utc),
    )
    if prereg_store.get(record.hypothesis_id, record.hypothesis_version) is None:
        prereg_store.register(record)
    print(f"\nPreregistered in PreregistrationStore: {record.hypothesis_id} v{record.hypothesis_version}", flush=True)
    print("\nSTEP 1 COMPLETE — no discovery analysis has run yet.", flush=True)


if __name__ == "__main__":
    main()
