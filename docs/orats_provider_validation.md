# Historical Options Data Provider Validation & ORATS Proof-of-Data (Phase 25)

## Headline answer

`ORATS_PROMISING_BUT_UNVERIFIED` (Part 26's exact vocabulary; see `src/options/provider_validation_decision.py::FINAL_DECISION`).

ORATS's field-level schema is now backed by real, independently-fetched **open-source client library
source code** (`FyZyX/orats-python`, MIT-licensed, wraps the real ORATS Data API) — a genuinely stronger
evidence tier than Phase 24 had (pure marketing/third-party summary). But no live ORATS API call was ever
made this phase, no real response payload was ever obtained, and ORATS's own official documentation and
pricing pages remained `EGRESS_BLOCKED` in this environment both this phase and Phase 24. ORATS's free
trial requires a credit card — per this phase's explicit instruction, that triggers `PAID_PROOF_REQUIRED`
and hands-on testing stopped there. **No account was created, no payment method was entered, no data was
purchased.**

## Part 1/2 — constraints honored this phase

- No subscription purchased, no paid plan entered, no payment credentials provided, no vendor committed to.
- ORATS's free-trial signup (`info.orats.com/free-trial`) was found (via WebSearch) to require a credit
  card before issuing any sample data. Per this phase's explicit instruction, this was recorded as
  `PAID_PROOF_REQUIRED` and direct hands-on/sample testing stopped there (`src/options/provider_field_validation.py::PAID_PROOF_REQUIRED_LOG`).
- Databento's $125 free-credit pool is also Stripe-gated (payment info collected up front even to draw
  down free credits) — treated the same way, `PAID_PROOF_REQUIRED`, not pursued further.
- ThetaData's community reporting describes a genuinely no-card-required free tier, but limited to 30
  rolling days of end-of-day data — insufficient depth for this project's actual research window
  (2021-2023) and not needed anyway once ORATS's evidence proved strong enough to bound further vendor
  research (Part 19, below). No ThetaData account was created.

## Part 3 — evidence-source honesty

`orats.com`, `docs.orats.com`, `docs.orats.io`, `orats-python.readthedocs.io`, `docs.thetadata.us`, and
`http-docs.thetadata.us` were all confirmed **`EGRESS_BLOCKED`** via direct `WebFetch` from this
environment — official vendor documentation for the two most promising candidates was not directly
reachable. This is stated explicitly, not silently worked around: `github.com` and
`raw.githubusercontent.com` were NOT blocked, and were used to fetch real, unmodified source code of
open-source client libraries wrapping each vendor's real API. That source code is real evidence of the
API's actual field names (a client library that invented field names would simply not function against
the live API), but it is **not** the same as a live probe — no response payload with real values was ever
seen. Every claim in this phase's matrix is tagged with exactly which evidence tier backs it
(`EvidenceTier` in `src/options/provider_field_validation.py`); nothing gathered via web research is ever
silently presented as `VERIFIED_AVAILABLE`.

## Part 4 — ORATS field validation matrix

Full matrix: `src/options/provider_field_validation.py::ORATS_FIELD_VALIDATION_MATRIX` (23 rows), printed
in full by `scripts/phase25_step1_orats_validation_report.py`. Every row uses exactly one of Part 4's 4
required values. Summary:

| Classification | Count | Representative fields |
|---|---|---|
| `VERIFIED_AVAILABLE` | 0 | — (no live probe was ever made) |
| `VERIFIED_UNAVAILABLE` | 0 | — (nothing was ever confirmed absent via a real probe) |
| `CLAIMED_AVAILABLE_UNVERIFIED` | 17 | contract identity (partial), underlying OHLC (adjusted+unadjusted), bid/ask+sizes, volume, open interest, IV (raw+bid/mid/ask+21-point delta smile), IV rank/percentile, Greeks, historical volatility, dividends, splits, earnings, trade_date-scoped historical querying, expired-contract queryability (inferred), pricing terms |
| `UNKNOWN` | 6 | first_listed_date/last_trading_date, exercise_style, multiplier/contract_status, IV/Greeks calculation methodology, sample/live validation, licensing terms |

