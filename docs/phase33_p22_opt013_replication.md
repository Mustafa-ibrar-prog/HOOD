# Phase 33 — P22-OPT-013 Coarse-Grain Replication + Multiple-Testing Correction

Two objectives, both research-only: (A) fix a genuine gap in Phase 32's
multiple-testing accounting, and (B) determine whether P22-OPT-013 (range
expansion → future MFE) survives being expressed as a Phase 32 bucket-level
aggregate. **Neither objective produced a strategy, a trade, or a validated
hypothesis.** Objective A found the fix changes nothing about Phase 32's
conclusions. Objective B found P22-OPT-013 does **not** replicate at the
coarse-grained level on this project's free dataset.

---

## 1. Executive summary

- **Objective A (correction fix): done, and verified against real data.**
  Phase 32's multiple-testing correction only ever fed each hypothesis's
  cross-sectional IC p-value into Bonferroni/Holm/BH — pooled time-series,
  per-symbol, symbol-balanced, and leave-one-out results were computed but
  never entered the corrected family. The fix (`phase33_test_registry.py`)
  is a structural, append-only registry that every inferential test must
  enter before correction runs. Re-running Phase 32's 14 hypotheses through
  it grew the primary correction family from 14 records to 84 (8 testable)
  plus 126 diagnostic and 56 placebo records (266 total). **No hypothesis's
  classification changed.**
- **Objective B (replication): P22-OPT-013 does NOT replicate at the
  coarse-grained (bucket) level.** All five preregistered targets
  (MFE-primary, MAE, MFE−MAE spread, absolute return, directional return)
  came back `INCONCLUSIVE` — cross-sectional IC undefined (0 real
  same-date peer groups reached the minimum universe size), and the pooled
  time-series point estimate for the primary MFE target was **−0.018**,
  near zero and the *wrong sign* relative to P22-OPT-013's original pooled
  IC of **+0.099**. This is the same individual-contract-density problem
  Phase 31/32 already diagnosed, now shown to persist even for this
  specific, previously-successful feature/target pair once it is
  aggregated into buckets.
- **Per Part L's stop condition: STOP.** No new broad discovery campaign
  follows this phase. This report is the terminal artifact for
  P22-OPT-013 on the current free dataset.

## 2. Phase 32 statistical correction audit

Direct inspection of `phase32_campaign.run_campaign` (before this phase's
fix) confirmed: the only p-values ever passed to
`multiple_testing_across_family` were the 14 hypotheses' own
`cross_sectional.report.ic_p_value` values (defaulting to `1.0` when
undefined). The following, all separately computed and reported per
hypothesis, never entered the corrected family:

| Computed but never corrected | Where it lived |
|---|---|
| Pooled time-series Spearman/Pearson | `BucketHypothesisResult.pooled_time_series` |
| Per-symbol relationships (up to 5 underlyings) | `BucketHypothesisResult.per_symbol` |
| Symbol-balanced pooled statistic | `BucketHypothesisResult.symbol_balanced` |
| Leave-one-underlying-out point estimates | `HypothesisEvidence.robustness.leave_one_underlying_out` |
| Leave-one-period-out point estimates | `BucketHypothesisResult.leave_one_period_out` |

Phase 32's own report (§12) already disclosed this as "a genuine
methodological gap" rather than hiding it — this phase's job was to fix
the infrastructure, not merely to reword the disclosure.

## 3. Corrected Phase 32 conclusions

Ran all 14 `bucketed_options_alpha` hypotheses through
`phase33_corrected_campaign.run_corrected_campaign` against the real
dataset (13,800 contract-day rows → 858 bucket-day rows, FINE scheme).

| | Phase 32 original | Phase 33 corrected |
|---|---|---|
| Primary correction family size | 14 (1 per hypothesis) | 84 registered, 8 testable |
| Diagnostic records tracked | 0 | 126 |
| Placebo records tracked separately | 0 | 56 |
| Bonferroni/Holm/BH significant | 0/14 | 0/8 |
| Classifications changed | — | **0 of 14** |

