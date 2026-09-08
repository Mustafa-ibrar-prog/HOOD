# Phase 40 — 14-Day Autonomous Options Paper-Trading Experiment (Infrastructure Report)

**Status of this document: INFRASTRUCTURE READINESS REPORT, not an experiment result.**
No 14-day experiment has been started. This document describes what was built, how it
was verified, and the exact commands needed to start the real, user-initiated
experiment in a future turn — per Part 32/34's explicit instruction, this phase does
not start the experiment, validate the strategy, or authorize live trading.

## 1. What this is (and is not)

Phase 40 builds an **optional, additive, structurally-isolated** paper-trading layer
on top of the existing, already-complete, already-tested autonomous engine
(`src.orchestrator.run_trading_cycle`). It answers one question the codebase could not
previously answer directly: *"If I started with $1,000 and let the existing autonomous
options engine run against real market data for two weeks, what would actually
happen?"*

It is not:
- A live-trading system. No code path in `src.paper_trading` or
  `scripts/paper_experiment.py` can place, modify, or cancel a real Robinhood order —
  verified by static AST scan, forbidden-call scan, and a subprocess-isolated dynamic
  import scan (§6).
- A validation mechanism. Profitable (or unprofitable) paper performance never marks
  `MOMENTUM_BREAKOUT_EXISTING_V1` as `VALIDATED` — it remains `NOT_READY` in the real
  `StrategyRegistry`, untouched by this package (§5).
- A scheduler. Nothing in this codebase calls a HOOD MCP tool on its own; each real
  cycle is still triggered by an explicit `run-cycle` invocation against
  agent-fetched data, exactly like the Phase 39 live-research runbook.

## 2. Architecture: reuse, not duplication

Per Part 1's explicit instruction, this phase **audited what already existed** before
writing anything new. The finding: `src.orchestrator.run_trading_cycle` is already a
complete, working, autonomous, options-only paper-trading engine — scan → risk-check
(11 checks) → simulated ask-price entry via `PaperExecutionGateway` → continuous
position monitoring → deterministic bid-price exits → trade journal. Phase 40 does
**not** reimplement any of this. Every real cycle:

1. Calls `src.research_recorder.recorder.run_observation_cycle` (Phase 37, unchanged)
   for real market data, provenance, and an `observation_cycle_id`. `MARKET_CLOSED`
   short-circuits the cycle with no paper decision (Part 22).
2. Overrides exactly **three** `Settings` fields via `dataclasses.replace` (never
   mutating the shared settings object) before calling
   `src.orchestrator.run_trading_cycle` unchanged: `scan_universe` (the experiment's
   own universe), `max_position_size_usd` (capped at the experiment's real remaining
   cash — see §4), and the experiment's own dedicated file paths (so a 14-day
   experiment never shares state with, or collides with, the general-purpose bot's own
   paper files).
3. Cross-references the resulting `CycleReport` against Phase 37's real, same-cycle
   normalized option data to build the enriched `PaperExperimentTradeRecord` (Part 19)
   and the equity snapshot (Part 17) — read-only cross-referencing, never a second
   decision.

Components explicitly reused, unmodified: `StrategyDecision`, `ProductionStrategy`,
`StrategyRegistry`, `RiskManager` (all 11 checks), `PositionSizer`/sizing logic,
`OpenPosition`, `MomentumBreakoutStrategy`, `PaperExecutionGateway`,
`PaperPositionStore`, `TradeJournal`, the Phase 37 recorder, and the Phase 39 live
bridge (`load_static_hood_client_from_dir`, `HoodMarketDataProvider`). Nothing in
`src/paper_trading/` re-implements strategy logic, order simulation, or risk checks.

## 3. New modules (`src/paper_trading/`)

