# Options-Specific Alpha Source Discovery (Phase 22)

Phase 21 falsified the two Phase 20 survivors: both `P19-OPT-009-EXPANDED`
and `P19-OPT-005-EXPANDED` turned out to be `INHERITED_FROM_UNDERLYING`.
Phase 22 asks a sharper question than either prior discovery family did:
**not** "does this feature correlate with the option's return," but
"does this feature tell us anything about the option that we couldn't
already get from predicting the underlying alone?" 13 new,
independently-motivated hypotheses were preregistered under a brand-new
family (`options_specific_alpha`, every member's `parent_hypothesis_id`
is `None`) and run through the same adversarial battery Phase 21
established, plus a mandatory underlying-control test for every single
one (not just the strongest survivors).

## Result, up front

**12 of 13 hypotheses: `INHERITED_FROM_UNDERLYING`.** One survived:
**`P22-OPT-013`** (the option's own recent range expansion predicts a
larger favorable excursion over the next 5 bars) is classified
**`DISCOVERY_SUPPORTED`** — worth deeper investigation, explicitly **not**
profitable, validated, or ready for trading. Its underlying-control
verdict is **`TRUE_OPTION_SPECIFIC_INFORMATION`**: an incremental R² of
0.234 (feature_p < 1e-15) from adding the feature on top of the
underlying's own forward return, versus a near-zero/negative Model A IC
(-0.023) — the strongest, cleanest separation between "this is genuinely
about the option" and "this is just underlying exposure" seen across
Phase 19-22.

## No new data gathered this phase

Every column here is a **causal derived feature computed from OHLC
already gathered** in Phase 19/20 (`logs/research_data/
phase20_research_panel.jsonl`, 9,044 rows / 120 contracts / 12
underlyings / 3 real expirations) — Part 21/23's instruction that Phase
22 must not fetch new MCP data and must never fabricate a historical
field neither gathered nor derivable from what was gathered.
`scripts/phase22_step1_build_feature_panel.py` builds
`logs/research_data/phase22_research_panel.jsonl` (same row count,
9,044) by adding ~25 new columns per row.

## New architecture (`src/options/`, additive to Phase 18-21)

- **`price_volatility_proxy.py`** (Part 7) — REALIZED_OPTION_PRICE_
  VOLATILITY_PROXY, never IV: close-to-close volatility, mean-abs-return,
  Parkinson volatility, a true-range proxy, a volatility-expansion ratio,
  and a range-expansion ratio. Deliberately framework-agnostic (plain
  float lists), so the SAME estimator computes both the option's own
  volatility (Theme C) and its underlying's (Theme B) — one
  implementation, not two parallel ones.
- **`momentum_features.py`** (Theme C) — the option contract's OWN price
  behavior: trailing momentum (a thin wrapper reusing the module above),
  return acceleration, gap, trend persistence, range expansion.
