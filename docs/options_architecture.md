# Options-Only Architecture (Phase 18)

**The system is being designed to trade options contracts only. No
equity/share trading is permitted as the final trading instrument.**

## Project objective (updated Phase 18)

- Final tradable instrument: **options contracts / defined options
  positions only.** Equities, OHLCV, SEC fundamentals, volatility, and
  market regime data may all be used as **input data** for options
  decisions; none of them may become the final trading instrument.
- Intended initial live account: **~$1,000.**
- Return objective: **aggressive** — a rough target of $20-$50 on a good
  day (~2-5% of account). **This is an aspiration, not a required
  backtest result.** No research in this or any future phase should be
  optimized toward manufacturing this number; it is not assumed
  achievable.
- **Aggressive does not mean uncontrolled.** Every future strategy must
  still quantify maximum loss, probability of ruin, exposure, liquidity,
  spread cost, slippage, expiration risk, assignment/exercise risk, and
  concentration. Risk limits are derived from a strategy's actual
  statistical behavior and this objective — never from an arbitrarily
  conservative convention chosen for its own sake, and never from
  ignoring risk because the objective is aggressive.

## Options-only execution restriction

This codebase is **already, by construction**, options-only at the
execution layer — confirmed by real repository inspection, not assumed:

- `src/execution/orders.py`'s `OrderLeg` **requires** `option_id: str`.
  There is no `shares`/`equity_symbol` field anywhere on `OrderLeg` or
  `OrderRequest` — a request shaped like "BUY AAPL 100 SHARES" cannot be
  constructed through this shape at all.
- `place_equity_order`/`review_equity_order`/`cancel_equity_order` are
  named **exactly once** in the entire `src/` tree — a docstring in
  `src/market/hood_client.py` documenting their deliberate absence. They
  are never actually called anywhere.
- `src/execution/gateway.py`'s `LiveExecutionGateway._place_pending()` is
  documented as "the ONLY method in this entire codebase that calls
  `place_option_order`."

`src/execution/asset_class_restriction.py` formalizes this as an
explicit, named, tested invariant: `ASSET_CLASS_RESTRICTION =
"OPTIONS_ONLY"` and `assert_options_only()`, a defense-in-depth guard.
No live/paper options trading is enabled by this phase.

## Options data architecture (`src/options/`)

New research-layer package, parallel to `src/data/`'s equity/SEC
architecture, distinct from `src/market/models.py`'s live-trading
`OptionQuote` and `src/position_manager/models.py`'s live single-leg
`OpenPosition` (both unchanged):

- **`instrument.py`** — `OptionContract`: underlying, option_id, call/put,
  strike, expiration, multiplier (confirmed 100 for every contract
  probed), exercise_style/settlement_type (confirmed **never** supplied
  by this source — stay `None`, never guessed), currency, provenance,
  and a corporate-action `is_standard_deliverable`/`deliverable_note`
  pair for non-100 adjusted contracts.
- **`chain.py`** — `OptionChainObservation` + `OptionsFieldStatus`
  (OBSERVED / DERIVED / ESTIMATED / UNAVAILABLE), tracked per field —
  never a blanket "this record is observed."
- **`greeks.py`** / **`implied_volatility.py`** — schema only, no
  solver. `GreeksProvenance`/`IVProvenance`
  (OBSERVED_FROM_SOURCE/DERIVED_FROM_MODEL/UNAVAILABLE for Greeks;
  OBSERVED/DERIVED/UNAVAILABLE for IV) with required metadata (model,
  inputs, volatility/rate/dividend assumptions, version, timestamp)
  whenever DERIVED — structurally enforced, never allowed to pretend a
  derived value is observed.
- **`liquidity.py`** — spread, spread%, volume, open interest, quote
  age. Architecture only; no thresholds chosen.
- **`point_in_time.py`** — `contract_existed_at()` returns `None` (never
  a guessed `True`) whenever a contract's first-listed date is unknown —
  which is every contract this source has ever returned. No
  survivorship-bias-free options universe is claimed.
- **`quality.py`** — bid>ask, negative bid/ask, invalid strike,
  expired-contract-observed-after-expiration, inconsistent
  multiplier/call-put/expiration/strike, invalid Greeks (delta outside
  [-1,1], negative gamma/vega), extreme IV (warning only), duplicate
  contract/timestamp, timestamp ordering.
- **`store.py`** — `OptionsDataStore`: `get_contract`/`get_chain` are
  real, working methods over whatever is persisted.
  `get_historical_chain`/`get_as_of_chain` **always raise**
  `HistoricalOptionsDataUnavailableError` — the interface exists and is
  documented, but does not pretend to work (statically verified: both
  method bodies contain `raise`). Also satisfies Phase 15's generic
  `OptionsStore` Protocol for interop.
