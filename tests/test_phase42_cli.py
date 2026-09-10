"""Phase 42 -- scripts/prepare_acquisition_plan.py CLI sanity."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "prepare_acquisition_plan.py"


def _load_cli_module():
    spec = importlib.util.spec_from_file_location("phase42_prepare_acquisition_plan", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = _load_cli_module()


def test_script_exists_and_loads():
    assert SCRIPT_PATH.is_file()
    assert hasattr(cli, "main")


def test_identity_command_prints_valid_json(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    import argparse

    rc = cli.cmd_identity(argparse.Namespace(experiment_id="exp-test", cadence_minutes=15, now="2026-09-08T13:30:00Z"))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["n_symbols"] == 12
    assert payload["market_open"] is True
    assert payload["slot_id"] == "2026-09-08-slot0000"


def test_strikes_command_prints_valid_json(capsys):
    import argparse

    rc = cli.cmd_strikes(argparse.Namespace(symbol="GOOGL", price=332.95, strike_increment=None, moneyness_band=0.20, max_strikes=6))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["symbol"] == "GOOGL"
    assert 330.0 in payload["strikes"] or 335.0 in payload["strikes"]
