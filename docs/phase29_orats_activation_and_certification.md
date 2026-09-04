# ORATS Provider Activation, Ingestion & Certification (Phase 29)

## Headline answer

**Path A applies: `ORATS_ACTIVATION_PENDING_HUMAN`.** No `ORATS_API_KEY` was found anywhere in this environment (checked directly via `os.environ` and every `.env`/`.env.example` file, nothing printed) — so per this phase's explicit instructions, the full ORATS adapter (config, field-provenance table, schema mapping, query builder, ingestion, storage, PIT/chain/execution/IV-Greeks/corporate-action certification, coverage reporting) was built and fully tested against real-schema-derived and clearly-labeled synthetic fixtures, and this phase **stopped before any call that would require a real credential.** No account was created, no payment was made, no API key was requested, entered, or stored anywhere in this repository.

**A genuine self-correction was made this phase**: while building the field-provenance table, re-reading the exact schema evidence this project already gathered in Phase 25 found that Phase 28's `ORATS_SCORECARD` had mistakenly scored `QUOTE_SIZES` at 1/5 ("no bid/ask SIZE field observed") — the real schema (`Strike.call_bid_size`/`call_ask_size`/`put_bid_size`/`put_ask_size`) has always had these fields. This is corrected in place in `phase28_provider_scorecard.py`/`phase28_provider_decision.py` (ORATS's total moves 47→50/100, still the highest-ranked candidate — no ranking or final decision changes).

## Part 1 — the ORATS adapter

`src/options/orats_field_provenance.py` — every field Part 1 requires, classified with its exact 4-value vocabulary:

| Classification | Fields |
|---|---|
| `VENDOR_SUPPLIED` | contract identity (partial), underlying, option type, strike, expiration, timestamp, OHLC (underlying), bid, ask, **bid_size, ask_size** (corrected), volume, open interest, IV, delta, gamma, theta, vega, rho, underlying_price, historical volatility, dividends, splits |
| `UNAVAILABLE` | multiplier, exercise_style, adjusted_contract_flag |
| `RECONSTRUCTED` / `DERIVED` | none — every field this adapter maps is either a real, confirmed vendor field or genuinely absent; nothing is computed from other ORATS fields |

`src/options/orats_schema_mapping.py` maps real ORATS `/strikes` row keys (`ticker`, `strike`, `expirDate`, `tradeDate`, `callBidPrice`/`callAskPrice`/`callBidSize`/`callAskSize`/`callVolume`/`callOpenInterest` + put-side equivalents, `iv`, `delta`/`gamma`/`theta`/`vega`/`rho`, `underlyingPrice`) into `ContractIdentity`/`ContractLifecycle`/`ProvenancedObservation` (Phase 15/24's existing types, reused unchanged). `multiplier=100` is the same explicit, flagged, unconfirmed market-convention assumption Phase 26 used (`MULTIPLIER_SOURCE_CONFIRMED = False`).

`src/options/orats_ingest.py`'s `ingest_strike_rows` builds a real, normalized store by reusing `InMemoryLeanSampleStore` (Phase 26) directly — every field of that class is provider-agnostic despite its name, and every Phase 26/27 quality/PIT/chain/execution function reads it structurally, never via an `isinstance` check, so this reuse is genuine, not a misnomer (documented explicitly in the module, not silently done).

## Part 2 — historical data query

`src/options/orats_client.py`'s `ORATSHistoricalStrikesQuery` builds the real, confirmed `tradeDate`-scoped request shape (Phase 25's evidence). `build_aapl_validation_query()` is the preferred first test (single symbol, one date) per Part 2's own instruction; `ORATSHistoricalStrikesQuery.__post_init__` structurally REJECTS more than 12 tickers, so a bulk pull can never even be constructed. `build_expansion_query()` covers Part 2's exact 11-symbol expansion list (NVDA/TSLA/SPY/QQQ/MSFT/AMD/AMZN/META/GOOGL/NFLX/IWM).

