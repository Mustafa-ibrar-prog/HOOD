# Research Methodology

This document explains the quantitative research validation layer built
across Phases 4–7 of this codebase, for anyone auditing what a
classification like `PROMISING`, `NOT_READY`, or `REJECTED` actually
means and how much confidence it should carry. It assumes no prior
familiarity with quantitative research methodology.

Everything described here is **research-only**. Nothing in `src/research/`
places, modifies, cancels, or evaluates a live or paper order, and no
function anywhere in this codebase can programmatically advance a
strategy into paper or live trading — see [The research gate](#the-research-gate)
below for the hard boundary.

## The research lifecycle

Before Phase 7, a hypothesis went from an idea straight to a full
backtest. Phase 7 introduces an explicit, four-stage **data lifecycle**
(`src/research/partition.py`) so that different kinds of evidence come
from genuinely different data:

| Stage | What it's for | Who may use it to pick a parameter? |
|---|---|---|
| `DISCOVERY_DATA` | Cheap, IC-based screening of a hypothesis's feature/target relationship — no backtest | Yes |
| `DEVELOPMENT_DATA` | Building and backtesting a strategy, sweeping parameters | Yes |
| `VALIDATION_DATA` | An intermediate check — visible for reporting, not for choosing | **No** |
| `FINAL_HOLDOUT_DATA` | Touched by nothing until parameters are already frozen | **No** |

The four date ranges are computed **from the actual available data**
(`determine_lifecycle_partitions`), never hand-picked, and
`assert_stage_allows_parameter_selection` raises if any code tries to use
`VALIDATION_DATA` or `FINAL_HOLDOUT_DATA` to choose a parameter.

## Why "statistically significant" isn't enough: economic significance

A feature can have a real, non-random relationship with future returns
and still not be worth trading — transaction costs, slippage, and
turnover can eat the entire edge. `src/research/economic_significance.py`
computes gross vs. net expectancy, an edge/cost ratio, and expected net
edge after 1×/2×/3× modeled costs. The research scorecard (below) will
**never** classify a hypothesis as anything other than `NOT_READY` until
its economic significance has actually been evaluated — IC evidence alone
is structurally insufficient (`src/research/scorecard.py`'s
`classify_with_scorecard`).

## The multiple-testing problem

Testing many hypotheses (or many parameter variants of one hypothesis)
and reporting only the best one systematically overstates how real the
"discovery" is — some fraction of tested ideas will look good by chance
alone, in proportion to how many were tried. `src/research/multiple_testing.py`
implements three corrections and documents when each applies:

- **Bonferroni** — controls the probability of *any* false positive
  across the family (family-wise error rate, FWER). Simple, conservative.
- **Holm-Bonferroni** — also controls FWER, but is uniformly more
  powerful than Bonferroni (rejects at least as many hypotheses) — prefer
  it over plain Bonferroni whenever FWER control is the goal.
- **Benjamini-Hochberg** — controls the *expected fraction* of false
  discoveries among rejected hypotheses (false discovery rate, FDR), not
  FWER. Less conservative — appropriate for large, exploratory families
  where a few false positives are tolerable.

None of these "fixes" the deeper issue that financial return correlations
are not i.i.d. — they make the *count* of tests explicit and penalize
accordingly, nothing more.

`src/research/research_family.py` groups every experiment sharing a
`research_family_id` and answers "how many variants of this idea have
already been tried?" directly from the append-only `ExperimentStore` —
never from memory or a hand count.

## Data snooping / overfitting diagnostics

- **Probability of Backtest Overfitting (PBO)** (`overfitting_metrics.py`)
  — via Combinatorially Symmetric Cross-Validation: splits a set of
  candidate parameter variants' per-period returns into every symmetric
  train/test half-split, and measures how often the in-sample winner
  ranks in the bottom half out-of-sample. A high PBO is the signature of
  a parameter sweep that fit noise. Requires ≥ 2 variants sharing the
  same even number of sub-periods (≥ 4) — otherwise reported as
  `NOT_APPLICABLE`.
- **Deflated Sharpe Ratio (DSR)** (Bailey & López de Prado, 2014) —
  answers "given that N variants were searched to find this Sharpe ratio,
  what's the probability the true Sharpe is actually positive?" The more
  trials searched, the more a given raw Sharpe is discounted. Requires
  ≥ 30 return observations and ≥ 2 trials, and reports `NOT_APPLICABLE`
  with a reason when the sample's skew/kurtosis make the formula's
  assumptions inapplicable.
- **Effective number of trials** — highly correlated parameter variants
  (e.g. 20-day vs. 22-day momentum) aren't genuinely independent tests;
  this estimates how many *independent* trials a correlated set is
  actually worth, via average pairwise correlation among their return
  series.

## Purged / embargoed cross-validation

Financial labels built from a forward-looking window (e.g. "return over
the next 5 bars") overlap in time with nearby samples — a naive train/test
split can let a training sample's label window bleed into the test
period, inflating apparent performance. `src/research/purged_cv.py`
implements:

- **Purging**: removing any training sample whose label window overlaps
  the test fold's date range at all.
- **Embargo**: an additional safety margin removed from training
  immediately after a test fold, since serial dependence can persist even
  without direct label overlap.

`tests/test_purged_cv.py` and `scripts/phase7_step5_purged_cv_real_data_demo.py`
both demonstrate this concretely: on this codebase's real 5-year daily
data with a 5-bar horizon, a naive 6-fold split leaked in 5 of 6 folds;
the purged version leaked in zero.

## Defense against p-hacking

Testing "5-day, 10-day, 15-day, 20-day, 25-day, 30-day momentum" and
reporting only the winner as "the" momentum hypothesis is a well-known
failure mode. `src/research/hypothesis_similarity.py` fingerprints every
hypothesis by its mechanism family, feature, target horizon, universe,
and a *bucketed* threshold (so 20-day and 22-day land in the same bucket,
a genuinely different mechanism does not), and flags — never blocks — a
new hypothesis that scores highly similar to one already tested, with the
prior related tests attached to the record.

## Placebo and negative-control tests

Two layers exist, deliberately different null models:

- **Trade-level** (`src/research/placebo.py`, Phase 5-6): randomizes
  entry timing, or entry timing *and* symbol, of realized backtest
  trades.
- **Panel-level** (`src/research/cross_sectional_placebo.py`, Phase 7):
  operates directly on the feature/target panel, before any backtest
  exists — shuffled-signal (randomizes which symbol got which feature
  value, within each timestamp), shifted-signal (deliberately misaligns
  feature and target to test whether the relationship is genuinely tied
  to the correct time offset), random-feature control (a synthetic
  Gaussian "feature" as a null baseline), irrelevant-feature control (a
  real but economically unrelated feature as a reference point), and
  time-shuffled-target (the most destructive null — breaks both temporal
  and cross-sectional structure).

Every placebo reports an `empirical_p_value` — the fraction of placebo
trials that matched or beat the observed result — and every one is
explicit that this is **not a formal significance guarantee**.

## Dependence-aware bootstrap

Trade returns and per-period returns are not i.i.d. — clustered wins
during a trend, for instance. Beyond the plain i.i.d. resample-with-
replacement bootstrap, `src/research/placebo.py` adds a **moving block
bootstrap** (resamples fixed-length contiguous blocks) and a
**stationary bootstrap** (Politis & Romano 1994 — geometrically
distributed random block lengths), both preserving local serial
dependence better than an i.i.d. resample. Both are documented as
approximations, not proofs — real trade dependence may not decay in the
way either method assumes.

## The research scorecard

`src/research/scorecard.py` deliberately does **not** collapse evidence
into one number. Twelve separate dimensions are each given a verdict
(`SUPPORTS` / `NEUTRAL` / `AGAINST` / `NOT_APPLICABLE`): statistical
evidence, economic significance, out-of-sample stability, parameter
stability, regime stability, universe stability, cost robustness,
execution robustness, data quality, multiple-testing penalty, research
contamination risk, and economic rationale.

The classification rule is fixed and documented, not tuned to a
particular answer:

1. If 8+ of 12 dimensions are `NOT_APPLICABLE`, or specifically if
   `economic_significance` itself is `NOT_APPLICABLE` (no backtest has
   run) → **`NOT_READY`**. A hypothesis is never called `PROMISING` on
   discovery-stage IC evidence alone.
2. If `statistical_evidence` or `economic_significance` is clearly
   `AGAINST` → **`REJECTED`**.
3. Otherwise, the fraction of evaluable dimensions that `SUPPORTS` the
   hypothesis determines `PROMISING` (≥ 70%), `INCONCLUSIVE` (≥ 40%), or
   `FRAGILE` (< 40%).

## Why `NOT_READY` exists, and why a high backtest return is insufficient

`NOT_READY` is not a euphemism for "rejected." It means the research
process has not yet reached the stage where a verdict is even meaningful
— e.g. a promising cross-sectional IC with no backtest, or a holdout
result on too small a sample. Phase 6 built this concept concretely for
MR-002: a positive backtest and a `PROMISING` rule-based classification
were *not* enough on their own — MR-002's independent holdout evidence
did not clear pre-registered pass criteria (single-symbol / top-5%-of-
trades concentration), and MR-002 remains `NOT_READY` for paper trading.
A high backtest return, by itself, has never been sufficient evidence
anywhere in this codebase's research process — it must survive out-of-
sample validation, cost stress, execution stress, multiple-testing
correction, placebo/bootstrap controls, and a genuinely untouched holdout
before it can even be *considered* for the next gate stage.

## The research gate

```
IDEA -> PREREGISTERED -> DISCOVERY_TESTED -> DEVELOPMENT_VALIDATED ->
STATISTICALLY_SUPPORTED -> INDEPENDENT_HOLDOUT -> HOLDOUT_VALIDATED ->
PAPER_TRADING_ELIGIBLE -> HUMAN_APPROVAL -> PAPER_TRADING ->
LIVE_ELIGIBLE -> LIVE_TRADING
```

(`src/research/research_gate.py`) No stage may be skipped —
`can_transition` only permits moving to the immediate next stage, or into
the side-state `NOT_READY` (reachable from anywhere, terminal — a fresh
hypothesis version is required to try again). `CODE_COMPUTABLE_STAGES`
caps what any function in this codebase may set programmatically at
`PAPER_TRADING_ELIGIBLE`; `HUMAN_APPROVAL` and everything after it raises
`StageRequiresHumanActionError` if any code attempts to set it — those
stages require a real decision, and eventually the live/paper trading
systems this research layer never touches.

## Interpreting a research result

- A positive backtest return is a starting point, not a conclusion.
- `PROMISING` means the *evidence gathered so far* supports the
  hypothesis across most evaluated dimensions — not that it is proven
  profitable, and not that it is cleared for paper or live trading.
- `NOT_READY` is common and expected, especially for anything evaluated
  only at the discovery (IC) stage — it says the research process hasn't
  reached a point where a verdict is meaningful yet, not that the idea is
  bad.
- Every number in this pipeline (`p`-values, IC, Sharpe, PBO, DSR,
  bootstrap CIs) carries documented assumptions and known limitations.
  Where those assumptions are not met, the codebase reports
  `NOT_APPLICABLE` with the specific reason rather than fabricating a
  number.
