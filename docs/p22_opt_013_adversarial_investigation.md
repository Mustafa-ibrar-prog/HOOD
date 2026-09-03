# P22-OPT-013 Adversarial Investigation & Tradeability Test (Phase 23)

Phase 22 found exactly one `DISCOVERY_SUPPORTED` hypothesis:
`P22-OPT-013` — an option's own range-expansion ratio predicts its
5-bar-forward maximum favorable excursion (`mfe_5`), IC=0.099, p<0.001,
n=7,070. Phase 23's job was not to improve that result. It was to try
to break it — and to answer the harder question the discovery itself
could not: **is this a real, repeatable option-specific relationship,
and can it be turned into something a trader could actually capture?**

## Headline result

**The discovery survives adversarially — the tradeable version does not,
not yet.**

- **Investigation classification: `NON_DIRECTIONAL_ONLY`.** The
  relationship is real, option-specific (survives 10 cumulative
  controls), symbol-robust, moneyness-robust, expiration-robust, and
  call/put-symmetric. But it predicts *how favorably a price wandered at
  its best point*, not *direction*, not *win probability*, and not
  *close-to-close return at any horizon*.
- **Tradeable-rule classification: `TRADEABLE_SIGNAL_FRAGILE`.** A
  simple next-bar-execution rule built on the same feature is
  percentage-return-positive and survives 1×-3× cost stress — but its
  positive mean is carried almost entirely by a handful of extreme
  winners (median trade loses money; the average trade's DOLLAR P&L is
  negative even though its average PERCENTAGE return is positive).
- **Advancement gate (Part 28, 14 criteria): not satisfied.** A future
  strategy-development phase is **not** justified on this candidate as
  it currently stands.

## Part 2 — Frozen parent, verified exactly

`scripts/phase23_step1_freeze_parent.py` loaded `P22-OPT-013` read-only,
recomputed its experiment fingerprint, and reproduced the exact Phase 22
result on the exact Phase 22 panel:

| | Frozen definition |
|---|---|
| Feature | `option_range_expansion_5` |
| Target | `mfe_5` |
| Horizon | 5 bars |
| Universe | the 12-symbol Phase 20 universe |
| `parent_hypothesis_id` | `None` (itself a top-level Phase 22 discovery) |

**Experiment fingerprint:** `c9226d827f192942bfc0186adb9f41a7c144c82ee4f09496980e7351fd8af55b`

**Reproduction:** recomputed pooled IC = 0.09852, p = 0.00001, n = 7070 —
an **exact match** to the committed Phase 22 result. Both the fingerprint
and this reproduction are enforced by `tests/test_phase23_frozen_parent.py`
as a standing regression guard.

Two new investigations were preregistered (`scripts/phase23_step2_preregister_investigation.py`)
BEFORE any Phase 23 result was computed, both with `parent_hypothesis_id="P22-OPT-013"`
— a child reference, never an edit to the parent: `P23-INV-P22-OPT-013`
(the adversarial investigation) and `P23-OPT-013-TRADEABLE` (the rule-based
transformation). The 10-control hierarchy, the 10-target validation
family (A-J), the 6 candidate 2022-concentration explanations, and the
5×4 threshold/holding-period grid were all fixed at this point, before
any of Part 3-20's results existed.

## Part 3 — Mechanism decomposition: what is the feature actually measuring?

Pooled Pearson correlation between `option_range_expansion_5` and 11
candidate mechanisms (mechanism identification only, not alpha):

| Candidate mechanism | r |
|---|---|
| underlying range expansion | **0.214** |
| persistence of option price movement | -0.084 |
| option price volatility (own) | -0.053 |
| call/put characteristic | 0.039 |
| moneyness (distance from ATM) | 0.034 |
| recent option momentum | 0.024 |
| option price acceleration | -0.025 |
| underlying volatility (level) | -0.019 |
| DTE | -0.019 |
| underlying volatility expansion | -0.005 |
| large recent option movement (gap) | -0.006 |

