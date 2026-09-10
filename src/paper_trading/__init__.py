"""Phase 40 — 14-day autonomous options paper-trading experiment.

RESEARCH/EXPERIMENT ONLY. This package NEVER places a real Robinhood
order — see tests/test_phase40_safety.py for the same static-AST +
forbidden-call + subprocess-isolated dynamic-import verification Phase
37/38/39 already established, extended to every module here.

Architecture (Part 1's audit, summarized — see
docs/phase40_14_day_paper_experiment.md for the full writeup):

`src/orchestrator.py::run_trading_cycle` is ALREADY a complete, real,
autonomous options-only paper-trading engine — strategy scan
(MomentumBreakoutStrategy) -> fresh re-validation (RiskManager,
11 checks) -> simulated entry (PaperExecutionGateway, ask-price fill,
audit-logged) -> position tracking (PaperPositionStore/OpenPosition) ->
deterministic exits (PositionEvaluator, priority-ordered: thesis
invalidation, hard stop, expiration, trailing, momentum-driven early
exit, profit target) -> TradeJournal. This package does NOT rebuild any
of that — every module below is a THIN, ADDITIVE layer on top of it,
built only to supply what a 14-day, $1,000, restart-safe EXPERIMENT
needs that the general-purpose bot infrastructure does not already
track: an explicit experiment identity/configuration, a $1,000 cash/
equity ledger derived from the existing paper-position/trade-journal
state, a calendar-day experiment clock and CREATED/RUNNING/PAUSED/
COMPLETED/ABORTED state machine, an enriched per-experiment trade
journal (gross/net P&L, spread cost, slippage, fees, MFE/MAE,
observation-cycle provenance), an equity-curve/daily-performance
rollup, and a CLI to start/pause/resume/stop/inspect it — plus real
Phase 37 recorder + Phase 39 live-bridge integration for the real
market data feeding every cycle.

Modules:
  - experiment_config.py — immutable ExperimentConfig (Part 5), the
    PAPER_EXPERIMENT_ONLY strategy mode (Part 2, structurally distinct
    from src.production.registry.StrategyStatus.VALIDATED — never
    accepted by the live pipeline).
  - state_machine.py — CREATED/RUNNING/PAUSED/COMPLETED/ABORTED (Part 24).
  - clock.py — calendar-day vs market-day tracking (Part 4).
  - account.py — the $1,000 cash/equity ledger, always RE-DERIVED from
    the trade journal + open positions, never incrementally mutated
    (Part 3's "never allow unexplained balance changes").
  - slippage.py — BASELINE/STRESSED cost assumptions, reusing
    src.options.cost_model.CostAssumption verbatim (Part 12/13 — never
    an invented favorable fee).
  - journal.py — the enriched PAPER_EXPERIMENT trade record (Part 19).
  - equity_curve.py / daily_performance.py — Parts 17-18.
  - risk_monitoring.py — Part 20.
  - engine.py — run_paper_experiment_cycle(), the per-cycle wrapper.
  - report.py — final-report data aggregation (Part 26-28).

Phase 41 — the automatic market-open scheduler (docs/phase41_automatic_
scheduler.md has the full operational runbook). Builds entirely on the
modules above, adds only:
  - market_calendar.py — market-open detection + deterministic intraday
    cadence slots, on top of Phase 37's unmodified is_market_open_for_
    recording (scheduling component A).
  - data_acquisition.py — the InboxDataAcquisitionProvider seam real
    agent-fetched Robinhood data flows through into a scheduled cycle;
    never a fake MCP client (scheduling component B).
  - scheduler_events.py — the scheduler's own append-only operational
    event log (PAPER_SCHEDULER_STARTED, MARKET_OPEN, DATA_COLLECTION_*,
    PAPER_CYCLE_*, PAPER_ENTRY/EXIT, EXPERIMENT_COMPLETED, ...).
  - cycle_runner.py — execute_paper_cycle(), the ONE real-cycle execution
    path shared by scripts/paper_experiment.py's CLI and the scheduler
    (scheduling component C — never re-implements run_paper_experiment_
    cycle, only wraps it).
  - scheduler.py — run_scheduler_tick()/run_scheduler_forever(), the
    deterministic decide-then-execute loop tying A+B+C together, plus
    duplicate-cycle protection via slot_id natural keys.
  - scripts/run_paper_scheduler.py — the CLI entrypoint that starts it.
"""