- **`position.py`** — `OptionsPosition` (multi-leg) +
  `analyze_position_risk()`: correctly computes max loss/profit for
  single-leg long/short call/put and same-expiration vertical spreads;
  returns `(None, None, "UNSUPPORTED_STRUCTURE: ...")` for anything else
  (3+ legs, mismatched expirations) rather than guessing a number.
- **`capability_audit.py`** — the real, evidence-backed
  `OPTIONS_CAPABILITY_MATRIX` (see below).

## The real historical options data capability audit

Every claim below is backed by a real, read-only probe made during this
phase's development (`get_option_chains`, `get_option_instruments`,
`get_option_historicals`, `get_option_quotes`) — never inferred from
tool names.

### What IS available (a genuine, decisive finding)

- **Contract identity for expired/historical contracts.**
  `get_option_instruments(chain_symbol=..., state="expired")` returns
  real contracts spanning **2017-09-15 through 2026** for AAPL, both
  with and without an `expiration_dates` filter — a real, enumerable
  contract-listing history.
- **Historical option OHLC price bars.** `get_option_historicals` on a
  real AAPL $175 call expiring 2022-01-21 (well inside the 2021-2023
  discovery window) returned rich, volatile, economically genuine daily
  price action (open $3.90 decaying to close $0.01 as expiration
  approached) — clearly real, not placeholder data.
  - **Caveat:** a deep-OTM contract over the same window showed a flat
    $0.01 series every day with no `interpolated` flag either way.
    Plausible (tick-floor pinning) but not independently confirmed
    genuine — treat deep-OTM historical series with caution; liquid,
    near-the-money contracts are the safer case.

### What is NOT available (confirmed absent, not assumed)

- **Volume** — never available, any contract, any date. The tool's own
  guide text states explicitly: *"Option bars carry no volume."*
- **Bid/ask** — a real probe of `get_option_quotes` against a real
  expired contract returned `results=[]` (empty). This endpoint is
  live-only, full stop.
- **Open interest, implied volatility, Greeks** — all confirmed present
  in a **live** `get_option_quotes` response (real probe: delta,
  gamma, theta, vega, rho, and implied_volatility all populated) but
  absent from `get_option_historicals`' bar shape. Live-only.

### An unclaimed extension point

The real live `get_option_quotes` payload is far richer than this
codebase currently parses: `bid_size`, `ask_size`, `break_even_price`,
`chance_of_profit_long`/`chance_of_profit_short`, and all five Greeks
plus IV are present in the raw response but not surfaced by
`src.market.models.OptionQuote` today. This is documented, not
implemented — extending the live path is out of scope for this
research-layer phase.

## Final decision: OPTIONS_RESEARCH_READY_WITH_LIMITATIONS

Real, usable historical option **price** data exists for the 2021-2023
discovery window and was independently verified — this is **not**
`HISTORICAL_OPTIONS_DATA_INSUFFICIENT`. Directional, mark-at-close
options research (e.g., long calls/puts priced off historical closes,
held to a target/stop/expiration) is feasible on real data.

What is **not** feasible without further data-source work:
execution-realism- or liquidity-sensitive research. Historical bid/ask,
volume, open interest, IV, and Greeks are all confirmed unavailable for
any past date — a future backtest must **assume** a spread/slippage
model rather than observe one, and must not claim liquidity-based
sizing was validated against real historical liquidity data.

## Corporate actions

`OptionContract.is_standard_deliverable`/`deliverable_note` represent a
split/merger-adjusted contract (non-100 multiplier, or a non-standard
deliverable) explicitly — `is_standard_deliverable=False` without a
`deliverable_note` is a construction error (Part 15: no unexplained
adjustments). No contract observed this phase carried a non-100
multiplier; the field exists for when one does.

## Reproducibility

Every `OptionContract`/`OptionChainObservation` carries `source`,
`retrieval_timestamp`, and `schema_version`. `OptionsDataStore` follows
the same JSONL, fail-closed persistence convention as
`HistoricalDataStore`/`SECFilingStore`.

## Remaining limitations

- No real historical bid/ask/volume/OI/IV/Greeks exist for any past
  date — confirmed, not assumed.
- Contract identity confirms existence, not a first-listed timestamp —
  PIT correctness before expiration is honestly `None` (unknown), never
  guessed `True`.
- `analyze_position_risk` handles single-leg and 2-leg vertical spreads
  only; anything more complex is explicitly `UNSUPPORTED_STRUCTURE`.
- No Greeks/IV solver exists — only the schema to represent one's output
  once computed.
- No options alpha hypothesis has been tested and no trading strategy
  has been created or modified this phase.