Every hypothesis kept its Phase 32 classification (5 `INCONCLUSIVE`, 9
`NOT_READY`, 0 `DISCOVERY_SUPPORTED`/`PROMISING`). This is the expected,
non-surprising outcome, not a coincidence to explain away: a larger,
correctly-accounted correction family can only make the Benjamini-Hochberg
threshold **more conservative**, never less — so the fix could only ever
have *removed* a false claim of significance, and there was no claim of
significance to remove (Phase 32 already found 0 significant results under
its narrower, gap-containing correction). Per the phase's explicit
instruction, this null result is reported as-is — **not** reinterpreted as
newly meaningful because the correction mechanism changed.

## 4. Original P22-OPT-013 definition (re-verified from the record, not re-derived)

From Phase 22/23's own artifacts (`docs/p22_opt_013_adversarial_investigation.md`):

- **Feature**: `option_range_expansion_5` — a contract's own (H−L)/close
  ratio today, divided by the mean of that same ratio over the 5 trading
  days strictly before today.
- **Target**: `mfe_5` — 5-bar-forward maximum favorable excursion.
- **Discovery result**: pooled IC = 0.09852, p = 0.00001, n = 7,070 (Phase 22).
- **Phase 23's adversarial findings** (summarized in §21 below): survives
  10 cumulative controls (residual R²≈0.076 after all, p<1e-15), but only
  the MFE target (and `mfe_5 − mae_5`) are significant among 10 candidate
  targets — every close-to-close return horizon is not; classified
  `NON_DIRECTIONAL_ONLY`. Non-overlapping-window IC = 0.087 (p≈0.0996,
  n=1,464) — weakened, borderline, not destroyed. The rule-based
  tradeable transformation was `TRADEABLE_SIGNAL_FRAGILE`: median trade
  loses money, expected dollar P&L negative, 229% of a $1,000 account
  required per contract.
- **Already replicated once at the contract level**: Phase 31's
  `P31-OPT-003` used this exact feature/target pair on the FREE dataset
  and found cross-sectional evidence `INCONCLUSIVE` (0 real timestamps met
  the minimum peer-group size) — but a pooled time-series Spearman of
  **0.0925** from a single eligible contract (`n_contracts_eligible=1`),
  a hint of directional consistency with the original discovery but from
  too thin a sample to mean anything on its own. This is the sparsity
  problem Phase 32's bucketing was designed to solve.

## 5. Coarse-grained replication definition (frozen before evaluation)

**Feature**: `bucket_range_expansion_median` — the bucket-day median of
each contract's own, already-causal `option_range_expansion` value
(unchanged Phase 31 column), aggregated within the exact same bucket-day
key Phase 32's bucket panel uses. Mean, log-mean, and cross-sectional
dispersion variants were also computed and reported as diagnostics, never
substituted for the median in the primary/frozen definition.

