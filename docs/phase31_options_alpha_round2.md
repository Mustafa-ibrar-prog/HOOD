# Phase 31 — Options Alpha Discovery Round 2 (`options_alpha_round2`)

## 1. Commit hash

See `git log -1` on branch `claude/inspect-repo-mcp-tools-s5ic0p` immediately following this report's addition. (Infrastructure landed in `237eadd`, the contract-selection fix in `f73f529`, this report and real results in the commit that follows.)

## 2. Total tests / 3. New tests / 4. Baseline failures

- **110 new tests** across 10 new `src/options/phase31_*.py` modules and 10 new test files (`test_phase31_panel_builder.py`, `test_phase31_hypotheses.py`, `test_phase31_underlying_control.py`, `test_phase31_evidence.py`, `test_phase31_affordability_liquidity.py`, `test_phase31_robustness.py`, `test_phase31_classification_and_gate.py`, `test_phase31_campaign.py`, `test_phase31_safety.py`, plus 4 added to `test_phase31_panel_builder.py` for the richness-selector fix).
- **Full suite: 2,481 passed, 4 failed** — the same 4 pre-existing `test_orchestrator.py` failures present since before Phase 30 began. No new failures.

## 5. Number of preregistered hypotheses

**16**, family `options_alpha_round2`, registered via `src.research.hypothesis.HypothesisRegistry` and `src.research.preregistration.PreregistrationStore` (`logs/research_data/phase31_hypotheses.jsonl` / `phase31_preregistration.jsonl`) **before** any evaluation touched real data — enforced structurally via `require_preregistered()` inside `run_campaign()`.

## 6. Hypothesis list

| ID | Name | Feature | Target | Primary horizon | Direction |
|---|---|---|---|---|---|
| P31-OPT-001 | Option Momentum | `option_momentum` | `forward_option_return_5` | 5d | positive |
| P31-OPT-002 | Option Mean Reversion | `option_mean_reversion` | `forward_option_return_5` | 5d | negative |
| P31-OPT-003 | Range Expansion | `option_range_expansion` | `mfe_5` | 5d | positive |
| P31-OPT-004 | Range Compression | `option_recent_range_pct` | `abs_forward_option_return_5` | 5d | negative |
| P31-OPT-005 | Relative Option Strength | `relative_option_strength` | `forward_option_return_5` | 5d | positive |
| P31-OPT-006 | Maturity Effects | `dte` | `forward_option_return_5_residualized` | 5d | unsigned |
| P31-OPT-007 | Moneyness Effects | `log_moneyness` | `forward_option_return_5_residualized` | 5d | unsigned |
| P31-OPT-008 | Call/Put Asymmetry | `call_put_numeric` | `forward_option_return_5_residualized` | 5d | unsigned |
| P31-OPT-009 | Option/Underlying Divergence | `option_underlying_divergence` | `forward_option_return_1` | 1d | negative |
| P31-OPT-010 | Convexity Response | `convexity_proxy` | `forward_option_return_5_residualized` | 5d | positive |
| P31-OPT-011 | Contract Relative Value | `relative_price_rank` | `forward_option_return_5` | 5d | negative |
| P31-OPT-012 | Liquidity/Price Interaction | `spread_pct` | `forward_option_return_5` | 5d | negative |
| P31-OPT-013 | DTE x Moneyness Interaction | `moneyness_x_dte_interaction` | `forward_option_return_5_residualized` | 5d | unsigned |
| P31-OPT-014 | Expiration Proximity | `inverse_dte` | `abs_forward_option_return_5` | 5d | positive |
| P31-OPT-015 | Option Volatility Persistence | `option_rolling_vol` | `forward_realized_vol_5` | 5d | positive |
| P31-OPT-016 | Option Shock Reversal | `option_daily_return` | `forward_option_return_1` | 1d | negative |

Full definitions (economic intuition, mechanism, falsification criteria) in `src/options/phase31_hypotheses.py`.

## 7. Data used / 8. Observations / 9. Underlyings / 10. Contracts / 11. Date coverage

- **Source**: `FREE_REFERENCE_DATASET` (Phase 26/27's certified QuantConnect/Lean sample) — no paid provider, no ORATS.
- **Underlyings with real daily-resolution options data**: AAPL, FOXA, GOOG, NWSA, TWX (5 of the dataset's 6 real underlyings — SPY's only real coverage is a single day of minute bars, contributing 0 daily rows, documented not hidden).
- **Contracts used**: 6,082 real contracts selected via `select_contracts_by_daily_richness` at `max_contracts_per_underlying=6000` — a cap that exceeds every real underlying's total contract count (AAPL's 4,532 is the largest), so **every** real contract with at least one real daily observation was used; nothing was excluded by the cap.
- **Panel rows**: **13,800** real (contract, date) daily observations.
- **Date coverage**: real trading dates within each underlying's actual Lean-sample window (AAPL/FOXA/NWSA/TWX 2013–2016, GOOG through late 2015) — inherited unchanged from Phase 26/27's certified coverage, not expanded this phase.

