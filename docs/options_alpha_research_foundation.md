# Options Alpha Discovery Foundation (Phase 19)

Phase 18 built the options data/instrument architecture and certified the
real historical-options-data capability. Phase 19 builds on that
architecture (nothing in Phase 18 is modified) to run a real,
preregistered DISCOVERY-stage options-alpha research campaign on real
option price data. **No trading strategy is created. No alpha is
declared as fact. No live/paper order is placed this phase.**

## The real data foundation

24 real option contracts, gathered via genuine `get_option_instruments` /
`get_option_historicals` MCP probes during this phase:

| Underlying | Strikes | Types | Expiration | Real spot context (Dec 2021) |
|---|---|---|---|---|
| AAPL | 150 / 165 / 180 | call + put | 2022-03-18 | ~$164.77 (unadjusted — no splits) |
| SPY  | 430 / 450 / 470 | call + put | 2022-03-18 | ~$450.50 (unadjusted — no splits) |
| NVDA | 275 / 300 / 325 | call + put | 2022-03-18 | real strike ladder confirmed up to $295+ via a real paginated probe; split-confound noted below |
| TSLA | 900 / 1000 / 1100 | call + put | 2022-03-18 | real strike ladder confirmed via a real paginated probe; split-confound noted below |

**Split-adjustment confound (documented, not hidden):** `HistoricalDataStore`'s
underlying closes are split-adjusted retroactively for splits that had not
yet occurred as of the observation date (NVDA's 2024 10:1 split, TSLA's
2022 3:1 split). Strikes were therefore selected by reading the REAL
strike ladder `get_option_instruments` returned for the 2022-03-18
expiration directly — never by trusting the split-adjusted equity close.
AAPL and SPY carry no such confound (no splits in this window).

Each contract's real daily OHLC bars span 2021-12-01 through 2022-03-17
(74 bars/contract, 1,776 contract-day rows total) — confirmed genuine,
volatile, economically real price action (not placeholder data). Zero
option bars were dropped for a missing matching underlying close.