The real field names underpinning this matrix come from `FyZyX/orats-python`'s
`src/orats/constructs/api/data.py` (classes `Ticker`, `Strike`, `Money`, `MoneyImplied`, `MoneyForecast`,
`Summary`, `Core`, `DailyPrice`, `HistoricalVolatility`, `DividendHistory`, `EarningsHistory`,
`StockSplitHistory`, `IvRank`) — fetched twice, independently, with identical results both times — and its
`src/orats/endpoints/data/{endpoints,request}.py` (confirming a real `trade_date` query parameter on a
`DataHistoryApiRequest` base class, and a `/hist/`-prefixed historical URL convention across `/strikes`,
`/monies/*`, `/summaries`, `/cores`, `/dailies`, `/hvs`).

## Part 5 — historical chain test

Answer: `CLAIMED_AVAILABLE_UNVERIFIED`, strong evidence tier. ORATS's `Strike` class is keyed by
`ticker` + `trade_date` + `expiration_date` + `strike` — structurally, a row IS a historical chain
snapshot entry, and the `DataHistoryApiRequest.trade_date` parameter is the confirmed mechanism for
requesting one as of an arbitrary past date. No live query was ever issued to confirm this returns real,
complete data for a specific test date (e.g. 2022-06-01) — the claim rests on schema design, not an
observed response.

## Part 6/9 — expired-contract test

Answer: `CLAIMED_AVAILABLE_UNVERIFIED`. No explicit contract-state field (analogous to Robinhood's
`state="expired"`) was observed in any fetched class. The inference that expired contracts are queryable
rests on the `trade_date`-scoped design itself (the entire point of date-scoping a `Strike` query is to
retrieve data for dates that may post-date a contract's active trading life) plus `Ticker.min_date`/
`max_date` implying multi-year coverage — a real, specific mechanism, not pure assumption, but still short
of a direct confirmation.

## Part 7 — point-in-time (PIT) test

`HISTORICAL_CONTRACT_EXISTENCE_UNKNOWN` in the strict "first-listed-date field" sense carried over from
Phase 24 still applies to ORATS too — no `first_listed_date`/`first_trade_date`/`created_at` field was
observed anywhere in the fetched schema. **However**, ORATS's `trade_date`-scoped `/strikes` query is a
genuinely stronger **practical** PIT tool than Robinhood's: it lets a caller ask directly "what did the
chain look like as of date T" (`ORATS_READINESS_SCORECARD`'s `PIT_CAPABILITY` dimension scores 3/5,
reflecting real-but-unverified evidence), rather than only "did this contract eventually reach an
expired-state flag" (Robinhood's capability, Phase 24). This distinction is preserved explicitly, not
blurred.

## Part 8 — bid/ask methodology

`UNKNOWN`. The fields (`call_bid_price`, `call_ask_price`, `put_bid_price`, `put_ask_price`, and matching
`_size` fields) are confirmed real, but whether they represent NBBO-derived, exchange-consolidated, or
vendor-reconstructed values, and the exact intraday snapshot timing, is not documented anywhere in the
evidence gathered this phase.

## Part 10 — volume / open interest

Both `CLAIMED_AVAILABLE_UNVERIFIED`. Confirmed as distinct real fields at both the per-strike level
(`Strike.call_volume`/`call_open_interest`, and the `put_*` equivalents) and the per-underlying aggregate
level (`Core.call_volume`/`call_open_interest`, `total_stock_volume`).

## Part 11/12 — IV / Greeks methodology

Fields themselves are `CLAIMED_AVAILABLE_UNVERIFIED` and unusually granular (raw IV, bid/mid/ask IV per
side, a 21-point delta-bucketed smile via `Money`, IV rank/percentile via a dedicated `IvRank` class, and
full Greeks — `delta`/`gamma`/`theta`/`vega`/`rho`/`phi`/`driftless_theta` — via `Strike`). The
**calculation methodology** behind them (option-pricing model, interest-rate source, dividend treatment)
is `UNKNOWN` — not documented anywhere reached this phase, and ORATS's own methodology pages were
`EGRESS_BLOCKED`.

## Part 13 — data depth

Still relying on Phase 24's reported (unverified) figures: near-EOD since 2007, 1-minute intraday since
August 2020. Not independently reconfirmed this phase — `orats.com`'s coverage pages remained
`EGRESS_BLOCKED`. `ORATS_READINESS_SCORECARD.HISTORICAL_DEPTH` scores only 2/5 to reflect this.

## Part 14 — intraday

Same status as Part 13 — the Aug-2020-intraday claim is carried over from Phase 24's weaker evidence tier
only; no intraday-specific field or endpoint was directly observed in the classes fetched this phase.
`INTRADAY` scores 1/5.

