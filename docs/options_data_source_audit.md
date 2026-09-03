# Historical Options Data Expansion & Alpha-Source Audit (Phase 24)

Phase 23 closed with an honest null-ish result on `P22-OPT-013`: real,
option-specific, but non-directional and not currently tradeable. Five
phases of OHLC-derived feature mining (19-23) have now shown the same
pattern repeatedly — apparent relationships that are inherited from the
underlying, mechanically amplified, regime/expiration-concentrated, or
statistically fragile once actually pressed. Phase 24 steps back from
alpha mining entirely and asks the infrastructure question underneath
all five phases: **is the historical options DATA itself the limiting
factor, and if so, what should this project actually get next?**

This phase is a research/audit only. No new hypothesis, no backtest, no
strategy, no order, no vendor purchase, no large dataset download.

## Headline answer

**Recommendation: B — obtain a better historical options dataset before
additional alpha research**, with one immediately actionable, zero-cost
sub-step available right now (Part 24 detail below). Final data-capability
classification: **`HISTORICAL_OPTIONS_DATA_PARTIALLY_AVAILABLE`**
(current Robinhood connector) — real OHLC + full historical chain
enumeration, but bid/ask, volume, open interest, IV, and Greeks are
permanently `UNAVAILABLE` from this source, and point-in-time contract
existence remains `HISTORICAL_CONTRACT_EXISTENCE_UNKNOWN`.

## Part 2 — Robinhood capability audit: real probes, not inference

This phase reused Phase 18's already-real `OPTIONS_CAPABILITY_MATRIX`
(`src.options.capability_audit`) and extended it with 5 new real probes
this phase (`src.options.historical_depth_audit`), never assuming
historical availability from a live capability existing.

**New this phase — decisive finding:** `get_option_instruments(chain_symbol=..., state="expired", expiration_dates=..., type=...)`,
called *without* specifying a strike, returns the **complete, paginated
strike ladder** for that expiration — real contract IDs, strikes, and
metadata for every strike that ever existed at that expiration. A probe
of AAPL puts at the 2022-03-18 expiration returned **all 78 real
strikes** ($70–$300) in one enumeration. Phase 19/20 hand-selected only
2–3 strikes per underlying per expiration when building their research
panels — **the full historical chain has been enumerable, at zero
additional cost, this entire time, and has gone unexploited.**

Historical depth was bracketed with 5 real probes: SPY empty at
2016-01-15 and 2017-01-20, populated (78 real contracts) at 2018-01-19;
AAPL populated at 2019-01-18 with real daily OHLC confirmed back to
2018-11-01 (a genuinely volatile, non-fabricated series, open $71.70 →
close $0.01 as the contract decayed). This is consistent with
Robinhood's own options-trading launch (December 2017) and roughly
matches Phase 18's separate AAPL anchor (2017-09-15).

