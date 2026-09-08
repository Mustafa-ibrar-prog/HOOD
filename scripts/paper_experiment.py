#!/usr/bin/env python3
"""Phase 40 — the 14-day, $1,000 autonomous options paper-trading
experiment CLI.

PAPER TRADING ONLY. Never places, modifies, or cancels a real Robinhood
order — every cycle runs through src.orchestrator.run_trading_cycle,
which itself only ever reaches a PaperExecutionGateway while
TRADING_MODE=paper (this script never sets TRADING_MODE=live).

Subcommands:
  start        Create a new experiment (CREATED -> RUNNING). Explicit,
               never automatic — see module docstring in
               src/paper_trading/__init__.py.
  run-cycle    Run ONE real cycle (Phase 37 recorder + Phase 39 live
               bridge + src.orchestrator.run_trading_cycle) against
               agent-fetched real data in --data-dir. Not a scheduler —
               see scripts/run_live_research_cycle.py's own docstring
               for why nothing in this codebase can call a HOOD MCP tool
               itself; the SAME manual-runbook convention applies here.
  pause        RUNNING -> PAUSED.
  resume       PAUSED -> RUNNING.
  stop         Explicit early stop -> ABORTED.
  status       Print the current experiment status, clock, account, and
               readiness summary. Also auto-marks the experiment
               COMPLETED (RUNNING -> COMPLETED) if the configured
               minimum 14-calendar-day duration has been reached —
               duration-based completion is the DESIGNED end condition
               (Part 25: never auto-stop merely because of a loss).
  report       Print/write the full final-report data (Part 26-28).

Usage:
    python3 scripts/paper_experiment.py start --capital 1000 --days 14
    python3 scripts/paper_experiment.py run-cycle --experiment-id <id> --data-dir <dir> [--now ISO8601] [--symbols A,B]
    python3 scripts/paper_experiment.py status --experiment-id <id>
    python3 scripts/paper_experiment.py pause --experiment-id <id>
    python3 scripts/paper_experiment.py resume --experiment-id <id>
    python3 scripts/paper_experiment.py stop --experiment-id <id> --reason "..."
    python3 scripts/paper_experiment.py report --experiment-id <id>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.settings import Settings  # noqa: E402
from src.live_bridge import load_static_hood_client_from_dir  # noqa: E402
from src.market.hood_provider import HoodMarketDataProvider  # noqa: E402
from src.paper_trading.account import compute_account_snapshot  # noqa: E402
from src.paper_trading.clock import compute_clock_status  # noqa: E402
from src.paper_trading.engine import (  # noqa: E402
    CYCLE_OK,
    MARKET_CLOSED_RESULT,
    NO_QUALIFIED_OPPORTUNITY,
    experiment_paths,
    run_paper_experiment_cycle,
)
from src.paper_trading.equity_curve import EquitySnapshotStore  # noqa: E402
from src.paper_trading.experiment_config import (  # noqa: E402
    ExperimentConfigStore,
    MINIMUM_EXPERIMENT_DAYS,
    build_experiment_config,
)
from src.paper_trading.journal import PaperExperimentTradeStore  # noqa: E402
from src.paper_trading.report import build_final_report  # noqa: E402
from src.paper_trading.slippage import SlippageAssumptionTier  # noqa: E402
from src.paper_trading.state_machine import ExperimentStateStore, ExperimentStatus  # noqa: E402


def _stores(experiment_id: str):
    paths = experiment_paths(experiment_id)
    return paths, ExperimentConfigStore(paths.experiment_config_file), ExperimentStateStore(paths.experiment_state_file)


def cmd_start(args: argparse.Namespace) -> int:
    now = datetime.now(timezone.utc)
    config = build_experiment_config(
        now=now, starting_capital_usd=args.capital, minimum_days=args.days,
        universe=tuple(args.symbols.split(",")) if args.symbols else None,
    )
    paths, config_store, state_store = _stores(config.experiment_id)
    config_store.approve(config)
    state_store.transition(experiment_id=config.experiment_id, to_status=ExperimentStatus.CREATED, at=now, reason="python3 scripts/paper_experiment.py start")
    state_store.transition(experiment_id=config.experiment_id, to_status=ExperimentStatus.RUNNING, at=now, reason="Explicit start")

    print(f"experiment_id={config.experiment_id}")
    print(f"status=RUNNING")
    print(f"starting_capital_usd={config.starting_capital_usd}")
    print(f"minimum_days={args.days}")
    print(f"strategy_id={config.strategy_id} strategy_content_hash={config.strategy_content_hash[:16]}")
    print(f"universe={','.join(config.universe)}")
    print(f"planned_minimum_end_timestamp={config.planned_minimum_end_timestamp.isoformat()}")
    print(f"storage_dir={paths.base_dir}")
    print(f"Next: python3 scripts/paper_experiment.py run-cycle --experiment-id {config.experiment_id} --data-dir <real-data-dir>")
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    _, _, state_store = _stores(args.experiment_id)
    state_store.transition(experiment_id=args.experiment_id, to_status=ExperimentStatus.PAUSED, at=datetime.now(timezone.utc), reason=args.reason or "manual pause")
    print("status=PAUSED")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    _, _, state_store = _stores(args.experiment_id)
    state_store.transition(experiment_id=args.experiment_id, to_status=ExperimentStatus.RUNNING, at=datetime.now(timezone.utc), reason=args.reason or "manual resume")
    print("status=RUNNING")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    _, _, state_store = _stores(args.experiment_id)
    state_store.transition(experiment_id=args.experiment_id, to_status=ExperimentStatus.ABORTED, at=datetime.now(timezone.utc), reason=args.reason or "manual stop")
    print("status=ABORTED")
    return 0


def cmd_run_cycle(args: argparse.Namespace) -> int:
    paths, config_store, state_store = _stores(args.experiment_id)
    config = config_store.get()
    if config is None:
        print(f"No experiment config found for {args.experiment_id!r} — run 'start' first", file=sys.stderr)
        return 1
    status = state_store.current_status()
    if status != ExperimentStatus.RUNNING:
        print(f"Experiment status is {status.value if status else 'MISSING'}, not RUNNING — no cycle run", file=sys.stderr)
        return 1

    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    base_settings = Settings.from_env()
    client = load_static_hood_client_from_dir(args.data_dir, base_settings.account_number)
    market = HoodMarketDataProvider(client, base_settings)

    result = run_paper_experiment_cycle(
        config=config, client=client, market=market, base_settings=base_settings, now=now,
        slippage_tier=SlippageAssumptionTier(args.slippage_tier), paths=paths,
    )
    print(f"outcome={result.outcome}")
    print(f"observation_cycle_id={result.observation_cycle_id}")
    print(f"new_trades={len(result.new_trades)} closed_trades={len(result.closed_trades)}")
    if result.account_snapshot is not None:
        s = result.account_snapshot
        print(f"cash_usd={s.cash_usd} equity_usd={s.equity_usd} open_positions={s.open_position_count}")
    if result.errors:
        print(f"errors={result.errors}", file=sys.stderr)

    # Auto-complete on reaching the minimum duration -- the designed end
    # condition (Part 25: never auto-stop merely because of a loss).
    clock = compute_clock_status(
        experiment_start=config.start_timestamp, planned_minimum_end=config.planned_minimum_end_timestamp, now=now,
        cycle_dates=frozenset(e.timestamp.date() for e in EquitySnapshotStore(paths.equity_curve_file).load_all()),
    )
    if clock.minimum_duration_met:
        state_store.transition(experiment_id=args.experiment_id, to_status=ExperimentStatus.COMPLETED, at=now, reason=f"Reached the {MINIMUM_EXPERIMENT_DAYS}-calendar-day minimum duration")
        print("status=COMPLETED (minimum duration reached)")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    paths, config_store, state_store = _stores(args.experiment_id)
    config = config_store.get()
    if config is None:
        print(f"No experiment config found for {args.experiment_id!r}", file=sys.stderr)
        return 1
    status = state_store.current_status()
    now = datetime.now(timezone.utc)
    equity_store = EquitySnapshotStore(paths.equity_curve_file)
    clock = compute_clock_status(
        experiment_start=config.start_timestamp, planned_minimum_end=config.planned_minimum_end_timestamp, now=now,
        cycle_dates=frozenset(e.timestamp.date() for e in equity_store.load_all()),
    )
    print(f"experiment_id={config.experiment_id}")
    print(f"status={status.value if status else 'MISSING'}")
    print(f"calendar_days_elapsed={clock.calendar_days_elapsed} (minimum {MINIMUM_EXPERIMENT_DAYS})")
    print(f"minimum_duration_met={clock.minimum_duration_met}")
    print(f"market_days_observed={clock.market_days_observed}")
    latest = equity_store.latest()
    if latest is not None:
        print(f"cash_usd={latest.cash_usd} equity_usd={latest.equity_usd} open_positions={latest.open_positions}")
        print(f"cumulative_pnl_usd={latest.cumulative_pnl_usd} drawdown_pct={latest.drawdown_pct:.2%}")
    else:
        print("No cycles have run yet.")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    paths, config_store, state_store = _stores(args.experiment_id)
    config = config_store.get()
    if config is None:
        print(f"No experiment config found for {args.experiment_id!r}", file=sys.stderr)
        return 1
    trade_store = PaperExperimentTradeStore(paths.experiment_trades_file)
    equity_store = EquitySnapshotStore(paths.equity_curve_file)
    now = datetime.now(timezone.utc)
    clock = compute_clock_status(
        experiment_start=config.start_timestamp, planned_minimum_end=config.planned_minimum_end_timestamp, now=now,
        cycle_dates=frozenset(e.timestamp.date() for e in equity_store.load_all()),
    )

    from src.production.registry import build_default_registry

    registry_entry = build_default_registry().get(config.strategy_id, config.strategy_version)

    latest_equity = equity_store.latest()
    latest_snapshot = None
    if latest_equity is not None:
        latest_snapshot = compute_account_snapshot(
            as_of=latest_equity.timestamp, starting_cash_usd=config.starting_capital_usd,
            closed_trades=[t for t in trade_store.load_all() if t.exit_timestamp is not None],
            open_positions=[], current_bid_by_option_id={},
        )
        # The re-derived snapshot above only reflects CLOSED trades (open
        # positions aren't reloaded here) -- override with the equity
        # curve's own already-correct cash/equity for the report's
        # headline numbers, which DO include open-position market value.
        import dataclasses as _dc
        latest_snapshot = _dc.replace(
            latest_snapshot, cash_usd=latest_equity.cash_usd, equity_usd=latest_equity.equity_usd,
            open_position_market_value_usd=latest_equity.market_value_usd,
            total_return_pct=(latest_equity.equity_usd - config.starting_capital_usd) / config.starting_capital_usd,
        )

    report = build_final_report(
        config=config, experiment_status=(state_store.current_status() or ExperimentStatus.CREATED).value,
        calendar_days_elapsed=clock.calendar_days_elapsed, market_days_observed=clock.market_days_observed,
        trades=trade_store.load_all(), equity_curve=equity_store.load_all(),
        latest_snapshot=latest_snapshot,
        strategy_registry_status=(registry_entry.status.value if registry_entry else "UNREGISTERED"),
    )
    print(json.dumps({
        "experiment_id": report.config.experiment_id, "status": report.experiment_status,
        "calendar_days_elapsed": report.calendar_days_elapsed, "starting_capital_usd": report.starting_capital_usd,
        "ending_equity_usd": report.ending_equity_usd, "net_pnl_usd": report.net_pnl_usd,
        "total_return_pct": report.total_return_pct, "max_drawdown_pct": report.max_drawdown_pct,
        "total_trades": report.trading.total_trades, "win_rate": report.trading.win_rate,
        "strategy_registry_status": report.strategy_registry_status, "small_sample_warning": report.small_sample_warning,
    }, indent=2, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start")
    p_start.add_argument("--capital", type=float, default=1000.0)
    p_start.add_argument("--days", type=int, default=MINIMUM_EXPERIMENT_DAYS)
    p_start.add_argument("--symbols", default=None, help="Comma-separated universe override")
    p_start.set_defaults(func=cmd_start)

    for name, fn in (("pause", cmd_pause), ("resume", cmd_resume), ("stop", cmd_stop), ("status", cmd_status), ("report", cmd_report)):
        p = sub.add_parser(name)
        p.add_argument("--experiment-id", required=True)
        if name in ("pause", "resume", "stop"):
            p.add_argument("--reason", default=None)
        p.set_defaults(func=fn)

    p_cycle = sub.add_parser("run-cycle")
    p_cycle.add_argument("--experiment-id", required=True)
    p_cycle.add_argument("--data-dir", required=True, type=Path)
    p_cycle.add_argument("--now", default=None)
    p_cycle.add_argument("--slippage-tier", default="BASELINE", choices=["BASELINE", "STRESSED"])
    p_cycle.set_defaults(func=cmd_run_cycle)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