## Part 15 — sample data

`PAID_PROOF_REQUIRED` / no sample obtained. No account was created, no API key was ever issued, so no
real response payload was ever seen. This is the single largest remaining verification gap: every
`CLAIMED_AVAILABLE_UNVERIFIED` row in the Part 4 matrix could, in principle, be wrong if the live API has
drifted from the open-source client's schema, or if the client covers only a subset of a paid tier's real
fields.

## Part 16 — schema validation

Not performable without a live sample (see Part 15) — reported as not possible this phase, not silently
skipped.

## Part 17 — corporate actions

Strong evidence: dedicated `DividendHistory` (`ex_dividend_date`, `dividend_amount`, `dividend_frequency`,
`declared_date`) and `StockSplitHistory` (`split_date`, `divisor`) classes, backed by real `/divs` and
`/splits` endpoints — not inferred from price-jump detection, a materially more transparent design than
most vendors reviewed in Phase 24.

## Part 18 — survivorship / licensing

Survivorship: plausible given `Ticker.min_date`/`max_date`'s per-ticker coverage-range design and general
vendor positioning, but not directly confirmed — `UNKNOWN`. Licensing: `UNKNOWN` — no
redistribution/automated-trading-use/commercial terms were found in any source reached this phase, and
this matters directly given this project is building an actual automated options-trading system; a future
purchase decision must not proceed without confirming this in writing first.

## Part 19 — alternative-provider check (bounded)

Per this phase's explicit instruction ("do not fully audit every provider if ORATS is successfully
verified... the goal is ONE BEST PRACTICAL SOURCE"), and because ORATS's evidence proved substantially
stronger than Phase 24's pure marketing-claims baseline, only a single bounded comparison point was
pursued: **ThetaData**.

- `docs.thetadata.us` and `http-docs.thetadata.us` (its official documentation) were both confirmed
  `EGRESS_BLOCKED` — the same restriction as ORATS's own docs.
- ThetaData's official Python client (`ThetaData-API/thetadata-python`) carries a deprecation notice in
  its own README, redirecting users to a REST API whose docs are the blocked domains above.
- The deprecated client's own source (`thetadata/client.py`, still fetchable on GitHub despite the
  deprecation notice) DOES contain real field-level evidence: `Quote` (bid/ask price/size/exchange/
  condition), `Trade` (price/size/exchange/condition), `OHLCVC`, `OpenInterest`, and contract fields
  (`root`/`exp`/`strike`/`isCall`/`isOption`) — comparable in kind, though smaller in scope, to ORATS's
  evidence. Notably, **no Greeks fields appear anywhere in this legacy client** — a real, negative data
  point (this legacy client may simply predate a Greeks feature the current v3 API has, or the v3 API may
  not compute Greeks at all; not resolved either way this phase).
- Databento and Cboe DataShop and OptionMetrics IvyDB were not further pursued this phase (Part 19's own
  instruction not to fully audit every provider once one candidate is well-evidenced) — Phase 24's
  scorecard rows for them stand, unchanged.

Conclusion: ORATS remains the strongest available candidate. ThetaData is a real, comparably-accessible
alternative worth a full evaluation in a future phase if ORATS's own live-sample verification (Part 15)
is ever completed and disappoints, but nothing gathered this phase displaces ORATS as the leading
candidate.

## Part 20 — quantitative readiness scorecard

`src/options/provider_readiness_scorecard.py::ORATS_READINESS_SCORECARD` — 15 dimensions, 0-5 each, every
score capped at 3/5 unless the evidence tier were `OWN_LIVE_API_PROBE` (never reached this phase, for any
provider):

| Dimension | Score | Dimension | Score | Dimension | Score |
|---|---|---|---|---|---|
| historical_depth | 2 | volume | 3 | pit_capability | 3 |
| daily_ohlc | 3 | open_interest | 3 | api_ergonomics | 2 |
| intraday | 1 | implied_volatility | 3 | cost_accessibility | 1 |
| bid_ask_historical | 3 | greeks | 3 | licensing_clarity | 0 |
| expired_contracts | 2 | historical_chain | 4 | contract_identity | 2 |