**No real query was ever sent.** The only concrete client this phase builds, `CredentialsUnavailableClient`, raises `ORATSCredentialsUnavailableError` on every method — never returns a value, fabricated or otherwise, and refuses even if a key happened to be configured (this phase never implements a real call under any condition).

## Part 3 — real data verification

`src/options/orats_ingest.py`'s `RealDataVerificationRecord` carries every field Part 3 requires (provider, product, query, retrieval timestamp, source timestamp, underlying, contract count, fields returned, raw response fingerprint) plus an explicit `actually_returned_by_provider: bool` with **no default** (must always be stated explicitly — `inspect.signature` tested) — every real caller in this phase's own `src/` code would have to pass `False` (no real caller exists yet; enforced by a test that no `src/` file ever writes `actually_returned_by_provider=True`). `fingerprint_raw_response` is a real, deterministic SHA-256 over the canonical JSON of whatever rows were actually retrieved.

## Part 4 — historical chain test

`src/options/orats_lifecycle_pit.py` re-exports Phase 26's `reconstruct_chain_as_of`/`contracts_incorrectly_visible_before_first_observation` unchanged (both already operate structurally on the shared store shape). Tested against a synthetic, ORATS-shaped, real-schema-named 2-day AAPL fixture (`tests/orats_fixtures.py`): the set of knowable contracts correctly grows from day 1 to day 2, and the adversarial "was any not-yet-observed contract incorrectly included" check returns zero violations — mirroring exactly the real test Phase 27 ran against real GOOG data, here run against clearly-labeled synthetic data pending real ORATS access.

Future contracts, expired contracts, later-listed strikes, adjusted contracts, and corporate actions are all explicitly addressed: the reused PIT machinery structurally excludes future/not-yet-observed contracts and correctly flags already-expired ones; corporate actions are handled in Part 8 below; **any PIT uncertainty remains explicitly flagged** — `PIT_CONTRACT_EXISTENCE_LIMITED` (below).

## Part 5 — bid/ask certification

`src/options/orats_execution_certification.py` deliberately does NOT bare-reuse Phase 26's `build_execution_realism_report` — that function's Grade A/B boundary checks only whether its `trades` dict is non-empty, which is correct for Lean data (real trade-price ticks) but would silently **mis-grade** ORATS: this provider's schema has no per-trade price field, only an aggregate daily volume count, which `orats_ingest.py` places in the same `trades` dict slot. A bare reuse would have falsely claimed Grade A. This module reuses Phase 26's real spread-statistics math unchanged, then corrects the grade ceiling to **B** (historical bid/ask + sizes, no real trade ticks) — tested explicitly against a synthetic fixture, confirming the downgrade fires only when it should.

## Part 6 — IV/Greeks certification

Unlike the free QuantConnect/Lean dataset (zero native IV/Greeks, everything reconstructed), **ORATS's real schema supplies IV and full Greeks directly** — classified `VENDOR_SUPPLIED`, never `RECONSTRUCTED`. `src/options/orats_iv_greeks_certification.py` cross-checks a vendor-supplied IV/delta against an independently-computed Black-Scholes value (reusing Phase 26's solver unchanged), using a fixture row whose bid/ask/underlying-price values are the SAME real numbers Phase 26 independently verified (AAPL, 2015-01-02, $109.33 close, $17.65 mid) — the real check reproduces a ~29.35% BS-implied IV and ~0.669 delta, both within 0.2% of the fixture's stated "vendor" values, confirming the consistency-check MACHINERY is correct. A deliberately wrong "vendor" IV (0.90) is correctly flagged inconsistent, never silently accepted — Part 6's explicit instruction ("differences are acceptable... the objective is consistency validation, not exact equality") is honored: the function never raises on a real disagreement, it reports one.

## Part 7 — contract lifecycle

