"""Phase 27, Part 6/10/14 — the certification result for the EXPANDED
real dataset (Phase 26's AAPL+SPY sample plus Phase 27's real
FOXA/GOOG/NWSA/TWX daily data and real multi-day GOOG/AAPL/FOXA/NWSA/TWX
minute data). Reuses Phase 26's `CertificationDimension`/
`DatasetCertificationScore`/`ResearchReadinessGate`/`evaluate_gate`
directly -- Part 1's "do not rewrite working components unnecessarily"
and Part 6's "do not weaken the standard" both argue against a parallel
scoring vocabulary.

Real numbers this score is built from (full derivation in
docs/phase27_historical_options_dataset_expansion.md):
  - 7,358 total real contracts across 6 real underlyings (AAPL, FOXA,
    GOOG, NWSA, SPY, TWX) -- up from Phase 26's ~4,536.
  - 0 merge conflicts (single real provider; the merge/conflict
    machinery is real and tested, but had nothing to actually disagree
    on this phase).
  - 5 real bid>ask critical flags, cross-validated two independent ways
    (this codebase's own check AND a direct awk scan of the raw CSVs) --
    every one is a tiny (1-2 cent), deep-OTM/near-worthless AAPL contract
    on 2014-06-06/06-09 (the exact split boundary), consistent with a
    genuine, real, brief market-microstructure crossed-quote event, not
    a data integrity defect.
  - 13 real AAPL split-boundary corporate-action flags, all correctly
    reporting no unambiguous successor (never asserting an unconfirmed
    merge).
  - A real ordering bug (see phase27_merge.py's docstring) found and
    fixed this phase, reconfirmed at 0 violations against the real
    combined data.
"""

from __future__ import annotations

from src.options.phase26_certification_score import CertificationDimension, DatasetCertificationScore, DimensionScore
from src.options.phase26_final_gate import ResearchReadinessGate, evaluate_gate

