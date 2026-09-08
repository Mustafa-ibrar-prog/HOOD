"""Phase 40, Part 5/24/25/26 -- scripts/paper_experiment.py CLI wiring:
start/pause/resume/stop/status/report, and run-cycle's own guard rails
(refuses when the experiment isn't RUNNING, refuses when it doesn't
exist). The underlying decision/execution logic (`run_paper_experiment_
cycle`) is exercised directly and thoroughly in test_phase40_engine.py;
this file tests the CLI's own state-machine wiring and report
aggregation, not a second copy of the engine's own logic."""

from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "paper_experiment.py"


def _load_cli_module():
    spec = importlib.util.spec_from_file_location("phase40_paper_experiment_cli", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = _load_cli_module()

NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _in_tmp_cwd(tmp_path, monkeypatch):
    """`experiment_paths()`'s default base_dir is the RELATIVE path
    logs/paper_experiments -- chdir into a tmp dir per test so nothing
    this file does ever touches the real repo's logs/ directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _ns(**kwargs):
    return argparse.Namespace(**kwargs)


def test_start_creates_created_then_running_and_prints_the_experiment_id(capsys):
    rc = cli.cmd_start(_ns(capital=1000.0, days=14, symbols="AAPL,MSFT"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "experiment_id=exp-" in out
    assert "status=RUNNING" in out
    assert "starting_capital_usd=1000.0" in out


def test_start_persists_a_running_state_readable_by_a_fresh_store():
    cli.cmd_start(_ns(capital=1000.0, days=14, symbols="AAPL"))
    from src.paper_trading.experiment_config import ExperimentConfigStore
    from src.paper_trading.state_machine import ExperimentStateStore, ExperimentStatus

    # Find the experiment via the CLI's own default paths root.
    root = Path("logs/paper_experiments")
    experiment_id = next(p.name for p in root.iterdir() if p.is_dir())
    paths, config_store, state_store = cli._stores(experiment_id)
    assert config_store.get() is not None
    assert state_store.current_status() == ExperimentStatus.RUNNING


def _start_one(capsys, *, capital=1000.0, days=14, symbols="AAPL"):
    cli.cmd_start(_ns(capital=capital, days=days, symbols=symbols))
    out = capsys.readouterr().out
    return next(line.split("=", 1)[1] for line in out.splitlines() if line.startswith("experiment_id="))


def test_pause_then_resume_round_trip(capsys):
    experiment_id = _start_one(capsys)
    assert cli.cmd_pause(_ns(experiment_id=experiment_id, reason="test pause")) == 0
    assert "PAUSED" in capsys.readouterr().out
    assert cli.cmd_resume(_ns(experiment_id=experiment_id, reason="test resume")) == 0
    assert "RUNNING" in capsys.readouterr().out

    from src.paper_trading.state_machine import ExperimentStatus

    _, _, state_store = cli._stores(experiment_id)
    assert state_store.current_status() == ExperimentStatus.RUNNING


def test_stop_transitions_to_aborted_and_is_terminal(capsys):
    experiment_id = _start_one(capsys)
    assert cli.cmd_stop(_ns(experiment_id=experiment_id, reason="explicit stop")) == 0
    assert "ABORTED" in capsys.readouterr().out

    from src.paper_trading.state_machine import ExperimentStatus, InvalidExperimentTransitionError

    _, _, state_store = cli._stores(experiment_id)
    assert state_store.current_status() == ExperimentStatus.ABORTED
    with pytest.raises(InvalidExperimentTransitionError):
        state_store.transition(experiment_id=experiment_id, to_status=ExperimentStatus.RUNNING, at=NOW, reason="x")


def test_status_before_any_cycle_reports_no_cycles_yet(capsys):
    experiment_id = _start_one(capsys)
    capsys.readouterr()
    rc = cli.cmd_status(_ns(experiment_id=experiment_id))
    assert rc == 0
    out = capsys.readouterr().out
    assert "No cycles have run yet." in out
    assert f"experiment_id={experiment_id}" in out
    assert "status=RUNNING" in out


def test_status_for_an_unknown_experiment_id_fails_cleanly():
    rc = cli.cmd_status(_ns(experiment_id="exp-does-not-exist"))
    assert rc == 1


def test_run_cycle_refuses_when_experiment_does_not_exist(tmp_path):
    rc = cli.cmd_run_cycle(_ns(experiment_id="exp-nope", data_dir=tmp_path, now=None, slippage_tier="BASELINE"))
    assert rc == 1


def test_run_cycle_refuses_when_experiment_is_paused(capsys, tmp_path):
    experiment_id = _start_one(capsys)
    cli.cmd_pause(_ns(experiment_id=experiment_id, reason="pause before cycle"))
    capsys.readouterr()
    rc = cli.cmd_run_cycle(_ns(experiment_id=experiment_id, data_dir=tmp_path, now=None, slippage_tier="BASELINE"))
    assert rc == 1


def test_report_reflects_manually_recorded_equity_and_trades(capsys):
    """Exercises cmd_report's own aggregation/override logic (Part 26-27)
    against directly-written stores, without requiring a full real
    StaticHoodClient data-dir fixture (that end-to-end wiring is a thin,
    already-tested pass-through to run_paper_experiment_cycle -- see
    test_phase40_engine.py)."""
    experiment_id = _start_one(capsys)
    capsys.readouterr()
    paths, config_store, state_store = cli._stores(experiment_id)
    config = config_store.get()

    from src.paper_trading.account import compute_account_snapshot
    from src.paper_trading.equity_curve import EquitySnapshotStore, build_equity_snapshot
    from src.paper_trading.journal import PAPER_EXPERIMENT_LABEL, PaperExperimentTradeRecord, PaperExperimentTradeStore
    from src.paper_trading.slippage import SlippageAssumptionTier

    trade = PaperExperimentTradeRecord(
        label=PAPER_EXPERIMENT_LABEL, experiment_id=experiment_id, trade_id="t1", strategy_id=config.strategy_id,
        strategy_content_hash=config.strategy_content_hash, entry_observation_cycle_id="cyc-1",
        exit_observation_cycle_id="cyc-2", entry_timestamp=NOW, exit_timestamp=NOW + timedelta(hours=1),
        symbol="AAPL", option_id="opt-1", strike=230.0, expiration=date(2026, 9, 18), option_type="call",
        dte_at_entry=10, moneyness_at_entry=0.01, entry_bid=1.9, entry_ask=2.0, entry_fill=2.0, exit_bid=2.4,
        exit_ask=2.5, exit_fill=2.4, quantity=1, gross_pnl_usd=40.0, spread_cost_usd=1.0, slippage_usd=0.5,
        fees_usd=1.3, net_pnl_usd=37.2, return_pct=0.186, mfe_pct=0.05, mae_pct=-0.01, exit_reason="PROFIT_TARGET",
        slippage_tier=SlippageAssumptionTier.BASELINE.value,
    )
    PaperExperimentTradeStore(paths.experiment_trades_file).append(trade)

    snapshot = compute_account_snapshot(
        as_of=NOW + timedelta(hours=1), starting_cash_usd=config.starting_capital_usd, closed_trades=[trade],
        open_positions=[], current_bid_by_option_id={},
    )
    equity_record = build_equity_snapshot(
        experiment_id=experiment_id, observation_cycle_id="cyc-2", snapshot=snapshot, first_snapshot_equity_today=1000.0,
    )
    EquitySnapshotStore(paths.equity_curve_file).append(equity_record)

    rc = cli.cmd_report(_ns(experiment_id=experiment_id))
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["starting_capital_usd"] == 1000.0
    assert payload["ending_equity_usd"] == pytest.approx(1037.2, abs=0.01)
    assert payload["net_pnl_usd"] == pytest.approx(37.2, abs=0.01)
    assert payload["total_trades"] == 1
    assert payload["win_rate"] == 1.0
    # Part 27: never annualize a two-week result -- no annualized_return key,
    # and the small-sample warning explicitly disclaims one exists.
    assert "annualized_return" not in payload
    assert "no annualized return is reported" in payload["small_sample_warning"].lower()
    assert payload["strategy_registry_status"] == "NOT_READY"


def test_default_symbols_use_the_established_twelve_symbol_universe(capsys):
    experiment_id = _start_one(capsys, symbols=None)
    _, config_store, _ = cli._stores(experiment_id)
    assert len(config_store.get().universe) == 12
