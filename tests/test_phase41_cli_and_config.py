"""Phase 41 -- scripts/run_paper_scheduler.py argument parsing +
SchedulerConfig environment wiring (cadence configurable via env/CLI, not
hard-coded -- the CADENCE requirement)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from src.paper_trading.scheduler import DEFAULT_CADENCE_MINUTES, SchedulerConfig
from src.paper_trading.slippage import SlippageAssumptionTier

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_paper_scheduler.py"


def test_scheduler_script_exists_and_is_valid_python():
    assert SCRIPT_PATH.is_file()
    import ast

    ast.parse(SCRIPT_PATH.read_text())


def test_scheduler_script_loads_without_running_the_forever_loop(monkeypatch):
    """Loading the module must not block -- `run_scheduler_forever` is
    only called inside `main()`, never at import time."""
    spec = importlib.util.spec_from_file_location("phase41_run_paper_scheduler", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "main")


def test_default_cadence_is_15_minutes():
    assert DEFAULT_CADENCE_MINUTES == 15


def test_scheduler_config_from_env_uses_the_environment_cadence():
    config = SchedulerConfig.from_env("exp-test", env={"PAPER_SCHEDULER_CADENCE_MINUTES": "5"})
    assert config.cadence_minutes == 5


def test_scheduler_config_from_env_falls_back_to_default_when_unset():
    config = SchedulerConfig.from_env("exp-test", env={})
    assert config.cadence_minutes == DEFAULT_CADENCE_MINUTES


def test_scheduler_config_explicit_override_wins_over_environment():
    config = SchedulerConfig.from_env("exp-test", env={"PAPER_SCHEDULER_CADENCE_MINUTES": "5"}, cadence_minutes=30)
    assert config.cadence_minutes == 30


def test_scheduler_config_data_timeout_and_poll_interval_from_env():
    config = SchedulerConfig.from_env("exp-test", env={
        "PAPER_SCHEDULER_DATA_TIMEOUT_SECONDS": "120",
        "PAPER_SCHEDULER_POLL_INTERVAL_SECONDS": "10",
    })
    assert config.data_acquisition_timeout_seconds == 120.0
    assert config.poll_interval_seconds == 10.0


def test_scheduler_config_default_inbox_root_is_under_the_experiment_dir():
    config = SchedulerConfig(experiment_id="exp-abc")
    resolved = config.resolved_inbox_root()
    assert "exp-abc" in str(resolved)
    assert "inbox" in str(resolved)


def test_scheduler_config_explicit_inbox_root_is_respected(tmp_path):
    config = SchedulerConfig(experiment_id="exp-abc", inbox_root=tmp_path / "custom")
    assert config.resolved_inbox_root() == tmp_path / "custom"


def test_scheduler_config_slippage_tier_defaults_to_baseline():
    config = SchedulerConfig(experiment_id="exp-abc")
    assert config.slippage_tier == SlippageAssumptionTier.BASELINE


def test_scheduler_config_holidays_default_to_empty_frozenset():
    """Per the Phase 41 requirement not to hard-code a holiday list."""
    config = SchedulerConfig(experiment_id="exp-abc")
    assert config.holidays == frozenset()