The feature correlates most (still only moderately, r=0.21) with the
**underlying's own range expansion** — expected, since a big underlying
move mechanically widens the option's own daily range too. It does
**not** reduce to option momentum, acceleration, or gap. Part 4 tests
whether this partial overlap explains the discovery.

## Part 4 — Cumulative control hierarchy: survives, but with a real confound absorbed

Ten preregistered controls, added cumulatively (never reordered after
seeing results):

| After control | incremental R² | feature p |
|---|---|---|
| 1. underlying forward return | 0.277 | <1e-15 |
| 2. + underlying abs forward return | 0.278 | <1e-15 |
| 3. + underlying realized vol | 0.276 | <1e-15 |
| 4. + underlying vol expansion | 0.276 | <1e-15 |
| 5. + underlying range expansion | 0.294 | <1e-15 |
| 6. + option trailing return | 0.294 | <1e-15 |
| 7. + option trailing volatility | 0.292 | <1e-15 |
| **8. + option's own recent range LEVEL** | **0.076** | <1e-15 |
| 9. + moneyness distance from ATM | 0.076 | <1e-15 |
| 10. + DTE | **0.076** | <1e-15 |

**Survives all 10 controls: True.** But note the sharp drop after
control 8 (option's own recent range *level*, `option_true_range_proxy_10`):
incremental R² falls from 0.29 to 0.076. A large share of the naive
relationship — though not all of it — is mechanically explained by the
option's own raw recent range level (an option that has recently had a
wide range keeps having a wide range, and a wide-range option has more
room to register a large MFE almost by construction). What survives
past that control (R²≈0.076, still enormous by cross-sectional-IC
standards, p<1e-15) is a real, option-specific residual. This is
reported honestly as a partial-but-incomplete mechanical explanation,
not hidden and not used to reject the finding outright (Part 4
explicitly says not to add controls "merely until the signal disappears" —
it did not disappear).

## Part 5 — Target-validation family: the decisive test

| Target | Definition | IC | p |
|---|---|---|---|
| A | forward_return_1 | 0.036 | 0.120 |
| B | forward_return_3 | 0.035 | 0.156 |
| C | forward_return_5 | 0.017 | 0.460 |
| D | forward_return_10 | 0.001 | 0.977 |
| E | forward_return_20 | 0.012 | 0.624 |
| **F** | **mfe_5 (the parent target)** | **0.099** | **0.00001** |
| G | mae_5 | -0.010 | 0.647 |
| **H** | mfe_5 − mae_5 | **0.072** | **0.0014** |
| I | forward_return_5 \| forward_return_5 > 0 | 0.025 | 0.398 |
| J | P(forward_return_5 > 0) | 0.016 | 0.498 |

**Only F and H are statistically significant.** Every close-to-close
return horizon (A-E), the adverse-excursion target (G), the
conditional-on-a-win magnitude (I), and the win-probability target (J)
are all statistically indistinguishable from zero. This is the single
most important finding of Phase 23: **the signal identifies contracts
whose price wanders favorably at some point in the next 5 bars, and
that favorable wander is not offset by a correspondingly larger adverse
excursion (H survives) — but it does not tell you whether the position
would actually be profitable at close, at any horizon, or at all.**

## Part 6 — Directional vs. non-directional: `NON_DIRECTIONAL_ONLY`

- Signed forward_return_5 (Target C): not significant.
- abs_forward_return_5 (pure magnitude): IC=-0.001, essentially zero —
  the feature does **not** predict "the option will move a lot," only
  that it predicts favorable-direction excursion specifically.
- Calls IC=0.132, puts IC=0.128 — nearly identical, no side dependency.
- Underlying-up-day IC=0.061, underlying-down-day IC=0.103 — both
  positive, no directional dependency on the underlying's own move.

**Classification: `NON_DIRECTIONAL_ONLY`.** This is the correct,
conservative label per Part 6's own framing — it tells you "this option
is likely to wander favorably at its best point," not "this option is
likely to move favorably for a long position by the time you'd exit."

## Part 9 — Overlapping window test: borderline

