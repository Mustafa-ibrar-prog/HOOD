# HOOD Options Trading System (Paper Mode)

An automated options trading system built on top of the HOOD (Robinhood)
MCP connection, running end-to-end in **paper mode**:

```
MARKET SCAN → FIND SETUP → PAPER ENTRY → MONITOR EVERY ~5 MINUTES →
HOLD / EARLY EXIT / TARGET EXIT / STOP → LOG EVERYTHING → SYNC WITH ROBINHOOD
```

Nothing in this codebase places, modifies, or cancels a real order —
`src/execution/gateway.py` physically refuses to do anything but simulate
while `TRADING_MODE=paper`, which is the only mode this system runs in
today. See "How the ~5-minute cadence actually works" below for an honest
account of what "automated" means on this platform (agent-mediated, not a
headless daemon — real decisions against real data, but not a fire-and-
forget background process).

## Safety model, in one paragraph

`TRADING_MODE` defaults to `paper`. `src/execution/gateway.py` is the single
choke point every order-related action must pass through: in paper mode it
returns a `PaperExecutionGateway` that only ever simulates a fill and writes
it to the audit log; in any other mode `get_execution_gateway()` raises
immediately, on purpose, because the live path (`LiveExecutionGateway`) is
an intentional stub whose methods unconditionally raise
`LiveTradingDisabledError`. Turning on real trading later requires a human
to deliberately implement that class — it does not happen by flipping an
environment variable. See "Before live trading" below.

## Project layout