| Module | Part(s) | Purpose |
|---|---|---|
| `experiment_config.py` | 5 | Immutable, write-once `ExperimentConfig` — $1,000 default, 14-calendar-day minimum, `PAPER_EXPERIMENT_ONLY` mode, strategy content hash, data provenance |
| `state_machine.py` | 24/25 | `ExperimentStatus` (CREATED/RUNNING/PAUSED/COMPLETED/ABORTED), append-only, restart-safe |
| `clock.py` | 4 | Calendar-day vs market-day accounting; closed dates derived honestly from actual cycle history (no fabricated holiday calendar) |
| `slippage.py` | 11/12/13 | Ask-entry/bid-exit only pricing (`NO_EXECUTABLE_QUOTE`, never a midpoint); BASELINE/STRESSED cost tiers reused from the existing, already-reviewed `src.options.cost_model` |
| `journal.py` | 19/23 | The full `PaperExperimentTradeRecord`, hard-labeled `PAPER_EXPERIMENT`; deterministic, restart-safe trade IDs |
| `account.py` | 3/14 | Pure, ledger-derived $1,000 account snapshot — cash, equity, drawdown; never a mutable balance that could drift |
| `equity_curve.py` | 17 | Append-only, per-cycle equity curve, deduped by `observation_cycle_id` |
| `daily_performance.py` | 18 | End-of-day rollups, computed on demand (no scheduler) |
| `risk_monitoring.py` | 20 | Exposure/concentration/liquidity monitoring, all thresholds caller-supplied |
| `engine.py` | 6/7/8/9/10/17/22 | The per-cycle wrapper described in §2 |
| `report.py` | 26/27/28 | Final-report aggregation; **no `annualized_return` field exists anywhere in this module** |

## 4. Capital, execution, and risk

- **Starting capital**: $1,000 (configurable), tracked as a pure function of the
  trade ledger — cash, open-position market value, equity, realized/unrealized P&L,
  return, drawdown, peak equity are always re-derived, never a separately mutable
  field that could drift from what the ledger says.
- **Aggressive by default** (Part 15): `max_position_size_fraction_of_equity = 1.0`.
  A position is capped only by real remaining cash — never the ambient `.env`'s
  unrelated $250 always-on-bot default.
- **Capital affordability** (Part 14) is enforced by the already-existing,
  **unmodified** `RiskManager.check_position_size`: the experiment's
  `max_position_size_usd` is computed as
  `min(available_cash, starting_capital * fraction)` and passed in via the same
  `Settings` override described in §2. No new capital-check code exists.
- **Execution realism** (Part 11): long entries fill at the real ask, exits at the
  real bid — never a midpoint. A missing required side returns the literal string
  `NO_EXECUTABLE_QUOTE`; no fill is ever fabricated.
- **The real fill** is recovered algebraically from the existing
  `TradeJournalEntry.realized_pnl_usd` (the same formula
  `src.orchestrator._realized_pnl` already uses, inverted) — authoritative, never a
  second independent fill.
- **Costs** (Part 12/13): BASELINE and STRESSED slippage/fee tiers reuse
  `src.options.cost_model.COST_SENSITIVITY_ASSUMPTIONS[0]` and `[2]` verbatim — no new
  favorable numbers invented. Gross P&L, spread cost, slippage, fees, and net P&L are
  reported separately per trade.
- **Universe**: the established 12-symbol universe (NVDA TSLA SPY QQQ AAPL MSFT AMD
  AMZN META GOOGL NFLX IWM) by default.
- **Structure**: options only, long call / long put (the only structures the frozen
  strategy emits). Any other structure would be recorded as `UNSUPPORTED_STRUCTURE`
  with no paper order created — checked defensively even though it is structurally
  unreachable given the frozen strategy and `OpenPosition.__post_init__`.

## 5. Validation and authorization stay untouched

- `MOMENTUM_BREAKOUT_EXISTING_V1` remains `NOT_READY` in the real, default
  `StrategyRegistry` — verified directly in the test suite (§7) and by static scan:
  no file in `src/paper_trading/` calls `StrategyRegistry.register` or
  `.mark_validated`, or references `StrategyStatus.VALIDATED`.
- `ExperimentStrategyMode.PAPER_EXPERIMENT_ONLY` is a completely separate,
  Phase-40-local enum with **zero import relationship** to
  `src.production.registry.StrategyStatus` in either direction — verified by AST scan
  (no `import`/`from ... import` of `StrategyStatus`/`StrategyRegistry` anywhere in
  `experiment_config.py`).
- `ExperimentStatus` (CREATED/RUNNING/PAUSED/COMPLETED/ABORTED) is verified disjoint
  from `src.execution.system_state.SystemState` — `RUNNING` can never be confused with
  `LIVE_AUTONOMOUS_TRADING`.