## 12. Primary results

**Zero hypotheses reached `DISCOVERY_SUPPORTED` or `PROMISING`.** 14 classified `INCONCLUSIVE`, 2 (`P31-OPT-005`, `P31-OPT-008`) classified `NOT_READY`. Every hypothesis's pooled cross-sectional IC was **undefined** (not merely weak) — `average_ic = None` for all 16.

**Root cause, verified directly (not assumed):** this free dataset's real per-contract observation density is compounding-sparse. A row needs BOTH (a) enough of that SAME contract's own prior history for a lookback feature (e.g. momentum needs 5+ prior real days) or its own `t-1` for a 1-day-lag feature, AND (b) enough of that contract's own FUTURE real history for the forward target (1 or 5 more real days) — simultaneously. Given the free dataset's contracts have a median of ~2 real daily observations each (heavily right-skewed — a handful of contracts have 100+ real days, most have 1-3), very few individual rows satisfy both requirements at once, and even fewer do so in groups of 3+ economically-comparable peers (same underlying + expiration + real date) on the same day. A direct diagnostic confirmed the underlying peer-group structure is real and populated (14 real peer groups of size ≥3 exist for a simple always-defined feature like `call_put_numeric` against a 1-day forward target — the wiring works), but none of the 16 preregistered feature/target combinations, each of which requires its OWN history AND a forward target simultaneously, ever reached 3 valid peer members on a shared date. This is a genuine, structural finding about this specific free archive's contract-level density, not a code defect (a real bug — evenly-strided-by-ID contract sampling drawing mostly single-day/minute-only IDs — WAS found and fixed this phase; see §24).

## 13. Multiple-testing results