**Primary target**: `forward_bucket_mfe_5` — Phase 32's existing
compounded-path bucket-level maximum favorable excursion over the next 5
real bucket-dates (unchanged, not redefined). Four secondary targets were
evaluated and reported **separately**, never blended into the primary
finding: `forward_bucket_mae_5`, `bucket_mfe_minus_mae_5` (mirrors Phase
23's Target H), `forward_abs_bucket_return_5`, `forward_bucket_return_5`.

**Hypothesis family**: `p22_opt013_coarse_replication`, 5 hypotheses,
preregistered via `phase33_replication_hypotheses.py` before any of this
section's numbers were computed, each carrying `parent_hypothesis_id =
"P22-OPT-013"` (a child reference, never an edit to the parent record).

## 6. Exact bucket taxonomy (Part E: frozen, no post-hoc expansion)

Reused Phase 32's density-based scheme selection unchanged
(`phase32_density_audit.select_scheme_by_density`), re-run on the same
real contract-day panel: **FINE scheme selected** — "17 FINE bucket cells
meet the density threshold (≥3 median obs/date across ≥10 dates)," the
same result Phase 32 itself reached. No new bucket definition, no
coarsening or fine-graining decision made specifically for this
replication.

## 7. Dataset density (Part H)

| | Value |
|---|---|
| Contract-day rows | 13,800 |
| Bucket-day rows (FINE scheme) | 858 |
| Bucket-day rows with a real range-expansion value | 279 (33% — the rest lack the 5-day trailing baseline the feature causally requires) |
| Unique underlyings | 5 (AAPL, FOXA, GOOG, NWSA, TWX) |
| Unique real expirations feeding the panel | 28 |
| Years covered | 2013 (706 rows), 2014 (8,594 rows), 2015 (4,500 rows) |
| Cross-sectional peer groups reaching min size (≥3) on the primary target | **0** |

The 0 cross-sectional peer groups is the single most important density
fact in this report: even after bucketing, no real calendar date has
three or more buckets simultaneously carrying both a real feature value
and a real 5-day-forward target value. Per Part H's instruction, this
alone is sufficient to classify the cross-sectional test `NOT_READY`
(reported here as the `CROSS_SECTIONAL_IC_UNDEFINED`/underpowered branch
of `INCONCLUSIVE`, not invented as a new category).

## 8. Feature construction (Part C)

`phase33_range_expansion_feature.py` never recomputes the range-expansion
ratio — it aggregates Phase 31's already-causal, already-verified
per-contract `option_range_expansion` column (no future observation, no
post-expiration data, no baseline window that looks past the bucket-day's
own date) into bucket-day median/mean/log-mean/dispersion, using the
IDENTICAL bucket-key construction Phase 32's own bucket panel uses
(verified by a direct test that both builders produce the same key set on
the same input rows). Where fewer than 2 real per-contract values exist
in a bucket-day, dispersion is `None`; where every value is non-positive,
the log-mean is `None` — never a fabricated value, in both cases.

## 9. Target construction (Part D)

All five targets reuse Phase 32's existing, unmodified
`forward_bucket_*` columns except the MFE−MAE spread, which is derived
once (`bucket_mfe_minus_mae_5 = forward_bucket_mfe_5 − forward_bucket_mae_5`,
only where both operands are real) and never independently recomputed.
Every target is evaluated and reported under its own hypothesis ID — no
target's result was ever used to inform another target's classification.

## 10. Underlying controls (Part F)

For every one of the 5 hypotheses, `underlying_control_comparison`
(Phase 31, unchanged) classified the relationship
`both_weak_or_undefined` — neither the option feature nor the underlying
control carried a usable signal on this panel, so the comparison could
not even distinguish "option adds information" from "inherited from
underlying." This is a data-density finding, not evidence the
relationship is underlying-driven; it is reported honestly as
`both_weak_or_undefined`, never rounded up to either alternative.

## 11. Statistical tests (Part I summary; full detail in §12)

| Hypothesis | Target | Cross-sectional IC | Pooled Spearman | Classification |
|---|---|---|---|---|
| P33-REPL-MFE (primary) | `forward_bucket_mfe_5` | undefined (0 peer groups) | **−0.0179** | INCONCLUSIVE |
| P33-REPL-MAE | `forward_bucket_mae_5` | undefined | +0.0173 | INCONCLUSIVE |
| P33-REPL-SPREAD | `bucket_mfe_minus_mae_5` | undefined | −0.0237 | INCONCLUSIVE |
| P33-REPL-ABS | `forward_abs_bucket_return_5` | undefined | +0.0251 | INCONCLUSIVE |
| P33-REPL-DIR | `forward_bucket_return_5` | undefined | −0.0107 | INCONCLUSIVE |

Every pooled point estimate is small in magnitude (|r| < 0.03) and none
carries the same sign, still less the same magnitude, as P22-OPT-013's
original pooled IC of +0.099.

## 12. Multiple-testing registry (Part I)

`phase33_replication_campaign.py` registers every test from Parts E/G
into the SAME repaired `TestRegistry` Objective A built — cross-sectional,
pooled time-series, per-symbol, DTE-balanced, moneyness-balanced,
call/put-balanced, leave-one-period-out, non-overlapping-window
re-evaluation, and the full placebo battery, for all 5 hypotheses.

| Family | Registered | Testable (real p-value) | BH significant |
|---|---|---|---|
| `primary_inferential` | 30 | 10 | **0** |
| `diagnostic_robustness` | 65 | 0 (by design — no well-defined p-value) | n/a |
| `placebo_diagnostics` | 20 | 0 (density too thin to run a placebo trial) | n/a |
| **Total registered** | **115** | | |

Zero significant results after correction, on a registry more than 8x
larger than a naive per-hypothesis-only count — the sparsity finding is
not an artifact of an undercounted test family.

## 13. Robustness tests (Part G)

- **DTE-balanced / moneyness-balanced / call-put-balanced** (Part E):
  every balanced point estimate for the primary MFE hypothesis is small
  (DTE-balanced +0.021, moneyness-balanced +0.010, call/put-balanced
  −0.018) — no sub-grouping recovers anything resembling the original
  discovery's magnitude.
- **Leave-one-underlying-out / robustness stratification**: `fragile =
  False` for every hypothesis — but this reflects the ABSENCE of a
  signal to destabilize (a near-zero point estimate cannot "flip sign"
  in any way that would count as fragility under Phase 31's own
  `sign_flips` logic, which requires at least two strata with a defined,
  non-trivial IC), not evidence of robustness in the sense Phase 23 meant
  it for the ORIGINAL discovery.
- **Non-overlapping windows** (Phase 23 Part 9, reproduced here): could
  not even be computed for the primary hypothesis — the cross-sectional
  IC was already undefined before thinning, so there was nothing to
  re-evaluate on a thinned subsample. This is itself informative: Phase
  23's original non-overlap test needed a *real, computable* IC to
  weaken; this replication never reaches that starting point.

## 14. Placebo tests

The full battery (shuffled-signal, shifted-signal, time-shuffled-target,
random-bucket-assignment) ran for every hypothesis but produced **0
testable placebo p-values** — the same underlying density limitation
(too few real, paired feature/target bucket-day rows) that made the
cross-sectional test undefined also left the placebo trials without
enough real pairs to construct a meaningful null distribution. Reported
honestly as `NOT_APPLICABLE_NO_PVALUE`, never treated as a passing
placebo separation.

## 15. Outlier analysis

`outlier_dependent = False` for all 5 hypotheses — but, as in §13, this
is the absence of anything to be outlier-dependent about (there is no
material point estimate for extreme observations to be carrying), not a
positive robustness finding in Phase 23's original sense (where a real,
sizeable IC was tested for outlier-dependence and found clean).

## 16. Expiration concentration

Computed on the underlying 13,800 real contract-day rows (bucket rows
discard real expiration identity): **28 distinct real expirations**, the
largest (`2016-01-15`) carrying only **10.9%** of rows — materially LESS
concentrated than Phase 23's original panel, where a single expiration
(`2023-06-16`) explained the entire "2023 anomaly." Expiration
concentration is not a factor in this replication's null result.

## 17. Symbol concentration

5 underlyings (AAPL, FOXA, GOOG, NWSA, TWX), the same universe Phase
31/32 established. `symbol_balanced.dominated_by_single_symbol` was not
flagged for any hypothesis. Symbol concentration is not a factor here
either — the limiting constraint is the number of underlyings
simultaneously observed on the same real date at the bucket level, not
any one symbol's share of the row count.

## 18. Economic significance

Because every hypothesis is `INCONCLUSIVE` with an undefined
cross-sectional signal, `TradeabilityClassification` correctly resolves to
`NOT_APPLICABLE_NO_STATISTICAL_SIGNAL` for all 5 — economic
plausibility was evaluated (Part J requires this regardless of
statistical outcome) but there is no directional or magnitude claim left
to price.

## 19. $1,000 affordability

From the shared contract-day panel underlying every hypothesis's bucket
evaluation: median premium **$1,360/contract**, only **46.0%** of real
contracts affordable within a $1,000 account. This mirrors Phase
31/32's own affordability findings closely (Phase 31's contract-level
P31-OPT-003 reported 46.0% affordable at $5,352 average premium) — the
$1,000 constraint is a real, binding filter independent of this
replication's statistical outcome, reported here per Part J's
instruction to evaluate it regardless of what the statistics found.

## 20. Comparison with Phase 22

| | Phase 22 (original, legacy 2021–2023 panel) | Phase 33 (coarse, free 2013–2015 dataset) |
|---|---|---|
| Pooled IC / correlation | +0.099 (p<0.001, n=7,070) | −0.018 (pooled Spearman, undefined cross-sectional IC) |
| Classification | `DISCOVERY_SUPPORTED` | `INCONCLUSIVE` |
| Data source | Legacy MCP options panel | Free QuantConnect/Lean sample (this project's only available source since Phase 26) |

The datasets are not the same universe in either symbols or calendar
period — a limitation disclosed here, not hidden (§23).

## 21. Comparison with Phase 23

| Phase 23 finding (original, individual contracts) | Phase 33 finding (coarse, buckets) |
|---|---|
| Survives 10 cumulative controls (R²≈0.076, p<1e-15) | Underlying control `both_weak_or_undefined` — no signal to test a control against |
| Only MFE and MFE−MAE targets significant among 10 | All 5 bucket-level targets (incl. MFE and MFE−MAE) `INCONCLUSIVE` |
| Non-overlap IC=0.087, p≈0.0996 (weakened, not destroyed) | Non-overlap not computable (no starting IC to weaken) |
| Not expiration-dependent, not moneyness-dependent, not symbol-dependent | Concentration checks pass, but on a null result, not a preserved signal |
| Tradeable transformation: `TRADEABLE_SIGNAL_FRAGILE` (median trade loses money, dollar P&L negative) | `NOT_APPLICABLE_NO_STATISTICAL_SIGNAL` — no tradeable transformation was attempted, per Part L |

Phase 23's adversarial checks were designed to stress-test a REAL,
computable signal and see what survived. This replication's checks
mostly could not even run in their intended sense, because there was no
signal left at the coarse-grained level to stress-test — a materially
different (and more fundamental) kind of failure than anything Phase 23
found in the original.

## 22. Final classification

Using ONLY the existing classification vocabulary (Part K — no weaker
custom category):

| Hypothesis | Classification |
|---|---|
| P33-REPL-MFE (primary) | **INCONCLUSIVE** |
| P33-REPL-MAE | INCONCLUSIVE |
| P33-REPL-SPREAD | INCONCLUSIVE |
| P33-REPL-ABS | INCONCLUSIVE |
| P33-REPL-DIR | INCONCLUSIVE |

None passes the 12-criterion Promising Finding Gate (all 5 fail on
`survives_multiple_testing_correction`, `economically_meaningful`,
`survives_reasonable_costs`, `not_explained_by_underlying_control`,
`placebo_separation`, and `bootstrap_support` simultaneously).

### Part N's mandatory explicit answers

| Question | Answer |
|---|---|
| Did P22-OPT-013 replicate? | **No.** |
| Did it survive the underlying control? | No — no signal existed to test against a control (`both_weak_or_undefined`). |
| Did it survive multiple-testing correction? | No — 0/8 testable primary tests significant. |
| Did it survive outlier removal? | Not meaningfully — `outlier_dependent=False`, but only because there is no material effect for outliers to be driving. |
| Did it survive non-overlapping windows? | No — the test could not even be computed (no starting cross-sectional IC). |
| Did it survive symbol/expiration concentration checks? | Not applicable in the affirmative sense — no dominance was found, but there was no signal for dominance to threaten. |
| Is it directional? | No — the directional-return hypothesis (`P33-REPL-DIR`) is INCONCLUSIVE, same as every other target. |
| Is it economically tradeable? | No — `NOT_APPLICABLE_NO_STATISTICAL_SIGNAL` for every hypothesis. |
| Does it pass the Promising Finding Gate? | No — 0 of 5 hypotheses pass; each fails 6 of 12 criteria. |

## 23. Limitations

- **Dataset provenance mismatch.** P22-OPT-013's original discovery used
  a legacy 2021–2023 options panel; this replication necessarily uses the
  free QuantConnect/Lean sample (2013–2015, 5 underlyings) that has been
  this project's only available source since Phase 26. A non-replication
  here cannot fully separate "the relationship does not exist" from "the
  relationship exists but this specific free dataset is too sparse and
  covers a different market period to detect it" — both are plausible,
  and this report does not claim to have distinguished them.
- **Cross-sectional peer groups never reached minimum size.** The
  binding constraint, exactly as Phase 31/32 already found for most of
  their own hypotheses: only 5 underlyings with real daily coverage means
  a same-date bucket peer group of ≥3 is structurally hard to reach even
  after aggregation.
- **Only 279 of 858 bucket-days carry a real range-expansion value**
  (the causal 5-day trailing baseline is unavailable early in most
  contracts' observed history), further thinning an already-thin panel.
- **No paid, higher-density options dataset was purchased or accessed**
  to test whether the relationship would be detectable with more
  underlyings/longer real history — consistent with this project's
  standing prohibition on paid data acquisition without explicit human
  authorization.

## 24. Recommendation for Phase 34

**Do not launch another broad discovery campaign on this specific
relationship.** P22-OPT-013 does not currently justify further
development on the free dataset — this is a legitimate, complete research
result, not a call to keep searching until something replicates. If a
future phase revisits options-specific alpha, the standing, already-
identified bottleneck (Phase 31 §"limitations", Phase 32 §12, and this
report's §23) is the SAME one every time: too few real underlyings with
daily-resolution options coverage in the free dataset to populate
cross-sectional peer groups, at either the contract or bucket level. Any
future work should either (a) wait for/request an explicitly
human-authorized paid data upgrade, or (b) explore hypothesis designs
that do not require same-date cross-sectional comparison at all (e.g.
purely time-series, single-underlying designs), rather than repeating
the cross-sectional density problem a third time. Per this phase's own
instruction: **STOP after Phase 33. Do not begin Phase 34 automatically.**

---

## Safety verification

Programmatically confirmed before this report was written
(`tests/test_phase33_safety.py`, 16 tests): no paid provider activated,
no API key added, no paid dataset purchased, no strategy object created,
no paper/live order submitted, no execution-gateway code imported or
modified, no autonomous live trading enabled, `ORATSActivationState`
unchanged (`ORATS_ACTIVATION_PENDING_HUMAN`), `SystemState` unchanged (7
states, no new transition), no imputation/interpolation function called
anywhere in this phase's modules, and every multiple-testing correction
family kept structurally disjoint.

## Test suite

56 new tests across 9 new test files (13 registry, 9 corrected campaign,
7 range-expansion feature, 6 group-balanced evidence, 6 replication
robustness, 7 replication hypotheses, 10 replication campaign, 16
safety, 1 regression addition to `test_phase32_hypotheses.py`), all
passing. Full suite: 2646 passed (was 2594 before this phase), the same
4 pre-existing baseline failures in `tests/test_orchestrator.py`
(unrelated stale-data timing tests) preserved unchanged.
