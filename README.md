# HOOD Options Trading System

An automated options trading system built on top of the HOOD (Robinhood)
MCP connection:

```
MARKET SCAN → FIND SETUP → ENTRY → MONITOR EVERY ~5 MINUTES →
HOLD / EARLY EXIT (momentum OR trailing-stop) / TARGET EXIT / STOP →
LOG EVERYTHING → SYNC WITH ROBINHOOD
```

**Today, this system runs in `TRADING_MODE=paper` only** — the real `.env`
in this deployment has `TRADING_MODE=paper` and no recurring live loop has
been started. Live execution (real, real-money orders) **is implemented**
in `src/execution/gateway.py`, but is a separate, deliberate opt-in gated by
two independent switches (`TRADING_MODE=live` and
`LIVE_TRADING_CONFIRMED=true`) that are both off by default and off in the
real deployment right now. See "The execution layer" and "Going live" below
for exactly how it works and what flipping it on would mean. See "How the
~5-minute cadence actually works" for an honest account of what "automated"
means on this platform (agent-mediated, not a headless daemon).

## Safety model, in one paragraph

`TRADING_MODE` defaults to `paper`. `src/execution/gateway.py` is the single
choke point every order-related action must pass through. In paper mode it
returns a `PaperExecutionGateway` that only ever simulates a fill and writes
it to the audit log — it can never call a real order tool, period. In live
mode it returns a `LiveExecutionGateway`, which still can't construct at all
unless `LIVE_TRADING_CONFIRMED=true` is *also* set (a second, independent
switch), and which routes every single order — every entry AND every exit —
through exactly one method, `_place_pending()`, the only place in this
entire codebase that calls `place_option_order`. Whether that method runs
immediately (deterministic risk rules only — see `LIVE_AUTO_EXECUTE`) or
waits for a separate, explicit confirmation step is the one behavior
`LIVE_AUTO_EXECUTE` controls; either way, every order is written to the
audit log the moment it's proposed, decided, and (if it happens) placed —
see "The execution layer" below.

## Project layout

```
src/
  config/            Settings (env-driven) + shared constants
  market/            Market data (verified live against real HOOD responses), indicators, scanning support
  strategy/          Decision model, momentum-evidence scoring, scanning framework + a concrete strategy
  position_manager/  Open-position model, evaluator (+ dynamic/trailing exit engine), monitor, paper ledger, real-position sync
  risk/              The 11-rule risk-control framework + persisted daily state (UNCHANGED throughout this build)
  execution/         Order shapes + the paper/live execution gateway (the safety boundary — see below)
  logging/           Structured decision/audit logging + general app logging
  orchestrator.py    Ties one full cycle together: scan → entry → monitor → exit → log → sync
  live_bridge.py     The manual live-data bridge + runbook for running a cycle, and the live-order confirmation bridge (see below)
tests/               One test module per src package, 270 tests total
scripts/             run_cycle.py (paper/live cycle driver), verify_live_readiness.py
                     (account preflight), confirm_pending_order.py / reject_pending_order.py
                     (the live-order confirmation bridge — see below)
.env.example         All configuration variables, documented
```

### `src/config/`
- **`constants.py`** — fixed values that aren't meant to be configured (contract
  multiplier, trading weekdays, valid `TRADING_MODE` values).
- **`settings.py`** — `Settings`, an immutable, validated snapshot built from
  environment variables (with a minimal built-in `.env` loader — no external
  dependency). Every risk threshold, market-hours boundary, and log path
  lives here. `Settings.is_paper` / `Settings.is_live` are the only
  properties the rest of the codebase should use to branch on trading mode.

### `src/market/`
- **`models.py`** — `OptionQuote`, `EquityQuote`, `PriceBar`, `MarketSnapshot`,
  `UnderlyingSnapshot` (equity-only data for scanning, before a contract is
  chosen). Field names and nesting were **verified against real, live,
  read-only HOOD MCP responses** (SPY; a SPY $780 call), not guessed —
  several assumptions from an earlier draft turned out wrong (the `{"data":
  {...}}` wrapper, nested `quote`/`close` objects, options having no
  `last_trade_price` field, bar field names) and were corrected against the
  real payloads. See `hood_provider.py`'s module docstring for the full
  account and `tests/test_hood_provider_real_shapes.py` for regression
  tests built directly from the captured responses.