```
src/
  config/            Settings (env-driven) + shared constants
  market/            Market data (verified live against real HOOD responses), indicators, scanning support
  strategy/          Decision model, momentum-evidence scoring, scanning framework + a concrete strategy
  position_manager/  Open-position model, evaluator, monitor (now submits simulated exit orders), paper ledger, real-position sync
  risk/              The 11-rule risk-control framework + persisted daily state (UNCHANGED throughout this build)
  execution/         Order shapes + the paper/live execution gateway (safety boundary, UNCHANGED)
  logging/           Structured decision/audit logging + general app logging
  orchestrator.py    Ties one full cycle together: scan → entry → monitor → exit → log → sync
  live_bridge.py     The manual live-data bridge + runbook for actually running a cycle (see below)
tests/               One test module per src package, 232 tests total
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
  expiration risk is checked next; then insufficient-data fails safe to
  HOLD; then a profitable position with corroborated weakening/reversing
  evidence EXITs *regardless of whether the profit target was reached*;
  reaching the target only forces `TARGET_EXIT` if momentum isn't still
  strengthening (if it is, the position HOLDs past the target too). This is
  the exact behavior from the spec's $0.95→$1.05 example.
- **`monitor.py`** — `PositionMonitor.run_once()` performs one
  fetch-evaluate-log cycle for one position, and — for an
  EXIT/TARGET_EXIT/STOP_EXIT decision — builds and submits a sell-to-close
  `OrderRequest` through the (paper-only) execution gateway; `acted=True`
  and an `order_result` come back when the simulated fill happens. Pass
  `simulate_exit=False` to decide-and-log only without submitting an order
  — used for positions synced read-only from the real account, which this
  system doesn't own the lifecycle of. **There is no timer or scheduler in
  this code** — `is_within_monitoring_window()` just tells a caller whether
  now is a sensible time to act, converting to the configured market
  timezone itself (a real bug, caught during live verification, made a raw
  UTC `now` compare against ET boundary times directly — fixed).
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
only, never act) → scan for a setup and paper-enter it if risk controls
allow → log everything, including an explicit `NO_TRADE` when nothing
happened and why. No scheduler here either — see below for what actually
drives the ~5-minute cadence.

### `src/live_bridge.py`
`StaticHoodClient` + the manual runbook for actually running a cycle
against real data — see "How the ~5-minute cadence actually works" below.

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

### `src/execution/` — unchanged throughout this build, on purpose
- **`orders.py`** — `OrderRequest`/`OrderLeg`/`OrderResult`/`SimulatedFill`,
  shaped to mirror `place_option_order`'s parameters so a future real bridge
  is a thin pass-through, not a redesign.
- **`gateway.py`** — the safety boundary described above:
  `assert_paper_mode()`, `PaperExecutionGateway` (simulates fills, logs
  everything, never calls an MCP tool), `LiveExecutionGateway` (every
  method unconditionally raises), and `get_execution_gateway()` (the only
  supported way to obtain a gateway; refuses outside paper mode).

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

## Configuration

Copy `.env.example` to `.env` and adjust. Key variables:

| Variable | Purpose |
|---|---|
| `TRADING_MODE` | `paper` (default, enforced) or `live` (parses, but execution still refuses — see below) |
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

232 tests currently pass, covering everything above plus: the real,
live-verified HOOD response parsing (including edge cases — invalid
symbols/contracts silently omitted from results, pagination, a bug where
that omission was almost mishandled as "use whatever row came back"), the
concrete momentum-breakout strategy, the paper-position ledger, real-
position sync, the monitor's simulated order submission, and the full
orchestrator cycle end-to-end — plus two real timezone bugs caught only by
running the system against actual live data (see below) and fixed with
regression tests.

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

**Order execution (exclusively for the future `LiveExecutionGateway`, once
explicitly built and approved):** `review_option_order`,
`place_option_order`, `cancel_option_order`. **Not called anywhere in this
codebase, and never will be while `TRADING_MODE=paper`.**

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
3. Never calls `place_option_order` / `review_option_order` /
   `cancel_option_order` — `TRADING_MODE` stays `paper`, and the execution
   gateway refuses regardless.

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

## What's still not built

1. A bearish (long-put) strategy — `MomentumBreakoutStrategy` is calls-only;
   the structure detectors it relies on only detect upside breaks. A
   mirrored breakdown/support detector plus a put-side strategy is real,
   scoped future work.
2. Daily-loss/portfolio reconciliation against the real account
   (`get_portfolio` / `get_pnl_trade_history`) — `RiskStateStore` currently
   tracks the day's P&L purely from this system's own paper fills, not
   cross-checked against Robinhood's own numbers.
3. A truly unattended, headless automation path. As explained above, this
   platform's architecture means live tool calls are agent-mediated — a
   different platform/integration with a persistent, credentialed bridge
   process would be a materially different (and far larger) undertaking,
   not a small addition to this codebase.
4. Multi-cycle, multi-session soak testing in paper mode across varied real
   market conditions (trending, choppy, low-liquidity, earnings volatility)
   — this build has been validated end-to-end against real data for one
   quiet-market snapshot, not battle-tested over time.

## What needs to happen before live trading can safely be enabled

This is a one-way door and should be treated as such:

1. Everything above, validated in paper mode across enough sessions and
   market conditions (trending, choppy, low-liquidity) to trust the
   HOLD/EXIT/TARGET_EXIT/STOP_EXIT calls and that every risk control
   actually fires when it should.
2. A human deliberately implements `LiveExecutionGateway` — it does not
   happen automatically. That implementation must call `review_option_order`
   before `place_option_order` and require explicit confirmation, per that
   tool's own documented workflow, and must respect `agentic_allowed`/
   `option_level` account checks before ever attempting an order.
3. `get_execution_gateway()` is deliberately updated to return a live
   gateway only under `TRADING_MODE=live` **and** `LIVE_TRADING_CONFIRMED=true`
   **and** the user's own explicit, in-the-moment go-ahead for that trading
   session — not just because the `.env` file says so once.
4. A real daily-loss and position-count reconciliation against the live
   account (not just local state) before every new order, so a restarted
   process can't silently forget it already hit the day's limit.
5. An explicit kill switch (env var or file check) the user can flip to
   force every gateway back to paper/refuse instantly, independent of the
   rest of the config.
6. A monitoring/alerting story for when the external ~5-minute trigger stops
   firing (e.g. the scheduler dies) while a live position is open — silence
   from the scheduler must not mean silence from risk controls.

None of this exists yet, on purpose. Paper mode is the only mode this
codebase can run in today.
