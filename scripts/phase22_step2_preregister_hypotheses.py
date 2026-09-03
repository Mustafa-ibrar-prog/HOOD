#!/usr/bin/env python3
"""Phase 22, STEP 2 — preregisters the NEW `options_specific_alpha`
hypothesis family (P22-OPT-001..013) BEFORE any discovery analysis
runs. Must be run AFTER scripts/phase22_step1_build_feature_panel.py.

Every P22-OPT-* hypothesis has parent_hypothesis_id=None -- this is a
NEW family, explicitly not a continuation of Phase 19's `options_alpha`
or Phase 21's falsification family. Per Part 22's discovery discipline:
exactly 13 hypotheses (within the requested ~12-15 range), every one
economically motivated BEFORE its result is computed, none added after
seeing a favorable number.

Themes covered (Part 4): A (option/underlying relative behavior) x2,
B (convexity/move magnitude) x3, C (option price behavior) x4,
D (underlying/option divergence) x1, E (moneyness interaction) x1,
F (DTE interaction) x1, G (volatility regime) x1.
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

# hypothesis_id -> (name, statement, theme, features, target, expected_direction, exclusions)
HYPOTHESES = {
    "P22-OPT-001": (
        "Naive option-vs-underlying excess momentum persists",
        "option_naive_excess_momentum_5 (trailing 5-day option return MINUS trailing 5-day underlying return, an "
        "unscaled OPTION_UNDERLYING_RELATIVE_RETURN) predicts option_naive_excess_return_5 (the same naive excess "
        "definition, forward) -- does recent unscaled outperformance persist.",
        "A", ("option_naive_excess_momentum_5",), "option_naive_excess_return_5", "positive",
        ("rows where trailing 5-day underlying return is unavailable (contract's first 5 observations)",),
    ),
    "P22-OPT-002": (
        "Beta-scaled option-vs-underlying excess momentum persists",
        "option_beta_scaled_excess_momentum_5 (trailing option return minus a rolling-15-day EMPIRICAL realized beta "
        "times trailing underlying return -- explicitly NOT a Greek, see src.options.relative_return) predicts "
        "option_beta_scaled_excess_return_5 (same beta-scaled definition, forward) -- the refined version of P22-OPT-001.",
        "A", ("option_beta_scaled_excess_momentum_5",), "option_beta_scaled_excess_return_5", "positive",
        ("rows without a rolling_beta_15 estimate (first 15 observations, or a degenerate/flat underlying window)",),
    ),
    "P22-OPT-003": (
        "Underlying volatility expansion predicts DIRECTIONAL option return",
        "underlying_vol_ratio_5_20 (5-day realized vol / 20-day realized vol -- >1 means recent vol expansion) "
        "predicts the SIGNED forward_return_5 of the option.",
        "B", ("underlying_vol_ratio_5_20",), "forward_return_5", "unsigned",
        ("rows without a defined 20-day underlying vol estimate (first 20 trading days of an underlying's series)",),
    ),
    "P22-OPT-004": (
        "Underlying volatility expansion predicts option MOVE MAGNITUDE (opportunity, not direction)",
        "underlying_vol_ratio_5_20 predicts abs_forward_return_5 -- explicitly separating 'opportunity magnitude' "
        "from P22-OPT-003's directional question; mandatory underlying-control test distinguishes genuine option-"
        "specific magnitude information from mechanical big-move-in-underlying pass-through.",
        "B", ("underlying_vol_ratio_5_20",), "abs_forward_return_5", "positive",
        ("rows without a defined 20-day underlying vol estimate",),
    ),
    "P22-OPT-005": (
        "Large recent underlying moves predict option continuation (post-move drift)",
        "underlying_squared_return (the underlying's own same-day squared daily return, a move-magnitude feature) "
        "predicts forward_return_5 of the option over the following 5 bars.",
        "B", ("underlying_squared_return",), "forward_return_5", "unsigned",
        ("rows without a defined underlying_daily_return (first observation of an underlying's series)",),
    ),
    "P22-OPT-006": (
        "Option's own short-term (5-day) momentum persists",
        "option_momentum_5 (the option contract's OWN trailing 5-day return, independent of the underlying) "
        "predicts forward_return_5 -- a classic momentum test on the option price itself.",
        "C", ("option_momentum_5",), "forward_return_5", "positive",
        ("rows without 5 prior observations for this contract",),
    ),
    "P22-OPT-007": (
        "Option's own medium-term (10-day) momentum REVERSES over the following 5 days",
        "option_momentum_10 (trailing 10-day option return) predicts forward_return_5 with a NEGATIVE expected "
        "sign -- a distinct economic mechanism/lookback from P22-OPT-006's short-term persistence hypothesis "
        "(medium-term mean reversion vs. short-term momentum are documented as genuinely different phenomena).",
        "C", ("option_momentum_10",), "forward_return_5", "negative",
        ("rows without 10 prior observations for this contract",),
    ),
    "P22-OPT-008": (
        "The option's OWN realized-volatility expansion (not the underlying's) carries information",
        "option_vol_ratio_5_20 (the OPTION contract's own close-to-close realized-vol expansion ratio, a "
        "REALIZED_OPTION_PRICE_VOLATILITY_PROXY -- never IV) predicts forward_return_5. Computed entirely from the "
        "option's own price series, independent of any underlying feature -- directly tests whether option-price-"
        "level information (not just underlying-derived information) is predictive.",
        "C", ("option_vol_ratio_5_20",), "forward_return_5", "unsigned",
        ("rows without a defined 20-bar option-own vol estimate for this contract",),
    ),
    "P22-OPT-009": (
        "Option-vs-underlying return-RATIO divergence predicts option return",
        "option_underlying_return_ratio_5 (trailing 5-day option return DIVIDED BY trailing 5-day underlying "
        "return -- a genuinely different transformation from P22-OPT-001/002's subtraction-based excess) predicts "
        "forward_return_5. Excludes rows where |trailing underlying return| < 0.2% (numerically unstable ratio).",
        "D", ("option_underlying_return_ratio_5",), "forward_return_5", "unsigned",
        ("rows where |trailing 5-day underlying return| < 0.2% (ratio numerically unstable, not fabricated)",
         "rows without 5 prior observations for this contract"),
    ),
    "P22-OPT-010": (
        "Moneyness modifies the underlying-volatility-expansion relationship",
        "vol_expansion_x_moneyness (underlying_vol_ratio_5_20 * log_moneyness, a NEW preregistered interaction "
        "term -- NOT a revival of Phase 21's rejected raw log-moneyness, P19-OPT-009) predicts forward_return_5. "
        "Tests whether moneyness modifies P22-OPT-003/004's independently-motivated vol-expansion relationship, "
        "per Part 4 Theme E's explicit instruction to interact rather than revive.",
        "E", ("vol_expansion_x_moneyness",), "forward_return_5", "unsigned",
        ("rows without a defined underlying_vol_ratio_5_20",),
    ),
    "P22-OPT-011": (
        "DTE modifies the underlying-move-magnitude relationship",
        "squared_move_x_dte (underlying_squared_return * dte, a NEW preregistered interaction term) predicts "
        "forward_return_5. Tests whether days-to-expiration modifies P22-OPT-005's move-magnitude relationship "
        "(shorter-dated contracts theoretically more convex to a given move). If the sample's DTE variance is "
        "insufficient, this hypothesis reports INSUFFICIENT_DTE_VARIANCE rather than a misleading statistic.",
        "F", ("squared_move_x_dte",), "forward_return_5", "unsigned",
        ("rows without a defined underlying_daily_return",),
    ),
    "P22-OPT-012": (
        "Underlying volatility REGIME/LEVEL changes option attractiveness",
        "underlying_lagged_realized_vol (the LEVEL of realized volatility, not its recent change/ratio -- Phase "
        "19/20's existing causal 20-day lagged realized-vol feature) predicts forward_return_5, with an explicit "
        "opportunity-vs-risk breakdown (comparing this feature's IC against forward_return_5 to its IC against "
        "abs_forward_return_5, and its behavior across the existing bull/bear x high/low-vol regime buckets) so a "
        "higher-vol-regime return is not automatically read as alpha rather than higher risk.",
        "G", ("underlying_lagged_realized_vol",), "forward_return_5", "unsigned",
        ("rows without a defined underlying_lagged_realized_vol (first 20 trading days of an underlying's series)",),
    ),
    "P22-OPT-013": (
        "Option's own range expansion predicts a larger favorable excursion (path-dependent target)",
        "option_range_expansion_5 (today's own (high-low)/close vs. the trailing 5-day baseline of that same ratio) "
        "predicts mfe_5 (max favorable excursion over the following 5 bars, reusing "
        "src.options.return_normalization.compute_normalized_return directly) -- a genuinely different, path-"
        "dependent target from every other hypothesis's close-to-close return.",
        "C", ("option_range_expansion_5",), "mfe_5", "positive",
        ("rows without 5 prior observations for this contract (range-expansion warmup)",
         "rows within the final 5 bars of a contract's own series (mfe_5 needs a full forward window)"),
    ),
}

PRIMARY_HORIZON = 5  # trading days -- shared primary horizon; several hypotheses use a horizon-5 target explicitly
FAMILY = "options_specific_alpha"


def main() -> None:
    universe = phase20_verified_underlying_universe()
    hyp_registry = HypothesisRegistry(Path("logs/research_data/hypotheses.jsonl"))
    prereg_store = PreregistrationStore(Path("logs/research_data/phase22_preregistrations.jsonl"))

    print(f"NEW FAMILY: {FAMILY} — every P22-OPT-* hypothesis has parent_hypothesis_id=None "
          f"(explicitly not a continuation of Phase 19's options_alpha or Phase 21's falsification family).\n", flush=True)
    print(f"UNIVERSE: {universe.name} — {universe.symbols}", flush=True)
    print("DATA: logs/research_data/phase22_research_panel.jsonl (feature-augmented, built from the already-"
          "gathered real Phase 19+20 panel -- no new MCP fetch this phase).\n", flush=True)
    print("LABEL (applies to every hypothesis): all research this phase is MARK_TO_MARKET_HISTORICAL_RESEARCH. "
          "No historical bid/ask/volume/OI/IV/Greeks exist for this connector and none are fabricated or "
          "reconstructed-and-presented-as-observed this phase.\n", flush=True)

    for hyp_id, (name, statement, theme, features, target, direction, exclusions) in HYPOTHESES.items():
        hypothesis = Hypothesis(
            hypothesis_id=hyp_id, name=name, version="1.0", description=statement, economic_intuition=statement,
            mathematical_definition=f"theme={theme}; features={features}; target={target}; horizon={PRIMARY_HORIZON}",
            required_data=("real option OHLC bars (Phase 19+20 get_option_historicals)", "real underlying OHLC bars (Phase 19+20 get_equity_historicals)"),
            required_features=features, prediction_horizon_bars=PRIMARY_HORIZON,
            test_methodology="cross-sectional IC (Spearman) / temporal-symbol-expiration-moneyness-call-put leave-one-out / "
                              "mandatory outlier treatment / underlying-control Model A-B-C / mechanical-leverage note "
                              "(HISTORICAL_GREEKS_UNAVAILABLE) / IC-based placebo battery (7 types) / temporal-shift test / "
                              "dependence-aware bootstrap (time-block, stationary, symbol-cluster) / multiple-testing "
                              "correction (Bonferroni/Holm/BH) / PBO/DSR where valid / cost sensitivity (1x-5x ASSUMPTION) / "
                              "economic significance -- MARK_TO_MARKET_HISTORICAL_RESEARCH only, no strategy, no order",
            expected_direction=direction,
            assumptions=(
                "this is a NEW hypothesis family (options_specific_alpha), explicitly not a continuation of Phase 19's "
                "options_alpha family or Phase 21's falsification family -- parent_hypothesis_id=None for every member",
                "all data is MARK_TO_MARKET_HISTORICAL_RESEARCH -- no historical bid/ask/volume/OI/IV/Greeks exist for "
                "this connector; none are fabricated, interpolated, or reconstructed-and-presented-as-observed",
                "any rolling-beta / relative-return feature is an EMPIRICAL realized statistic, explicitly NOT a Greek "
                "(see src.options.relative_return's module docstring for the exact limitation)",
                f"underlying universe is {universe.name}: the same 12 symbols verified in Phase 19/20, no new symbol added",
                "contract existence before first observation is UNKNOWN_EXISTENCE (unchanged from Phase 19/20/21) -- no "
                "survivorship-bias-free options universe is claimed",
                f"theme={theme} (Part 4 taxonomy: A=relative behavior, B=convexity/magnitude, C=option price behavior, "
                "D=divergence, E=moneyness interaction, F=DTE interaction, G=volatility regime)",
            ),
            family=FAMILY, target_definition=target,
            holding_period_bars=None, entry_rule="N/A — discovery-stage only, no trading strategy this phase", exit_rule="N/A",
            universe=universe.symbols, expected_mechanism=statement,
            falsification_criteria=(
                "IC (Spearman) not reliably in the expected direction after multiple-testing correction",
                "the relationship fails the underlying-control test (Model A IC >= Model B IC / incremental R2 below "
                "threshold) -> classified INHERITED_FROM_UNDERLYING",
                "the relationship does not survive the IC-based placebo battery (7 types)",
                "the relationship's sign flips under modest outlier treatment (top-1% removal or <=5% winsorization) "
                "-> classified OUTLIER_DEPENDENT",
                "the effect disappears under 1x ASSUMPTION-labeled cost sensitivity",
                "insufficient sample/variance for the hypothesis's own interaction dimension (DTE for P22-OPT-011) "
                "-> classified DATA_INSUFFICIENT rather than reporting a misleading statistic",
            ),
            parent_hypothesis_id=None, development_version=None,
        )
        if hyp_registry.get(hyp_id) is None:
            hyp_registry.register(hypothesis)
        print(f"Registered: {hyp_id} [{theme}] — {name}", flush=True)

        record = PreregistrationRecord(
            hypothesis_id=hyp_id, hypothesis_version="1.0", rationale=statement, expected_direction=direction,
            target_definition=target, features=features, universe_name=universe.name, time_horizon_bars=PRIMARY_HORIZON,
            parameter_ranges={
                "short_vol_window": 5, "long_vol_window": 20, "momentum_short": 5, "momentum_medium": 10,
                "rolling_beta_window": 15, "parkinson_window": 10, "true_range_window": 10, "trend_window": 10,
                "range_expansion_window": 5, "primary_horizon": PRIMARY_HORIZON,
            },
            validation_methodology="see Hypothesis.test_methodology",
            cost_assumptions="1x/2x/3x/5x ASSUMPTION-labeled spread/slippage/commission sensitivity "
                              "(src.options.cost_model) -- never presented as an observed cost",
            success_criteria=("see scripts/phase22_step3_discovery_campaign.py's per-hypothesis classification logic",),
            falsification_criteria=hypothesis.falsification_criteria, registered_at=datetime.now(timezone.utc),
        )
        if prereg_store.get(hyp_id, "1.0") is None:
            prereg_store.register(record)
        # explicit exclusion-rule record, distinct from falsification_criteria (Part 3 requires both be listed)
        print(f"  exclusions: {exclusions}", flush=True)

        # Part 3/4: an immutable experiment fingerprint, computed once at preregistration time (BEFORE any
        # result exists) -- an identical re-run of this script reproduces the identical hex digest.
        dims = ExperimentDimensions(
            feature_definition=str(features), parameter_range={"theme": theme, "horizon": PRIMARY_HORIZON},
            universe_name=universe.name, target_definition=target, execution_model="n/a-discovery-only",
            cost_model="assumption-only-1x-2x-3x-5x", validation_methodology=hypothesis.test_methodology,
        )
        fingerprint = compute_experiment_fingerprint(dims)
        print(f"  experiment fingerprint: {fingerprint}", flush=True)

    print(f"\n{len(HYPOTHESES)} hypotheses registered under family={FAMILY!r}.", flush=True)

    family_record = PreregistrationRecord(
        hypothesis_id="P22-OPT-FAMILY", hypothesis_version="1.0",
        rationale="Shared discovery family manifest for the options_specific_alpha campaign -- the complete "
                  "preregistered 13-hypothesis test matrix, fixed before any Phase 22 analysis ran.",
        expected_direction="unsigned", target_definition="varies per hypothesis (see individual records)",
        features=tuple(sorted({f for _, _, _, feats, _, _, _ in HYPOTHESES.values() for f in feats})),
        universe_name=universe.name, time_horizon_bars=PRIMARY_HORIZON,
        parameter_ranges={"hypothesis_ids": list(HYPOTHESES.keys())},
        validation_methodology="cross-sectional IC / leave-one-out (symbol, expiration, moneyness) / mandatory outlier "
                                "treatment / underlying-control / IC-based placebo battery / temporal-shift / "
                                "dependence-aware bootstrap / multiple-testing (Bonferroni/Holm/BH) / PBO/DSR where "
                                "valid / cost sensitivity / economic significance",
        cost_assumptions="1x/2x/3x/5x ASSUMPTION-labeled sensitivity only -- not applicable at the discovery stage as an observed cost",
        success_criteria=("see scripts/phase22_step3_discovery_campaign.py's per-hypothesis classification logic",),
        falsification_criteria=("a nominal p<0.05 alone is NOT sufficient", "post-hoc observations outside this family are never counted as preregistered"),
        registered_at=datetime.now(timezone.utc),
    )
    if prereg_store.get(family_record.hypothesis_id, family_record.hypothesis_version) is None:
        prereg_store.register(family_record)
    print(f"Preregistered family manifest: {family_record.hypothesis_id} v{family_record.hypothesis_version}", flush=True)
    print("\nSTEP 2 COMPLETE — no discovery analysis has run yet.", flush=True)


if __name__ == "__main__":
    main()