- **`indicators.py`** — dependency-free EMA, RSI, MACD, VWAP, higher-highs/
  lower-highs, breakout-continuation and failed-breakout detection, spread%,
  and liquidity checks. Pure functions, fully unit-tested.
- **`data_provider.py`** — the `MarketDataProvider` abstract interface:
  `get_market_snapshot` (one option contract + its underlying),
  `get_underlying_snapshot` (equity-only, for scanning),
  `get_option_expirations` (cheap — avoids pulling an underlying's entire
  chain to find a DTE window), `get_option_chain_candidates` (paginated
  contract lookup). `NotConfiguredMarketDataProvider` fails loudly instead
  of returning fabricated data when nothing is wired up.
- **`hood_client.py`** — `HoodToolClient`, the typed seam to the real HOOD
  MCP tools. Nothing in this codebase can call an MCP tool directly (only
  the orchestrating agent's own tool-call interface can) — this Protocol is
  what gets injected, real or faked in tests. No implementation of it, real
  or fake, has an order-placement method.
- **`hood_provider.py`** — `HoodMarketDataProvider`, the real implementation.
  Critical data (quotes) raises typed errors on failure; supplementary data
  (bars) degrades to empty/None with a warning rather than aborting a
  cycle. RSI/MACD/EMA/VWAP are computed locally from fetched OHLCV bars
  (not from `get_equity_technical_indicators`, whose response shape was
  never verified). Freshness uses the tools' own timestamps, picking the
  *oldest* of the fetch time and both quotes' real timestamps — a quote
  Robinhood itself hasn't refreshed is correctly flagged stale even if the
  call just returned. A response row for a symbol/contract the API can't
  resolve is silently *omitted*, not a null placeholder — confirmed live;
  the parsers require an actual match rather than falling back to
  "whatever came back," which an earlier version got wrong.
- **`errors.py`** — `MarketDataError` and subclasses (`QuoteUnavailableError`,
  `InvalidQuoteError`, `OptionContractNotFoundError`, `HoodToolError`).

### `src/strategy/`
- **`decision.py`** — the `Decision` enum (`BUY`, `HOLD`, `EXIT`,
  `TARGET_EXIT`, `STOP_EXIT`, `NO_TRADE`), `TradeThesis` (with
  `to_dict`/`from_dict` for persistence), `DecisionResult`.
- **`evidence.py`** — `MomentumEvidence` + `evaluate_momentum()`, the scoring
  engine that turns a bundle of technical signals into `STRENGTHENING /
  STABLE / WEAKENING / REVERSING / INSUFFICIENT_DATA`. Deliberately requires
  *multiple corroborating signals* before calling a move weakening — a
  single soft blip (RSI ticking down a point, volume dipping slightly) is
  not enough, so the system never exits on a mere pause.
- **`base.py` / `scanner.py`** — `Strategy` (abstract), `SetupCandidate`, and
  `StrategyScanner`, which runs registered strategies and produces a ranked
  candidate list or an explicit `NO_TRADE`.
- **`momentum_breakout.py`** — `MomentumBreakoutStrategy`, the first concrete
  strategy: bullish, calls-only (the structure detectors in `indicators.py`
  are asymmetric — upside breaks only; a mirrored bearish/put strategy is
  legitimate future work, not something half-implemented here). Requires a
  confirmed breakout *and* a `STRENGTHENING` momentum assessment before
  even looking for a contract (scanning is more conservative than holding);
  resolves the nearest expiration in a configurable DTE window, the
  nearest-the-money strike, and applies liquidity/spread pre-filters before
  proposing a `SetupCandidate` — final gating is still `RiskManager`'s job.

### `src/position_manager/`
- **`models.py`** — `OpenPosition` (entry price, thesis, target, stop,
  expiration) with `unrealized_pnl_usd`/`unrealized_pnl_pct` helpers
  (rounded to the cent) and `to_dict`/`from_dict` for persistence.
- **`evaluator.py`** — `PositionEvaluator`, the core HOLD/EXIT/TARGET_EXIT/
  STOP_EXIT decision tree: thesis invalidation and hard stop-loss always win;
  expiration risk is checked next; **then a deterministic, price-only
  dynamic/trailing exit check** (see below); then insufficient-data fails
  safe to HOLD; then a profitable position with corroborated
  weakening/reversing momentum evidence EXITs *regardless of whether the
  profit target was reached*; reaching the target only forces `TARGET_EXIT`
  if momentum isn't still strengthening (if it is, the position HOLDs past
  the target too). This is the exact behavior from the spec's $0.95→$1.05
  example.
  > **Dynamic/trailing exit**: once a position's unrealized gain reaches
  > `TRAILING_ARM_FRACTION` (default 0.5) of the distance from entry to its
  > profit-target price, trailing protection "arms". From then on, if price
  > gives back `TRAILING_GIVEBACK_FRACTION` (default 0.3) of the gain made
  > from entry to the position's peak price so far, it exits immediately —
  > independent of the momentum-evidence engine, and even when there isn't
  > enough momentum data to classify the move at all. Worked example, straight
  > from the requirement: entry $0.95, target $1.15 (a $0.20 range) — price
  > reaching $1.05 arms it (50% of the way to target); price then falling
  > back to $1.02 (giving back 30% of the $0.10 gained) exits there, rather
  > than waiting for $1.15. See `_evaluate_trailing_exit()`.