**`PIT_CONTRACT_EXISTENCE_LIMITED` applies to ORATS**, identically to every other provider this project has evaluated (Robinhood, QuantConnect/Lean): no first-listed-date/first-observed-date field exists anywhere in the real schema (`Ticker.min_date`/`max_date` describe data-coverage range for a symbol, not a per-contract listing date — the same distinction drawn every prior phase). The confirmed real `trade_date` query parameter remains a genuinely stronger PRACTICAL PIT mechanism than Robinhood's eventual-existence-only capability (it directly answers "what did the chain look like as of date T"), but this does NOT resolve the first-listed-date gap — both facts are held at once, honestly, in `src/options/orats_lifecycle_pit.py`'s own constant.

## Part 8 — corporate actions

`src/options/orats_corporate_actions.py` re-tests the Phase 26 AAPL split discontinuity against ORATS's schema by reusing Phase 27's real structural detector unchanged (`find_split_boundary_discontinuities`, imported directly, tested to be the exact same function object). **Real, confirmed improvement**: ORATS has a dedicated `/splits` endpoint (`StockSplitHistory`: ticker/split_date/divisor) that QuantConnect/Lean's options data entirely lacks. **Real, confirmed remaining gap**: ORATS's own `Strike` rows still carry no adjusted-contract flag or explicit legacy/successor identity mapping, so Phase 27's root cause narrows from a two-part finding (`SOURCE_LIMITATION` + `MISSING_ADJUSTMENT_METADATA`) to just `MISSING_ADJUSTMENT_METADATA` — the endpoint itself is not a source limitation; the missing per-contract mapping is. **Never verified against real ORATS data** — no live call was made.

## Part 9 — data quality

Every one of Phase 26's 12 automated quality rules (`phase26_quality_rules.run_all_quality_checks`) runs, unmodified, against the ORATS-shaped store built from synthetic fixtures — zero critical flags, confirming the adapter's own construction is internally consistent (no bid>ask, no negative values, no OHLC violations, no timestamp-ordering issues) before any real data ever flows through it. The reused machinery still never silently repairs anything — every anomaly (were one found) would be a flag, not a fix.

## Part 10 — data storage

`src/options/orats_ingest.py`: `write_raw_archive` is immutable by construction (raises `FileExistsError` rather than overwrite an existing raw file, tested); `write_normalized_dataset` writes a SEPARATE file, never touching the raw archive (tested by comparing raw-file bytes before and after normalization runs), with a manifest carrying `dataset_version="phase29_orats_v1"`, the real source fingerprint, provider, and contract count. Every persisted contract record carries `multiplier_source_confirmed: false` explicitly — the same honesty discipline as Phase 26/27.

## Part 11 — dataset separation

`src/options/orats_activation_state.py`'s `DatasetSourceRole` — exactly Part 11's 3-way vocabulary (`FREE_REFERENCE_DATASET`, `ORATS_DATASET`, `OTHER_PROVIDER_DATASET`), enforced structurally: every ORATS observation this adapter could ever build carries `OptionDataProvenance.source="orats"` (permanent, per-observation), distinct from Phase 26/27's `"quantconnect_lean_open_source_sample"` — `dataset_role_for_source()` is the real, tested mapping function a future merge layer must consult. **No merge was performed or is even possible yet** — zero real ORATS data exists to merge with anything.

## Part 12 — coverage audit

`src/options/orats_coverage_report.py` reuses Phase 27's exact `TARGET_UNDERLYINGS`/`TARGET_YEARS` lists. **The current, real, honest coverage matrix (`CURRENT_ORATS_COVERAGE`) is entirely `NO_DATA`** — every one of the 12×8=96 cells. This is not a placeholder oversight; it is the accurate statement that zero real ORATS observations exist for any underlying, target or otherwise. The reporting MACHINERY itself is proven correct against a synthetic, populated fixture (a synthetic AAPL row correctly marks `("AAPL", 2021)` as `REAL_DATA` and nothing else, never crediting a non-target underlying to a target row).

## Part 13 — dataset certification

`src/options/orats_certification_score.py` — a new 15-dimension scorecard matching Part 13's exact list (adding `QUOTE_SIZES`/`INTRADAY`/`COVERAGE` as explicit dimensions vs. Phase 26/27's own 15-dim list), reusing Phase 26's exact `ResearchReadinessGate` 5-value OUTPUT vocabulary directly (Part 13's own "possible final states" list is identical to it).

