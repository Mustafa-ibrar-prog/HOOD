# Options Alpha Falsification & Statistical Validation (Phase 21)

Phase 20 left 2 survivors — `P19-OPT-009-EXPANDED` (log-moneyness →
5-day forward option return, primary metric: pooled cross-sectional IC)
and `P19-OPT-005-EXPANDED` (call vs. put 5-day forward return,
primary metric: group mean gap) — with pooled IC/gap that looked real
but untested against deliberate attempts to break them. **Phase 21's
job was not to find another positive result.** It was to try, honestly
and on the record, to kill both. Nothing here builds a strategy, places
an order, or touches validation/holdout data.

## Result, up front

**Both candidates: `INHERITED_FROM_UNDERLYING`.** Neither survives
Part 11's underlying-control test — the apparent option-level signal
disappears once the underlying's own forward return is controlled for.
That is a real answer, not a null result to be worked around, and per
Part 23's mapping it is the final classification for both, regardless
of anything else in the scorecard. `0/2` candidates are
`ROBUST_DISCOVERY_CANDIDATE`. No candidate qualifies for a
strategy-development phase.

## Frozen definitions (Part 2/4)

Both candidates and their parents were read (never edited) from
`HypothesisRegistry`/`PreregistrationStore` and fingerprinted before any
falsification analysis ran (`scripts/phase21_step1_verify_frozen_definitions.py`):

| Candidate | Parent | Feature | Target | Horizon | Universe | Metric |
|---|---|---|---|---|---|---|
| `P19-OPT-009-EXPANDED` | `P19-OPT-009` | `log_moneyness` | `forward_return_5` | 5 bars | Phase 20's 12-underlying universe | pooled cross-sectional IC |
| `P19-OPT-005-EXPANDED` | `P19-OPT-005` | `call_put` | `forward_return_5` | 5 bars | Phase 20's 12-underlying universe | mean(call target) − mean(put target) |

Immutable SHA256 experiment fingerprints (`src.research.experiment_fingerprint`):

- `P19-OPT-009-EXPANDED`: `fdb7572e19161a6901a519e0ddaaa8c329b4b9d0862a6d209b7b232c2fa20b69`
- `P19-OPT-005-EXPANDED`: `aaf818d3586909f14aa2cb07ca6d59be2ecb3a54a92758c8f51b0b4b8fb7dc49`