- **`peak_tracker.py`** — `PeakPriceStore`, a tiny JSON-file-backed
  option_id → highest-price-seen ledger that gives the trailing-exit check
  real memory across cycles (needed because real, Robinhood-synced
  positions are rebuilt fresh every cycle — see `hood_sync.py` — with no
  natural place of their own to carry state forward). Fails closed on a
  corrupted file, like every other store in this codebase.
- **`monitor.py`** — `PositionMonitor.run_once()` performs one
  fetch-evaluate-log cycle for one position — updating its peak price via
  `PeakPriceStore` first — and, for an EXIT/TARGET_EXIT/STOP_EXIT decision,
  builds and submits a sell-to-close `OrderRequest` through whichever
  execution gateway this cycle is running with (paper: always a simulated
  fill; live: a pending approval, or an immediate placement under
  `LIVE_AUTO_EXECUTE` — see "The execution layer"). `acted=True` and an
  `order_result` come back only once the position is actually closed
  (`simulated_fill` or `placed`), never for a live `pending_approval`. Pass
  `simulate_exit=False` to decide-and-log only without submitting an order
  at all — used for real positions this system doesn't consider its own to
  act on (see `LiveBotPositionsStore` below). **There is no timer or
  scheduler in this code** — `is_within_monitoring_window()` just tells a
  caller whether now is a sensible time to act, converting to the
  configured market timezone itself (a real bug, caught during live
  verification, made a raw UTC `now` compare against ET boundary times
  directly — fixed).
- **`store.py`** — `PaperPositionStore`, the JSON-backed ledger of positions
  *this system* opened via simulated paper entries — the only record of
  them, since Robinhood has no knowledge of a simulated trade. Fails closed
  on a corrupted file, like `risk/store.py`.
- **`hood_sync.py`** — `sync_open_positions_from_hood()`, read-only sync of
  the user's **real** open option positions via `get_option_positions`
  (+ `get_option_instruments` for strike/type, since the position row
  doesn't carry them). Verified live against the real response shape. Only
  long positions are represented (this system's model, and the HOOD order
  tools' single-leg capability, don't cover short options — those are
  logged and skipped, not misrepresented). A position this system didn't
  open has no known thesis/target/stop — those are filled from
  `SYNCED_POSITION_PROFIT_TARGET_PCT` / `SYNCED_POSITION_STOP_LOSS_PCT`, a
  configured default policy, clearly labeled as such in the thesis notes.

### `src/orchestrator.py`
`run_trading_cycle()` is **one** cycle: sync real positions (read-only) →
monitor this system's paper positions (HOLD/EXIT/TARGET_EXIT/STOP, with a
simulated closing order on exit) → monitor real positions (decide + log
always; propose an exit order only in live mode, and only for a real
position this system itself opened — see `LiveBotPositionsStore`) → scan for
a setup and enter it if risk controls allow → log everything, including an
explicit `NO_TRADE` when nothing happened and why. `CycleReport.
pending_approvals` lists any live orders (entries or exits) proposed this
cycle that are waiting on a decision. No scheduler here either — see below
for what actually drives the ~5-minute cadence.

