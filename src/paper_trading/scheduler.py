"""Phase 41 — the automatic market-open paper-trading scheduler.

Builds ONLY on already-existing, unmodified components:

  A. Scheduling/orchestration -- THIS FILE. Decides WHEN a cycle is due
     (market-open detection: `src.paper_trading.market_calendar`, itself
     built on Phase 37's unmodified `is_market_open_for_recording`),
     assigns each intended cycle a deterministic slot_id for duplicate
     protection, and drives execution end to end.
  B. Robinhood data acquisition -- `src.paper_trading.data_acquisition`.
     Nothing in this codebase can call a HOOD MCP tool directly (see
     `src/live_bridge.py`'s module docstring, still unmodified and still
     true). This file never invents fake MCP connectivity; it only calls
     whatever `DataAcquisitionProvider` it is given, and NEVER runs a
     cycle, and NEVER fabricates/interpolates/substitutes data, when
     acquisition fails.
  C. Paper-cycle execution -- `src.paper_trading.cycle_runner.
     execute_paper_cycle`, itself a thin wrapper around Phase 40's own
     `run_paper_experiment_cycle` (UNCHANGED). This file never
     re-implements the decision pipeline, the strategy, or risk checks.

Testability: `run_scheduler_tick` performs exactly ONE decision for a
given `now` and returns a short outcome tag — the entire state machine is
a pure function of (experiment state on disk, scheduler event log on
disk, `now`, what the acquisition provider returns), so tests drive it
directly with fabricated clocks and fake providers, never real sleeping.
`run_scheduler_forever` is the thin real-time loop around it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from src.config.settings import Settings
from src.paper_trading.data_acquisition import DataAcquisitionProvider, InboxDataAcquisitionProvider
from src.paper_trading.cycle_runner import execute_paper_cycle
from src.paper_trading.engine import DATA_UNAVAILABLE, MARKET_CLOSED_RESULT, NO_QUALIFIED_OPPORTUNITY as ENGINE_NO_QUALIFIED_OPPORTUNITY, experiment_paths
from src.paper_trading.experiment_config import ExperimentConfigStore
from src.paper_trading.market_calendar import is_market_open_now, slot_id_for
from src.paper_trading.scheduler_events import (
    DATA_COLLECTION_FAILED,
    DATA_COLLECTION_PARTIAL,
    DATA_COLLECTION_STARTED,
    EXPERIMENT_COMPLETED,
    MARKET_CLOSED,
    MARKET_OPEN,
    NO_QUALIFIED_OPPORTUNITY,
    PAPER_CYCLE_COMPLETED,
    PAPER_CYCLE_FAILED,
    PAPER_CYCLE_STARTED,
    PAPER_ENTRY,
    PAPER_EXIT,
    PAPER_SCHEDULER_STARTED,
    PAPER_SCHEDULER_STOPPED,
    SLOT_ALREADY_COMPLETED,
    WAITING_FOR_MARKET_OPEN,
    SchedulerEvent,
    SchedulerEventStore,
)
from src.paper_trading.slippage import SlippageAssumptionTier
from src.paper_trading.state_machine import ExperimentStateStore, ExperimentStatus

DEFAULT_CADENCE_MINUTES = 15
DEFAULT_DATA_ACQUISITION_TIMEOUT_SECONDS = 600.0
DEFAULT_POLL_INTERVAL_SECONDS = 30.0


def _env_int(env: dict, key: str, default: int) -> int:
    raw = env.get(key)
    return int(raw) if raw not in (None, "") else default


def _env_float(env: dict, key: str, default: float) -> float:
    raw = env.get(key)
    return float(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class SchedulerConfig:
    experiment_id: str
    cadence_minutes: int = DEFAULT_CADENCE_MINUTES
    data_acquisition_timeout_seconds: float = DEFAULT_DATA_ACQUISITION_TIMEOUT_SECONDS
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    inbox_root: Path | None = None  # defaults to logs/paper_experiments/<experiment_id>/scheduler/inbox
    slippage_tier: SlippageAssumptionTier = SlippageAssumptionTier.BASELINE
    holidays: frozenset = field(default_factory=frozenset)  # honestly empty by default -- see market_calendar.py

    def resolved_inbox_root(self) -> Path:
        if self.inbox_root is not None:
            return Path(self.inbox_root)
        return experiment_paths(self.experiment_id).base_dir / "scheduler" / "inbox"

    @classmethod
    def from_env(cls, experiment_id: str, env: dict | None = None, **overrides) -> "SchedulerConfig":
        """Cadence and timeouts are configurable through the environment
        (`PAPER_SCHEDULER_CADENCE_MINUTES`, `PAPER_SCHEDULER_DATA_TIMEOUT_SECONDS`,
        `PAPER_SCHEDULER_POLL_INTERVAL_SECONDS`) rather than hard-coded, per
        the Phase 41 CADENCE requirement -- explicit keyword `overrides`
        (e.g. from CLI flags) win over the environment."""
        import os

        env = env if env is not None else dict(os.environ)
        kwargs = dict(
            experiment_id=experiment_id,
            cadence_minutes=_env_int(env, "PAPER_SCHEDULER_CADENCE_MINUTES", DEFAULT_CADENCE_MINUTES),
            data_acquisition_timeout_seconds=_env_float(
                env, "PAPER_SCHEDULER_DATA_TIMEOUT_SECONDS", DEFAULT_DATA_ACQUISITION_TIMEOUT_SECONDS,
            ),
            poll_interval_seconds=_env_float(env, "PAPER_SCHEDULER_POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS),
        )
        kwargs.update(overrides)
        return cls(**kwargs)


def _events_path(config: SchedulerConfig) -> Path:
    return experiment_paths(config.experiment_id).base_dir / "scheduler" / "scheduler_events.jsonl"


def build_event_store(config: SchedulerConfig) -> SchedulerEventStore:
    return SchedulerEventStore(_events_path(config))


def build_acquisition_provider(config: SchedulerConfig, *, sleep_fn: Callable[[float], None] = time.sleep) -> DataAcquisitionProvider:
    return InboxDataAcquisitionProvider(
        inbox_root=config.resolved_inbox_root(), timeout_seconds=config.data_acquisition_timeout_seconds,
        poll_interval_seconds=min(config.poll_interval_seconds, config.data_acquisition_timeout_seconds) or 1.0,
        sleep_fn=sleep_fn,
    )


def run_scheduler_tick(
    *,
    config: SchedulerConfig,
    event_store: SchedulerEventStore,
    acquisition_provider: DataAcquisitionProvider,
    now: datetime,
    base_settings: Settings | None = None,
) -> str:
    """Performs at most ONE decision (and, if a cycle is due, one real
    cycle execution) for `now`. Returns a short outcome tag, primarily
    for tests/introspection -- the durable record of what happened is
    always the appended `SchedulerEvent`(s), never this return value."""
    base_settings = base_settings or Settings.from_env()
    experiment_id = config.experiment_id

    config_store = ExperimentConfigStore(experiment_paths(experiment_id).experiment_config_file)
    state_store = ExperimentStateStore(experiment_paths(experiment_id).experiment_state_file)
    exp_config = config_store.get()
    if exp_config is None:
        event_store.append(SchedulerEvent(
            event=PAPER_CYCLE_FAILED, experiment_id=experiment_id, at=now,
            message=f"No experiment config found for {experiment_id!r} -- run 'start' first",
        ))
        return "NO_EXPERIMENT"

    status = state_store.current_status()
    if status in (ExperimentStatus.COMPLETED, ExperimentStatus.ABORTED):
        event_store.append(SchedulerEvent(event=EXPERIMENT_COMPLETED, experiment_id=experiment_id, at=now, outcome=status.value))
        return "EXPERIMENT_TERMINAL"
    if status != ExperimentStatus.RUNNING:
        # PAUSED (or MISSING, which should not happen once CREATED->RUNNING
        # has been recorded) -- wait without attempting acquisition/a cycle.
        event_store.append(SchedulerEvent(event=WAITING_FOR_MARKET_OPEN, experiment_id=experiment_id, at=now, message=f"status={status.value if status else 'MISSING'}"))
        return "EXPERIMENT_NOT_RUNNING"

    if not is_market_open_now(now, base_settings, config.holidays):
        event_store.append(SchedulerEvent(event=WAITING_FOR_MARKET_OPEN, experiment_id=experiment_id, at=now))
        return "MARKET_CLOSED"

    slot_id = slot_id_for(now, base_settings, config.cadence_minutes)
    event_store.append(SchedulerEvent(event=MARKET_OPEN, experiment_id=experiment_id, at=now, slot_id=slot_id))

    if slot_id in event_store.completed_slot_ids():
        event_store.append(SchedulerEvent(event=SLOT_ALREADY_COMPLETED, experiment_id=experiment_id, at=now, slot_id=slot_id))
        return "SLOT_ALREADY_COMPLETED"

    universe = exp_config.universe
    event_store.append(SchedulerEvent(
        event=DATA_COLLECTION_STARTED, experiment_id=experiment_id, at=now, slot_id=slot_id,
        symbols_attempted=len(universe),
    ))
    acquisition = acquisition_provider.acquire(universe, slot_id)

    if not acquisition.ready:
        event_store.append(SchedulerEvent(
            event=DATA_COLLECTION_FAILED, experiment_id=experiment_id, at=now, slot_id=slot_id,
            symbols_attempted=len(universe), symbols_collected=0, symbols_failed=len(universe),
            message=acquisition.reason,
        ))
        return "DATA_COLLECTION_FAILED"

    if not acquisition.collected_symbols:
        event_store.append(SchedulerEvent(
            event=DATA_COLLECTION_FAILED, experiment_id=experiment_id, at=now, slot_id=slot_id,
            symbols_attempted=len(universe), symbols_collected=0, symbols_failed=len(acquisition.failed_symbols),
            message="Inbox was marked READY but no symbol's equity_quotes file was found",
        ))
        return "DATA_COLLECTION_FAILED"

    if acquisition.failed_symbols:
        event_store.append(SchedulerEvent(
            event=DATA_COLLECTION_PARTIAL, experiment_id=experiment_id, at=now, slot_id=slot_id,
            symbols_attempted=len(universe), symbols_collected=len(acquisition.collected_symbols),
            symbols_failed=len(acquisition.failed_symbols),
            message=f"missing: {','.join(acquisition.failed_symbols)}",
        ))

    event_store.append(SchedulerEvent(event=PAPER_CYCLE_STARTED, experiment_id=experiment_id, at=now, slot_id=slot_id))

    try:
        outcome = execute_paper_cycle(
            experiment_id=experiment_id, data_dir=acquisition.data_dir, now=now,
            slippage_tier=config.slippage_tier, base_settings=base_settings,
        )
    except Exception as exc:  # noqa: BLE001 -- a failure here must never crash the daemon or corrupt state
        event_store.append(SchedulerEvent(
            event=PAPER_CYCLE_FAILED, experiment_id=experiment_id, at=now, slot_id=slot_id,
            message=f"{type(exc).__name__}: {exc}",
        ))
        return "PAPER_CYCLE_FAILED"

    if not outcome.ok:
        event_store.append(SchedulerEvent(event=PAPER_CYCLE_FAILED, experiment_id=experiment_id, at=now, slot_id=slot_id, message=outcome.error))
        return "PAPER_CYCLE_FAILED"

    result = outcome.result
    equity_usd = result.account_snapshot.equity_usd if result.account_snapshot else None
    open_positions = result.account_snapshot.open_position_count if result.account_snapshot else None

    if result.outcome == MARKET_CLOSED_RESULT:
        event_store.append(SchedulerEvent(event=MARKET_CLOSED, experiment_id=experiment_id, at=now, slot_id=slot_id))
        return "MARKET_CLOSED_DURING_CYCLE"

    if result.outcome == DATA_UNAVAILABLE:
        event_store.append(SchedulerEvent(
            event=PAPER_CYCLE_FAILED, experiment_id=experiment_id, at=now, slot_id=slot_id,
            message=f"DATA_UNAVAILABLE: {result.errors}",
        ))
        return "DATA_UNAVAILABLE"

    for trade in result.new_trades:
        event_store.append(SchedulerEvent(
            event=PAPER_ENTRY, experiment_id=experiment_id, at=now, slot_id=slot_id,
            observation_cycle_id=result.observation_cycle_id, option_id=trade.option_id, equity_usd=equity_usd,
        ))
    for trade in result.closed_trades:
        event_store.append(SchedulerEvent(
            event=PAPER_EXIT, experiment_id=experiment_id, at=now, slot_id=slot_id,
            observation_cycle_id=result.observation_cycle_id, option_id=trade.option_id, equity_usd=equity_usd,
        ))

    if result.outcome == ENGINE_NO_QUALIFIED_OPPORTUNITY:
        event_store.append(SchedulerEvent(
            event=NO_QUALIFIED_OPPORTUNITY, experiment_id=experiment_id, at=now, slot_id=slot_id,
            observation_cycle_id=result.observation_cycle_id, equity_usd=equity_usd, open_positions=open_positions,
        ))
        return_tag = "NO_QUALIFIED_OPPORTUNITY"
    else:  # CYCLE_OK
        event_store.append(SchedulerEvent(
            event=PAPER_CYCLE_COMPLETED, experiment_id=experiment_id, at=now, slot_id=slot_id,
            observation_cycle_id=result.observation_cycle_id, equity_usd=equity_usd, open_positions=open_positions,
            symbols_attempted=len(universe), symbols_collected=len(acquisition.collected_symbols),
        ))
        return_tag = "CYCLE_OK"

    if outcome.auto_completed:
        event_store.append(SchedulerEvent(event=EXPERIMENT_COMPLETED, experiment_id=experiment_id, at=now, outcome="COMPLETED"))

    return return_tag


def run_scheduler_forever(
    config: SchedulerConfig,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    max_iterations: int | None = None,
    base_settings: Settings | None = None,
) -> None:
    """The real-time loop. Every iteration is one `run_scheduler_tick`
    call followed by a sleep of `config.poll_interval_seconds` -- never a
    busy loop, never assumes one market-open tick is enough to manage an
    open position (subsequent ticks keep evaluating exits, per the
    CADENCE requirement). Stops only when the experiment reaches a
    terminal state (COMPLETED/ABORTED) or `max_iterations` is reached
    (test-only escape hatch; real usage passes `max_iterations=None`)."""
    event_store = build_event_store(config)
    acquisition_provider = build_acquisition_provider(config, sleep_fn=sleep_fn)
    base_settings = base_settings or Settings.from_env()

    event_store.append(SchedulerEvent(
        event=PAPER_SCHEDULER_STARTED, experiment_id=config.experiment_id, at=now_fn(),
        message=f"cadence_minutes={config.cadence_minutes} data_acquisition_timeout_seconds={config.data_acquisition_timeout_seconds}",
    ))

    iterations = 0
    try:
        while True:
            outcome = run_scheduler_tick(
                config=config, event_store=event_store, acquisition_provider=acquisition_provider,
                now=now_fn(), base_settings=base_settings,
            )
            if outcome == "EXPERIMENT_TERMINAL":
                break
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            sleep_fn(config.poll_interval_seconds)
    finally:
        event_store.append(SchedulerEvent(event=PAPER_SCHEDULER_STOPPED, experiment_id=config.experiment_id, at=now_fn()))
