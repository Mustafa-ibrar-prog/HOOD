# Phase 41 — Automatic Market-Open Paper-Trading Scheduler

Builds an automatic runner on top of the already-running, unmodified
Phase 40 14-day, $1,000, `PAPER_EXPERIMENT_ONLY` experiment
(`exp-20260908T183001Z-21ca70b3`, strategy `MOMENTUM_BREAKOUT_EXISTING_V1`).
This document is the operational runbook for the scheduler; Phase 40's
own `docs/phase40_14_day_paper_experiment.md` is unchanged and still
describes the underlying experiment/engine.

## Why a "fully automatic" scheduler is honestly only partial

Nothing in this codebase can call a HOOD MCP tool from Python —
`src/live_bridge.py`'s module docstring has documented this since Phase
39, and it is still true; Phase 41 does not change it and does not
pretend otherwise. The real, read-only Robinhood tool responses every
cycle needs must still be fetched by an agent's own tool-call interface.

What Phase 41 actually automates is everything AROUND that fetch:
deciding **when** a cycle is due (real market-open detection, configurable
intraday cadence, weekend/holiday awareness), **waiting** for the data to
arrive, **running** the cycle the instant it does, **never** running one
when it doesn't, and **repeating** this for the life of the 14-day
experiment without a human re-issuing "RUN" for every cycle.

## Architecture

Three explicitly separated components, per the Phase 41 requirement:

```
A. Scheduling/orchestration   src/paper_trading/scheduler.py
                               src/paper_trading/market_calendar.py
                               src/paper_trading/scheduler_events.py

B. Robinhood data acquisition src/paper_trading/data_acquisition.py
                               (InboxDataAcquisitionProvider)

C. Paper-cycle execution      src/paper_trading/cycle_runner.py
                               src/paper_trading/engine.py (Phase 40,
                               UNCHANGED: run_paper_experiment_cycle)
```

`scripts/run_paper_scheduler.py` is the CLI entrypoint that wires A+B+C
together via `run_scheduler_forever`.

### A. Scheduling/orchestration

`market_calendar.is_market_open_now` reuses Phase 37's unmodified
`is_market_open_for_recording` for the actual weekday + time-of-day gate,
adding only an (honestly empty by default) injectable holiday set — this
codebase has no holiday-calendar dependency, so none is hard-coded.

`market_calendar.slot_id_for` computes a deterministic identity for "the
intraday cadence slot `now` falls into," anchored at that day's real
market open (e.g. `2026-09-08-slot0000` for the 9:30 ET slot at a
15-minute cadence). A scheduler that restarts mid-slot (9:35 after a 9:30
wake) computes the *same* slot_id — this natural key is the entire
duplicate-cycle-protection mechanism; no separate "already ran" flag file
is needed.

`scheduler.run_scheduler_tick` performs exactly one decision for a given
`now`: check experiment status → check market hours → compute slot_id →
skip if that slot already completed → acquire data → run the cycle →
log the outcome. `run_scheduler_forever` is the thin real-time loop
around it (`tick`, sleep `poll_interval_seconds`, repeat) — it stops only
when the experiment reaches `COMPLETED`/`ABORTED`.

### B. Robinhood data acquisition

`InboxDataAcquisitionProvider` polls `<inbox_root>/<slot_id>/` for real
HOOD responses saved with `src.live_bridge.save_hood_response_to_data_dir`'s
existing naming convention, plus a `READY` sentinel file
(`data_acquisition.mark_inbox_slot_ready`) the agent writes only once
every response it intends to supply for that slot has actually been
written. The provider never treats a directory without `READY` as
complete, never fabricates a missing symbol's quote, and reports a
timeout (no `READY` within `data_acquisition_timeout_seconds`) as a clean
failure — no cycle runs for that slot.

**The agent's job at each scheduled slot** (identical in spirit to the
Phase 39/40 manual runbook, just now targeting the scheduler's inbox
instead of an ad hoc directory):

1. Watch for (or compute ahead of time) the current `slot_id` — a small
   helper: `src.paper_trading.market_calendar.slot_id_for(now, settings, cadence_minutes)`.
2. Fetch the real, read-only HOOD tool responses the experiment's
   universe needs this cycle (same tools as before: `get_equity_quotes`,
   `get_equity_historicals`, `get_option_chains`, `get_option_instruments`,
   `get_option_quotes`, `get_option_positions`).
3. Save each one into `<inbox_root>/<slot_id>/` using
   `src.live_bridge.save_hood_response_to_data_dir` — same filenames as
   always (`equity_quotes_<SYMBOL>.json`, etc.).
4. Call `src.paper_trading.data_acquisition.mark_inbox_slot_ready(inbox_root, slot_id)`
   once done. This is the ONLY signal the provider accepts.

If a symbol's data can't be obtained, simply don't write that symbol's
files — the scheduler logs `DATA_COLLECTION_PARTIAL` (or
`DATA_COLLECTION_FAILED` if nothing at all arrives) and proceeds honestly
with whatever real data exists, exactly like Phase 37/40 already did.

### C. Paper-cycle execution