### `src/live_bridge.py`
`StaticHoodClient` + the manual runbook for actually running a cycle
against real data — see "How the ~5-minute cadence actually works" below.
Also `StaticLiveOrderPlacer`, the equivalent bridge for the live-order
confirmation flow (see "The execution layer" below) — unlike
`StaticHoodClient`, it wraps a response from a REAL `place_option_order`
call that already happened, never a call it makes itself.

### `src/risk/` — unchanged throughout this build, on purpose
- **`models.py`** — `RiskLimits` (built from `Settings`).
- **`manager.py`** — `RiskManager`, with one check method per control:
  `check_trade_count`, `check_daily_loss`, `check_position_size`,
  `check_duplicate_position`, `check_cooldown`, `check_data_freshness`,
  `check_spread`, `check_liquidity`, `check_extended_move`,
  `check_cutoff_time`, `check_no_size_increase_after_loss`.
  `evaluate_new_trade()` runs all eleven and only allows a trade if every
  one passes. `evaluate_exit_conditions()` is advisory-only (exits are a
  risk-*reducing* action and are never blocked), except stale data, which
  tells the caller the evaluation itself isn't trustworthy this cycle.
  > `check_cutoff_time` (and `check_cooldown`'s use of `now`) expect `now`
  > to already be expressed in local market time — they don't convert it
  > themselves. `orchestrator.py` localizes `now` to `Settings.market_timezone`
  > **once**, at the top of `run_trading_cycle`, before it ever reaches
  > `RiskManager` — this was deliberately fixed there, not here, to satisfy
  > "keep the existing risk controls unchanged" while still fixing a real
  > bug (caught live: a raw UTC `now` made the entry cutoff fire ~4 hours
  > early) without touching this file. Any other caller of `RiskManager`
  > needs to do the same localization first.
- **`store.py`** — `RiskStateStore`, JSON-file-backed persistence for daily
  counters (trades opened, daily P&L, last exit time per symbol, last
  trade's size/outcome). Exists because there's no long-running process
  here — state must survive between externally-triggered evaluation
  cycles. A corrupted state file **fails closed** (raises) rather than
  silently resetting counters, which would quietly bypass the daily limits.

### `src/execution/` — the execution layer

`src/risk/` (unchanged, see below) decides whether a trade is ALLOWED;
`src/execution/` decides what actually HAPPENS to an allowed trade. That
split is deliberate: strategy/evaluator code produces a structured
BUY/HOLD/EXIT decision, `RiskManager` deterministically enforces every
control against it, and only then does this layer ever build or submit an
order — nothing here re-decides whether a trade should happen.

- **`orders.py`** — `OrderRequest`/`OrderLeg`/`OrderResult`/`SimulatedFill`/
  `LiveFill`, shaped to mirror `place_option_order`'s real, verified
  parameters (`account_number`, `legs[option_id, side, position_effect,
  ratio_quantity]`, `quantity`, `type`, `price`, `stop_price`,
  `time_in_force`, `market_hours`, `ref_id`) so the execution bridge is a
  thin pass-through, not a redesign. Documents exactly which order types
  are verified available (`limit`, `market`, `stop_limit`, `stop_market`)
  and which one this codebase actually ever builds (`limit`, single-leg,
  always — see the module docstring for the full breakdown).
- **`gateway.py`** — the safety boundary. `PaperExecutionGateway` simulates
  fills and logs everything; it can never call a real order tool, in any
  mode. `LiveExecutionGateway` refuses to even construct unless
  `TRADING_MODE=live` **and** `LIVE_TRADING_CONFIRMED=true`. Its
  `submit_order()` always creates a `PendingLiveOrder` first (full audit
  trail no matter what happens next), then either:
    - stops there (`status="pending_approval"`) — the default — waiting for
      a separate, explicit `confirm_and_place()` call, **or**
    - (only if `LIVE_AUTO_EXECUTE=true` **and** a `LiveOrderPlacer` was
      injected) immediately calls `_place_pending()` itself, with no
      separate step — `RiskManager` + `PositionEvaluator`'s deterministic
      checks (already run before `submit_order` was ever reached) are the
      only gate. `_place_pending()` is the **one and only** method in this
      codebase that calls `place_option_order` — both paths funnel through
      it, so there's exactly one implementation of "what happens when a
      live order is placed" to audit. `get_execution_gateway()` is the only
      supported way to obtain a gateway (paper by default; live requires an
      explicit `PendingOrderStore`, so a caller can't get a live-capable
      gateway by accident).
- **`pending.py`** — `PendingLiveOrder` (id, order, status
  `awaiting_approval`/`approved`/`rejected`/`expired`/`placed`/`failed`,
  timestamps, `decided_by`) + `PendingOrderStore`, a JSON-backed ledger
  (fails closed on corruption, like every other store here). A pending
  order past `PENDING_ORDER_EXPIRY_MINUTES` can never be placed —
  `confirm_and_place()` re-checks expiry and refuses a stale proposal
  rather than filling it against a quote that's moved on.
- **`live_positions.py`** — `LiveBotPositionsStore`: tracks which real
  (Robinhood-synced) positions *this system itself* opened via a confirmed
  live order, so the position monitor only ever proposes an exit for its
  own trades — never for something the user holds for reasons of their own
  that this bot knows nothing about. Updated automatically by
  `_place_pending()` (added on a confirmed entry, removed on a confirmed
  exit).
- **`live_client.py`** — `LiveOrderPlacer`, the typed seam (same pattern as
  `market/hood_client.py`'s `HoodToolClient`) for whatever actually has the
  ability to call `place_option_order` / `review_option_order` /
  `cancel_option_order` / `get_accounts` / `get_portfolio` — deliberately
  separate from `HoodToolClient`, which explicitly excludes order-placement
  methods.
- **`preflight.py`** — `verify_account_preflight()`: checks a real
  `get_accounts` + `get_portfolio` response for `agentic_allowed=true`,
  `option_level_2`/`option_level_3`, active account state, and sufficient
  buying power — every field defensively parsed, anything missing or
  ambiguous is a FAILING check, never a skipped one. Must pass before the
  first live order is ever proposed (`scripts/verify_live_readiness.py`).

### `src/logging/`
- **`app_logger.py`** — general diagnostic logging (stdlib `logging`,
  console + rotating file handler).
- **`decision_logger.py`** — `DecisionLogger`, the structured JSONL audit
  trail. Every `HOLD`, `EXIT`, `TARGET_EXIT`, `STOP_EXIT`, `NO_TRADE`, risk
  block, simulated order, and simulated cancel gets one append-only,
  immediately-flushed JSON record — silence is never how this system
  records "nothing happened."
  > Naming note: this package is intentionally named `logging` (matching
  > the requested layout). It's safe because it's only ever imported as
  > `src.logging...` — see the caution comment in `src/logging/__init__.py`
  > and don't add `src/` itself to `sys.path`.
- **`trade_journal.py`** — `TradeJournal`, the "teaching moment" record.
  Every time a position (paper or live) actually closes, `run_trading_cycle`
  calls `record_close()`, which appends one structured JSONL entry: the
  original thesis, entry price/time, how it exited and why, the realized
  P&L, hold time, the momentum evidence at exit, and a short deterministic
  `lesson` string derived from that evidence via template rules (e.g. "hard
  stop — the stop capped the downside as designed" for a `STOP_EXIT`,
  "trailing stop did its job" for a winning trailing exit). `summary()`
  gives cheap aggregate stats (win rate, total realized P&L, exit-type
  counts) for a quick look at the account's history so far.
  > **Deliberately NOT a learning/auto-tuning system.** Nothing here ever
  > mutates `RiskManager`'s limits, the strategy's momentum thresholds, or
  > position sizing. Two hard reasons: (1) at `MAX_TRADES_PER_DAY=2` on a
  > small account, any given day produces a small handful of closed trades
  > at most — nowhere near enough to "learn" anything statistically real;
  > auto-tuning off 2-3 trades is overfitting to noise, not learning. (2)
  > every risk parameter (`MAX_POSITION_SIZE_USD`, `MAX_DAILY_LOSS_USD`,
  > `MAX_TRADES_PER_DAY`, ...) was set by a deliberate human decision, and a
  > system that silently loosens or tightens those from its own trade
  > history would be exactly the autonomous-risk-control-mutation this
  > project has been explicitly told never to do. Any change to those
  > numbers stays a human decision, made the same way every prior change to
  > them has been made in this project — by being asked for, explicitly.

## Configuration

Copy `.env.example` to `.env` and adjust. Key variables:

| Variable | Purpose |
|---|---|
| `TRADING_MODE` | `paper` (default, enforced) or `live` (implemented — see "The execution layer" — but off in this deployment's real `.env`) |
| `LIVE_TRADING_CONFIRMED` | Second, independent switch `LiveExecutionGateway` also requires before it will even construct. Default `false`. |
| `LIVE_AUTO_EXECUTE` | `false` (default): every live order stops at a pending approval. `true`: an order is placed the instant it clears every deterministic risk check, no conversational per-trade approval. Only matters together with the two switches above. |
| `PENDING_ORDERS_FILE` / `PENDING_ORDER_EXPIRY_MINUTES` | Live pending-order ledger path and how long a proposal stays approvable (default 15 min) |
| `LIVE_BOT_POSITIONS_FILE` | Tracks which real positions this system itself opened live, for exit-proposal ownership |
| `PEAK_PRICES_FILE` | Cross-cycle peak-price memory for the trailing-exit engine |
| `TRADE_JOURNAL_FILE` | Append-only "teaching moment" record, one entry per closed trade — see `src/logging/trade_journal.py`. Never mutates config. |
| `TRAILING_ARM_FRACTION` / `TRAILING_GIVEBACK_FRACTION` | Dynamic/trailing exit thresholds (defaults 0.5 / 0.3 — see the worked example above) |
| `MAX_TRADES_PER_DAY` | Default 4 |
| `MAX_DAILY_LOSS_USD` | Realized+unrealized daily loss cap |
| `MAX_POSITION_SIZE_USD` | Per-trade capital cap |
| `COOLDOWN_MINUTES_AFTER_EXIT` | Re-entry cooldown per symbol |
| `STALE_DATA_MAX_SECONDS` | Data older than this blocks entries and exit-signal trust |
| `MAX_SPREAD_PCT` / `MIN_OPTION_VOLUME` / `MIN_OPTION_OPEN_INTEREST` | Spread + liquidity gates |
| `MAX_EXTENDED_MOVE_PCT` | Anti-chasing threshold |
| `ENTRY_CUTOFF_TIME` | No new entries after this local time |
| `MONITOR_INTERVAL_MINUTES` | Documentation only — no code reads this to drive a timer |
| `ROBINHOOD_ACCOUNT_NUMBER` | Required to run a cycle. Never auto-selected from `get_accounts` by code — pick it explicitly. |
| `SCAN_UNIVERSE` | Comma-separated symbols the scanner considers each cycle |
| `MAX_NEW_ENTRIES_PER_CYCLE` | Cap on new paper positions per cycle (0 disables scanning/entries; monitoring/exits still run) |
| `SYNCED_POSITION_PROFIT_TARGET_PCT` / `SYNCED_POSITION_STOP_LOSS_PCT` | Default target/stop applied to positions synced read-only from the real account |
| `PAPER_POSITIONS_FILE` | The paper-position ledger's path |

## Running the tests

```bash
pip install -e ".[dev]"   # installs pytest only
pytest
```

270 tests currently pass, covering everything above plus: the real,
live-verified HOOD response parsing (including edge cases — invalid
symbols/contracts silently omitted from results, pagination, a bug where
that omission was almost mishandled as "use whatever row came back"), the
concrete momentum-breakout strategy, the paper-position ledger, real-
position sync, the monitor's simulated order submission, the dynamic/
trailing exit engine (including the exact $0.95/$1.05/$1.15 worked
example), and the full live-execution architecture — pending orders,
confirm/reject, the auto-execute path, preflight checks, and the guarantee
that `place_option_order` is reachable from exactly one method in the whole
codebase — plus two real timezone bugs caught only by running the system
against actual live data (see below) and fixed with regression tests.

## HOOD MCP tools this codebase actually calls

**Market data (read-only, verified live):** `get_option_quotes`,
`get_equity_quotes`, `get_option_chains`, `get_option_instruments`,
`get_option_historicals`, `get_equity_historicals`.

**Positions (read-only, verified live):** `get_option_positions` (+
`get_option_instruments` for strike/type lookups), `get_accounts` (used
once, interactively, to pick `ROBINHOOD_ACCOUNT_NUMBER` — never
auto-selected by code).

**Inspected but not yet used:** `get_equity_technical_indicators` (response
shape not verified — indicators are computed locally instead, see
`hood_provider.py`), `get_scanner_filter_specs` / `create_scan` / `run_scan`
/ `get_scans` (a future scanning strategy could use Robinhood's own saved
screeners instead of/alongside `MomentumBreakoutStrategy`), `get_portfolio`
/ `get_pnl_trade_history` (a future enhancement could reconcile daily P&L
against the real account instead of locally-tracked risk state).

**Order execution (implemented, but only reachable through
`LiveExecutionGateway._place_pending()` — never called anywhere else in this
codebase, and never called at all while `TRADING_MODE=paper`, which is the
mode this deployment's real `.env` is in today):** `place_option_order`. Its
schema was verified live (account requirements, leg/type/price rules,
idempotent `ref_id`). `review_option_order` and `get_portfolio` are wired
into the `LiveOrderPlacer`/preflight seam but not yet called by any code
path in this build. `cancel_option_order` is deliberately not wired to
anything — see `LiveExecutionGateway.cancel_order()`.

## How the ~5-minute cadence actually works

Read this before assuming there's a headless, code-only daemon — there
isn't, and pretending otherwise would be exactly the "fake scheduler" this
project was explicitly told not to build.

Nothing in this codebase can call a HOOD MCP tool from Python — only the
orchestrating agent's own tool-call interface can. `HoodMarketDataProvider`
decides which tool to call, and with what arguments, *as it runs* (e.g. it
only looks up option contracts for a symbol that already showed a bullish
breakout at the equity level) — so the calls can't be fully pre-planned and
batch-fetched ahead of time. That means true automation here is
**agent-mediated**: a real recurring wake-up (this platform's `/loop`
skill, backed by `ScheduleWakeup` — note `CronCreate`/Routines cannot go
below an hourly interval, so they cannot drive a 5-minute cadence; `/loop`
can) brings the agent back roughly every 5 minutes, and at each wake the
agent:

1. Checks the time — no-ops outside 9:30–16:00 ET on a trading weekday.
2. Otherwise, follows the runbook in `src/live_bridge.py`'s module
   docstring: make the real, read-only HOOD tool calls one cycle needs (in
   the order `HoodMarketDataProvider` needs them), record each response on
   a `StaticHoodClient`, then call `src.orchestrator.run_trading_cycle()`
   against it.
3. In this deployment, `TRADING_MODE` stays `paper` throughout, so the
   execution gateway never calls `place_option_order` /
   `review_option_order` / `cancel_option_order` regardless. If a future
   session runs this with `TRADING_MODE=live` and `LIVE_TRADING_CONFIRMED=
   true`, a proposed live order still can't be placed inside this same
   step — see "The live-order confirmation bridge" below for why, and what
   the agent does instead.

This was validated against real, live data during development (not just
mocks): a full cycle correctly synced the real account's positions (zero,
correctly), correctly gated on market hours and the entry cutoff (in ET,
not UTC — see the risk/ section above for a bug this caught), correctly
found no qualifying setup for SPY against its actual recent price action,
and logged that decision — placing zero orders throughout.

**Every decision is computed by the same tested Python logic** (evaluator,
risk manager, strategy, orchestrator) against real, live, just-fetched
market data — this is not a code-level fake. It is not, however, a
fire-and-forget background daemon: each firing takes the agent's active
participation, following the runbook, and there is no code in this
repository that can run the system unattended without that.

### The live-order confirmation bridge

`place_option_order` has a real, irreversible side effect, so — unlike
market data — it can't be "recorded ahead of time and replayed." The flow,
only relevant once `TRADING_MODE=live` and `LIVE_TRADING_CONFIRMED=true`:

1. A cycle's `submit_order()` creates a `PendingLiveOrder` (never calls
   `place_option_order` itself) — see `PendingOrderStore`.
2. Under `LIVE_AUTO_EXECUTE=false` (the default), that pending order just
   sits there until a separate, explicit action decides it — either
   `scripts/confirm_pending_order.py` (after the agent makes a REAL
   `place_option_order` call with that pending order's exact parameters and
   records the real response) or `scripts/reject_pending_order.py`. Under
   `LIVE_AUTO_EXECUTE=true`, this is what happens immediately: nothing
   waits for a message-and-reply round trip, but the mechanics — a real
   tool call, then a script that processes its real response — are the
   same, because Python still can't call `place_option_order` itself.
3. Either way, `LiveExecutionGateway._place_pending()` is the one method
   that ever calls it, and it always updates `PendingOrderStore`,
   `LiveBotPositionsStore`, and the decision/audit log from what actually
   happened — never a fabricated result.

## What's still not built

1. A bearish (long-put) strategy — `MomentumBreakoutStrategy` is calls-only;
   the structure detectors it relies on only detect upside breaks. A
   mirrored breakdown/support detector plus a put-side strategy is real,
   scoped future work.
2. Daily-loss/portfolio reconciliation against the real account
   (`get_portfolio` / `get_pnl_trade_history`) — `RiskStateStore` currently
   tracks the day's P&L purely from this system's own fills, not
   cross-checked against Robinhood's own numbers. `get_portfolio` is wired
   into the preflight check's buying-power test, but not (yet) into
   ongoing daily-loss reconciliation.
3. A truly unattended, headless automation path. As explained above, this
   platform's architecture means live tool calls are agent-mediated — a
   different platform/integration with a persistent, credentialed bridge
   process would be a materially different (and far larger) undertaking,
   not a small addition to this codebase. Concretely: even with
   `LIVE_AUTO_EXECUTE=true`, an order still requires the agent to make a
   real tool call and feed its response back into a script — there is no
   in-process path from "cycle ran" to "order placed."
4. An explicit kill switch (env var or file check) the user can flip to
   force every gateway back to paper/refuse instantly, independent of the
   rest of the config.
5. A monitoring/alerting story for when the external ~5-minute trigger stops
   firing (e.g. the scheduler dies) while a live position is open — silence
   from the scheduler must not mean silence from risk controls.
6. Multi-cycle, multi-session soak testing in paper mode across varied real
   market conditions (trending, choppy, low-liquidity, earnings volatility)
   — this build has been validated end-to-end against real data for one
   quiet-market snapshot, not battle-tested over time.
7. `scripts/verify_live_readiness.py` has been built and unit-tested but
   never actually run against a real `get_accounts`/`get_portfolio` pull in
   this deployment — do that, and read its output, before ever proposing a
   live order for real.

## Going live: what this deployment has and hasn't done

Live execution **is built and tested** (see "The execution layer" and "The
live-order confirmation bridge" above) — 270 tests pass, including the
guarantee that `place_option_order` is reachable from exactly one method.
**No live order has been proposed or placed by this build, and none will be
until a human deliberately does all of the following:**

1. Run `scripts/verify_live_readiness.py` against a real, fresh
   `get_accounts` + `get_portfolio` pull and confirm it passes.
2. Set `TRADING_MODE=live` and `LIVE_TRADING_CONFIRMED=true` in `.env`
   (both are `false`/`paper` in this deployment's real `.env` right now).
3. Decide, deliberately, whether `LIVE_AUTO_EXECUTE` should be `true`
   (no conversational per-trade approval — an order is placed the instant
   it clears `RiskManager`/`PositionEvaluator`'s checks) or stay `false`
   (every order needs a separate, explicit confirm/reject action first).
   This is a real, materially different risk posture, not a cosmetic
   toggle — treat it as its own decision, not a default to inherit.
4. Only then start a recurring live cycle — and even so, every cycle still
   only ever *proposes* orders; whether they're placed immediately or held
   for confirmation follows directly from step 3's choice.

This is a one-way door and should be treated as such: soak-test in paper
mode across varied market conditions first (see "What's still not built"
above), and treat `LIVE_AUTO_EXECUTE=true` as something to turn on only
after the gated (`false`) mode has actually been exercised against real
account activity, not as the first live setting ever tried.