**Total: 35/75.** Critical-blocker override rule (Part 20's exact instruction — "no expired contracts /
no historical bid-ask / no historical chain / no usable historical contract identity" disqualifies
regardless of total score): **none of ORATS's 4 critical-blocker dimensions scored 0** — every one has at
least weak, real schema-grounded evidence — so **ORATS is NOT disqualified**. `licensing_clarity` scored 0
but is not one of the 4 literal critical-blocker dimensions named in the prompt, so it lowers the total
score without triggering disqualification; the override logic itself is exercised by a synthetic test
(`tests/test_options_provider_readiness_scorecard.py`) to prove it actually fires when a real blocker is
hit, not merely that it happens to stay inactive for ORATS's specific numbers.

## Part 21 — architecture role preserved

`src/options/provider_ingestion_pipeline.py::ARCHITECTURE_ROLE_PRESERVATION`:

> Historical Provider → Research Dataset → Strategy → Live Robinhood Scanner → Risk Engine → OPTIONS_ONLY
> Execution.

Robinhood (this project's existing HOOD MCP connector) remains the sole LIVE, ACCOUNT, and EXECUTION
source. A historical provider (ORATS or any future alternative) supplies the research dataset a strategy
is developed and backtested against — it never supplies a live quote used for sizing or execution, and
never places, reviews, or cancels an order.

## Part 22 — provider-neutral ingestion flow (design only)

`src/options/provider_ingestion_pipeline.py` — the exact 11-stage flow, as an `IngestionStage` enum plus
one `Protocol`/dataclass per stage transition (no concrete provider implementation, enforced by an AST
safety test):

```
Provider Raw Data → Raw Archive → Normalized Option Contract → Historical Quote → Historical Trade →
Historical Chain → Historical IV/Greeks → Contract Lifecycle → Provenance → Quality Validation →
Research Dataset
```

Built on top of Phase 24's `historical_data_interfaces.py` (`ContractIdentity`, `ContractLifecycle`,
`OptionDataProvenance` reused directly, not re-derived). `RawProviderPayload` is the *only* type allowed
to hold an unstructured, provider-specific raw dict — every later stage type is fully normalized, and a
structural test (`test_raw_payload_is_the_only_type_holding_a_raw_dict`) checks that no provider-specific
field name can leak past the normalization stage into `ResearchDatasetRecord`.

## Part 23 — future data quality certification spec (design only)

`src/options/data_quality_certification.py::DATA_QUALITY_CERTIFICATION_SPEC` — 15 criteria (`DQC-01`
through `DQC-15`), covering PIT chain completeness, expired-contract depth, bid/ask presence and timing,
quote staleness, volume/OI consistency, IV/Greeks methodology disclosure, corporate-action adjustment
transparency, survivorship-bias freedom, contract identity completeness, timestamp/timezone clarity, data
revision policy, sample validation against an independent source, licensing clarity, and API
reliability/rate-limit documentation. `CertificationStatus` currently has exactly one member
(`NOT_YET_ASSESSED`) — nothing is scored against this spec this phase; that is deliberate and enforced by
a test asserting no `CertificationResult` type exists yet.

## Part 24 — explicit non-scope

This phase built **zero** alpha hypotheses, features, strategies, backtests, or P&L optimizations.
`tests/test_phase25_safety.py` enforces this the same way Phase 24's safety test did (no
`Hypothesis(`/`compute_ic_series(`/`grid_search(`/`run_backtest(` patterns anywhere in this phase's
files), plus new guards specific to this phase: no stored ORATS/vendor API key, no `stripe.`/`checkout.`/
`credit_card`/`payment_method=` pattern anywhere, and the field-matrix/decision enums are locked to their
exact required vocabularies.

## Part 25 — tests

6 new test files, 56 tests total, covering: the field matrix's 4-value vocabulary and evidence-tier
honesty; the readiness scorecard's dimension coverage, score bounds, and (critically) the critical-blocker
override rule exercised via a synthetic disqualifying case, not just ORATS's own non-disqualifying
numbers; the ingestion pipeline's stage ordering, architecture-preservation text, and no-raw-leakage
guarantee; the certification spec's 15-criterion completeness and design-only status; the final decision's
5-value vocabulary and the purchase recommendation's structural inability to be marked as acted-upon; and
the phase-wide safety guards (no live trading, no vendor purchase, no hypothesis, no fabricated field, no
`VALIDATION`/`FINAL_HOLDOUT` access).

## Part 26 — final decision

**`ORATS_PROMISING_BUT_UNVERIFIED`**

