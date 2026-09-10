"""Phase 41 -- src.paper_trading.cycle_runner.execute_paper_cycle: the
shared single-cycle execution path used by both the CLI and the
scheduler. Behavior must be byte-for-byte identical to what
scripts/paper_experiment.py::cmd_run_cycle did before the Phase 41
refactor (verified independently by tests/test_phase40_cli.py, which
still passes unmodified against the refactored CLI)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.paper_trading.cycle_runner import execute_paper_cycle
from src.paper_trading.engine import CYCLE_OK, MARKET_CLOSED_RESULT, experiment_paths
from src.paper_trading.experiment_config import ExperimentConfigStore, build_experiment_config
from src.paper_trading.state_machine import ExperimentStateStore, ExperimentStatus

NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)


def _paths(tmp_path, experiment_id):
    return experiment_paths(experiment_id, base_dir=tmp_path / "paper_experiments")


def test_refuses_when_no_experiment_config_exists(tmp_path):
    outcome = execute_paper_cycle(experiment_id="exp-does-not-exist", data_dir=tmp_path, now=NOW, base_settings=_settings())
    assert outcome.ok is False
    assert "run 'start' first" in outcome.error
    assert outcome.result is None


def test_refuses_when_experiment_is_paused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = build_experiment_config(now=NOW, universe=("AAPL",))
    paths = experiment_paths(config.experiment_id)
    ExperimentConfigStore(paths.experiment_config_file).approve(config)
    state_store = ExperimentStateStore(paths.experiment_state_file)
    state_store.transition(experiment_id=config.experiment_id, to_status=ExperimentStatus.CREATED, at=NOW, reason="x")
    state_store.transition(experiment_id=config.experiment_id, to_status=ExperimentStatus.RUNNING, at=NOW, reason="x")
    state_store.transition(experiment_id=config.experiment_id, to_status=ExperimentStatus.PAUSED, at=NOW, reason="x")

    outcome = execute_paper_cycle(experiment_id=config.experiment_id, data_dir=tmp_path, now=NOW, base_settings=_settings())
    assert outcome.ok is False
    assert "not RUNNING" in outcome.error


def test_market_closed_data_dir_produces_market_closed_outcome(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = build_experiment_config(now=NOW, universe=("AAPL",))
    paths = experiment_paths(config.experiment_id)
    ExperimentConfigStore(paths.experiment_config_file).approve(config)
    state_store = ExperimentStateStore(paths.experiment_state_file)
    state_store.transition(experiment_id=config.experiment_id, to_status=ExperimentStatus.CREATED, at=NOW, reason="x")
    state_store.transition(experiment_id=config.experiment_id, to_status=ExperimentStatus.RUNNING, at=NOW, reason="x")

    saturday = datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc)
    outcome = execute_paper_cycle(experiment_id=config.experiment_id, data_dir=tmp_path, now=saturday, base_settings=_settings())
    assert outcome.ok is True
    assert outcome.result.outcome == MARKET_CLOSED_RESULT
    assert outcome.auto_completed is False


def test_auto_completes_when_minimum_duration_is_reached(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = build_experiment_config(now=NOW, universe=("AAPL",), minimum_days=14)
    paths = experiment_paths(config.experiment_id)
    ExperimentConfigStore(paths.experiment_config_file).approve(config)
    state_store = ExperimentStateStore(paths.experiment_state_file)
    state_store.transition(experiment_id=config.experiment_id, to_status=ExperimentStatus.CREATED, at=NOW, reason="x")
    state_store.transition(experiment_id=config.experiment_id, to_status=ExperimentStatus.RUNNING, at=NOW, reason="x")

    far_future_saturday = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)  # 18 days later, a Saturday -> MARKET_CLOSED but still checks duration
    outcome = execute_paper_cycle(experiment_id=config.experiment_id, data_dir=tmp_path, now=far_future_saturday, base_settings=_settings())
    assert outcome.ok is True
    assert outcome.auto_completed is True
    assert state_store.current_status() == ExperimentStatus.COMPLETED


def _settings():
    from src.config.settings import Settings

    return Settings.from_env(env={"ROBINHOOD_ACCOUNT_NUMBER": "TEST123"})