Bonferroni: 0/16 significant. Holm: 0/16 significant. Benjamini-Hochberg: 0/16 significant. (All 16 raw p-values defaulted to 1.0 where IC was undefined, per the campaign's honest "never treat undefined as maximally significant" convention.)

## 14. Underlying-control results

The Model A (`target ~ underlying_return`) vs Model B (`target ~ underlying_return + option_feature`) OLS regression — which uses ALL rows with the two required columns present, not scoped to same-day peer groups — DID run for most hypotheses (e.g. P31-OPT-001: ΔR²≈0.0017; P31-OPT-006: ΔR²≈0.0616), but the cross-sectional IC-gap half of the comparison (`src.options.mechanical_baseline.compare_option_vs_underlying_signal`, itself economically-scoped) came back undefined for the same reason as §12, so every hypothesis's underlying-control classification landed at `BOTH_WEAK_OR_UNDEFINED` — never `OPTION_ADDS_INFORMATION`, never `INHERITED_FROM_UNDERLYING`. No conclusion could be drawn either way.

## 15. Placebo results

The full 7-method placebo battery (shuffled-signal, random-feature, time-shuffled-target, within-symbol-time-shuffle, symbol-identity-shuffle, block-preserving-shuffle, sign-flip diagnostic) ran for every hypothesis at `n_trials=25`, but with no real observed statistic to compare against (IC undefined), every placebo comparison is likewise undefined — `placebo_separates()` correctly returned `False` everywhere, contributing to the Promising Finding Gate's `placebo_separation` failure on all 16.

## 16. Bootstrap results

Symbol-cluster bootstrap (`n_resamples=100`) produced `[None, None]` confidence intervals for all 16 — no point estimate exists to bootstrap around when the underlying IC is undefined.

## 17. Temporal-alignment results

Shifts of +1/+2/+5/+10 real observations were tested for all 16; every `true_ic`/`shifted_ic` pair is `None`, so `TEMPORAL_ALIGNMENT_CONCERN` never fired (correctly — there is nothing to compare).

## 18. Robustness results

Year/underlying/expiration/moneyness-bucket/call-put stratification and leave-one-underlying-out all ran, but every stratum's own IC was likewise undefined (each real stratum is even sparser than the pooled panel), so `fragile=False` by default (no sign flip is detectable when every value is `None`) — this must be read as "untestable," not "robust."

## 19. Affordability results

Averaged across the real panel's priced rows: **average premium ≈ $5,352/contract**, only **46.0%** of observed contract-days were affordable within a $1,000 account. This is a real, disclosed `ACCOUNT_INFEASIBLE_EXPENSIVE_CONTRACTS`-leaning result for a large share of this dataset's real contracts — separate from (and not a reason to discount) the statistical-validity finding above, per Part 8's explicit instruction.

## 20. Execution-cost results

**65.3%** of rows had a real two-sided quote (`pct_quote_available`); **average spread ≈ 15.8%** of mid — wide, consistent with real, often-illiquid contract-days in this dataset. Cost-sensitivity (1x/2x/3x) could not be evaluated for any hypothesis (`survives=None` throughout) since no gross economic effect (quantile spread) existed to net costs against.

## 21. Classification for every hypothesis

All 16: see the table in §12's discussion — 14 `INCONCLUSIVE` (P31-OPT-001,002,003,004,006,007,009,010,011,012,013,014,015,016), 2 `NOT_READY` (P31-OPT-005, P31-OPT-008 — neither cross-sectional nor time-series evidence could even be computed for these two). Zero `DISCOVERY_SUPPORTED`, `PROMISING`, `FRAGILE`, `REJECTED`, or `INHERITED_FROM_UNDERLYING`.

## 22. Strongest candidates

**None.** No hypothesis passed the Promising Finding Gate (0/12 criteria cleared for every hypothesis beyond `preregistered`/`causal`/`no_unresolved_major_leakage`, which are structural guarantees, not data-dependent). Per Part 15: *"If nothing qualifies, THAT IS A VALID RESULT. Do not manufacture a winner."*

## 23. Reasons candidates failed

Every hypothesis failed at the same root cause: **insufficient real per-contract observation density** in the free dataset to simultaneously satisfy (a) a causal lookback/lag requirement on the feature side and (b) a causal forward-target requirement, for enough economically-comparable peers on a shared real date. This is not a fixable parameter-tuning problem within this dataset — it is a structural characteristic of how sparse most individual contracts' real observation histories are (median ≈2 real daily dates/contract), even after correcting a real contract-selection sampling bug this phase found (§24) that had made the problem look even worse than it structurally is.

## 24. Dataset limitations

All limitations from `src.options.free_dataset_limitations.FREE_DATASET_LIMITATIONS` (Phase 30) apply unchanged, plus one NEW finding from this phase:

- **NEW — per-contract density limitation**: even where an underlying/date has real daily coverage, most INDIVIDUAL contracts within this free archive have very few real observed daily dates (median ≈2), sharply limiting any test that needs a contract's own lookback history and forward-looking target simultaneously. This compounds the already-documented `RESOLUTION_LIMITATIONS`/`COVERAGE_CONCENTRATION` findings and should be added to a future update of the limitations registry.
- A real methodological bug was found and fixed THIS phase: `select_contracts()`'s evenly-strided-by-ID sampling drew mostly single-day/minute-only AAPL contract IDs (since AAPL's real contract-ID space is numerically dominated by short one-off probe files), producing only 701 usable daily rows in the first real run. `select_contracts_by_daily_richness()` (ranking by real observed-date count, never by any feature/target value) fixed this, growing the panel to 13,800 rows — real progress, even though the deeper density limitation above remained.

## 25. Exact recommendation for Phase 32

**Do not continue searching THIS free dataset for options-specific cross-sectional alpha at the individual-contract-day grain.** The infrastructure built this phase (panel builder, underlying-control, evidence, robustness, classification, gate — all in `src/options/phase31_*.py`) is real, tested, and reusable, but the free dataset's per-contract density is the binding constraint, not the statistical methodology. Two honest paths forward for Phase 32:

1. **Coarsen the unit of analysis** — instead of per-exact-contract per-exact-date rows, aggregate to (underlying, moneyness-bucket, DTE-bucket, date) buckets averaged across nearby strikes, trading some contract-level precision for far more usable peer-group density. This is a genuinely different (and defensible) design, not a re-run of the same test with looser thresholds.
2. **Accept the null result and redirect research effort** toward the ALREADY-available, richer Phase 22/23 legacy panel (`P22-OPT-013`'s `TRUE_OPTION_SPECIFIC_INFORMATION` finding, later found `TRADEABLE_SIGNAL_FRAGILE`) — investigating whether ITS mechanism (range-expansion → MFE) replicates on the free dataset once a coarser unit of analysis (option 1) is available, rather than starting a third fresh hypothesis family.

Either way: **do not purchase ORATS or any paid provider to solve this** — the binding constraint is CONTRACT-LEVEL granularity within a real, free, already-obtained archive, not overall data volume, and a coarser unit of analysis is a legitimate, no-cost next step.

---

*No live order was placed. No paper order was placed. No trading strategy was created. No paid data was purchased. `SystemState` and OPTIONS_ONLY remain exactly as Phase 28 left them. See `tests/test_phase31_safety.py`.*