Overlapping (standard): IC=0.099, n=7,070. Non-overlapping (every 5th
observation per contract, so forward windows never overlap): IC=0.087,
p=0.0996, n=1,464. The effect weakens modestly and its significance
becomes borderline (just above the conventional 0.05 cutoff) — expected
partly because n falls by 80%, which mechanically widens the p-value
regardless of the true effect's stability. **Not** classified
`OVERLAP_DEPENDENT` (the point estimate survives, at ~88% of its
original size), but this is not a clean pass either — flagged
explicitly rather than glossed over.

## Part 10 — Signal persistence and clustering

Signal frequency (feature > 1.5): 16.5% of contract-days. Average
cluster length: 1.24 days (mild clustering, not severe). 940 distinct
signal episodes out of 1,163 flagged days (223, or 19%, are repeats
within a cluster and would overstate the count of genuinely independent
opportunities if each were treated as its own trade). A first-signal-only
vs. every-signal comparison, computed **within the already-flagged
subsample** (IC=0.306 vs. 0.309 respectively — a dose-response finding:
more extreme signal values correlate with even larger favorable
excursions among already-flagged contracts, mildly supporting the
mechanism's plausibility), is not directly comparable to the pooled
discovery-stage IC of 0.099 (a different, conditioned sample) and is
reported here as a distinct persistence-analysis statistic, not a
replication of the primary result.

## Part 11 — 2022 concentration: a structural, not a regime, story

Six candidate explanations were fixed before this decomposition ran:

- **Candidate A (regime): mixed, not the driver.** Within 2022 alone,
  `bear_high_vol` (IC=0.16) and `bear_low_vol` (IC=0.18) are strong but
  `bull_high_vol` (IC=-0.02) and `bull_low_vol` (IC=0.01) are weak — no
  single regime cleanly explains the year effect.
- **Candidate B (expiration): a dominant, defensible explanation.**
  2023 in this panel **is** the 2023-06-16 expiration (IC=-0.023,
  n=1,950) — the only expiration in the panel with a negative point
  estimate. 2021/2022 map almost entirely onto the other two
  expirations (2022-03-18 IC=0.18-0.21; 2022-06-17 IC=0.14), both
  positive.
- **Candidate C/E (symbols / data availability): also dominant.** 2021
  has only 4 symbols (AAPL/NVDA/SPY/TSLA). 2022 has 10. **2023 has only
  5, and is a materially different set** (AAPL/GOOGL/NVDA/SPY/TSLA) —
  GOOGL appears *only* in 2023 (a real, Phase-20-documented consequence
  of avoiding its 2022 split confound), and none of AMD/AMZN/IWM/MSFT/
  NFLX/QQQ have any 2023 representation at all.
- **Candidate D (moneyness/call-put): not a driver** — proportions are
  stable across years.
- **Candidate F (random variation): cannot be ruled out** with only 3
  years of data — stated honestly rather than dismissed.

**Conclusion, not post-hoc-selected:** "2022 concentration" is better
described as **"2023-06-16 expiration + a smaller, non-overlapping
5-symbol subset,"** a structural artifact of this project's still-thin
historical options dataset (3 real expirations, gathered across
different symbol sets — see Phase 20's own documentation of why), not
evidence that the relationship is regime-dependent or decaying over
calendar time.

## Part 12/13/14/15 — Symbol, expiration, moneyness, call/put robustness

- **Symbols:** equal-weight average IC=0.111 vs. pooled 0.099 — close.
  Strongest (QQQ, IC=0.216) removed → 0.096 (barely moves). Weakest
  (AAPL, IC=0.038) removed → 0.109. Symbol-cluster bootstrap 90% CI
  [0.067, 0.125] excludes zero (n=11 symbols with a usable IC; AMZN/META
  had too few rows).
- **Expiration:** 2022-03-18 IC=0.19, 2022-06-17 IC=0.14, 2023-06-16
  IC=-0.02. Leave-one-out never flips the pooled sign or crosses zero
  (worst case, removing 2022-03-18, still leaves IC=0.058). **Not**
  `EXPIRATION_DEPENDENT` by that criterion — though the ~70% relative
  drop when removing 2022-03-18 alone is a real sensitivity, noted here.
- **Moneyness:** all 5 buckets positive (0.099-0.172), sign_consistency
  = 1.00, equal-weight average = 0.126. **Not** `MONEYNESS_DEPENDENT` —
  the strongest robustness result in the whole investigation.
- **Call/put:** calls 0.132, puts 0.128 — no side dependency.

## Part 19 — Clustered bootstrap: robust at 90%, thin at 95% on the coarse axes

| Method | 90% CI | 95% CI |
|---|---|---|
| Time-block | [0.050, 0.143] | [0.040, 0.152] |
| Stationary | [0.050, 0.146] | [0.043, 0.154] |
| Symbol-cluster (n=11) | [0.065, 0.126] | [0.061, 0.133] |
| Expiration-cluster (n=3) | [0.058, 0.167] | **[-0.023, 0.188]** |
| Year-cluster (n=3) | [0.026, 0.212] | **[-0.023, 0.212]** |

Every 90% CI excludes zero. At 95%, the two coarsest axes — expiration
and year, each with only 3 clusters — cross zero. With only 3
independent units along those axes, this is an honest degrees-of-freedom
limitation, not a contradiction of the 90% result, but it means the
evidence is **not** bulletproof at the stricter confidence level along
exactly the two axes Part 11 already flagged as structurally thin.

## Outlier check (discovery-stage IC): clean

`mfe_5`'s own outlier concentration (top-1% share ≈ 0.32) is much lower
than the ~0.97-1.0 seen for raw option returns throughout Phase 19-22
(a bounded "best point in a window" statistic is naturally less
extreme-tail-dominated than a raw return). Winsorizing at 5% barely
moves the IC (0.0985 → 0.0996). **Not** `OUTLIER_DEPENDENT` at the
discovery-IC level — see the tradeable-transformation section below for
a very different finding once this becomes a mean-return P&L simulation.

## Part 20 — PBO/DSR: P22's weakness is carried forward, not hidden

**P22 original (kept in this report, unhidden): PBO=0.700, DSR=0.999.**
A P23 recomputation using a partially different 4-variant pool
(substituting mechanistically-related variants for Phase 22's original
comparison set) produced PBO=0.350 — notably lower, but **not
presented as resolving Phase 22's concern**: PBO is sensitive to which
alternative-strategy universe it's computed against, and the two runs
used different variant pools for defensible but different reasons. Both
numbers are reported side by side per Part 20's explicit instruction.

## Part 21 — Multiple testing (P23-INV family)

21 raw p-values collected across Parts 4/5/9. Bonferroni, Holm-Bonferroni,
and Benjamini-Hochberg all agree: **12/21 significant** after correction.

## Investigation final classification

| Flag | Value |
|---|---|
| `underlying_inherited` | False (survives all 10 controls) |
| `outlier_dependent` | False (discovery-stage IC only) |
| `expiration_dependent` | False |
| `moneyness_dependent` | False |
| `overlap_dependent` | False (borderline) |
| `non_directional_only` | **True** |

**`P22-OPT-013` investigation classification: `NON_DIRECTIONAL_ONLY`.**
This does not mean validated, profitable, or ready for trading.

---

## Part 7/8 — The tradeable transformation: `P23-OPT-013-TRADEABLE`

`scripts/phase23_step4_tradeable_transformation.py` converts the
discovery into the simplest possible rule: IF `option_range_expansion_5`
`> threshold` THEN enter long the option — over the preregistered 5×4
grid (thresholds 1.25-2.50, holding periods 1-10 bars), with entry at
the **next** bar's open or close (never the signal bar's own OHLC —
Part 8's explicit prohibition on an impossible fill), exit at
`entry + holding_period` bars' close.

**A self-caught bug, fixed before this result was reported:** the first
run entered a handful of trades at a **$0.01 tick-floor-pinned** price
(the exact data-mechanics artifact Phase 19's `find_suspicious_flat_price_run`
already documented) — producing single-trade "returns" of 100-6,700%
that alone inflated grid-cell mean returns to 300-700%. Caught by
inspecting the top individual trades, fixed with an explicit
`MIN_ENTRY_PRICE=$0.05` floor, and the full grid rerun. Every number
below is from the corrected run.

**32/40 grid cells** (5 thresholds × 4 holding periods × 2 entry-timing
variants) are positive and nominally significant (p<0.05, uncorrected).

**PRIMARY grid point** (threshold=1.75, holding=5, next-bar-open —
chosen before this run on principled grounds: the grid's median
threshold, the parent's own horizon, the most conservative entry
timing): **n=740 trades, mean return +45.8%, win rate 40.3%, p<0.00001.**

### A second self-caught issue: the tradeable P&L is itself outlier-dependent

Applying the same mandatory-outlier discipline used throughout Phase
19-23 to the trade-return distribution itself (not just the discovery
IC) revealed:

- **Median trade return: -7.4%** (a LOSS), despite a +45.8% mean.
- Top 1% of trades account for **47%** of the total return sum; top 5%
  account for **89%**; top 10% account for **112%** (i.e., the bottom
  90% of trades collectively lose money).
- Top 5 winning trades: +3,804%, +3,191%, +2,890%, +2,555%, +1,266% —
  extreme but legitimate (not the $0.01 artifact; these survive the
  price floor) — genuinely rare, enormous winners.
- Winsorizing at 5% roughly halves the mean return (+45.8% → +18.6%),
  though it stays positive.

**`TRADE_OUTLIER_DEPENDENT: True`.** The percentage-return significance
is real but is substantially carried by a small number of extreme
winners, not representative of what a typical trade in this rule would
produce.

### Cost, execution stress, and economic significance

- **Cost sensitivity:** survives 1×/2×/3× ASSUMPTION-labeled cost
  stress (net returns +36%/+28%/+16%), fails 5× (-6%). Not
  `COST_FRAGILE` by the 1×-survival criterion, but the margin shrinks
  fast.
- **Execution stress** (entry AND exit each delayed by 1 extra bar):
  n=701, mean=+32.1%, p=0.00002 — still positive and significant.
- **Small-account feasibility:** mean premium $22.87/share → **$2,287
  required per contract — 229% of a $1,000 account.**
  `CURRENTLY_NOT_CAPITAL_FEASIBLE: True`, with no leverage/margin
  assumption used to hide this. Worst single observed loss: **-$14,545**
  (a real, if extreme, trade on a higher-premium contract that collapsed
  toward zero — the maximum possible loss on a long option is -100% of
  premium paid, consistent with this).
- **The economically decisive number: expected dollar P&L per trade is
  NEGATIVE (-$191),** even though the mean PERCENTAGE return is
  positive (+45.8%). This is not a contradiction: percentage returns
  are entry-price-relative (a cheap contract's huge percentage winner
  contributes little in dollars; an expensive contract's percentage
  loss contributes a lot in dollars). **In the unit that actually
  determines account P&L, this rule loses money on average.**
- **Position sizing proxy** (0.5%/1%/2%/5% of a $1,000 account): at
  every risk level, **0 contracts** can be sized to the worst observed
  loss — the position size a responsible risk budget would allow is
  currently zero.

### PBO/DSR for the tradeable transformation

P22 original: PBO=0.700, DSR=0.999 (kept, not hidden). P23 tradeable
transformation: PBO=0.100, DSR≈1.00 — but the DSR here is computed on a
return series with skew=8.99 and kurtosis=103, a severely fat-tailed,
non-normal distribution that stresses DSR's own underlying assumptions;
treat this DSR figure as unreliable in the direction of overstatement,
not as a clean pass.

### Multiple testing (P23-TRADEABLE family)

40 raw p-values across the grid. Bonferroni: 18/40. Holm-Bonferroni:
21/40. Benjamini-Hochberg: 32/40.

### Tradeable-signal final classification

**`TRADEABLE_SIGNAL_FRAGILE`** — positive and nominally significant in
percentage-return terms, survives 1×-3× cost stress and execution
delay, but is outlier-dependent (median trade loses, expected dollar
P&L is negative) and is currently capital-infeasible on a $1,000
account without leverage.

---

## Part 28 — Advancement gate: not satisfied

| # | Criterion | Verdict |
|---|---|---|
| 1 | Option-specific after stronger controls | ✅ Yes (R²≈0.076 after all 10 controls, p<1e-15) |
| 2 | Survives alternative economically meaningful targets | ❌ No (fails A-E, G, I, J — only F and H survive) |
| 3 | Not solely an MFE artifact | ⚠️ Partial (H survives too, but the practical targets don't) |
| 4 | Survives realistic next-bar execution | ⚠️ Partial (% return yes; $ P&L no) |
| 5 | Not solely caused by overlapping observations | ⚠️ Weakened, not destroyed (borderline p≈0.10) |
| 6 | Not solely one expiration | ✅ Yes |
| 7 | Not solely one symbol | ✅ Yes |
| 8 | Not solely one moneyness bucket | ✅ Yes (strongest result) |
| 9 | Not solely calls or puts | ✅ Yes |
| 10 | Clustered bootstrap supports the effect | ⚠️ Yes at 90%, not fully at 95% on 2 thin axes |
| 11 | Multiple-testing concerns accounted for | ✅ Yes (reported, not selectively) |
| 12 | PBO weakness addressed, not ignored | ✅ Addressed and carried forward (not resolved) |
| 13 | Plausible path to profitability after costs | ❌ **No** — expected dollar P&L is negative |
| 14 | Can eventually translate into a contract-selection rule | ⚠️ Uncertain given #2/#13 |

**2 of 14 criteria clearly fail (#2, #13), several more are only
partially satisfied. The advancement gate is not met.** A future
strategy-development phase is **not** justified on `P22-OPT-013` /
`P23-OPT-013-TRADEABLE` as currently defined. This is a legitimate,
successful research result under this project's own stated principle:
research integrity over producing a trade.

## What this phase explicitly did not do

No live or paper strategy created, no order placed, no execution-gateway
modification, no `VALIDATION_DATA`/`FINAL_HOLDOUT_DATA` access, no
promotion of `P22-OPT-013` to a validated status — mechanically verified
by `tests/test_phase23_safety.py`.

## Two self-caught bugs, both fixed before this report

1. **The $0.01 tick-floor-pinned entry-price bug** (described above under
   Part 7/8) — caught by inspecting individual trades before trusting an
   implausibly large grid-wide mean return.
2. **The mean-return-vs-outlier-dependence gap**: a MEAN-based P&L
   simulation is exactly the kind of statistic Phase 19-22's own
   documented finding (extreme low-basis option price moves dominate
   mean-based statistics) predicts will be outlier-fragile in a way
   Phase 19-22's primarily RANK-based (Spearman IC) statistics are not.
   Applying the SAME mandatory outlier discipline this project has used
   since Phase 21 to the tradeable P&L itself (not just the discovery
   IC) surfaced the median-trade-loses-money finding that changed the
   final classification from `TRADEABLE_SIGNAL_SUPPORTED` to
   `TRADEABLE_SIGNAL_FRAGILE`.

## Recommended next phase

Not a strategy-development phase on this candidate. If pursued further,
the most promising unresolved thread is Part 5's finding that Target H
(`mfe_5 − mae_5`, IC=0.072, p=0.0014) survives independently of Target F
— a genuinely different, spread-based economic framing that might
translate into a defined-risk (e.g. debit spread) structure better
matched to what this signal actually predicts (favorable path
excursion without a corresponding predicted adverse excursion) than a
single-leg long option judged on close-to-close or win-probability
terms. Any such follow-up would need its own fresh preregistration —
per Part 23's explicit instruction, this observation is `POST_HOC` and
is not evidence, only a candidate for a future, honestly-labeled
hypothesis.
