# HOOD Options Trading System — Foundation (Paper/Dry-Run Only)

This repository is the software foundation for an automated options trading
system built on top of the HOOD (Robinhood) MCP connection. **It is a
foundation, not a running trading bot.** Nothing in this codebase places,
modifies, or cancels a real order, and nothing here reads live market data
yet — those are the next phases, described at the bottom of this file.

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
  market/            Market-data shapes, indicator math, data-provider interface
  strategy/          Decision model, momentum-evidence scoring, scanning framework
  position_manager/  Open-position model, HOLD/EXIT/TARGET_EXIT/STOP_EXIT evaluator, monitor
  risk/              The 11-rule risk-control framework + persisted daily state
  execution/         Order shapes + the paper/live execution gateway (safety boundary)
  logging/           Structured decision/audit logging + general app logging
tests/               One test module per src package, ~120 tests total
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
- **`models.py`** — `OptionQuote`, `EquityQuote`, `PriceBar`, `MarketSnapshot`.
  Field names are modeled after what `get_option_quotes`, `get_equity_quotes`,
  `get_option_historicals`, `get_equity_historicals`, and
  `get_equity_technical_indicators` will eventually supply.
- **`indicators.py`** — dependency-free EMA, RSI, MACD, VWAP, higher-highs/
  lower-highs, breakout-continuation and failed-breakout detection, spread%,
  and liquidity checks. Pure functions, fully unit-tested.
- **`data_provider.py`** — the `MarketDataProvider` abstract interface plus
  `NotConfiguredMarketDataProvider`, which fails loudly (`NotImplementedError`)
  instead of returning fabricated data. This is the seam where a future
  implementation wires in the actual HOOD MCP tool calls (see below).

### `src/strategy/`
- **`decision.py`** — the `Decision` enum (`BUY`, `HOLD`, `EXIT`,
  `TARGET_EXIT`, `STOP_EXIT`, `NO_TRADE`), `TradeThesis`, `DecisionResult`.
- **`evidence.py`** — `MomentumEvidence` + `evaluate_momentum()`, the scoring
  engine that turns a bundle of technical signals into `STRENGTHENING /
  STABLE / WEAKENING / REVERSING / INSUFFICIENT_DATA`. Deliberately requires
  *multiple corroborating signals* before calling a move weakening — a
  single soft blip (RSI ticking down a point, volume dipping slightly) is
  not enough, so the system never exits on a mere pause.
- **`base.py` / `scanner.py`** — `Strategy` (abstract), `SetupCandidate`, and
  `StrategyScanner`, which runs registered strategies and produces a ranked
  candidate list or an explicit `NO_TRADE`. No concrete strategy is
  implemented yet — that's real future work, not a placeholder to fill in
  blindly.

### `src/position_manager/`
- **`models.py`** — `OpenPosition` (entry price, thesis, target, stop,
  expiration) with `unrealized_pnl_usd`/`unrealized_pnl_pct` helpers
  (rounded to the cent to avoid binary-float threshold misses).
- **`evaluator.py`** — `PositionEvaluator`, the core HOLD/EXIT/TARGET_EXIT/
  STOP_EXIT decision tree: thesis invalidation and hard stop-loss always win;
  expiration risk is checked next; then insufficient-data fails safe to
  HOLD; then a profitable position with corroborated weakening/reversing
  evidence EXITs *regardless of whether the profit target was reached*;
  reaching the target only forces `TARGET_EXIT` if momentum isn't still
  strengthening (if it is, the position HOLDs past the target too). This is
  the exact behavior from the spec's $0.95→$1.05 example.
- **`monitor.py`** — `PositionMonitor.run_once()` performs exactly one
  fetch-evaluate-log cycle for one position. **There is no timer or
  scheduler in this code** — `is_within_monitoring_window()` just tells an
  external scheduler whether now is a sensible time to call `run_once()`.
  The real ~5-minute-during-market-hours cadence is meant to come from
  outside this process (a cron job, a Routine/trigger, a supervised loop —
  whatever the deployment uses), not from a fake `sleep()` loop baked into
  the library.

