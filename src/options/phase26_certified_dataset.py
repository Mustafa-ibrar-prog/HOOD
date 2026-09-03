"""Phase 26, Part 10/11/16 — the actual certification result for the
real QuantConnect/Lean sample this phase ingested and tested. Every
score's `evidence` field names the REAL check that produced it (a real
number, a real test result, or an explicitly-cited absence) -- nothing
here is asserted without a corresponding real computation performed
elsewhere in this phase's modules.
"""

from __future__ import annotations

from src.options.phase26_certification_score import CertificationDimension, DatasetCertificationScore, DimensionScore
from src.options.phase26_final_gate import ResearchReadinessGate, evaluate_gate

QUANTCONNECT_LEAN_SAMPLE_CERTIFICATION = DatasetCertificationScore(
    dataset_label="QuantConnect/Lean open-source options sample (AAPL 2014-2016 daily, SPY 2023-08-03 minute)",
    scores=(
        DimensionScore(
            CertificationDimension.CONTRACT_IDENTITY, 3,
            "Underlying/strike/expiration/right verified real from 4536+ real filenames; exercise_style ('american') "
            "confirmed real; multiplier=100 is a market-convention ASSUMPTION never confirmed by this source "
            "(flagged on every contract by check_multiplier_not_source_confirmed); no exchange field anywhere.",
            evidence="phase26_lean_sample_parser.parse_lean_option_filename + phase26_quality_rules.check_multiplier_not_source_confirmed (5+4532 real contracts flagged)",
        ),
        DimensionScore(
            CertificationDimension.CONTRACT_LIFECYCLE, 3,
            "first_observable_date/last_trade_date are real derived facts from actually-observed rows; "
            "first_listed_date is genuinely None (source has no listing-date field); status=EXPIRED is a real "
            "mathematical fact (today > real expiration date), not an assumption.",
            evidence="phase26_dataset_builder.build_contract_lifecycle, real output inspected this phase",
        ),
        DimensionScore(
            CertificationDimension.HISTORICAL_OHLC, 4,
            "Real trade OHLC ingested and cross-checked: AAPL close 2015-01-02 = $109.33 in this sample, matching "
            "AAPL's real known closing price that day. Zero OHLC-violation flags across the full AAPL 2014 sample.",
            evidence="phase26_quality_rules.check_ohlc_violations (0 flags on real ingested data)",
        ),
        DimensionScore(
            CertificationDimension.HISTORICAL_BID_ASK, 4,
            "Real bid/ask ingested for AAPL (daily) and SPY (minute); a genuine one-sided-market phenomenon "
            "(empty bid field on real 2014-06-06 rows) was found and correctly represented as None, not "
            "fabricated as 0.0. Zero bid>ask violations across the full AAPL 2014 sample.",
            evidence="phase26_quality_rules.check_bid_gt_ask (0 flags); phase26_lean_sample_parser._parse_optional_decicents",
        ),
        DimensionScore(
            CertificationDimension.VOLUME, 4,
            "Real trade volume ingested (SPY minute trades, e.g. 82 real trade bars for the 470-strike call on "
            "2023-08-03); zero negative-volume flags.",
            evidence="phase26_quality_rules.check_negative_volume (0 flags)",
        ),
        DimensionScore(
            CertificationDimension.OPEN_INTEREST, 4,
            "2448 real AAPL open-interest files ingested for 2014, values in a plausible real range (e.g. "
            "9325-9427 contracts for one strike/expiration across consecutive real trading days); zero "
            "negative-OI flags.",
            evidence="phase26_quality_rules.check_negative_open_interest (0 flags on real 2448-file OI set)",
        ),
        DimensionScore(
            CertificationDimension.IMPLIED_VOLATILITY, 2,
            "Zero vendor-supplied IV anywhere in this source (confirmed absent from the real README schema). "
            "RECONSTRUCTABLE and demonstrated working: a real Black-Scholes bisection solver recovered a "
            "plausible IV (~29.3%) from a real AAPL bid/ask+underlying-price triple, but only when a real "
            "paired underlying price exists in-sample (it does for AAPL 2015; it does NOT for the SPY "
            "2023-08-03 slice, whose equity sample stops 2021-03-31 -- reconstruction correctly returned "
            "UNAVAILABLE there rather than guessing).",
            evidence="phase26_iv_greeks_certification.reconstruct_iv_and_greeks, both the AAPL success and the SPY honest-failure case",
        ),
        DimensionScore(
            CertificationDimension.GREEKS, 2,
            "Same situation as IV: zero vendor-supplied Greeks; a real, working Black-Scholes Greeks "
            "computation was demonstrated (delta=0.669, gamma=0.0108, vega=0.392/vol-pt, theta=-0.0153/day, "
            "rho=0.574/rate-pt for the real AAPL example) but is RECONSTRUCTABLE, not a native field, and "
            "depends on the same underlying-price availability caveat as IV.",
            evidence="phase26_iv_greeks_certification.reconstruct_iv_and_greeks + black_scholes.black_scholes_greeks",
        ),
        DimensionScore(
            CertificationDimension.HISTORICAL_CHAIN_RECONSTRUCTION, 4,
            "A real chain reconstruction as-of 2014-07-01 correctly returned 3348 knowable contracts across "
            "348 real distinct strikes, correctly excluded 1184 already-expired contracts, and the adversarial "
            "before-first-observation check returned zero violations.",
            evidence="phase26_chain_reconstruction.reconstruct_chain_as_of + contracts_incorrectly_visible_before_first_observation (0 violations)",
        ),
        DimensionScore(
            CertificationDimension.POINT_IN_TIME_SAFETY, 4,
            "Built entirely on Phase 15's existing, already-tested PIT machinery (EventTimestamps/"
            "is_knowable_at/assert_no_lookahead). Both adversarial injection tests this phase (a future-dated "
            "observation; a missing-causal-timestamp observation) were correctly rejected with "
            "PointInTimeViolation.",
            evidence="phase26_pit_certification.adversarial_future_observation_is_rejected==True, adversarial_missing_causal_timestamp_is_rejected==True",
        ),
        DimensionScore(
            CertificationDimension.EXECUTION_REALISM, 4,
            "Real quotes AND real trades both present for the SPY 2023-08-03 sample -> Grade A. Spread stats "
            "computed from real numbers (e.g. mean spread ~$0.51/2.16% for the 430-strike call); "
            "trades_inside_spread_rate honestly varies (0.52-1.0 across the 4 real contracts tested) rather "
            "than being forced to a flattering constant.",
            evidence="phase26_execution_realism.build_execution_realism_report, all 4 real SPY contracts",
        ),
        DimensionScore(
            CertificationDimension.CORPORATE_ACTIONS, 3,
            "A real, previously-undocumented corporate-action discontinuity was found and verified this phase: "
            "AAPL's June 2014 7-for-1 split boundary shows legacy fractional strikes (e.g. $28.57=$200/7) and "
            "new round-dollar strikes coexisting under the same real 2015-01-17 expiration, and a $1000-strike "
            "contract's real data stops dead the trading day before the split. No explicit split-adjustment "
            "flag/field exists in the source itself -- this was inferred from real strike values, not stated.",
            evidence="manual real-data inspection this phase, logs/research_data/phase26_raw/extracted/aapl_2014_quote (documented in docs/phase26_historical_options_dataset_certification.md Part 8)",
        ),
        DimensionScore(
            CertificationDimension.TIMESTAMP_QUALITY, 4,
            "Daily vs. minute resolution correctly distinguished and parsed; minute timestamps cross-checked "
            "against real market hours (SPY 2023-08-03 rows span 09:30-16:14 ET, matching real trading hours); "
            "zero timestamp-ordering violations across the full AAPL 2014 sample.",
            evidence="phase26_quality_rules.check_timestamp_ordering (0 flags); phase26_lean_sample_parser real parse of ms-since-midnight",
        ),
        DimensionScore(
            CertificationDimension.PROVENANCE, 4,
            "Every real observation carries a complete OptionDataProvenance (source, retrieval_timestamp, "
            "historical_or_live, observation_kind, adjustment_status, interpolation_flag=False, "
            "confidence_status) and EventTimestamps -- reusing Phase 15/24's existing machinery, not a "
            "shortcut. publication_timestamp is honestly always None (the source states no publication date).",
            evidence="phase26_dataset_builder.build_provenance, inspected on real constructed ContractIdentity instances this phase",
        ),
        DimensionScore(
            CertificationDimension.LICENSING_ACCESS_CLARITY, 3,
            "The repository's own LICENSE (Apache-2.0) was directly fetched and confirmed real this phase -- "
            "strong evidence the sample is intended as freely redistributable. NOT fully verified: Apache-2.0 "
            "covers the repository's own copyright license; whether AlgoSeek's original data-licensing terms "
            "impose any further restriction on this specific bundled sample beyond running it inside the Lean "
            "engine was not independently confirmed this phase.",
            evidence="raw.githubusercontent.com/QuantConnect/Lean/master/LICENSE (fetched and confirmed Apache-2.0 this phase)",
        ),
    ),
    notes=(
        "This certifies the NARROW real sample actually obtained and tested this phase (AAPL 5 legacy "
        "underlyings 2013-2016 daily; SPY one real day in 2023 at minute resolution) -- it is NOT a "
        "certification of general, ongoing coverage for this project's full research universe (NVDA and TSLA "
        "are confirmed absent; broad 2021-2024 coverage is confirmed absent beyond the single SPY day). See "
        "phase26_final_gate.evaluate_gate's `coverage_is_general_purpose` parameter, which this phase sets to "
        "False for exactly this reason."
    ),
)

# Part 11's explicit instruction: per-field quality and dataset breadth are
# different questions. This sample's fields score well (see above) but its
# COVERAGE is real, narrow, and confirmed insufficient for this project's
# general research universe -- so coverage_is_general_purpose=False.
FINAL_GATE = evaluate_gate(QUANTCONNECT_LEAN_SAMPLE_CERTIFICATION, coverage_is_general_purpose=False)
