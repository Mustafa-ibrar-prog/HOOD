"""Phase 41, scheduling component C — the ONE real-cycle execution path,
shared by the manual CLI (`scripts/paper_experiment.py run-cycle`) and
the automatic scheduler (`src.paper_trading.scheduler`), so the two never
drift apart.

Does not reimplement anything Phase 40's engine already does: this is a
thin, byte-for-byte-identical extraction of the exact sequence
`scripts/paper_experiment.py::cmd_run_cycle` already performed before
this file existed (load config/state, refuse if the experiment is
missing or not RUNNING, build the real `StaticHoodClient` +
`HoodMarketDataProvider`, call `run_paper_experiment_cycle` — UNCHANGED,
Phase 40 — then apply the SAME duration-based auto-complete check Part 25
already specified: never auto-stop merely because of a loss, only because
the configured minimum duration was reached). `scripts/paper_experiment.py`
now calls this function too, instead of duplicating it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.config.settings import Settings
from src.live_bridge import load_static_hood_client_from_dir
from src.market.hood_provider import HoodMarketDataProvider
from src.paper_trading.clock import compute_clock_status
from src.paper_trading.engine import ExperimentPaths, PaperExperimentCycleResult, experiment_paths, run_paper_experiment_cycle
from src.paper_trading.equity_curve import EquitySnapshotStore
from src.paper_trading.experiment_config import ExperimentConfigStore, MINIMUM_EXPERIMENT_DAYS
from src.paper_trading.slippage import SlippageAssumptionTier
from src.paper_trading.state_machine import ExperimentStateStore, ExperimentStatus


@dataclass(frozen=True)
class CycleRunOutcome:
    ok: bool  # False => refused before ever touching market data (missing experiment / not RUNNING)
    error: str | None
    result: PaperExperimentCycleResult | None
    auto_completed: bool
    paths: ExperimentPaths | None


def execute_paper_cycle(
    *,
    experiment_id: str,
    data_dir: Path,
    now: datetime | None = None,
    slippage_tier: SlippageAssumptionTier = SlippageAssumptionTier.BASELINE,
    base_settings: Settings | None = None,
) -> CycleRunOutcome:
    paths = experiment_paths(experiment_id)
    config_store = ExperimentConfigStore(paths.experiment_config_file)
    state_store = ExperimentStateStore(paths.experiment_state_file)

    config = config_store.get()
    if config is None:
        return CycleRunOutcome(
            ok=False, error=f"No experiment config found for {experiment_id!r} — run 'start' first",
            result=None, auto_completed=False, paths=paths,
        )
    status = state_store.current_status()
    if status != ExperimentStatus.RUNNING:
        return CycleRunOutcome(
            ok=False, error=f"Experiment status is {status.value if status else 'MISSING'}, not RUNNING — no cycle run",
            result=None, auto_completed=False, paths=paths,
        )

    now = now or datetime.now(timezone.utc)
    base_settings = base_settings or Settings.from_env()
    client = load_static_hood_client_from_dir(data_dir, base_settings.account_number)
    market = HoodMarketDataProvider(client, base_settings)

    result = run_paper_experiment_cycle(
        config=config, client=client, market=market, base_settings=base_settings, now=now,
        slippage_tier=slippage_tier, paths=paths,
    )

    # Auto-complete on reaching the minimum duration -- the designed end
    # condition (Part 25: never auto-stop merely because of a loss).
    auto_completed = False
    clock = compute_clock_status(
        experiment_start=config.start_timestamp, planned_minimum_end=config.planned_minimum_end_timestamp, now=now,
        cycle_dates=frozenset(e.timestamp.date() for e in EquitySnapshotStore(paths.equity_curve_file).load_all()),
    )
    if clock.minimum_duration_met:
        state_store.transition(
            experiment_id=experiment_id, to_status=ExperimentStatus.COMPLETED, at=now,
            reason=f"Reached the {MINIMUM_EXPERIMENT_DAYS}-calendar-day minimum duration",
        )
        auto_completed = True

    return CycleRunOutcome(ok=True, error=None, result=result, auto_completed=auto_completed, paths=paths)