EXPANDED_DATASET_CERTIFICATION = DatasetCertificationScore(
    dataset_label="Phase 26+27 combined QuantConnect/Lean real sample (AAPL, FOXA, GOOG, NWSA, SPY, TWX)",
    scores=(
        DimensionScore(
            CertificationDimension.CONTRACT_IDENTITY, 3,
            "Unchanged real gaps from Phase 26 (multiplier unconfirmed, no exchange field); this phase's merge "
            "layer additionally VALIDATES identity consistency across combined sources (raises on a real "
            "mismatch) -- a real, tested new safeguard, not yet exercised by an actual mismatch this phase.",
            evidence="phase27_ingest.build_expanded_store_from_directories's _register identity-consistency check; 0 mismatches found across 7,358 real contracts",
        ),
        DimensionScore(
            CertificationDimension.CONTRACT_LIFECYCLE, 3,
            "Unchanged: first_listed_date remains genuinely None (no listing-date field in this source); "
            "first_observable_date/last_trade_date remain real derived facts, now computed correctly across "
            "merged multi-resolution sources for the same contract.",
            evidence="phase26_dataset_builder.build_contract_lifecycle, applied to the merged real dataset",
        ),
        DimensionScore(
            CertificationDimension.HISTORICAL_OHLC, 4,
            "Real OHLC now cross-checked across 6 real underlyings (previously 2); zero OHLC-violation flags "
            "across the full expanded 7,358-contract real set.",
            evidence="phase26_quality_rules.check_ohlc_violations, 0 flags on the expanded real dataset",
        ),
        DimensionScore(
            CertificationDimension.HISTORICAL_BID_ASK, 4,
            "5 real bid>ask flags found across the full expanded set -- cross-validated independently via a "
            "direct awk scan of the raw CSVs (identical 5 rows found both ways). Every one is a 1-2 cent "
            "crossed quote on a deep-OTM/near-worthless AAPL contract on the exact 2014 split-boundary dates -- "
            "a genuine, tiny, real market-microstructure event (brief crossed markets are a documented real "
            "phenomenon in illiquid options, especially around corporate-action-driven volatility), not a "
            "data-integrity defect. Score held at 4/5 (unchanged from Phase 26) -- this finding is honest "
            "evidence of realism, not grounds for either an upgrade or a downgrade.",
            evidence="phase26_quality_rules.check_bid_gt_ask (5 flags) + independent awk cross-validation this phase, both identifying the exact same 5 real rows",
        ),
        DimensionScore(
            CertificationDimension.VOLUME, 4,
            "Unchanged real evidence tier, now spanning 6 real underlyings.",
            evidence="phase26_quality_rules.check_negative_volume, 0 flags on the expanded real dataset",
        ),
        DimensionScore(
            CertificationDimension.OPEN_INTEREST, 4,
            "Unchanged real evidence tier; real OI now also present for GOOG and TWX (previously only AAPL).",
            evidence="phase26_quality_rules.check_negative_open_interest, 0 flags on the expanded real dataset",
        ),
        DimensionScore(
            CertificationDimension.IMPLIED_VOLATILITY, 2,
            "Unchanged: zero native IV anywhere in this source, for any of the 6 real underlyings. "
            "RECONSTRUCTABLE (Phase 26's Black-Scholes solver) remains the only path, and remains dependent on "
            "a real paired underlying price existing in-sample.",
            evidence="Same real absence confirmed across the expanded README/schema; no new evidence changes this",
        ),
        DimensionScore(
            CertificationDimension.GREEKS, 2,
            "Same situation as IV -- unchanged.",
            evidence="Same real absence confirmed across the expanded dataset",
        ),
        DimensionScore(
            CertificationDimension.HISTORICAL_CHAIN_RECONSTRUCTION, 4,
            "Real, NEW evidence this phase: a genuine multi-day (3 consecutive real trading days, "
            "2015-12-23/24/28) GOOG minute-resolution chain reconstruction was demonstrated growing correctly "
            "day-over-day (more contracts knowable on day 3 than day 1) -- a stronger real PIT-chain test than "
            "Phase 26's single-date AAPL test. Score held at 4/5 (still a static flat-file bundle, no "
            "independent listing feed).",
            evidence="tests/test_phase27_real_data_integration.py::test_real_goog_chain_grows_across_the_three_real_consecutive_trading_days, real data, passing",
        ),
        DimensionScore(
            CertificationDimension.POINT_IN_TIME_SAFETY, 4,
            "Reconfirmed on the expanded real dataset (both adversarial injection tests still correctly "
            "rejected); the real ordering bug found this phase (see TIMESTAMP_QUALITY) was a MERGE-layer issue, "
            "never a PIT-safety issue -- Phase 15's causal-timestamp machinery itself was never wrong.",
            evidence="phase26_pit_certification adversarial tests, reconfirmed against the expanded real store",
        ),
        DimensionScore(
            CertificationDimension.EXECUTION_REALISM, 4,
            "Unchanged real evidence tier (Grade A for the SPY sample); real minute-resolution quotes now also "
            "exist for AAPL/GOOG/FOXA/NWSA/TWX around their respective real dates, broadening (not yet fully "
            "re-graded per-contract) the real execution-realism evidence base.",
            evidence="phase26_execution_realism.build_execution_realism_report, reusable unchanged against any of the 6 real underlyings",
        ),
        DimensionScore(
            CertificationDimension.CORPORATE_ACTIONS, 4,
            "Real improvement this phase: Phase 26 only OBSERVED the AAPL split discontinuity; Phase 27 built "
            "a structural DETECTOR (find_split_boundary_discontinuities), confirmed the real root cause "
            "(SOURCE_LIMITATION + MISSING_ADJUSTMENT_METADATA, not a codebase bug), and adversarially verified "
            "it never asserts an unconfirmed legacy/successor merge (6 real+synthetic tests, all passing).",
            evidence="phase27_corporate_actions.py + tests/test_phase27_corporate_actions.py (6 tests) + real 13-flag result on the actual AAPL 2014 data",
        ),
        DimensionScore(
            CertificationDimension.TIMESTAMP_QUALITY, 4,
            "A real ordering bug was found this phase (combining real daily+minute data for the same contract "
            "without a deterministic merge step produced 118 real out-of-order flags) and FIXED via a proper "
            "merge layer -- reconfirmed at 0 violations against the full real expanded dataset afterward. This "
            "is a genuine robustness improvement (the underlying data's own timestamp quality was always real; "
            "what improved is this codebase's guarantee under multi-source combination).",
            evidence="phase27_merge.py's module docstring documents the exact real bug and fix; phase26_quality_rules.check_timestamp_ordering reconfirms 0 flags post-fix",
        ),
        DimensionScore(
            CertificationDimension.PROVENANCE, 4,
            "Unchanged -- every real observation across all 6 underlyings still carries a complete "
            "OptionDataProvenance/EventTimestamps pair.",
            evidence="phase26_dataset_builder.build_provenance, applied unchanged to the expanded real dataset",
        ),
        DimensionScore(
            CertificationDimension.LICENSING_ACCESS_CLARITY, 3,
            "Unchanged: the same real Apache-2.0 LICENSE covers every file fetched this phase (all from the "
            "same repository); the same caveat about AlgoSeek's original data terms not being independently "
            "confirmed still applies.",
            evidence="Same real LICENSE file, unchanged this phase",
        ),
    ),
    notes=(
        "This certifies the EXPANDED real sample (7,358 contracts, 6 real underlyings: AAPL, FOXA, GOOG, NWSA, "
        "SPY, TWX). Total: 53/75 (up from Phase 26's 52/75 -- a real, modest, evidence-backed improvement, "
        "mostly from CORPORATE_ACTIONS rigor, not from any weakening of the standard). Per Part 14's explicit "
        "instruction ('do not upgrade merely because the aggregate score is high'), the final gate below is "
        "NOT upgraded on this score alone -- coverage breadth against the project's actual target underlying "
        "list remains the binding constraint, exactly as in Phase 26."
    ),
)

# Part 14: coverage_is_general_purpose stays False -- of the 12 target underlyings
# (Part 2's list), only AAPL and SPY have ANY real data, and even AAPL's real data
# entirely predates the required 2019-2026 window (Part 12); SPY has exactly one
# real day (2023-08-03) in that window. NVDA/TSLA/QQQ/MSFT/AMD/AMZN/META/GOOGL/NFLX/
# IWM remain completely absent. This is a REAL, confirmed, unimproved finding, not
# an assumption carried over from Phase 26.
EXPANDED_FINAL_GATE = evaluate_gate(EXPANDED_DATASET_CERTIFICATION, coverage_is_general_purpose=False)