- Live authorization and the emergency stop are never touched by this package: the
  experiment's `Settings` override explicitly does **not** override
  `emergency_stop_file`, `system_state_log_file`, or `account_number` — these stay
  pointed at the same real, global files, so the experiment is always checked against
  (and can never diverge from) the real emergency-stop/authorization state.

## 6. Safety verification (Part 29-30)

`tests/test_phase40_safety.py` (19 tests, all passing) verifies:

1. No `src/paper_trading/*.py` or `scripts/paper_experiment.py` file directly imports
   `src.execution.live_client` (the real order-placement Protocol) or
   `src.execution.gateway` — both are only reachable transitively through the
   unmodified `src.orchestrator` call graph.
2. Def-aware scan: no Phase 40 file calls `place_option_order`, `place_equity_order`,
   `place_crypto_order`, `submit_order`, `cancel_*_order`, `modify_order`,
   `confirm_and_place`, `review_option_order`, or `review_equity_order`.
3. A **subprocess-isolated** dynamic import of every Phase 40 module (including the
   CLI script) confirms `src.execution.live_client` never enters `sys.modules`.
4. No Phase 40 file sets `live_trading_confirmed=True`, `live_auto_execute=True`, or
   `trading_mode="live"`.
5. `get_execution_gateway` returns `PaperExecutionGateway` (never `LiveExecutionGateway`)
   for this repository's actual configured `TRADING_MODE=paper`.
6. No Phase 40 file touches the emergency stop (`.clear(`/`.activate(`) or records a
   human-authorized system-state transition.
7. `place_option_order` is still called from **exactly one place** in the entire
   repository (`src/execution/gateway.py`) — unchanged by Phase 40.
8. Live authorization is OFF, the emergency stop is ACTIVE, `.env` is unchanged
   (`TRADING_MODE=paper`, `LIVE_TRADING_CONFIRMED=false`), and no Phase 40 file
   contains a credential-shaped string literal (reusing
   `src.research_recorder.security.assert_no_credential_shaped_content`).
