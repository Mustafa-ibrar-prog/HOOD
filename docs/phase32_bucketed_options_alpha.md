# Phase 32 — Bucketed Options Alpha Discovery

## 1. Executive summary

Phase 32 tested whether aggregating individual option contracts into economically meaningful buckets (underlying × call/put × DTE bucket × moneyness bucket × date) solves the contract-level sparsity problem that produced Phase 31's clean null. **The answer is mixed and honest: bucketing genuinely improved SOME density problems but not others, and the overall result remains a null** — zero hypotheses are statistically significant after correction, zero survive underlying controls, zero pass the 12-criterion Promising Finding Gate. No alpha survived. No alpha is independent of the underlying (none could even be confirmed as adding information — the underlying-control comparison itself came back undefined for every hypothesis). No alpha is statistically significant after correction. No alpha is economically tradeable. No candidate passes the Promising Finding Gate.

## 2. Research question

Determine whether real historical options data contains statistically defensible predictive relationships when individual contracts are aggregated into economically meaningful buckets, without introducing survivorship, lookahead, or cross-contract leakage.

## 3. Exact preregistration

- **14 hypotheses**, family `bucketed_options_alpha` (`src/options/phase32_hypotheses.py`), registered via `HypothesisRegistry`/`PreregistrationStore` BEFORE any bucket evaluation (`logs/research_data/phase32_hypotheses.jsonl` / `phase32_preregistration.jsonl`), enforced structurally via `require_preregistered()`.
- **Two bucket schemes** preregistered before density was measured: FINE (`src.options.expiration.DTEBucket` × `src.options.moneyness.MoneynessBucket`, the project's existing 5×5 taxonomy) and COARSE (a 3×3 fallback merge). `select_scheme_by_density` picks between them using fixed, pre-set thresholds (≥3 median observations/date, ≥10 dates, ≥5 usable cells).
- **Minimum sample requirements**, fixed before any result was seen (`MinimumSampleRequirements`): bucket existence ≥3 contracts, bucket-series ≥10 dates, per-symbol evaluation ≥15 bucket-date rows, pooled evaluation ≥30 rows, cross-sectional peer group ≥3 buckets.

## 4. Dataset coverage

Same real free dataset as Phase 30/31 (`FREE_REFERENCE_DATASET`, Phase 26/27's QuantConnect/Lean sample). Built the identical real contract-day panel Phase 31 used: **13,800 real contract-day rows**, 6,082 real contracts, across AAPL, FOXA, GOOG, NWSA, TWX (SPY excluded — real coverage is minute-only, zero daily rows, as established in Phase 30/31).

## 5. Density before vs after bucketing

| | Before (Phase 31, contract-level) | After (Phase 32, bucket-level) |
|---|---|---|
| Analysis unit rows | 13,800 (1 per contract-day) | **858** (1 per bucket-day) |
| Real economically-scoped peer groups (≥3 members, valid feature+target) | ~0 for every tested feature/target pair | Cross-sectional: still ~0 (see §9) |
| Pooled time-series usable observations | N/A (not attempted at contract level) | **215** for the primary hypothesis (P32-BKT-001) |
| Underlyings with ANY usable per-symbol evidence | 0 | **1 (AAPL only)** |

Underlying/date density audit (`phase32_density_audit.py`): 274 real (underlying, date) cells, **0 duplicate observations**, **0 impossible prices** (zero/negative or crossed quotes) in the selected contract subsample. FINE scheme reached 180 total bucket cells (17 meeting the density threshold); COARSE reached 72 cells (13 meeting threshold) — **FINE was selected** (more usable cells at the finer resolution, contrary to the a priori expectation that coarsening would be necessary).

## 6. Bucket definitions

FINE scheme selected: DTE buckets `0-7/8-30/31-60/61-120/120+` (unchanged from `DTEBucket`), moneyness buckets `deep_itm/itm/near_atm/otm/deep_otm` (unchanged from `MoneynessBucket`). No exclusions were needed at the top level (FINE beat its ≥5-usable-cell bar); 163 of 180 FINE cells did NOT meet the ≥3-obs/≥10-date threshold and were excluded from bucket-series time-series testing (still included in bucket-day cross-sectional grouping, since that threshold is separate).

## 7. Feature definitions

20 causal bucket features across all 5 required families (`phase32_bucket_panel.py`):
- **A (cross-sectional option behavior)**: `bucket_median_return`, `bucket_mean_return`, `bucket_return_dispersion`, `bucket_positive_return_fraction`, `bucket_extreme_return_fraction`, `bucket_cross_sectional_range`.
- **B (call/put)**: `call_put_return_spread`, `call_put_positive_fraction_spread`, `call_put_dispersion_diff`.
- **C (moneyness)**: `atm_otm_spread`, `itm_atm_spread`, `otm_atm_spread`, `moneyness_slope`.
- **D (maturity)**: `short_medium_dte_spread`, `medium_long_dte_spread`, `dte_slope`.
- **E (option-vs-underlying)**: `option_minus_underlying_return`, `option_magnitude_minus_underlying_magnitude`, `dispersion_minus_underlying_vol`. No delta-scaled feature exists anywhere in the codebase (this dataset has no native delta) — verified by `test_no_delta_scaled_feature_is_ever_fabricated`.

## 8. Target definitions

Directional: `forward_bucket_return_{h}` (compounded product of the bucket's own median daily returns over the next h real bucket-dates), `forward_bucket_return_underlying_adjusted_{h}`. Non-directional: `forward_abs_bucket_return_{h}`, `forward_bucket_mfe_{h}`, `forward_bucket_mae_{h}`, `forward_dispersion_{h}`, `forward_range_expansion_ratio_{h}`. h ∈ {1,3,5,10,20}. No target is ever described as directional trading edge when it is a magnitude/volatility quantity (enforced by keeping the two families in distinctly-prefixed columns and separate hypothesis definitions).

## 9. Causal methodology

Bucket membership at date t depends ONLY on that day's real contract-day rows (themselves already causal, from Phase 31/30). **No-survivorship-leakage was directly tested, not assumed**: `test_no_survivorship_leakage_bucket_membership_independent_of_future` confirms a bucket-day's stats are byte-identical whether or not a later date's data exists at all. Forward targets walk each bucket-SERIES' own real date sequence, never fabricating a missing future observation.

## 10. Underlying controls

Ran for every hypothesis with `forward_underlying_return_h` available (`phase31_underlying_control.underlying_control_comparison`, reused unmodified). **Every single hypothesis classified `BOTH_WEAK_OR_UNDEFINED`** — the ΔR² (Model B − Model A OLS) was computable and small (e.g. P32-BKT-001: ΔR²≈0.0004) but the IC-gap half of the classifier came back undefined for the same cross-sectional-density reason as everywhere else in this report. **No hypothesis could be confirmed as adding information beyond the underlying, and none could be confirmed as purely inherited either — the honest answer is "untested," not "passed."**

## 11. Statistical methodology

Pooled time-series (`analyze_feature`), cross-sectional (`evaluate_cross_sectional_evidence`, same-date peer groups across ALL underlyings/buckets), per-symbol, and symbol-balanced pooled relationships (Part 8 A-D) — all real, run for all 14 hypotheses.

## 12. Multiple-testing results

Bonferroni: 0/14. Holm: 0/14. Benjamini-Hochberg: 0/14. **Important caveat, disclosed not hidden**: this campaign's formal multiple-testing correction is anchored to each hypothesis's CROSS-SECTIONAL IC p-value (the same convention Phase 31 established) — since cross-sectional IC was undefined for every hypothesis (§9), every p-value defaulted to 1.0, so the correction never had a real p-value to work with. The POOLED time-series relationship (§5, e.g. P32-BKT-001's real spearman=-0.138 on 215 observations) exists OUTSIDE this formal significance pathway and was never claimed as "significant" — a genuine methodological gap worth closing in a future phase (extend the correction to also cover pooled/per-symbol p-values), not evidence of a hidden discovery.

## 13. Robustness results

Year/underlying/DTE-bucket/moneyness-bucket/call-put stratification and leave-one-underlying-out (reused `phase31_robustness.evaluate_robustness` unmodified) ran for all 14; `fragile=False` by default when every stratum's own IC is undefined (untestable, not "robust" — the same honest caveat as Phase 31). Leave-one-period-out (`phase32_bucket_robustness.leave_one_period_out`, new) ran using 4 chronological chunks. Equal-weight vs observation-weighted aggregation comparison (`compare_equal_vs_observation_weighting`) showed **no material disagreement** for the tested hypotheses — but this is because only ONE underlying (AAPL) ever had enough data to be "equal-weighted" against in the first place (n_symbols_eligible=1 throughout), not because multiple underlyings genuinely agreed.

## 14. Placebo results

Full battery ran (shuffled feature, shifted feature, shuffled target, random-bucket-assignment via `symbol_identity_shuffle_placebo`, underlying-only control, leave-one-symbol-out, leave-one-period-out, top-outlier removal, equal-vs-observation-weighted) for all 14 hypotheses. With no real cross-sectional statistic to separate from chance, `placebo_separates()` correctly returned `False` everywhere.

## 15. Economic significance

No hypothesis reached the cross-sectional significance tier required to even ask "is this tradeable" in the sense of a confirmed directional edge; the pooled time-series relationships that DID compute (e.g. P32-BKT-001) were explicitly labeled with `analyze_feature`'s own significance caveat ("overlapping multi-bar future returns are autocorrelated... NOT a valid i.i.d. significance test").

## 16. $1,000 affordability

From the real contract-day panel (Part 13's extended report): **median premium ≈ $1,360/contract**, 25th percentile ≈ $95, 75th percentile ≈ $6,040, **46.0% of real observed contracts affordable within $1,000** — essentially unchanged from Phase 31 (same real dataset, same real premiums; bucketing doesn't change what a single contract costs). Every hypothesis's tradeability was classified `NOT_APPLICABLE_NO_STATISTICAL_SIGNAL` (Part 14's separate tradeability dimension — never gating statistical validity, per Part 8's explicit instruction) since none reached `DISCOVERY_SUPPORTED`/`PROMISING`.

## 17. Phase 31 comparison (Part 15's 9 questions, answered from this campaign's real results)

1. **Did bucket aggregation solve the contract-density problem?** Partially. Q1=True in the narrow sense that usable bucket cells exist and the pooled/per-symbol pathway became computable; but cross-sectional (same-date, ≥3-peer) density remains essentially unsolved.
2. **Did effective sample size materially increase?** Yes for pooled/time-series (0 → 215 usable observations for the primary hypothesis); the raw unit count actually SHRANK (13,800 → 858 rows) by design (aggregation), which is expected and correct.
3. **Did any Phase 31 null become statistically testable?** Yes — pooled time-series and per-symbol relationships, which were entirely uncomputable in Phase 31, produced real numbers here.
4. **Did any relationship survive underlying controls?** No — every hypothesis's underlying-control classification was `BOTH_WEAK_OR_UNDEFINED` (untested, not passed).
5. **Did any relationship survive multiple-testing correction?** No — 0/14 under all three methods.
6. **Did any relationship survive placebo tests?** No — no real cross-sectional statistic existed to separate from the placebo distributions.
7. **Did any relationship survive symbol/period robustness?** Nominally yes (`fragile=False`), but only because a single underlying (AAPL) dominated every testable pathway — not genuine multi-symbol robustness.
8. **Did any relationship become affordable for a $1,000 account?** No new conclusion — affordability is unchanged from Phase 31 (same real premiums), and no hypothesis reached the statistical tier where tradeability is even evaluated.
9. **Did any candidate pass the Promising Finding Gate?** No — 0/14, same as Phase 31's 0/16.

**Phase 32 is still a null result. This is an acceptable and valuable result**, per Part 15's explicit instruction — and a more informative null than Phase 31's, since it now separates "the pooled/per-symbol density problem" (meaningfully improved) from "the cross-sectional same-day peer-density problem" (essentially unchanged) and "the single-underlying-dominance problem" (persists at the bucket level too).

## 18. Candidate findings

**None cleared the bar to be called a candidate.** The closest observation worth flagging for future investigation (NOT a finding, NOT advanced): P32-BKT-001 (Bucket Momentum) showed a real, non-trivial pooled Spearman correlation of −0.138 (n=215, AAPL only) between `bucket_median_return` and `forward_bucket_return_5` — opposite in sign from the preregistered positive-momentum direction, suggestive of short-horizon mean reversion rather than momentum at the bucket level — but this is explicitly a single-underlying, non-cross-sectionally-confirmed, uncorrected-for-multiple-testing observation and must not be treated as a discovery.

## 19. Final classifications

**5 INCONCLUSIVE** (P32-BKT-001, 002, 004, 012, 014) and **9 NOT_READY** (P32-BKT-003, 005, 006, 007, 008, 009, 010, 011, 013). **0 DISCOVERY_SUPPORTED, 0 PROMISING, 0 FRAGILE, 0 REJECTED, 0 INHERITED_FROM_UNDERLYING.** Every tradeability tag: `NOT_APPLICABLE_NO_STATISTICAL_SIGNAL`.

## 20. Limitations

All Phase 30 `FREE_DATASET_LIMITATIONS` and Phase 31's per-contract density finding apply unchanged, plus:
- **Cross-sectional same-day peer density remains the binding constraint**, even after bucketing — very few real dates have ≥3 economically-comparable buckets simultaneously carrying both a valid feature and a valid forward target.
- **Single-underlying dominance persists at the bucket level**: only AAPL ever reached the per-symbol minimum-observation bar; FOXA/GOOG/NWSA contributed to bucket-day construction but never to per-symbol/robustness evidence.
- **The formal multiple-testing correction only covers the cross-sectional pathway** (§12) — a real methodological gap, not a hidden result.
- SPY contributes zero bucket rows (no real daily options coverage, established since Phase 30).

## 21. Recommendation for Phase 33

1. **Extend the multiple-testing correction to cover pooled/per-symbol p-values**, not only cross-sectional IC — the current pipeline structurally cannot credit a real pooled relationship (§12's gap) even if one existed.
2. **If a genuine cross-sectional test is still wanted**, the unit of comparison likely needs to widen further than "same exact date" — e.g. a short rolling window (3-5 real trading days) of same-bucket observations pooled together as one cross-sectional snapshot, trading temporal precision for peer density. This is a genuinely new design choice for a future phase, not a re-run of Phase 32 with looser thresholds.
3. **Do not purchase ORATS or any paid provider** — the binding constraints (same-day peer density, single-underlying dominance) are about how this specific free archive's real observations are distributed across dates and underlyings, not about total data volume, and are not solved by paying for more of the same kind of data without first confirming a denser provider would look different.
4. **A null result across two full campaigns (Phase 31 individual-contract, Phase 32 bucketed) is itself a legitimate, reportable research conclusion** about this free dataset's limits — a future phase could reasonably pivot to a different question entirely (e.g. revisiting Phase 22/23's `P22-OPT-013` mechanism on the legacy MCP panel, which has denser real per-contract history than the free archive) rather than a third variation on this same dataset.

---

*No live order was placed. No paper order was placed. No trading strategy was created. No paid data was purchased. No missing observation was imputed or interpolated (`IMPUTATION_USED = False`, asserted by `tests/test_phase32_safety.py`). `SystemState` and OPTIONS_ONLY remain exactly as Phase 28 left them.*