`cycle_runner.execute_paper_cycle` is a thin, byte-for-byte extraction of
what `scripts/paper_experiment.py::cmd_run_cycle` already did: refuse if
the experiment is missing or not `RUNNING`, build the real
`StaticHoodClient` + `HoodMarketDataProvider` from the inbox directory,
call `engine.run_paper_experiment_cycle` (Phase 40, UNCHANGED), then
apply the same duration-based auto-complete check. Both the manual CLI
and the scheduler call this ONE function — they cannot drift.

## Starting the automatic runner

```
python3 scripts/run_paper_scheduler.py \
    --experiment-id exp-20260908T183001Z-21ca70b3 \
    --cadence-minutes 15 \
    --data-timeout-seconds 600 \
    --poll-interval-seconds 30
```

Cadence/timeouts default to the environment
(`PAPER_SCHEDULER_CADENCE_MINUTES`, `PAPER_SCHEDULER_DATA_TIMEOUT_SECONDS`,
`PAPER_SCHEDULER_POLL_INTERVAL_SECONDS`) when a flag is omitted — see
`SchedulerConfig.from_env`. The process runs until the experiment reaches
`COMPLETED` (the 14-calendar-day minimum) or `ABORTED`, or is stopped.

## Market-open detection

`America/New_York`, regular session open `09:30`, using the unmodified
Phase 37 weekday + time-of-day gate. No holiday calendar dependency
exists in this repo, so a market holiday falling on a weekday is not
distinguished in advance from a normal trading day — the exact same
honest limitation `src/paper_trading/clock.py` already discloses for the
14-day experiment clock, now shared by the scheduler. `market_calendar`
accepts an (empty-by-default) `holidays: frozenset[date]` injection point
for if/when a real calendar dependency is added later.

## Default intraday cadence

15 minutes (`DEFAULT_CADENCE_MINUTES`), configurable via
`PAPER_SCHEDULER_CADENCE_MINUTES` or `--cadence-minutes`. Every cadence
slot during market hours runs its own independent cycle — an open paper
position is re-evaluated (for exits, via the unmodified
`PositionEvaluator`/`RiskManager` inside `run_trading_cycle`) on every
subsequent slot, not just the market-open slot.

## Restart recovery

Everything the scheduler needs to resume correctly is durable, replayed
from disk, never held only in memory:

- Experiment status/config: `ExperimentStateStore`/`ExperimentConfigStore`
  (Phase 40, unchanged).
- Account state (cash, equity, realized/unrealized P&L, drawdown, open
  positions, trade journal): `EquitySnapshotStore`, `PaperPositionStore`,
  `PaperExperimentTradeStore` (Phase 40, unchanged) — a process restart
  never resets the $1,000 account.
- Scheduler-specific operational history (which slot ran, last
  successful/attempted cycle, data-acquisition failures, scheduler
  status): `SchedulerEventStore` (`scheduler_events.jsonl`, Phase 41,
  additive, append-only, replayed on read).

## Duplicate-cycle prevention

`slot_id_for` is a deterministic natural key computed purely from `now`
and the day's real market-open time — no separate "did this run" flag
needs to be persisted or raced. `SchedulerEventStore.completed_slot_ids()`
replays the event log for every `PAPER_CYCLE_COMPLETED`/
`NO_QUALIFIED_OPPORTUNITY` event's `slot_id`; a tick for an already-completed
slot short-circuits (`SLOT_ALREADY_COMPLETED`) before ever calling the
acquisition provider or running a cycle again. A slot that only ever
*failed* (data-collection failure, malformed data, an exception) is
deliberately NOT marked completed, so the next tick may retry it.

## Operational log events

`PAPER_SCHEDULER_STARTED`, `PAPER_SCHEDULER_STOPPED`, `MARKET_CLOSED`,
`WAITING_FOR_MARKET_OPEN`, `MARKET_OPEN`, `DATA_COLLECTION_STARTED`,
`DATA_COLLECTION_PARTIAL`, `DATA_COLLECTION_FAILED`, `PAPER_CYCLE_STARTED`,
`PAPER_CYCLE_COMPLETED`, `NO_QUALIFIED_OPPORTUNITY`, `PAPER_ENTRY`,
`PAPER_EXIT`, `PAPER_CYCLE_FAILED`, `EXPERIMENT_COMPLETED`,
`SLOT_ALREADY_COMPLETED` — each carries `experiment_id`, `slot_id` (where
applicable), `observation_cycle_id` (where applicable), a real
`at` timestamp, and (where applicable) symbols attempted/collected/
failed, option-contract counts, outcome, equity, and open-position count.
Stored in `logs/paper_experiments/<experiment_id>/scheduler/scheduler_events.jsonl`
(gitignored, same as the rest of `logs/paper_experiments/`).

## Safety

Identical structural guarantees to Phase 40, re-verified for every new
Phase 41 file by `tests/test_phase41_safety.py`: no direct import of
`src.execution.live_client`/`src.execution.gateway`; `LiveExecutionGateway`
and `place_option_order` are unreachable except transitively through the
unmodified `run_trading_cycle` call graph (which itself only ever
constructs a `PaperExecutionGateway` while `TRADING_MODE=paper`); no
Phase 41 file touches the emergency stop, forces live trading mode,
records a human-authorized system-state transition, or mutates the
`StrategyRegistry`; `MOMENTUM_BREAKOUT_EXISTING_V1` remains `NOT_READY`;
`ExperimentStatus` values remain disjoint from `SystemState` values.