**Reconciling this with Phase 19/20's `UNKNOWN_EXISTENCE` finding (Part 7):**
chain enumeration proves a contract **existed and eventually expired**
— it does NOT prove the contract was **listed and tradable on an
arbitrary earlier date T**, because no `first_listed_date`/
`first_trade_date`/`created_at` field exists anywhere in the
`get_option_instruments` response schema (confirmed structurally across
every probe this phase and Phase 18's). `HISTORICAL_CONTRACT_EXISTENCE_UNKNOWN`
therefore remains the **correct** point-in-time classification — chain
enumeration is a real, separate, and previously underused lever for
*expanding OHLC coverage*, not a fix for PIT existence verification.
See `POINT_IN_TIME_EXISTENCE_RECONCILIATION` for the exact reasoning.

Reconfirmed this phase (matching Phase 18 exactly): `get_option_quotes`
against a real expired contract returns `results: []` — genuinely
empty, live-only, no historical bid/ask/OI/IV/Greeks archive exists
anywhere behind it. `get_option_historicals`' own guide text states
explicitly: *"Option bars carry no volume."* `get_option_chains` only
ever lists **current/future** expirations (2026-09 through 2028-12 for
AAPL, probed this phase) — it is not a historical-chain tool at all;
`get_option_instruments(state="expired")` is the real path to
historical contract identity.

## Part 3 — Requirements matrix

| Category | Field | Robinhood status |
|---|---|---|
| Contract identity | id/underlying/call-put/strike/expiration/multiplier | ✅ real, both live and expired |
| Contract identity | exercise style | Present as an option-order concept elsewhere in this codebase; not itemized in `get_option_instruments`'s own response fields |
| Contract identity | first-listed/first-observable date | ❌ no field exists |
| Contract identity | delisting/expiration status | ✅ `state`/`tradability` fields, real |
| Market data | OHLC | ✅ real, confirmed to ~2018 |
| Market data | bid/ask/sizes/last trade/trade size/volume/OI | ❌ none available historically |
| Option analytics | IV/delta/gamma/theta/vega/rho | ❌ none available historically (all confirmed present LIVE only, and not currently parsed into this codebase's `OptionQuote` model even for the live case — a separate, already-documented Phase 18 finding) |
| Underlying | OHLC/volume/corporate actions | ✅ OHLC real (this project's existing equity pipeline); corporate actions handled manually per-phase (Phase 20's GOOGL/AMZN/META split handling), not via a structured feed |
| Microstructure | spread/midpoint/depth/liquidity | ❌ none available historically (no bid/ask to derive them from) |
| Provenance | source/retrieval/publication timestamps, adjustment/interpolation/confidence status | Now formally representable via `OptionDataProvenance` (this phase's new architecture, Part 16) — not previously a first-class concept in this codebase |

## Part 4/5 — External vendor research

Nine vendors researched via web search/documentation (one, `orats.com`,
`thetadata.net`, and `polygon.io` were unreachable for direct fetch this
phase — network egress restrictions — so those rows rely on search-result
summaries and third-party comparison articles, honestly labeled
`VENDOR_DOCUMENTATION_OR_THIRD_PARTY_SUMMARY` rather than presented as
independently verified). Full detail in `src.options.vendor_scorecard`
and the scorecard table below. **No vendor was purchased, no API key
was used, no dataset was downloaded.**

## Part 6/7/8/9/10/11/12 — the pattern across every real vendor reviewed

- **Expired contracts:** every serious vendor (Polygon/Massive, ThetaData,
  CBOE DataShop, Databento, ORATS, OptionMetrics) claims coverage;
  OptionMetrics IvyDB is explicitly designed to be survivorship-bias-free.
  None independently confirmed this phase (no API keys used).
- **Point-in-time existence:** OptionMetrics IvyDB is the strongest
  claimed candidate (academic gold standard, 1996+); ORATS's
  "any-minute chain reconstruction" framing is the most concretely
  PIT-shaped of the accessible-priced vendors.
- **Bid/ask:** every serious vendor except Tradier's own native API
  claims real historical bid/ask (Tradier gets it only via an ORATS
  partnership — not a genuinely separate source).
- **Volume vs. open interest:** kept explicitly distinct throughout the
  scorecard (Part 9's instruction) — several vendor claims name one but
  not the other explicitly in the sources reviewed; flagged as "not
  itemized" rather than assumed present.
- **IV/Greeks:** ThetaData is the most methodologically transparent —
  Greeks *calculated* (bisection IV) from real NBBO + the contemporaneous
  underlying tick, not a vendor black box. ORATS and OptionMetrics both
  claim smoothed/cleaned IV surfaces. Databento (raw OPRA tape) does
  **not** supply IV/Greeks directly — they'd need to be computed
  downstream from the raw feed.
- **Chain snapshots:** ORATS's "go back in time to the options chain
  for any minute" and OptionMetrics's core design are the two strongest
  claimed chain-reconstruction capabilities.
- **Intraday:** ThetaData, Databento, ORATS (since Aug 2020), CBOE
  DataShop (trade-by-trade), and QuantConnect/AlgoSeek (minute
  resolution since 2010) all claim intraday depth.

## Part 13 — minimum credible dataset: not currently met by Robinhood alone

Robinhood alone cannot meet the "minimum acceptable research dataset"
bar (Part 13) because it structurally lacks bid/ask, volume, OI, and IV
— not a depth problem, a *field* problem no amount of additional
fetching fixes. Several external vendors (ORATS, OptionMetrics, CBOE
DataShop, Databento, Polygon/Massive) claim to meet or exceed the
3-year-minimum / 5-year-ideal bar with the full required field list —
**unverified this phase**, and each would need direct evaluation before
being relied upon.

## Part 14/15 — data quality & survivorship

Robinhood's real OHLC has one already-documented quality caveat from
Phase 18: a deep-OTM contract's historical series can sit flat at the
$0.01 tick floor for many consecutive days with no `interpolated` flag
either way — plausible (real tick-floor pinning, and Phase 19 built an
entire negative-control hypothesis, P19-OPT-011, around exactly this
phenomenon) but not distinguishable from a data gap by the
`interpolated` flag alone. No vendor's data-quality practices (duplicate
handling, crossed/locked markets, corporate-action adjustment) were
independently tested this phase — Part 14's formal quality score is not
yet computable without a real data sample from each candidate.
Robinhood is **not** `SURVIVORSHIP_BIASED` in the strict sense (expired
contracts ARE enumerable and their OHLC IS real) but **is** point-in-time-blind
(Part 7) — a distinct, narrower limitation.

## Part 16 — provider-agnostic architecture (built this phase)

New, additive `src/options/` modules, **no vendor implemented**:

- **`historical_data_interfaces.py`**: `OptionDataProvenance` (source,
  retrieval/publication timestamps, historical-vs-live semantics,
  adjustment status, interpolation flag, confidence status — Part 3's
  full provenance field list); `ContractIdentity` and `ContractLifecycle`
  dataclasses (the latter's date fields are all `Optional`, never
  approximated from an OHLC series — Part 7's explicit prohibition,
  enforced structurally: constructing a `ContractLifecycle` requires an
  explicit `status`, no silent default to `ACTIVE`); and 8 `typing.Protocol`
  interfaces — `HistoricalOptionContractStore`, `HistoricalOptionChainStore`,
  `ContractLifecycleStore`, plus `HistoricalOptionQuoteStore`/
  `TradeStore`/`GreeksStore`/`IVStore`/`OpenInterestStore`, the last 5
  deliberately reusing Phase 15's existing generic `ProvenancedObservation`
  shape (a natural key + field name + value + provenance) rather than
  inventing five new bespoke schemas Part 16 didn't actually need
  distinct shapes for.
- **`historical_depth_audit.py`**: this phase's real probe evidence,
  additive to Phase 18's matrix (`extended_capability_matrix()` — proven
  by test to contain every original Phase 18 row unchanged, plus exactly
  one new row).
- **`vendor_scorecard.py`**: the Part 17 scorecard, `VENDOR_SCORECARD`
  (12 rows), each with an explicit `verification_level` so no
  web-researched vendor claim is ever presented with the same confidence
  as a real MCP probe.

## Part 17 — vendor scorecard

| Source | Bid/Ask | OI | IV | Greeks | Expired | Chain | PIT | Cost | Overall |
|---|---|---|---|---|---|---|---|---|---|
| **Robinhood (current)** | ❌ | ❌ | ❌ | ❌ | ✅ | Partial | ❌ | Free | **B** |
| **ORATS** | ✅* | ~ | ✅* | ✅* | ~* | ✅* | ✅* | $99–399/mo* | **A** |
| Polygon.io / Massive | ✅* | ✅* | ✅* | ✅* | ~ | ✅* | ~ | $29–399+/mo* | B |
| ThetaData | ✅* | ~ | ✅* | ✅* | ~ | ~ | ~ | ~$25/mo+* | B |
| Cboe DataShop | ✅* | ~ | ✅* (add-on) | ✅* (add-on) | ~ | ~ | ~ | Contact/academic 50% off | B |
| Databento (OPRA) | ✅* | ~ | ❌ (raw tape only) | ❌ (raw tape only) | ~ | ✅* | ~ | Pay-as-you-go* | B |
| OptionMetrics IvyDB | ✅* | ✅* | ✅* | ~ | ✅* | ✅* | ✅* | Institutional/WRDS | C |
| EODHD | ~ | ~ | ✅* | ✅* | ~ | ~ | ~ | ~$99.99/mo* | C |
| QuantConnect (AlgoSeek) | ~ | ~ | ✅* | ✅* | ~ | ✅* | ~ | Platform-bundled | C |
| Intrinio | ~ | ~ | ~ | ~ | ~ | ~ | ~ | Institutional ("expensive") | C |
| Tradier (via ORATS) | ✅ (ORATS only) | ~ | ✅ (ORATS only) | ✅ (ORATS only) | ~ | ~ | ~ | Brokerage-based | D |
| Alpha Vantage | ~ | ~ | ~ | ~ | ~ | ~ | ~ | $49.99–249.99/mo* | UNSUITABLE |

`✅` = verified or clearly claimed, `~` = not itemized in sources
reviewed, `❌` = confirmed or clearly stated unavailable, `*` = claim
from vendor documentation / third-party summary, **not independently
verified this phase**. Full detail (18 columns) in
`src.options.vendor_scorecard.VENDOR_SCORECARD`.

## Part 18 — Robinhood-specific conclusion (definitive, evidence-based)

- **What it can provide historically:** real daily (and likely intraday
  — not probed this phase for options specifically) OHLC price bars,
  and complete historical CHAIN ENUMERATION (every strike that ever
  existed at a given expiration), both confirmed back to ~2018.
- **What it can provide only live:** bid/ask/sizes, volume, open
  interest, implied volatility, delta/gamma/theta/vega/rho — all
  confirmed present in a real live `get_option_quotes` response, all
  confirmed absent from every historical path.
- **What cannot be obtained at all, from this source, at any date:**
  a genuine point-in-time "was this contract listed on date T" answer
  (no first-listed-date field exists), and — as a consequence — a true
  survivorship-free chain SNAPSHOT at an arbitrary historical timestamp
  (only "eventually reached this state" is knowable, not "was tradable
  as of this exact date").
- **Deepest historical date reachable:** confirmed real data to at
  least 2018-01-19 (SPY) / 2018-11-01 (AAPL daily bars); consistent with,
  not necessarily identical to, Robinhood's real options-trading launch
  (Dec 2017). Untested dates between the last-empty and first-populated
  probes remain genuinely unknown, not assumed either way.
- **Expired contracts enumerable:** **YES**, confirmed, and currently
  underexploited relative to what Phase 19-22 actually fetched.
- **Historical bid/ask/IV/OI/Greeks recoverable:** **NO**, confirmed,
  structurally (the only endpoint carrying any of these is a live-only
  snapshot tool with no time-range parameter).
- **Historical chains reconstructable:** **PARTIALLY** — full strike
  ladder per expiration yes; as-of-an-arbitrary-timestamp snapshot no.

## Part 19/20 — audit discipline followed

No dataset was downloaded beyond the ~10 small, targeted probes needed
to verify these claims (well under Part 19's "tiny probe" allowance).
No new hypothesis was registered, no backtest run, no parameter
optimized, no P&L computed, no paper or live order placed, no holdout
accessed — mechanically verified by `tests/test_phase24_safety.py`.

## Part 21 — capital and future objective, unaffected

Nothing in this phase changes the ~$1,000-account, quantitative-not-daily-target
objective (Part 21) — this phase is purely about whether the DATA
exists to eventually support that objective more rigorously than OHLC
alone can.

## Part 23 — final classification

**`HISTORICAL_OPTIONS_DATA_PARTIALLY_AVAILABLE`** (current Robinhood
connector, standalone). Real, usable OHLC + full chain-enumeration
capability, but structurally missing every field (bid/ask/volume/OI/IV/
Greeks) a realistic options-quant research program eventually needs, and
permanently blind to point-in-time contract existence.

Per-provider classifications: see the scorecard above — **ORATS: A**;
Robinhood, Polygon/Massive, ThetaData, CBOE DataShop, Databento OPRA:
**B**; OptionMetrics IvyDB, EODHD, QuantConnect, Intrinio: **C**;
Tradier: **D**; Alpha Vantage: **UNSUITABLE**. All non-Robinhood grades
are provisional pending direct verification.

## Part 24 — final recommendation

**B: obtain a better historical options dataset before additional alpha
research** — with one important nuance the letter grade alone doesn't
capture: **there is a zero-cost, zero-new-integration step available
right now.** Robinhood's `state="expired"` chain enumeration has gone
unused since Phase 19 — building a genuinely broader OHLC-only panel
(more strikes per expiration, more expirations, more underlyings, back
to ~2018 instead of the current 2021-2023 window) costs nothing and
requires no new vendor relationship. That alone will not solve the
bid/ask/IV/Greeks/OI gap Phase 19-23 have run into repeatedly, but it
is real, available, and unexploited.

**Best available external candidate: ORATS** (`orats.com`, Data API /
Intraday Data API products).

- **Exact dataset/product:** ORATS Data API (near-EOD, since 2007) and/or
  Intraday Data API (1-minute, since Aug 2020) — "any-minute chain
  reconstruction," SMV (Smoothed Market Value) cleaned bid-ask quotes
  and Greeks.
- **Exact fields needed:** historical bid/ask, SMV Greeks (delta/gamma/
  theta/vega/rho), SMV/interpolated IV, chain-shaped historical access.
- **Approximate historical depth:** EOD since 2007 (~18 years); 1-minute
  intraday since August 2020 (~5 years).
- **Why it is better:** it is the only vendor reviewed this phase that
  concretely claims ALL of: real historical bid/ask, full Greeks/IV,
  chain-shaped historical (any-minute) reconstruction, AND a published,
  individual-researcher-accessible price point — every other vendor
  reviewed either lacks one of these (Databento's raw tape has no
  IV/Greeks; Tradier has no native bid/ask), costs enterprise/
  institutional money with no public price (OptionMetrics, CBOE
  DataShop, Intrinio), or has an unverified field list (Polygon/Massive,
  ThetaData, EODHD, QuantConnect).
- **Estimated cost (reported, not independently verified — orats.com
  was unreachable for direct fetch this phase):** Delayed Data API
  $99/month (20,000 requests); Live Data API $199/month; Live Intraday
  API $399/month; a $29 14-day trial reported to exist.
- **What the project would gain:** genuine historical bid/ask (enabling,
  for the first time, real `EXECUTION_REALISTIC_RESEARCH` instead of
  `MARK_TO_MARKET_HISTORICAL_RESEARCH` for every past phase's cost
  sensitivity work), real historical IV/Greeks (removing "Do not
  reconstruct Greeks and pretend they were observed" as a permanent
  research ceiling), and a genuine chain-reconstruction capability that
  could finally test point-in-time contract selection rather than only
  a hand-picked panel.

**This vendor was NOT purchased.** This is a recommendation for the
project's operator to evaluate directly (starting with the $29 trial,
if that reported figure is accurate), not an action taken this phase.

## Whether alpha research should wait for better data

**Yes, for anything that needs bid/ask, IV, Greeks, or open interest** —
five phases (19-23) have now independently hit this exact ceiling, most
recently and concretely in Phase 23's finding that `P22-OPT-013`'s
tradeable-rule cost/execution analysis had to be built entirely on
ASSUMPTION-labeled spread stress rather than a single real historical
spread observation. **No, for the zero-cost chain-enumeration expansion**
described above — that can proceed immediately without waiting on any
vendor decision, though per Part 20 it is explicitly NOT part of this
phase's own scope (infrastructure/audit only).

## What this phase did not do

No strategy was created. No order (paper or live) was placed. No
validation/holdout data was accessed. No vendor was purchased or
API-tested. No large dataset was downloaded. No new alpha hypothesis was
registered. Mechanically verified by `tests/test_phase24_safety.py`.