Negative/mechanical-baseline control (text, per the prompt's Part 2):
`log_moneyness -> underlying_forward_return_5` — the Phase 19/20
mechanical-baseline comparison, which is exactly what Part 11 below
reuses as Model A.

Data source: the existing `logs/research_data/phase20_research_panel.jsonl`
(9,044 rows, 120 contracts, 12 underlyings) — no new MCP fetch this
phase, no options-specific `VALIDATION_DATA`/`FINAL_HOLDOUT_DATA`
partition exists to touch (confirmed by reading `src/research/partition.py`;
enforced the same way every prior options phase enforced it — by
grepping every Phase 21 script for the `VALIDATION`/`FINAL_HOLDOUT`/
`DEVELOPMENT` partition-stage constants and asserting none appear —
`tests/test_phase21_safety.py::test_no_phase21_file_touches_development_validation_or_final_holdout_data`).

## P19-OPT-009-EXPANDED (log-moneyness IC)

Pooled effect: **IC = 0.01781, p = 0.105** (full 9,044-row panel).

- **Temporal (Part 5):** sign flips year to year — 2021 −0.034,
  2022 +0.071, 2023 −0.049. `sign_consistency = 0.67` (2/3 years share
  a sign, but the negative years bracket the positive one). Effect
  dispersion across years (stdev) = 0.065 — larger than the pooled
  effect itself. Not stable across time.
- **Symbol (Part 6):** leave-one-out effects range from −0.057 (QQQ,
  IWM) to +0.120 (AMZN); `positive_symbol_fraction = 0.67`. No single
  symbol drives it, but the sign is not consistent across symbols
  either.
- **Expiration (Part 7):** 2022-03-18 +0.055, 2022-06-17 +0.047,
  2023-06-16 −0.049 — leaving out either 2022 expiration collapses the
  pooled effect to ~0.00; leaving out 2023-06-16 raises it to +0.053.
  The result depends heavily on which expiration is included.
- **Moneyness (Part 8):** wildly inconsistent by bucket — deep ITM
  −0.118, ITM +0.057, near-ATM −0.006, OTM −0.014, deep OTM +0.182.
  `sign_consistency(buckets) = 0.60`.
- **Call/put (Part 9):** calls +0.180, puts −0.139 — **sign reverses**
  between calls and puts. A pooled IC across both sides is averaging
  two opposite relationships.
- **Outlier (Part 10, mandatory):** the underlying `forward_return_5`
  column is itself outlier-dominated by construction (top 1% of
  absolute values already account for ~97% of the pooled sum — a
  Phase 20 finding, not new). Even so, the log-moneyness IC itself is
  **not** classified `OUTLIER_DEPENDENT`: removing the top 1%
  positive/negative or winsorizing at 1%/2.5%/5% keeps the effect in a
  tight 0.0149–0.0240 band, same sign throughout.
- **Underlying control (Part 11) — the decisive test:** Model A
  (`log_moneyness → underlying_forward_return_5`) has IC = **−0.0346**,
  larger in magnitude than Model B's option-level IC of **+0.0178**.
  `compare_option_vs_underlying_signal` classifies this
  `inherited_from_underlying`. Model C's incremental R² from adding the
  option feature on top of the underlying's own forward return is
  **0.0006** — below the 0.005 threshold used here for "adds real
  information." **Verdict: `INHERITED_FROM_UNDERLYING`.**
- **Mechanical leverage (Part 12):** `HISTORICAL_GREEKS_UNAVAILABLE` —
  no delta-adjusted analysis was attempted or fabricated. Same-day
  dollar P&L per contract: mean **−$37.14**, stdev **$720.93** (huge
  dispersion relative to the mean).
- **Placebo battery (Part 13, all 7 types):** none of the 5
  distribution-based placebos separate the observed IC from its null
  (`p` = 0.14, 0.815, 0.475, 0.17, 0.695) — `clearly_distinguishable =
  False`. The sign-flip diagnostic passed exactly (flipped = −observed).
- **Temporal shift (Part 14):** shifted +1/+2/+5 bars all produce an IC
  **at or above** the true (unshifted) IC — a red flag for
  autocorrelation rather than a genuine t→t+5 relationship; only the
  +10 shift falls below it.
- **Dependence-aware bootstrap (Part 15/21):** time-block, stationary,
  and symbol-cluster (12 symbols, 1,000 resamples) 90% and 95% CIs
  **all cross zero** (e.g. symbol-cluster 90% CI: [−0.00005, 0.0457]).
- **Cost sensitivity (Part 17):** fails even the gentlest 1× assumption
  (net effect magnitude −0.063) — **`COST_FRAGILE = True`**.
- **Economic significance (Part 18):** mean premium $30.81/share
  ($3,081/contract) — 0 contracts affordable on a $1,000 account before
  any position sizing.
- **PBO / DSR (Part 20):** PBO = 0.450 (near coin-flip — roughly even
  odds the in-sample-best of 4 feature variants underperforms
  out-of-period); DSR = 0.709 (observed Sharpe-like 1.81 deflated for 4
  trials).

## P19-OPT-005-EXPANDED (call/put gap)

Pooled effect: **gap = +2.779, p = 0.006** (Welch t-test, full panel).

- **Temporal (Part 5):** positive in all 3 years (`sign_consistency =
  1.00`), but wildly unstable in size — 2021 +0.099, 2022 +3.747, 2023
  +0.772; effect dispersion (stdev) = 1.94, larger than most of the
  yearly values themselves. One quarter (2022Q1) is actually slightly
  negative.
- **Symbol (Part 6):** driven overwhelmingly by 2 of 12 symbols — AMZN
  (+27.4) and META (+29.5) — while most other symbols are near zero or
  negative (AAPL −0.07, TSLA −0.02, QQQ −0.55, MSFT −0.43, AMD −0.30,
  NFLX −1.02, IWM −0.45). Only 4/12 symbols (`positive_symbol_fraction
  = 0.33`) are positive on their own. Removing AMZN or META alone drops
  the pooled effect from 2.78 to ~1.4.
- **Expiration (Part 7):** 2022-06-17 alone is +4.76; 2022-03-18 is
  actually *negative* (−0.27); leaving out 2022-06-17 collapses the
  pooled effect to +0.31. This candidate is almost entirely one
  expiration's result.
- **Moneyness (Part 8):** deep ITM +6.93 and ITM +8.43 dominate; near
  ATM/OTM/deep OTM are all near zero or negative. `sign_consistency
  (buckets) = 0.60`.
- **Call/put underlying-direction control (Part 9):** the gap survives
  in both directions (up-days +4.94, down-days +0.78) but shrinks by
  6× on down days — not a clean, direction-independent effect.
- **Outlier falsification (Part 10, mandatory) — decisive on its own:**
  removing the top 1% positive observations **flips the sign** (+2.78 →
  **−0.12**); winsorizing at 1%/2.5%/5% keeps it negative throughout
  (−0.12, −0.10, −0.08). **`OUTLIER_DEPENDENT = True`** — the entire
  positive pooled gap is an artifact of a handful of extreme
  observations, exactly the failure mode Part 10 exists to catch. "Do
  not hide this": the raw pooled effect of +2.78 does not represent a
  stable relationship.
- **Underlying control (Part 11) — also decisive:** the call/put gap is
  **+4.94 on underlying up-days and +0.78 on underlying down-days** —
  same sign both directions. By construction (Part 11's own criterion)
  a same-sign-both-ways asymmetry is consistent with mechanical
  option convexity/skew, not a direction-dependent option-specific
  signal. **Verdict: `INHERITED_FROM_UNDERLYING`.**
- **Mechanical leverage (Part 12):** same panel-wide numbers as above
  (`HISTORICAL_GREEKS_UNAVAILABLE`, mean $&L −$37.14/contract).
- **Placebo battery (Part 13) — using the dedicated group-gap mirror
  battery (`src.options.placebo_extensions`'s `*_group_gap_*`
  functions), not the IC-based one:** the observed gap (+2.78) clears 4
  of 5 distribution-based placebos decisively (p = 0.0, 0.0, 0.0, 0.0)
  but **fails the symbol-identity shuffle** (p = 0.11, just above the
  0.10 bar) — consistent with Part 6's finding that 2 symbols drive
  most of the effect. `clearly_distinguishable = False`. The sign-flip
  diagnostic passed exactly.
- **Temporal shift (Part 14):** every shifted variant (+1/+2/+5/+10)
  produces a smaller or negative gap versus the true +2.78 — unlike
  candidate 1, this one does *not* show the "shift beats truth" red
  flag.
- **Dependence-aware bootstrap (Part 15/21):** symbol-cluster bootstrap
  (12 symbols, 1,000 resamples) 90% CI [−0.117, 7.105], 95% CI [−0.184,
  8.682] — **both cross zero**, despite the strong-looking point
  estimate and non-cluster-aware p-value.
- **Cost sensitivity (Part 17):** survives all 4 assumption levels
  (1×/2×/3×/5×) — `COST_FRAGILE = False`. This is the one dimension
  where the gap looks robust, but it is moot given Parts 10 and 11.
- **Economic significance (Part 18):** same feasibility numbers as
  candidate 1 — 0 contracts affordable on $1,000 before position
  sizing.
- **PBO / DSR (Part 20):** not computed — a group mean gap is not a
  per-timestamp IC series, and Part 20 explicitly says not to force
  these metrics when their assumptions don't hold. Reported as such,
  not silently skipped.

## A design fix made mid-phase, and why it mattered

The first run of the falsification campaign reused the IC-based placebo
battery (`src.research.cross_sectional_placebo`) for **both**
candidates, feeding it a numeric encoding of `call_put` for the
gap-metric candidate. That produced a placebo "observed" statistic
(IC of `call_put_numeric` vs. target, ≈ −0.074) with no relationship to
the candidate's actual primary metric (the +2.78 group gap) — an
internal inconsistency that would have silently misreported Part 13/14
for `P19-OPT-005-EXPANDED`. This was caught before committing anything,
not shipped and rationalized: `src/options/placebo_extensions.py` was
extended with a full `*_group_gap_*` mirror of all 7 placebo types (plus
the Part 14 shift test) that computes the real group-mean-gap statistic
under each randomization, and the campaign script now dispatches by
each candidate's actual `metric` (`"ic"` vs `"gap"`). The numbers in the
P19-OPT-005-EXPANDED section above are from the corrected battery. This
does not change either candidate's final classification (Part 11's
underlying-control test governs both, and is unaffected by this fix),
but it does change what Part 13 honestly reports for candidate 2, which
matters under Part 1's adversarial-honesty mandate.

## Multiple testing (Part 19)

18 raw p-values were collected across both candidates' pooled effects,
yearly effects, and 5 distribution-based placebo tests each:

| Method | Significant (α=0.05) |
|---|---|
| Bonferroni (FWER) | 7 / 18 |
| Holm-Bonferroni (step-down FWER) | 8 / 18 |
| Benjamini-Hochberg (FDR) | 10 / 18 |

Reported in full, favorable and unfavorable results alike, per Part 19's
explicit instruction not to selectively report only favorable tests.

## Robustness scorecard (Part 22) & final classification (Part 23)

| Dimension | P19-OPT-009-EXPANDED | P19-OPT-005-EXPANDED |
|---|---|---|
| Statistical significance | PASS | PASS |
| Temporal stability | FAIL | PASS |
| Symbol stability | PASS | PASS |
| Outlier stability | PASS | **FAIL** |
| Placebo separation | FAIL | FAIL |
| Underlying control | **FAIL** | **FAIL** |
| Cost sensitivity | FAIL | PASS |
| **Dimensions passed** | **3 / 7** | **4 / 7** |

Per Part 23's explicit decision rule, the underlying-control failure is
checked first and overrides everything else:

- **`P19-OPT-009-EXPANDED` → `INHERITED_FROM_UNDERLYING`**
- **`P19-OPT-005-EXPANDED` → `INHERITED_FROM_UNDERLYING`**

`ROBUST_DISCOVERY_CANDIDATE` does **not** mean validated — it would only
mean a relationship survived Phase 21 enough to justify a dedicated
strategy-development phase. **0/2 candidates reach it.** Neither
candidate is `REJECTED`, `FRAGILE`, or `INCONCLUSIVE` either — Part 23
gives `INHERITED_FROM_UNDERLYING` priority as its own terminal outcome
whenever the underlying-control test fails, which it did for both.

## What this phase explicitly did not do (Part 24)

No live strategy, no paper strategy, no connection from this research to
`src/execution/`, no paper or live order placed, no
`VALIDATION_DATA`/`FINAL_HOLDOUT_DATA` access, no claim of profitability,
no parameter optimization, no tuning of either hypothesis's definition
to its own Phase 21 results — `tests/test_phase21_safety.py` asserts all
of this mechanically (AST/substring scans), the same pattern used by
every prior phase's safety test.

## Architecture added (`src/options/`, additive to Phase 18/19/20)

- **`placebo_extensions.py`** (Part 13) — the 3 placebo types not
  already reusable from Phase 7 (within-symbol time shuffle,
  symbol-identity shuffle, block-preserving shuffle) plus a sign-flip
  diagnostic, all IC-based; **plus** a full `*_group_gap_*` mirror of
  all 7 placebo types (including the Part 14 shift test) for candidates
  whose primary metric is a group mean gap rather than an IC.
- **`outlier_treatment.py`** (Part 10) — `winsorize`, `remove_top_percent`,
  `top_observations`, and `compute_outlier_attribution` (top 1%/5%/10%
  share of the pooled sum).
- **`dependence_bootstrap.py`** (Part 15/21) — `symbol_cluster_bootstrap_ic`,
  resampling the *set of symbols* with replacement (not rows), so a CI
  reflects "~12 independent underlyings," not "9,044 independent rows."

All three modules reuse `src.research.ic`/`src.research.cross_sectional_placebo`
directly rather than reimplementing IC or placebo math — enforced by
`tests/test_phase21_safety.py::test_placebo_extensions_module_never_duplicates_the_phase7_ic_helpers_signature_incorrectly`.

## Honest summary

Two candidates entered Phase 21 looking like real, if modest,
cross-sectional relationships. Both failed the single test designed to
distinguish "genuine option-specific information" from "the option is
just a leveraged bet on its underlying" — Part 11's underlying-control
comparison. `P19-OPT-005-EXPANDED` additionally turned out to be
outlier-dependent (Part 10) and symbol-concentrated in 2 of 12 names
(Part 6) once examined adversarially. Neither survives to a strategy
development phase. Per the phase's own stated principle: **research
integrity is more important than producing a trade — if all candidates
fail, that is a successful research result.** This phase found that
result honestly, including catching and fixing its own internal
statistical inconsistency (the placebo-battery mismatch above) before
it could distort the reported evidence.
