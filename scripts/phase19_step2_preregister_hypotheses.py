#!/usr/bin/env python3
"""Phase 19, STEP 2 — preregisters the NEW `options_alpha` hypothesis
family (P19-OPT-001..012) BEFORE any discovery analysis runs. Must be
run AFTER scripts/phase19_step1_ingest_real_options_panel.py.

Explicitly NOT a continuation of any prior-phase hypothesis (MR-002,
P7-VOLANOM-A, any P9/P10/P11/P12/P13-*) -- every P19-OPT-* hypothesis has
parent_hypothesis_id=None and lives in its own `family="options_alpha"`.
Covers Part 4's 12 research dimensions (moneyness, DTE/theta-decay,
moneyness x DTE interaction, tail-risk/skew by moneyness, call/put
asymmetry, volatility-driven magnitude, short-horizon reversal, per-
underlying stability, horizon stability, a mechanical-baseline placebo
check, a data-quality negative control, and expiration-proximity decay).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.options.price_history import STANDARD_FORWARD_HORIZONS  # noqa: E402
from src.options.universe import phase19_verified_underlying_universe  # noqa: E402
from src.research import Hypothesis, HypothesisRegistry  # noqa: E402
from src.research.preregistration import PreregistrationRecord, PreregistrationStore  # noqa: E402

PRIMARY_HORIZON = 5  # trading days -- primary forward-return horizon, preregistered before results
PRIMARY_TARGET = "forward_return_5"

# hypothesis_id -> (name, statement, features)
HYPOTHESES = {
    "P19-OPT-001": ("Log-moneyness predicts forward option return", "log_moneyness, ranked cross-sectionally across the 24-contract panel at each timestamp, predicts forward_return_5.", ("log_moneyness",)),
    "P19-OPT-002": ("Days-to-expiration predicts forward option return (theta decay)", "dte, ranked cross-sectionally, predicts forward_return_5 -- shorter DTE expected to correlate with more negative forward returns (accelerating time decay) all else equal.", ("dte",)),
    "P19-OPT-003": ("Moneyness x DTE interaction", "forward_return_5 ~ log_moneyness + dte + log_moneyness*dte (OLS) shows a significant interaction term beyond either main effect.", ("log_moneyness", "dte", "moneyness_x_dte_interaction")),
    "P19-OPT-004": ("Deep-OTM contracts show heavier-tailed forward-return distributions than ITM/ATM", "The DEEP_OTM moneyness bucket's forward_return_5 distribution has materially higher variance/more extreme tails than the ITM/NEAR_ATM buckets.", ("moneyness_bucket",)),
    "P19-OPT-005": ("Calls and puts show asymmetric forward-return means", "Pooled mean forward_return_5 differs materially between call and put contracts, consistent with the underlying's realized drift over the discovery window.", ("call_put",)),
    "P19-OPT-006": ("Underlying realized volatility predicts option forward-return MAGNITUDE", "A lagged realized-volatility feature on the underlying predicts |forward_return_5| (magnitude, not direction) of the option.", ("underlying_lagged_realized_vol",)),
    "P19-OPT-007": ("Large 1-day option moves exhibit short-horizon reversal", "The top quintile of |option daily_return| shows a NEGATIVE sign-consistency with forward_return_5 (reversal).", ("abs_option_daily_return", "option_daily_return")),
    "P19-OPT-008": ("The moneyness-return relationship is stable across underlyings", "P19-OPT-001's log_moneyness IC has the SAME sign in a leave-one-underlying-out analysis for at least 3 of the 4 underlyings (AAPL/NVDA/SPY/TSLA).", ("log_moneyness",)),
    "P19-OPT-009": ("The moneyness-return relationship is stable across forward horizons", "P19-OPT-001's log_moneyness IC has the same sign at horizons 1, 3, 5, 10, and 20 trading days.", ("log_moneyness",)),
    "P19-OPT-010": ("Option forward return carries information beyond the underlying's own forward return", "log_moneyness's IC against forward_return_5 (option) is NOT merely a restatement of the underlying's own forward-return IC -- checked via a mechanical-baseline placebo comparing option IC to underlying-equity IC on the same feature/horizon.", ("log_moneyness", "underlying_forward_return_5")),
    "P19-OPT-011": ("Tick-floor-pinned deep-OTM contracts show near-zero forward-return variance (data-quality negative control)", "Contract-day rows flagged by find_suspicious_flat_price_run (option closes pinned at the $0.01 tick floor for >=10 consecutive bars) show materially LOWER forward_return_5 variance than unflagged rows -- an expected data-mechanics finding, not a claimed alpha source.", ("is_flat_pinned",)),
    "P19-OPT-012": ("Expiration-proximity accelerates the magnitude of decay", "The 0-7 DTE bucket shows the most negative mean forward_return_1 among all DTE buckets (fastest theta bleed immediately before expiration).", ("dte_bucket",)),
}


def main() -> None:
    universe = phase19_verified_underlying_universe()
    hyp_registry = HypothesisRegistry(Path("logs/research_data/hypotheses.jsonl"))
    prereg_store = PreregistrationStore(Path("logs/research_data/phase19_preregistrations.jsonl"))

    print("READ-ONLY confirmation — no prior-phase hypothesis is touched by this family "
          "(family='options_alpha' is entirely new; every P19-OPT-* has parent_hypothesis_id=None).\n", flush=True)
    print(f"UNIVERSE: {universe.name} — {universe.symbols} (real, verified historical-options evidence per member; see src/options/universe.py)", flush=True)
    print(f"DATA: logs/research_data/phase19_research_panel.jsonl — 24 real contracts, 2022-03-18 expiration, "
          f"2021-12-01..2022-03-17 daily bars. Horizons: {STANDARD_FORWARD_HORIZONS}. Primary target: {PRIMARY_TARGET}.\n", flush=True)
    print("LABEL (Part 10, applies to every hypothesis in this family): all research this phase is MARK-TO-MARKET "
          "HISTORICAL RESEARCH (priced off get_option_historicals closes) -- no EXECUTION_REALISTIC_RESEARCH is claimed "
          "or possible, since real historical bid/ask does not exist for this connector.\n", flush=True)

    for hyp_id, (name, statement, features) in HYPOTHESES.items():
        hypothesis = Hypothesis(
            hypothesis_id=hyp_id, name=name, version="1.0", description=statement, economic_intuition=statement,
            mathematical_definition=f"features: {features}; primary target: {PRIMARY_TARGET}; horizons: {STANDARD_FORWARD_HORIZONS}",
            required_data=("real option OHLC bars (get_option_historicals)", "real underlying OHLC bars (HistoricalDataStore)"),
            required_features=features, prediction_horizon_bars=PRIMARY_HORIZON,
            test_methodology="cross-sectional IC (Spearman + Pearson) across the 24-contract panel / quantile analysis / "
                              "OLS interaction / per-underlying leave-one-out / horizon stability / mechanical-baseline "
                              "placebo / multiple-testing correction / bootstrap / PBO / DSR / purged-CV leakage check "
                              "-- MARK-TO-MARKET HISTORICAL RESEARCH only, no backtest, no trading strategy this phase",
            expected_direction="positive" if hyp_id not in ("P19-OPT-002", "P19-OPT-012") else "negative",
            assumptions=(
                "this is a NEW hypothesis family (options_alpha), explicitly NOT a continuation of any prior-phase equity hypothesis",
                "all data is MARK-TO-MARKET HISTORICAL RESEARCH -- no historical bid/ask/volume/OI/IV/Greeks exist for this connector",
                "the panel is small (24 contracts, one expiration cycle, ~74 trading days) -- explicitly NOT a claim of a large, "
                "diversified sample; per-hypothesis classification accounts for this via wide caution in the final report",
                f"underlying universe is {universe.name}: real, verified via a real get_option_instruments probe per member",
                "contract existence before first observation is UNKNOWN_EXISTENCE (Part 16) -- no survivorship-bias-free options "
                "universe is claimed",
            ),
            family="options_alpha", target_definition=PRIMARY_TARGET,
            holding_period_bars=None, entry_rule="N/A — discovery-stage only, no trading strategy this phase", exit_rule="N/A",
            universe=universe.symbols, expected_mechanism="documented per-hypothesis in the statement above",
            falsification_criteria=(
                "IC (Spearman or Pearson) not reliably in the expected direction after multiple-testing correction (BH)",
                "the relationship does not survive the placebo battery (shuffle, time-shuffle, shifted-alignment, mechanical baseline)",
                "the relationship is concentrated in one underlying or is not a real cross-sectional relationship (n<3 at most timestamps)",
                "the result does not replicate across the preregistered forward horizons",
                "the effect disappears under 1x/2x/3x ASSUMPTION-labeled cost sensitivity (net-of-cost)",
            ),
            parent_hypothesis_id=None, development_version=None,
        )
        if hyp_registry.get(hyp_id) is None:
            hyp_registry.register(hypothesis)
        print(f"Registered: {hyp_id} — {name}", flush=True)

        record = PreregistrationRecord(
            hypothesis_id=hyp_id, hypothesis_version="1.0", rationale=statement, expected_direction=hypothesis.expected_direction,
            target_definition=PRIMARY_TARGET, features=features, universe_name=universe.name, time_horizon_bars=PRIMARY_HORIZON,
            parameter_ranges={"horizons": list(STANDARD_FORWARD_HORIZONS), "primary_horizon": PRIMARY_HORIZON},
            validation_methodology="see Hypothesis.test_methodology",
            cost_assumptions="1x/2x/3x ASSUMPTION-labeled spread/slippage/commission sensitivity (src.options.cost_model) -- never presented as an observed cost",
            success_criteria=("see scripts/phase19_step3_discovery_campaign.py's per-hypothesis classification logic",),
            falsification_criteria=hypothesis.falsification_criteria, registered_at=datetime.now(timezone.utc),
        )
        if prereg_store.get(hyp_id, "1.0") is None:
            prereg_store.register(record)

    print(f"\n{len(HYPOTHESES)} hypotheses registered under family='options_alpha'.", flush=True)

    family_record = PreregistrationRecord(
        hypothesis_id="P19-OPT-FAMILY", hypothesis_version="1.0",
        rationale="Shared discovery family manifest for the options_alpha campaign -- the complete preregistered test matrix, fixed before any analysis ran.",
        expected_direction="unsigned", target_definition=PRIMARY_TARGET, features=("log_moneyness", "dte", "call_put"),
        universe_name=universe.name, time_horizon_bars=PRIMARY_HORIZON,
        parameter_ranges={"hypothesis_ids": list(HYPOTHESES.keys()), "horizons": list(STANDARD_FORWARD_HORIZONS)},
        validation_methodology="cross-sectional IC, quantile, OLS interaction, leave-one-out, horizon stability, mechanical-baseline "
                                "placebo, multiple-testing (Bonferroni/Holm/BH), bootstrap, PBO, DSR, purged-CV leakage check",
        cost_assumptions="1x/2x/3x ASSUMPTION-labeled sensitivity only -- not applicable at the discovery stage as an observed cost",
        success_criteria=("see scripts/phase19_step3_discovery_campaign.py's per-hypothesis classification logic",),
        falsification_criteria=("a nominal p<0.05 alone is NOT sufficient",), registered_at=datetime.now(timezone.utc),
    )
    if prereg_store.get(family_record.hypothesis_id, family_record.hypothesis_version) is None:
        prereg_store.register(family_record)
    print(f"Preregistered family manifest: {family_record.hypothesis_id} v{family_record.hypothesis_version}", flush=True)
    print("\nSTEP 2 COMPLETE — no discovery analysis has run yet.", flush=True)


if __name__ == "__main__":
    main()