Every fact above traces to a real, read-only MCP probe made during this
phase (see the session's tool-call record); nothing is inferred from a
tool name or assumed from a prior phase.

## Architecture built (`src/options/`, additive to Phase 18)

- **`universe.py`** — `UnderlyingUniverse` / `OptionableUnderlying` /
  `UnderlyingFilterConfig`: a dynamic, evidence-gated universe of
  optionable underlyings. `has_verified_historical_options=True`
  structurally requires an `evidence_note` (Part 2's discipline).
  `has_verified_live_options` stays honestly `False` for every member —
  Phase 19 never probed a live chain. `phase19_verified_underlying_universe()`
  is the real 4-symbol universe this phase's campaign actually used.
- **`moneyness.py`** — causal log-moneyness (`ln(S/K)`, the primary
  measure) + raw ratio + a 5-bucket taxonomy
  (`DEEP_ITM`/`ITM`/`NEAR_ATM`/`OTM`/`DEEP_OTM`), with the call/put sign
  convention documented explicitly.
- **`expiration.py`** — `days_to_expiration` + a 6-bucket DTE taxonomy.
- **`price_history.py`** — `OptionPriceBar` (deliberately **no volume
  field** — Phase 18 confirmed option bars never carry real volume;
  recording 0 would misrepresent "not available" as "zero traded").
  Strictly causal `future_option_return`: `out[i]` uses only
  `bars[i]`/`bars[i+h]`, is `None` at the tail (never padded, never
  wraps), proven by `tests/test_options_price_history.py`'s lookahead
  tests.
- **`contract_existence.py`** — the requested 4-state
  `ExistenceState` (`KNOWN_EXISTENCE`/`UNKNOWN_EXISTENCE`/
  `KNOWN_EXPIRED`/`INSUFFICIENT_PIT_EVIDENCE`), built on top of Phase
  18's `ContractExistenceEvidence` (reused, not duplicated; Phase 18's
  `point_in_time.py` is untouched).
- **`research_observation.py`** — `OptionResearchObservation`: one
  (contract, day) research row combining option OHLC, a REFERENCE to the
  underlying's own close (not a duplicated bar object), DTE/DTE-bucket,
  and moneyness. `build_research_series()` drops (never fabricates) a bar
  with no matching underlying close.
- **`cost_model.py`** — `ResearchRealismLabel`
  (`MARK_TO_MARKET_HISTORICAL_RESEARCH` vs `EXECUTION_REALISTIC_RESEARCH`)
  and `CostAssumption` (label must contain the word "ASSUMPTION" —
  enforced structurally). `COST_SENSITIVITY_ASSUMPTIONS` is the
  preregistered 1x/2x/3x sensitivity ladder used by the campaign.
- **`opportunity_score.py`** — the `UnderlyingCandidate` →
  `ChainCandidate` → `ContractCandidate` → `SignalEvaluation` →
  `OpportunityScore` pipeline SCHEMA. `ContractCandidate.render_field()`
  returns the exact sentinel string `"UNAVAILABLE_HISTORICALLY"` for any
  field not OBSERVED/DERIVED. `OpportunityScore.composite_score` defaults
  to `None` with `scoring_method="NOT_COMPUTED_THIS_PHASE"` — no
  Phase 19 code path computes a real composite score (that is a strategy
  decision, out of scope).
- **`quality.py` (extended, additive)** — `find_missing_business_days`,
  `find_suspicious_flat_price_run` (mechanizes Phase 18's deep-OTM
  tick-floor caveat), `find_corporate_action_inconsistency`.

## The `options_alpha` hypothesis family (P19-OPT-001..012)

12 hypotheses, preregistered via `scripts/phase19_step2_preregister_hypotheses.py`
BEFORE `scripts/phase19_step3_discovery_campaign.py` ran — every one has
`family="options_alpha"` and `parent_hypothesis_id=None` (a brand-new
family, not a continuation of any prior-phase equity hypothesis).
Dimensions covered: moneyness, DTE/theta-decay, moneyness×DTE
interaction, moneyness-bucket tail risk, call/put asymmetry,
volatility→magnitude, short-horizon reversal, per-underlying stability,
horizon stability, a mechanical-baseline placebo (does the option carry
information beyond the underlying's own forward return?), a
data-quality negative control (tick-floor-pinned contracts), and
expiration-proximity decay.

## Discovery campaign results (MARK-TO-MARKET HISTORICAL RESEARCH only)

Run via `scripts/phase19_step3_discovery_campaign.py`, reusing Phase
7+'s existing statistical machinery end to end (`src.research.ic`,
`.quantile`, `.multiple_testing`, `.return_series_bootstrap`,
`.overfitting_metrics`, `.purged_cv`, `.cross_sectional_placebo`) —
nothing in this phase reimplements IC, bootstrap, PBO, DSR, or purged CV.

Final classification: **5 of 12 DISCOVERY_SUPPORTED**, 5 INCONCLUSIVE, 1
FRAGILE, 1 REJECTED (see the script's own stdout for the full run, or
`logs/research_data/phase19_gate_transitions.jsonl` for the recorded
gate transitions). Headline, honestly-labeled findings:

- **Cross-sectional structural limitation (a real, important finding,
  not a bug):** because every contract in this panel shares the SAME
  expiration, DTE is IDENTICAL across the 24-contract cross-section at
  any given timestamp — a cross-sectional IC for `dte` is structurally
  UNDEFINED (zero variance to rank), not merely weak. A pooled
  time-series correlation is reported instead, explicitly labeled
  DESCRIPTIVE ONLY (no valid p-value — the stacked rows are not
  independent observations). A future multi-expiration panel would not
  have this limitation.
- Primary feature `log_moneyness` vs `forward_return_5`: pooled
  Spearman IC ≈ 0.055, BH-significant across the family, but **not
  monotonic across quantiles** — classified `FRAGILE` (P19-OPT-001),
  not `DISCOVERY_SUPPORTED`.
- Call/put mean forward-return asymmetry is large and Welch-significant
  (P19-OPT-005, `DISCOVERY_SUPPORTED`) — consistent with, not
  independent evidence beyond, the underlying's own realized drift over
  this specific window.
- Deep-OTM contracts show materially higher forward-return dispersion
  than ITM/near-ATM (P19-OPT-004, `DISCOVERY_SUPPORTED`).
- The `log_moneyness` IC's sign is stable across all 4 underlyings
  (P19-OPT-008) and across all 5 preregistered horizons (P19-OPT-009).
- The mechanical-baseline check (P19-OPT-010) found the OPTION's IC was
  actually SMALLER in magnitude than the UNDERLYING EQUITY's own IC on
  the identical feature/horizon — i.e., this specific real panel did
  **not** show the option data adding predictive information beyond
  what the underlying's own price already carried; classified
  `INCONCLUSIVE`, reported honestly rather than suppressed.
- The data-quality negative control (P19-OPT-011) found **zero**
  tick-floor-pinned rows in this specific 24-contract panel (none of the
  chosen strikes were deep enough OTM to pin at $0.01) — an honest
  `INCONCLUSIVE` (n=0), not a fabricated result.
- Cost sensitivity (Part 10, `ASSUMPTION`-labeled only): the Q5-Q1
  mark-to-market spread survives only the 1x (tightest) cost assumption;
  it is net-negative under the 2x and 3x assumptions. No historical
  bid/ask exists to calibrate these assumptions against real spread
  data — they are stress cases, not observed costs.

## Limitations (explicit, not hidden)

1. **Panel size.** 24 contracts, one expiration cycle, ~74 trading days
   — small relative to prior equity-research phases (dozens of symbols,
   years of data). Every classification above accounts for this.
2. **Single-expiration structural limitation.** DTE cannot vary
   cross-sectionally within this panel (see above) — a genuinely
   multi-expiration panel is future work, not something this phase
   fabricates around.
3. **MARK-TO-MARKET HISTORICAL RESEARCH only.** No real historical
   bid/ask/volume/open-interest/IV/Greeks exist for any date this phase
   probed (Phase 18's finding, reaffirmed). Every cost figure in this
   phase is an explicitly labeled `ASSUMPTION`, never an observed cost.
4. **Contract existence before first observation is `UNKNOWN_EXISTENCE`**
   for every contract (Part 16) — no survivorship-bias-free options
   universe is claimed.
5. **`OpportunityScore.composite_score` is never populated this phase** —
   choosing a real scoring/weighting function is a strategy decision,
   explicitly out of scope.
6. No options alpha hypothesis in this family should be read as a
   trading recommendation. `DISCOVERY_SUPPORTED` is a discovery-stage
   research classification, not a validated, tradable edge.
