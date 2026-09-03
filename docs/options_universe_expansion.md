# Options Research Universe Expansion & Cross-Sectional Validation (Phase 20)

Phase 19 built the options-alpha discovery foundation on 4 underlyings
(AAPL/NVDA/SPY/TSLA) and one expiration (2022-03-18) — a real but small
and structurally limited panel (DTE had zero cross-sectional variance).
Phase 20 asks the central question: **does the Phase 19 relationship
survive a materially broader and more diverse research universe?**
This phase does not build a trading strategy, place any order, or
declare anything validated — it replicates.

## The real, expanded data foundation

120 real option contracts across **all 12 of Part 1's target
underlyings** (NVDA, TSLA, SPY, QQQ, AAPL, MSFT, AMD, AMZN, META,
GOOGL, NFLX, IWM) and **3 real expirations** (2022-03-18 from Phase 19,
plus 2022-06-17 and 2023-06-16 gathered this phase), all via genuine
`get_option_instruments`/`get_option_historicals` MCP probes:

| Underlying | Expirations | Contracts | Notes |
|---|---|---|---|
| AAPL, NVDA, SPY, TSLA | 2022-03-18, 2022-06-17, 2023-06-16 | 18 each | the only 4 symbols with 3 real expirations |
| QQQ, MSFT, AMD, META, IWM, NFLX | 2022-06-17 | 6 each | |
| AMZN | 2022-06-17 | 6 | queried post its 2022-06-06 20:1 split |
| GOOGL | 2023-06-16 only | 6 | **deliberately** post its 2022-07 20:1 split — 2022-06-17 was skipped for GOOGL specifically to avoid a pre/post-split strike confound (see `src/options/universe.py`'s `phase20_verified_underlying_universe()` docstring) |

9,044 real contract-day observations total, 0 dropped for missing
underlying-close alignment (`scripts/phase20_step1_ingest_expanded_panel.py`).
AMD and NFLX had no prior local equity OHLC data — both were fetched
fresh via a real `get_equity_historicals` call
(`scripts/phase20_step0_ingest_amd_nflx_equity.py`).

**META was queried as "META", never "FB"** — Meta's ticker changed from
FB to META on 2022-06-09, before the 2022-06-17 expiration this phase
used, so no ticker-transition confound applies.

### Real dynamic-discovery evidence (Part 1 / 21)

Beyond the curated 12-symbol list, this phase ran a real, live scanner
query (`mcp__HOOD__create_scan(preset="HIGH_OPTIONS_VOLUME_IV")` +
`run_scan`) — relative options volume > 2x its 30-day average, filtered
to stocks — and got **69 real, live matches**, sorted by implied
volatility, including 6 of the 12 curated symbols (NVDA, TSLA, META,
AMZN, GOOGL, AAPL) alongside many others (DELL, MU, AVGO, PLTR, SNOW,
PANW, CRDO, HPE, and more). This proves the liquidity-driven,
non-hardcoded discovery architecture Part 21 asks to be preserved for
the eventual live scanner is real and exercised — see
`src.options.universe.PHASE20_DYNAMIC_DISCOVERY_EVIDENCE`. The 12-symbol
curated universe remains the one this phase actually built real
historical option data for; the scan is architecture evidence, not a
claim that all 69 names have historical data behind them.

## Architecture added (`src/options/`, additive to Phase 18/19)

- **`research_eligibility.py`** (Part 8) — the requested pipeline:
  `UnderlyingUniverse` → `UnderlyingCandidate` (reused from Phase 19's
  `opportunity_score.py`) → `OptionChainCandidate` → `OptionContractCandidate`
  → `ResearchEligibleContract`, with explicit `InclusionReason`/
  `ExclusionReason` codes (`UNDERLYING_INCLUDED_LIQUIDITY`,
  `UNDERLYING_INCLUDED_DATA_COVERAGE`, `CONTRACT_INCLUDED_PRICE_HISTORY`,
  `CONTRACT_EXCLUDED_INCOMPLETE_HISTORY`, `CONTRACT_EXCLUDED_UNKNOWN_EXISTENCE`,
  `CONTRACT_EXCLUDED_INVALID_DATA`). Also carries Part 4's disclosure:
  `summarize_existence_impact()`.
- **`expiration_diversity.py`** (Part 5) — `has_cross_sectional_variance()`
  makes Phase 19's discovery mechanical: a single-expiration panel has
  none for `dte`, and any caller must report `CROSS_SECTIONAL_IC_UNDEFINED`
  rather than silently substituting a pooled statistic.
- **`moneyness_diversity.py`** (Part 6) — per-bucket contract/observation
  counts, average DTE, sample share, incomplete-history fraction.
- **`data_balance.py`** (Part 7) — generic top-share concentration
  (`compute_concentration`) applied to symbol/sector/expiration/
  moneyness/call-put/year.
- **`return_normalization.py`** (Part 13) — `compute_normalized_return()`:
  raw % return, dollar return per contract, return relative to premium,
  and CAUSAL max-adverse/max-favorable excursion (computed only from the
  bars strictly within the given entry→exit window, proven by
  `tests/test_options_return_normalization.py`'s no-lookahead test).
- **`mechanical_baseline.py`** (Part 11/12) — formalizes Phase 19's
  inline option-vs-underlying IC comparison into a reusable
  `compare_option_vs_underlying_signal()` with an explicit
  `OPTION_ADDS_INFORMATION` / `INHERITED_FROM_UNDERLYING` /
  `BOTH_WEAK_OR_UNDEFINED` classification.
- **`universe.py`** (extended, additive) — `phase20_verified_underlying_universe()`
  (12 symbols) and `DynamicDiscoveryEvidence`/`PHASE20_DYNAMIC_DISCOVERY_EVIDENCE`.

## Replication results (`P19-OPT-XXX-EXPANDED`, family=`options_alpha_replication`)

Every Phase 19 `DISCOVERY_SUPPORTED` hypothesis (004, 005, 008, 009, 012)
was re-registered as a frozen-parent replication run
(`scripts/phase20_step3_preregister_replication.py`) and re-tested on
the expanded panel (`scripts/phase20_step4_replication_campaign.py`).
**No original P19-OPT-* definition was edited.** Final vocabulary is
`EXPANDED_DISCOVERY_SUPPORTED` / `EXPANDED_WEAKENED` /
`EXPANDED_REJECTED` / `EXPANDED_INCONCLUSIVE` — **never** "VALIDATED"
(Part 23).

| Hypothesis | Original (Phase 19) | Expanded (Phase 20) | Verdict |
|---|---|---|---|
| P19-OPT-004 (deep-OTM tail risk) | deep_otm σ=0.515 vs ITM/ATM σ=0.397 | deep_otm σ=5.12 vs ITM/ATM σ=44.91 (ITM/ATM now the WIDER tail — see outlier caveat below) | **EXPANDED_WEAKENED** |
| P19-OPT-005 (call/put asymmetry) | gap=−0.272, Welch p≈0 | gap=+2.779, Welch p=0.006 (sign reversed) | EXPANDED_DISCOVERY_SUPPORTED* |
| P19-OPT-008 (per-underlying stability) | 4/4 underlyings agreed in sign | 8/12 underlyings agreed in sign | **EXPANDED_WEAKENED** |
| P19-OPT-009 (horizon stability) | same sign at all 5 horizons | same sign at all 5 horizons | EXPANDED_DISCOVERY_SUPPORTED |
| P19-OPT-012 (DTE-bucket decay) | most-negative bucket = 0-7 DTE | most-negative bucket = 31-60 DTE | **EXPANDED_WEAKENED** |

**2 of 5 replication runs classified `EXPANDED_DISCOVERY_SUPPORTED`; 3 weakened.**
Multiple-testing correction on the Phase 20 replication family's 6 raw
p-values (kept SEPARATE from Phase 19's family, Part 19): only 1/6
survives Bonferroni/Holm/BH at α=0.05 — the primary pooled IC test, not
either mean-based test. The primary pooled cross-sectional
IC(`log_moneyness`, `forward_return_5`) is **0.0178** (vs Phase 19's
0.0552 on the smaller panel) — smaller in magnitude, still same sign.

### A genuine, important limitation surfaced by this expansion (not a bug)

Several mean-based statistics above (P19-OPT-004's stdevs, P19-OPT-005's
call/put means, P19-OPT-012's bucket means) show extreme values (e.g. a
mean forward return of +450%) driven by a small number of REAL, GENUINE
contract-day rows where an option's price moved from a near-zero base
(e.g. $0.01) to a much larger one within days — confirmed real,
volatile price action (Phase 18/19's own finding), not a computational
error. Rank-based statistics (Spearman IC, used for the primary
finding and P19-OPT-008/009) are robust to this; **raw-mean-based
statistics are not**, and the marked `EXPANDED_DISCOVERY_SUPPORTED`
verdict on P19-OPT-005 above should be read with that caveat — it is
the classification the pre-registered rule produces, not a claim that
the underlying evidence is robust to outliers. `return_normalization.py`
exists as the documented path (dollar return per contract, MAE/MFE) a
future phase should prefer for headline claims instead of raw
percentage means.

### Mechanical baseline (Part 11/12)

`log_moneyness`'s option-target IC (0.0178) vs its underlying-equity-
target IC (−0.0346): gap = −0.0167 → **`INHERITED_FROM_UNDERLYING`** —
same classification as Phase 19's smaller panel. The apparent
moneyness/forward-return relationship in the option data is not shown
to add information beyond what the underlying equity's own forward
return already carries, on this evidence.

### Time / regime stability (Part 17)

Per-year pooled IC: 2021 = −0.034, 2022 = +0.071, 2023 = −0.049 — **the
sign flips across years**, an honest instability finding, not averaged
away. Regime-bucketed mean forward returns are also dominated by the
same outlier effect described above and should be read with the same
caveat.

### Cost sensitivity (Part 20, `ASSUMPTION`-labeled only)

The diagnostic deep-OTM − ITM mean-return gap is net-negative under
all three preregistered 1x/2x/3x cost assumptions on the expanded
panel — unlike Phase 19's smaller panel, where the 1x assumption alone
survived. All figures remain `MARK_TO_MARKET_HISTORICAL_RESEARCH`; no
`EXECUTION_REALISTIC_RESEARCH` is claimed or possible (no historical
bid/ask exists for any date probed).

## Data balance / concentration (Part 7)

- Symbol: top = AAPL at **14.9%** of 9,044 observations — no single
  symbol dominates (Part 7's 80%-NVDA example does not apply here).
- Sector: top = technology at **44.9%** (5 of 12 curated underlyings —
  AAPL/NVDA/MSFT/AMD/GOOGL — are classified "technology").
- Expiration: top = 2022-06-17 at **55.5%** (11 of 12 underlyings used
  it; only the original 4 also have 2022-03-18/2023-06-16).
- Moneyness: top = deep_otm/deep_itm tied at **28.0%** each — not
  concentrated (no bucket exceeds 50%).
- Call/put: exactly 50.0%/50.0% (by construction — every strike was
  queried as a call+put pair).
- Year: top = 2022 at **69.3%** (most expirations fall in 2022).

None of these concentrations are extreme enough to call the panel
"broadly diversified" without qualification — see the table above for
exact figures before citing this research elsewhere.

## Contract-existence disclosure (Part 4)

**100% of the panel's 9,044 rows carry `existence_state=UNKNOWN_EXISTENCE`**
(reaffirming Phase 18/19: this data source never supplies a first-listed
date for any contract). Every result in this document is materially
affected by uncertain contract existence by
`research_eligibility.ExistenceImpactSummary`'s own >50% threshold, and
is reported with that in mind — no claim here is presented as
point-in-time-clean.

## Limitations (explicit, not hidden)

1. **Expiration coverage is uneven.** Only AAPL/NVDA/SPY/TSLA have 3
   real expirations; the other 8 underlyings have exactly 1 each (7 at
   2022-06-17, GOOGL at 2023-06-16). Per-underlying `dte`
   cross-sectional variance is still `False` (UNDEFINED) for those 8
   symbols alone — only the POOLED panel (all 12 underlyings across all
   3 expirations) restores real cross-sectional DTE variance.
2. **Outlier sensitivity of raw percentage returns** (see above) — a
   real, disclosed data characteristic requiring care in any future
   phase, not resolved here.
3. **Still small in absolute terms.** 120 contracts, 3 expirations —
   materially broader than Phase 19's 24/1, but still far from an
   exhaustive options research dataset.
4. **No `EXECUTION_REALISTIC_RESEARCH` is possible.** Historical
   bid/ask/volume/open-interest/IV/Greeks remain confirmed unavailable
   for every date this phase (or Phase 18/19) probed.
5. **No hypothesis is validated.** `EXPANDED_DISCOVERY_SUPPORTED` is a
   replication-stage research classification, never a trading
   recommendation, and 3 of the 5 replicated findings weakened on the
   larger universe — the correct, honest reading of this expansion is
   that Phase 19's findings were mostly fragile, not confirmed.