ORATS's field-level schema is now backed by real, independently-fetched open-source client library source
code, confirming a genuinely richer and more transparent field set than any provider in Phase 24's
scorecard, plus a real `trade_date`-scoped historical query mechanism — a meaningfully stronger practical
PIT tool than Robinhood's own capability. However, ORATS's own official documentation and pricing pages
were `EGRESS_BLOCKED` this phase, its free trial requires a credit card (`PAID_PROOF_REQUIRED`), and no
live API call, real response payload, historical-depth reconfirmation, methodology detail, or licensing
term was ever independently obtained. Every field in the Part 4 matrix is `CLAIMED_AVAILABLE_UNVERIFIED`
or `UNKNOWN` — never `VERIFIED_AVAILABLE`. A single bounded comparison against ThetaData (Part 19) found
its official docs equally `EGRESS_BLOCKED` and its actively-maintained client library deprecated in favor
of an undocumented-from-here REST API, so ORATS remains the strongest available candidate without
displacing the UNVERIFIED qualifier.

## Part 27 — purchase recommendation (NOT acted upon — awaiting human approval)

`src/options/provider_validation_decision.py::PURCHASE_RECOMMENDATION`:

- **RECOMMENDED_PROVIDER**: ORATS
- **EXACT_PRODUCT**: Delayed Data API (reported ~$99/mo tier) — the entry tier sufficient to validate the
  Part 4 field matrix before considering the pricier Live/Intraday tiers.
- **WHY**: the only source evaluated across Phase 24 and 25 with (a) a real, independently-fetched
  field-level schema, (b) an explicit historical `trade_date` query mechanism, and (c) dedicated
  dividends/splits/earnings endpoints supporting this project's existing corporate-action/earnings
  research.
- **FIELDS_AVAILABLE**: see the Part 4 matrix above — every field `CLAIMED_AVAILABLE_UNVERIFIED` pending
  a real API key.
- **HISTORICAL_DEPTH**: reported (unverified): near-EOD since 2007, 1-minute intraday since August 2020.
- **APPROXIMATE_COST**: reported (unverified, in apparent tension across sources): $99-399/mo; a $29
  14-day trial reported in one source, in tension with a separate report that the free trial requires a
  credit card.
- **TRIAL_AVAILABILITY**: `PAID_PROOF_REQUIRED` — no trial was started this phase.
- **LICENSING**: `UNKNOWN` — must be confirmed in writing before any purchase.
- **EXPECTED_RESEARCH_GAIN**: would move this project from its current Phase 19-24 hand-selected,
  2-3-strikes-per-underlying OHLC panel to a genuine multi-year, full-chain, bid/ask+volume+OI+IV+Greeks
  research dataset — directly unblocking every P22/P23-style hypothesis previously
  `INHERITED_FROM_UNDERLYING` purely for lack of real option-specific historical fields.

**This recommendation requires explicit human approval and has not been, and will not be, automatically
acted upon.** `PurchaseRecommendation.awaiting_human_approval` is `True` by construction and cannot be
constructed as `False` (`ValueError` is raised) — enforced by
`tests/test_options_provider_validation_decision.py`.

## Part 28 — final report (35 items)

1. **Objective**: determine, via the strongest available evidence, whether ORATS can deliver the historical
   options data this project needs, without purchasing anything.
2. **Constraint honored**: no subscription, no paid plan, no payment credentials, no vendor commitment.
3. **PAID_PROOF_REQUIRED triggered for**: ORATS (credit-card-gated free trial), Databento (Stripe-gated
   free credits).
4. **Not triggered / not pursued**: ThetaData's reported no-card free tier was not signed up for (bounded
   scope per Part 19; its docs were also `EGRESS_BLOCKED`, reducing the marginal value of an account).
5. **Egress blocked domains**: `orats.com` and 3 subdomains, `docs.thetadata.us`, `http-docs.thetadata.us`,
   `polygon.io`, `thetadata.net` (carried over from Phase 24).
6. **Egress open and used**: `github.com`, `raw.githubusercontent.com`.
7. **Strongest new evidence source**: `FyZyX/orats-python` — a real, MIT-licensed, working client wrapping
   the ORATS Data API.