**Real, current result: 26/75, disqualified via `COVERAGE=0`, gate = `HISTORICAL_OPTIONS_DATA_INSUFFICIENT`.** This is the honest, correct outcome given zero real data — it is a statement that **no real evidence exists yet to certify**, not a claim that ORATS's real data would be insufficient once obtained. Every non-zero score reflects only the same real open-source-client-schema evidence tier Phase 25/28 already established; nothing reaches `VERIFIED_BY_ACTUAL_DATA`. The critical-blocker override itself is exercised by a synthetic non-disqualifying case and a synthetic disqualifying case, not merely inferred from the one real (disqualified) result.

## Part 14 — no alpha research

No strategy development, alpha discovery, profitability testing, signal/parameter/P&L/Sharpe optimization, trade selection, or live order was performed this phase — enforced by `tests/test_phase29_safety.py`.

## Part 15 — autonomous execution audit

Re-confirmed, not re-built: Phase 28's `src/execution/system_state.py` (7-state machine, no per-trade-approval state) and `src/execution/autonomous_architecture_audit.py` (all 15 pipeline stages, 14 `READY` + 1 `PARTIAL`) are both completely untouched this phase — `tests/test_phase29_safety.py` re-verifies `len(SystemState) == 7`, no `WAITING_FOR_TRADE_APPROVAL`-shaped name exists, and all 15 pipeline stages remain non-`MISSING`, directly against the real Phase 28 modules (not a copy).

## Part 16 — options only

Re-confirmed structurally, not re-implemented: `src/execution/orders.py`'s `OrderLeg`/`OrderRequest` still require an `option_id` on every leg — no equity/ETF-share order shape exists (re-checked this phase via a direct file read, not merely assumed).

## Part 17 — testing

13 new test files (12 ORATS-module files + 1 safety file), **100 new tests**, covering: config (credential masking, never a bare-value leak); field provenance (including the self-correction assertion); schema mapping (call/put extraction, one-sided-market handling, missing-key honesty); the query builder and credentials-unavailable client (every method raises, never fabricates, even when "configured"); ingestion (multi-day merge, zero critical quality flags, deterministic fingerprints, immutable raw archive, raw/normalized separation); execution-realism grading (the A→B downgrade correction, tested explicitly); IV/Greeks consistency (a real-value-reused cross-check, a deliberately-wrong-vendor-value rejection, graceful handling of missing/expired inputs); PIT/lifecycle (multi-day chain growth, zero adversarial violations, `PIT_CONTRACT_EXISTENCE_LIMITED`); corporate actions (the narrowed root cause, direct re-import identity check); the certification score (structural correctness, the override exercised both ways, the real disqualified result); activation state (dataset-role mapping); coverage reporting (honest current NO_DATA, machinery correctness against a synthetic fixture); and the phase-wide safety guards (no credential leakage, no purchase, no live/paper trading enabled, the unmodified autonomous state machine, structural OPTIONS_ONLY).

## Final report (27 items)