### `src/risk/`
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
- **`store.py`** — `RiskStateStore`, JSON-file-backed persistence for daily
  counters (trades opened, daily P&L, last exit time per symbol, last
  trade's size/outcome). Exists because there's no long-running process
  here — state must survive between externally-triggered evaluation
  cycles. A corrupted state file **fails closed** (raises) rather than
  silently resetting counters, which would quietly bypass the daily limits.

### `src/execution/`
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

## Running the tests

```bash
pip install -e ".[dev]"   # installs pytest only
pytest
```

118 tests currently pass, covering: config parsing/validation, the
execution guard (proving paper mode can't place a live order and live mode
can't either, because it's unimplemented), all eleven risk controls plus
persisted-state behavior (including fail-closed on corruption), indicator
math, momentum-evidence scoring (including the "a pause is not evidence"
case), the position evaluator's full HOLD/EXIT/TARGET_EXIT/STOP_EXIT
decision tree (including the spec's $0.95→$1.05 example, both directions),
decision logging, the scanning framework, and the monitor's one-shot
evaluation cycle.

## HOOD MCP tools available for the future implementation

Inspected (schemas only — none called by this codebase):

**Market data (for `MarketDataProvider`):** `get_option_quotes`,
`get_equity_quotes`, `get_option_chains`, `get_option_instruments`,
`get_option_historicals`, `get_equity_historicals`,
`get_equity_technical_indicators` (rsi/macd/ema/vwap/bollinger/atr/etc.),
`get_equity_price_book`, `get_option_watchlist`.

**Positions/account (for reconciling `OpenPosition` against reality):**
`get_option_positions`, `get_equity_positions`, `get_accounts`,
`get_portfolio`.

**Scanning (for a future concrete `Strategy`):** `get_scanner_filter_specs`,
`create_scan`, `run_scan`, `get_scans`.

**Order execution (exclusively for the future `LiveExecutionGateway`, once
explicitly built and approved):** `review_option_order`,
`place_option_order`, `cancel_option_order`. **Not called anywhere in this
codebase.**

## What still needs to be built before paper trading actually runs

This foundation defines the *shapes and rules*; it doesn't yet move real
data through them. Concretely:

1. A real `MarketDataProvider` implementation that calls the HOOD MCP tools
   above and assembles `MarketSnapshot` objects (today only
   `NotConfiguredMarketDataProvider` exists, which fails loudly by design).
2. At least one concrete `Strategy` implementation for the scanner (today
   only the abstract framework exists).
3. Wiring `PositionMonitor` to a real closing-order path in paper mode —
   right now `run_once()` decides and logs an `EXIT`/`TARGET_EXIT`/
   `STOP_EXIT`, but does not yet build and submit the corresponding
   `OrderRequest` to `PaperExecutionGateway`. That's a deliberate gap, not
   a bug: it keeps "decide" and "act" separable and independently
   reviewable.
4. Position reconciliation against `get_option_positions`/`get_portfolio`
   so `OpenPosition` state reflects the real (paper or live) account rather
   than being hand-constructed.
5. Wiring `RiskManager`/`RiskStateStore` into the actual scan → size →
   place-paper-order flow, and into the account daily-loss figure from
   `get_portfolio`/`get_pnl_trade_history` rather than a manually-tracked
   number.
6. An external trigger for `PositionMonitor.run_once()` roughly every 5
   minutes during market hours (a Routine/cron/supervised process) — this
   codebase intentionally does not include one.
7. End-to-end paper-mode integration tests once the above exist, run
   against real (delayed is fine) market data for at least one full session
   before trusting the decisions it produces.

## What needs to happen before live trading can safely be enabled

This is a one-way door and should be treated as such:

1. Everything in the list above, validated in paper mode across enough
   sessions and market conditions (trending, choppy, low-liquidity) to trust
   the HOLD/EXIT/TARGET_EXIT/STOP_EXIT calls and that every risk control
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