8. **Evidence tiers used honestly, never conflated**: `OWN_LIVE_API_PROBE` (never reached), `OPEN_SOURCE_
   CLIENT_LIBRARY_SCHEMA` (this phase's main new evidence), `VENDOR_MARKETING_OR_THIRD_PARTY_SUMMARY`
   (Phase 24's tier, still used for depth/pricing rows), `NO_EVIDENCE_GATHERED`.
9. **Part 4 matrix size**: 23 rows, 0 `VERIFIED_AVAILABLE`, 0 `VERIFIED_UNAVAILABLE`, 17 `CLAIMED_
   AVAILABLE_UNVERIFIED`, 6 `UNKNOWN`.
10. **Contract identity gap**: multiplier, exercise_style, contract_status, first_listed_date, and
    last_trading_date are all `UNKNOWN` — not observed in any fetched class.
11. **Historical chain**: strongest-evidenced capability — `Strike` rows are keyed by `trade_date`, the
    strongest single piece of evidence gathered this phase.
12. **Expired contracts**: inferred, not directly confirmed — no explicit contract-state field observed.
13. **PIT capability**: a real, confirmed `trade_date` query parameter — a genuinely stronger practical
    mechanism than Robinhood's, while still short of `VERIFIED_AVAILABLE`.
14. **Bid/ask**: real fields confirmed (`call_bid_price`/`call_ask_price`/sizes, both sides); NBBO-vs-
    reconstructed methodology `UNKNOWN`.
15. **Volume/OI**: both confirmed as real, distinct fields at strike and aggregate level.
16. **IV**: unusually granular real schema — raw, bid/mid/ask, and a 21-point delta-bucketed smile.
17. **IV rank/percentile**: a dedicated `IvRank` class confirmed.
18. **Greeks**: full set (delta/gamma/theta/vega/rho/phi/driftless_theta) confirmed as real fields;
    calculation methodology `UNKNOWN`.
19. **Historical volatility**: 45+ real fields across 11 lookback windows, plus ex-earnings variants.
20. **Corporate actions**: dedicated, real `DividendHistory`/`StockSplitHistory`/`EarningsHistory`
    endpoints — the strongest corporate-action evidence of any vendor reviewed across Phases 24-25.
21. **Sample data**: none obtained — `PAID_PROOF_REQUIRED` stopped this at the credit-card gate.
22. **Schema live-validation**: not performable without a sample; reported as such, not silently skipped.
23. **Data depth**: unverified, carried over from Phase 24 (2007 EOD / Aug 2020 intraday).
24. **Pricing**: unverified, and two third-party sources are in apparent tension with each other ($99-399/mo
    tiered vs. a $29 trial) and with this phase's own credit-card-gated-trial finding.
25. **Licensing**: `UNKNOWN` — a real, unresolved gap given this project's automated-trading intent.
26. **Alternative-provider check**: bounded to ThetaData only (Part 19's own instruction); its docs are
    also blocked, its maintained client is deprecated, and its (still-fetchable) legacy schema has no
    Greeks fields — a real negative data point.
27. **Readiness scorecard total**: 35/75; no critical blocker triggered; not disqualified.
28. **Architecture preserved**: Robinhood remains the sole live/account/execution source; a historical
    provider is research/backtest-only.
29. **Ingestion flow**: 11-stage design built, provider-agnostic, reusing Phase 24's interfaces — zero
    concrete provider implementation.
30. **Certification spec**: 15 future criteria defined (`DQC-01`..`DQC-15`); nothing scored against them
    yet.
31. **No alpha/strategy/backtest work performed this phase** (Part 24's explicit prohibition, enforced by
    tests).
32. **Final decision**: `ORATS_PROMISING_BUT_UNVERIFIED`.
33. **Purchase recommendation issued**: yes — ORATS Delayed Data API, ~$99/mo, structurally marked as
    awaiting human approval and not acted upon.
34. **Tests**: 6 new files, 56 tests, all passing; full suite 1890 passed / 4 pre-existing, unrelated
    `test_orchestrator.py` failures (same 4 as Phase 24's baseline, untouched this phase).
35. **Git footprint**: purely additive — 13 new files (5 `src/options/`, 1 `scripts/`, 1 `docs/`, 6 `tests/`), zero existing files modified.

## What this phase did not do

No account created with ORATS, ThetaData, or Databento. No payment method entered anywhere. No API key
obtained or stored. No data purchased. No alpha hypothesis registered. No feature engineered from a new
data source. No strategy built. No backtest run. No paper or live order placed. No `VALIDATION`/
`FINAL_HOLDOUT` partition accessed. No provider-specific concrete store implemented — only provider-neutral
Protocols and dataclasses, exactly as Part 22 required.

**STOP AFTER PHASE 25 — awaiting explicit review before Phase 26.**