1. **Commit hash**: recorded in this phase's commit (git log).
2. **Total tests**: 2,269 collected (2,265 passed + 4 pre-existing baseline failures).
3. **New tests**: 100, across 13 new files.
4. **Baseline failures**: the same 4 pre-existing `test_orchestrator.py` failures as every prior phase — untouched.
5. **Whether ORATS access was available**: No — `ORATS_ACTIVATION_PENDING_HUMAN` (Path A).
6. **Whether any actual ORATS data was retrieved**: No — zero real API calls were made.
7. **Exact fields actually verified**: none `VERIFIED_BY_ACTUAL_DATA` — every field's evidence remains at the real-open-source-client-schema tier (Phase 25, corrected this phase for bid/ask sizes).
8. **Fields unavailable**: multiplier, exercise_style, adjusted_contract_flag, first-listed-date.
9. **PIT status**: `PIT_CONTRACT_EXISTENCE_LIMITED` — no listing-date field; the real `trade_date` parameter is a stronger practical (not complete) PIT mechanism.
10. **Contract lifecycle status**: real schema fields for identity/dates exist; no per-contract adjustment/state field; multiplier unconfirmed.
11. **Historical chain status**: mechanism (real `trade_date` parameter) confirmed by schema; reconstruction MACHINERY tested and correct against synthetic data; never exercised against a real response.
12. **Bid/ask status**: `VENDOR_SUPPLIED` (schema-confirmed, corrected this phase to include sizes); never confirmed via a live response.
13. **Volume status**: `VENDOR_SUPPLIED` (schema-confirmed); never confirmed live.
14. **OI status**: `VENDOR_SUPPLIED` (schema-confirmed); never confirmed live.
15. **IV status**: `VENDOR_SUPPLIED` (schema-confirmed, richest of any provider evaluated); consistency-check machinery tested and correct; never confirmed live.
16. **Greeks status**: `VENDOR_SUPPLIED` (schema-confirmed); never confirmed live.
17. **Execution grade**: capped at **B** (bid/ask+sizes only — no real trade-tick field in the schema), corrected from a naive reuse that would have wrongly claimed A.
18. **Corporate-action status**: real dedicated `/splits` endpoint confirmed (an improvement over Lean); no per-contract adjustment mapping confirmed; root cause narrows to `MISSING_ADJUSTMENT_METADATA` alone.
19. **Target-universe coverage**: 0 of 96 real cells (12 underlyings × 2019-2026) — entirely `NO_DATA`, honestly.
20. **Year coverage**: none — zero real ORATS observations exist for any year.
21. **Dataset size**: 0 real contracts, 0 real observations.
22. **Dataset fingerprint**: none — no real raw response was ever fetched to fingerprint (the fingerprinting/persistence MACHINERY is built and tested against synthetic data, ready for Path B).
23. **Licensing status**: unchanged from Phase 28 — `LICENSING_UNVERIFIED`.
24. **Final certification**: `HISTORICAL_OPTIONS_DATA_INSUFFICIENT` for ORATS specifically (26/75, disqualified via `COVERAGE=0`) — meaning "no real evidence exists yet," not "ORATS's real data would be insufficient." The project's overall dataset state remains anchored by the FREE_REFERENCE_DATASET's own separate, unchanged Phase 26/27 certification (`HISTORICAL_OPTIONS_DATA_PARTIAL`), which this phase did not touch, delete, or merge with anything.
25. **Remaining blockers**: real ORATS credentials (a human decision, per Phase 28's still-pending `PAID_PROVIDER_RECOMMENDATION_PENDING_HUMAN_APPROVAL`); once credentials exist, a real Path-B client implementation (this phase deliberately builds none); ORATS's own licensing terms, still completely unverified.
26. **Exact next action**: a human must explicitly approve (or decline) acquiring ORATS's Delayed Data API (Phase 28's unchanged recommendation) — no other action from this phase requires human input. If approved, a future phase implements a real `ORATSHistoricalClient`, retrieves the Part 2 AAPL validation sample first, and re-runs this exact certification machinery against real data.
27. **Autonomous trading architecture status**: unchanged from Phase 28, re-confirmed not re-built — the system-level state machine (7 states, no per-trade approval), the 15-stage pipeline readiness (14 ready, 1 partial), and structural OPTIONS_ONLY enforcement all still hold; nothing in this phase touched `settings.py`, `gateway.py`, or `orchestrator.py`.

## What this phase did not do

No account was created with ORATS or any vendor. No payment method was entered anywhere. No API key was requested, obtained, printed, logged, or stored anywhere in this repository (`.env`/`.env.example` both confirmed free of any ORATS credential). No real ORATS API call was ever made. No data was purchased. No alpha hypothesis was registered. No signal was searched for. No strategy was built. No profitability, parameter, P&L, or Sharpe optimization was performed. No live or paper order was placed. No per-trade human-approval requirement was added anywhere — the unmodified Phase 28 state machine (no such state exists) was re-confirmed, not weakened. No Phase 26/27 file was touched, and the free reference dataset was neither deleted nor silently merged with anything.