9. `logs/paper_experiments/` (where a real experiment's data will live) is confirmed
   gitignored, matching the same convention already established for
   `logs/research_data/phase37/`.

## 7. Test results

| File | Tests | Result |
|---|---|---|
| `tests/test_phase40_experiment_config.py` | 12 | pass |
| `tests/test_phase40_state_machine_and_clock.py` | 13 | pass |
| `tests/test_phase40_account_and_slippage.py` | 26 | pass |
| `tests/test_phase40_engine.py` | 9 | pass |
| `tests/test_phase40_cli.py` | 10 | pass |
| `tests/test_phase40_safety.py` | 19 | pass |
| **Total (Phase 40)** | **89** | **89 passed** |

`tests/test_phase40_engine.py` exercises a **real entry and restart-safety** scenario
end to end: a bullish `UnderlyingSnapshot` + liquid option chain drives
`MomentumBreakoutStrategy` through `run_trading_cycle` to a genuine simulated ask-price
fill; the resulting `PaperExperimentTradeRecord` is verified labeled `PAPER_EXPERIMENT`,
tied to its real `observation_cycle_id`, and priced correctly. A second cycle against
the same still-open position proves `RiskManager`'s own (unmodified) "no existing
position in this underlying/contract" check prevents a duplicate entry — restart-safety
holds structurally, not just at the trade-store dedup layer. Insufficient starting
capital (`$1` against a $105 contract) is verified to never force a trade.

### Full project suite

```
python -m pytest tests/ -q
3188 passed, 5 failed
```

The 5 failures, **none caused by, or touched during, Phase 40**:

- **4 pre-existing `tests/test_orchestrator.py` failures**
  (`test_full_cycle_finds_setup_and_opens_a_paper_position`,
  `test_entries_still_allowed_before_local_cutoff_even_when_utc_clock_is_later`,
  `test_existing_paper_position_stop_exits_and_is_removed_from_ledger`,
  `test_everything_gets_logged`) — root cause: these tests hardcode a fixed
  `fetched_at`/`NOW` of 2026-08-18, but `MarketSnapshot.data_age_seconds` /
  `UnderlyingSnapshot.data_age_seconds` are computed against the **real wall clock**
  (`datetime.now(timezone.utc)`), not the business-logic `now` passed into
  `run_trading_cycle`. As real time has advanced past that hardcoded date, the fixture
  data now reads as stale and `RiskManager` correctly blocks the entry. This predates
  Phase 40 and was explicitly called out as a known, do-not-fix baseline per Part 31.
  (Phase 40's own engine tests avoid this exact issue by setting `fetched_at` to the
  real current time, decoupled from the synthetic business-logic `now` — see
  `tests/test_phase40_engine.py`'s module docstring.)
- **1 environment-dependent failure**,
  `tests/test_phase38_campaign.py::test_campaign_against_the_real_currently_empty_default_stores`
  — this test asserts the real `logs/research_data/phase37/` store is empty. It is no
  longer empty: earlier in this same session (before Phase 40 began), two real Phase 39
  observation cycles were run against live Robinhood data (`cyc-20260908T170535Z-9fc3429f`
  and `cyc-20260908T174932Z-2be78f56`), writing 36 real normalized-option rows to that
  store. This is a real, honest side effect of the Phase 39 work already reported to
  the user, not a Phase 40 defect — no Phase 40 file writes to that path (every Phase
  40 test uses its own `tmp_path`-scoped `research_recorder_dir`, verified via
  `experiment_paths()`).

Neither category was fixed, modified, or worked around to force a green suite.

## 8. Starting the real experiment (not done in this phase)

Per Part 32/34, the experiment has **not** been started. To start it explicitly in a
future turn:

```bash
# Start (creates an immutable ExperimentConfig, CREATED -> RUNNING)
python3 scripts/paper_experiment.py start --capital 1000 --days 14

# Run one real cycle (requires real, agent-fetched Robinhood data in --data-dir,
# following the same manual runbook convention as scripts/run_live_research_cycle.py)
python3 scripts/paper_experiment.py run-cycle --experiment-id <id> --data-dir <real-data-dir>

# Check status (also auto-completes RUNNING -> COMPLETED once the 14-calendar-day
# minimum is reached -- duration-based, never loss-based)
python3 scripts/paper_experiment.py status --experiment-id <id>

# Pause / resume / stop (explicit only -- never automatic on a loss)
python3 scripts/paper_experiment.py pause  --experiment-id <id> --reason "..."
python3 scripts/paper_experiment.py resume --experiment-id <id> --reason "..."
python3 scripts/paper_experiment.py stop   --experiment-id <id> --reason "..."

# Final report (Part 26-28: starting/ending capital, net P&L, return, max drawdown,
# trade count -- never annualized, never implying strategy validation)
python3 scripts/paper_experiment.py report --experiment-id <id>
```

Each real cycle still requires the same manual runbook Phase 39 established (nothing
in this codebase calls a HOOD MCP tool by itself): fetch real quotes via the
authenticated Robinhood MCP tools, save them into a `--data-dir`, then run `run-cycle`.

## 9. Verdict

**A. PAPER_EXPERIMENT_ENGINE_READY**

- Starting capital: $1,000 (configurable)
- Minimum duration: 14 calendar days (continues across weekends/holidays; no trading
  while closed, clock keeps running)
- Strategy configured: `MOMENTUM_BREAKOUT_EXISTING_V1`, status `NOT_READY` in the real
  registry (unchanged), running in `PAPER_EXPERIMENT_ONLY` mode — structurally
  distinct from, and never a path to, `VALIDATED_STRATEGY` or live authorization
- Data source: real-time Robinhood market data only, via the existing Phase 37
  recorder + Phase 39 live bridge — no fabricated, random, or stale-as-current data
- Safety verified: 19/19 Phase 40 safety tests pass (§6); live authorization OFF;
  emergency stop ACTIVE; zero reachable real-order call paths (static + dynamic +
  subprocess-isolated verification)
- Test results: 89/89 Phase 40 tests pass; full-suite run shows only the 4 known
  pre-existing `test_orchestrator.py` failures plus 1 environment-dependent failure
  from earlier real data collection this session — neither caused by or touched during
  Phase 40

This report does **not** claim `MOMENTUM_BREAKOUT_EXISTING_V1` is validated, does
**not** claim live-trading readiness, and no real Robinhood order has been or can be
placed by this package. The 14-day experiment has not been started — that is an
explicit, separate, user-initiated action using the commands in §8.