- **`relative_return.py`** (Theme A/D) — `OPTION_UNDERLYING_RELATIVE_
  RETURN`: `rolling_beta` (a purely empirical, realized OLS slope of a
  contract's own daily returns on its underlying's — explicitly
  documented as **NOT delta**: no options pricing model, no current
  Greeks, nothing risk-neutral, just "how has this contract actually
  moved alongside its underlying recently"), plus naive and beta-scaled
  excess-return functions used as BOTH features (backward) and targets
  (forward).
- **`cost_model.py`** (additive) — `FIVE_X_ASSUMPTION`, promoted from a
  script-local constant (Phase 21) to a shared, importable constant so
  both phases' 1x/2x/3x/5x cost ladders reference the identical
  assumption.

## The 13 preregistered hypotheses

| ID | Theme | Feature | Target | Direction |
|---|---|---|---|---|
| P22-OPT-001 | A | naive excess momentum (option − underlying, trailing 5d) | naive excess return (forward 5d) | positive |
| P22-OPT-002 | A | beta-scaled excess momentum (trailing 5d) | beta-scaled excess return (forward 5d) | positive |
| P22-OPT-003 | B | underlying vol expansion ratio (5d/20d) | forward_return_5 (signed) | unsigned |
| P22-OPT-004 | B | underlying vol expansion ratio | abs_forward_return_5 (magnitude) | positive |
| P22-OPT-005 | B | underlying squared daily return | forward_return_5 | unsigned |
| P22-OPT-006 | C | option's own trailing 5d momentum | forward_return_5 | positive |
| P22-OPT-007 | C | option's own trailing 10d momentum | forward_return_5 | negative (reversal) |
| P22-OPT-008 | C | option's own vol expansion ratio (5d/20d) | forward_return_5 | unsigned |
| P22-OPT-009 | D | option/underlying trailing-return RATIO (5d) | forward_return_5 | unsigned |
| P22-OPT-010 | E | vol-expansion × log-moneyness interaction | forward_return_5 | unsigned |
| P22-OPT-011 | F | squared-move × DTE interaction | forward_return_5 | unsigned |
| P22-OPT-012 | G | underlying realized-vol LEVEL (not ratio) | forward_return_5 | unsigned |
| P22-OPT-013 | C | option's own range-expansion ratio (5d) | mfe_5 (max favorable excursion, forward 5d) | positive |

Theme E deliberately does **not** revive Phase 21's rejected raw
log-moneyness (`P19-OPT-009`) — `tests/test_phase22_safety.py` asserts
no hypothesis uses `("log_moneyness",)` alone as its feature set.
Every hypothesis has `parent_hypothesis_id=None` and an immutable,
deterministic SHA256 experiment fingerprint computed at preregistration
time (`scripts/phase22_step2_preregister_hypotheses.py`), before any
result existed.

## Per-hypothesis results (pooled IC, primary metric for every hypothesis)

| ID | Pooled IC | p | Outlier-dependent | Underlying control | Placebo-separated | Cost-fragile | Scorecard | Classification |
|---|---|---|---|---|---|---|---|---|
| P22-OPT-001 | 0.029 | 0.450 | No | INHERITED | No | Yes | 3/7 | INHERITED_FROM_UNDERLYING |
| P22-OPT-002 | 0.059 | 0.043 | No | INHERITED | No | Yes | 3/7 | INHERITED_FROM_UNDERLYING |
| P22-OPT-003 | -0.008 | 0.314 | No | INHERITED | No | Yes | 2/7 | INHERITED_FROM_UNDERLYING |
| P22-OPT-004 | 0.018 | 0.450 | No | INHERITED | No | Yes | 2/7 | INHERITED_FROM_UNDERLYING |
| P22-OPT-005 | -0.001 | 0.945 | **Yes** | INHERITED | No | Yes | 1/7 | INHERITED_FROM_UNDERLYING |
| P22-OPT-006 | 0.029 | 0.441 | No | INHERITED | No | Yes | 3/7 | INHERITED_FROM_UNDERLYING |
| P22-OPT-007 | 0.114 | 0.006 | No | INHERITED | No | No | 5/7 | INHERITED_FROM_UNDERLYING |
| P22-OPT-008 | 0.055 | 0.060 | No | INHERITED | **Yes** | Yes | 4/7 | INHERITED_FROM_UNDERLYING |
| P22-OPT-009 | -0.007 | 0.868 | No | INHERITED | No | Yes | 3/7 | INHERITED_FROM_UNDERLYING |
| P22-OPT-010 | 0.016 | 0.142 | No | INHERITED | No | Yes | 3/7 | INHERITED_FROM_UNDERLYING |
| P22-OPT-011 | 0.005 | 0.557 | No | INHERITED | No | Yes | 3/7 | INHERITED_FROM_UNDERLYING |
| P22-OPT-012 | 0.005 | 0.510 | No | INHERITED | No | Yes | 2/7 | INHERITED_FROM_UNDERLYING |
| **P22-OPT-013** | **0.099** | **<0.001** | No | **TRUE_OPTION_SPECIFIC_INFORMATION** | **Yes** | **No** | **7/7** | **DISCOVERY_SUPPORTED** |

(The table above is from the corrected, final run — see "A self-caught
bug" below for why a first run briefly showed P22-OPT-013 as `UNCERTAIN`
instead of `TRUE_OPTION_SPECIFIC_INFORMATION`.)

## P22-OPT-013 in depth (the one survivor)

**Hypothesis**: today's option range — (high−low)/close — relative to
its own trailing 5-day baseline, predicts the option's own maximum
favorable excursion (MFE) over the next 5 bars.

- **Pooled IC = 0.099, p < 0.00001**, n = 7,070 eligible rows.
- **Temporal**: positive in 2021 (0.212) and 2022 (0.153), slightly
  negative in 2023 (-0.023) — sign_consistency = 0.67 across years, but
  strongly regime-dependent: bear/high-vol (0.144) and bear/low-vol
  (0.090) regimes carry the relationship; bull/high-vol is flat (-0.004).
- **Symbol**: positive in 10/10 symbols with a usable per-symbol IC
  (AMZN/META had too few eligible rows for a stable per-symbol estimate)
  — QQQ (0.216), AMD (0.197), GOOGL (0.175), IWM (0.152) strongest;
  AAPL (0.038) weakest but still positive. `positive_symbol_fraction =
  1.00`.
- **Expiration**: positive at both 2022 expirations (0.188, 0.139),
  slightly negative at 2023-06-16 (-0.023) — the effect is concentrated
  in 2022, a real limitation.
- **Moneyness**: positive and reasonably consistent across all 5
  buckets (0.098-0.172), `sign_consistency(buckets) = 1.00` — unlike
  every other Phase 19-22 candidate tested, this one does NOT flip sign
  by moneyness bucket.
- **Call/put**: survives in both, nearly identical magnitude (calls
  0.132, puts 0.128) — not a call/put-driven artifact.
- **Outlier (mandatory)**: `mfe_5`'s own outlier concentration is much
  milder than raw `forward_return_N` (top-1% share of the pooled sum is
  0.32, vs. ~0.97 for every raw-return target elsewhere in this
  project) — a real, structural property of a maximum-excursion target
  (it is bounded below by construction, unlike a raw return). Removing
  the top 1% positive/negative or winsorizing at 1%/2.5%/5% leaves the
  IC essentially unchanged (0.096-0.100 throughout). **Not**
  `OUTLIER_DEPENDENT`.
- **Underlying control (Part 9, the decisive test)**: Model A (feature →
  `underlying_forward_return_5`) IC = **-0.023** — the feature tells you
  almost nothing about the underlying's own future direction. Model B
  (feature → `mfe_5`) IC = **0.099** — over 4x larger in magnitude and
  opposite in sign tendency. Model C (`mfe_5 ~ underlying_return +
  feature`, OLS): incremental R² from adding the feature = **0.234**,
  `feature_p < 1e-15`. **Verdict: `TRUE_OPTION_SPECIFIC_INFORMATION`** —
  this is the first hypothesis across Phase 19/20/21/22 to clear this
  bar. Economically this makes sense: an option's own recent range
  behavior is a statement about *that contract's* liquidity/trading
  dynamics, not a restatement of "the stock is moving."
- **Mechanical leverage**: `HISTORICAL_GREEKS_UNAVAILABLE`, same as
  every hypothesis this phase — no delta-adjusted analysis is possible
  or attempted.
- **Placebo (7 types, IC-based)**: clears all 5 distribution-based
  placebos decisively (p = 0.0 for shuffle, time-shuffle, symbol-shuffle,
  randomized-target, block-shuffle). `placebo_clearly_distinguishable =
  True` — the only hypothesis this phase to achieve this.
- **Temporal shift**: shift +1/+2/+5 all produce a *negative* IC (the
  opposite sign of the true +0.099) — the true alignment is
  meaningfully different from a deliberately-misaligned one, unlike
  several other Phase 19-22 candidates whose shifted IC matched or
  exceeded the true one.
- **Dependence-aware bootstrap**: symbol-cluster (11 symbols — AMZN/META
  excluded for insufficient per-symbol sample — 500 resamples) 90% CI
  [0.068, 0.124], 95% CI [0.064, 0.130] — **does not cross zero** at
  either level, the first Phase 19-22 candidate for which this is true.
- **Cost sensitivity**: survives the 1x ASSUMPTION (net = +0.018) but
  fails 2x/3x/5x. **`COST_FRAGILE = False`** only because it clears the
  gentlest tier — a real, disclosed fragility, not glossed over.
- **Economic significance**: mean premium $34.03/share ($3,403/contract)
  — 0 contracts affordable on a $1,000 account before any
  position-sizing discipline, same feasibility constraint as every
  hypothesis this phase (this is a feasibility note, not a target).
- **Multiple testing**: one of 117 raw p-values collected across the
  whole family; survives Bonferroni/Holm/BH correction (see below).
- **PBO/DSR**: PBO = 0.70 (high — the in-sample-best of 4 tested
  variant features has a substantial chance of underperforming
  out-of-period; disclosed honestly, not hidden because the headline
  result looks strong), DSR = 0.999 (observed Sharpe-like 4.98 deflated
  for 4 trials, n=192).

**Honest limitation**: PBO = 0.70 and the effect's concentration in 2022
(and in bear-regime periods) mean `DISCOVERY_SUPPORTED` here means
exactly what Part 24 says it means — worth a dedicated follow-up, not a
settled result. The 2x+ cost fragility and the temporal
concentration are real, disclosed weaknesses sitting alongside its
otherwise-unusually-clean scorecard.

## A self-caught bug

The first campaign run computed Model C's significance gate as
`(feature_p or 1.0) < 0.05`. For P22-OPT-013, the OLS regression's
actual `feature_p` was exactly `0.0` (a legitimately extreme
significance, verified independently: `n=7,070`, incremental
R²=0.234) — and in Python, `0.0 or 1.0` evaluates to `1.0`, since `0.0`
is falsy. This silently substituted `1.0` for a real `0.0`, failing the
`< 0.05` gate and misclassifying the verdict as `UNCERTAIN` instead of
`TRUE_OPTION_SPECIFIC_INFORMATION` on the first run. A parallel latent
instance of the same bug (`(pos_frac or 1) <= 0.45`, which would
similarly mishandle a legitimate `pos_frac == 0.0`) was also found and
fixed, though it did not happen to change any hypothesis's result this
run (no hypothesis had `pos_frac` exactly `0.0`). Caught by directly
reproducing the OLS computation independently and comparing to the
printed value, before writing this document — not shipped and
rationalized. Both fixes are in
`scripts/phase22_step3_discovery_campaign.py`; the campaign was rerun
in full afterward, and every number in this document is from that
corrected run.

## Multiple testing (whole family)

117 raw p-values collected across all 13 hypotheses (pooled effect +
yearly breakdown + 5 distribution-based placebo tests each):

| Method | Significant (α=0.05) |
|---|---|
| Bonferroni (FWER) | 18 / 117 |
| Holm-Bonferroni (step-down FWER) | 18 / 117 |
| Benjamini-Hochberg (FDR) | 22 / 117 |

Reported in full, favorable and unfavorable results alike, per Part 16's
explicit instruction not to selectively report only successful
hypotheses.

## What this phase explicitly did not do

No live or paper strategy, no connection from this research to
`src/execution/`, no order placed, no `VALIDATION_DATA`/
`FINAL_HOLDOUT_DATA` access, no fabricated historical IV/Greeks/
volume/OI/bid-ask, no reconstructed-and-presented-as-observed Greek
(`rolling_beta` is explicitly documented as NOT delta), no hypothesis
modified after seeing its result, no post-hoc hypothesis silently
counted as preregistered. `tests/test_phase22_safety.py` (19 tests) and
`tests/test_phase22_metric_compatibility.py` (6 tests, proving every
hypothesis's placebo statistic is mathematically identical in form to
its primary statistic — the exact Phase 21 mistake, structurally
prevented this phase) verify this mechanically.

## Honest summary

13 economically-motivated, preregistered hypotheses, spanning all 7
requested research themes, were tested against the SAME adversarial
battery Phase 21 established — including, for the first time, a
mandatory underlying-control test applied to every single hypothesis
rather than just the strongest survivors. 12 failed that test. One —
option range expansion predicting favorable excursion — passed it
cleanly, survived every placebo, had a bootstrap CI that does not cross
zero, and showed the strongest underlying-vs-option separation seen in
this project so far, while still carrying real, disclosed weaknesses
(temporal concentration, 2x+ cost fragility, PBO=0.70). It is
`DISCOVERY_SUPPORTED` — worth a dedicated follow-up phase — not
validated, not profitable, not ready for trading. Twelve honest
negative results and one genuinely promising lead is a credible
research outcome, not a disappointing one.
