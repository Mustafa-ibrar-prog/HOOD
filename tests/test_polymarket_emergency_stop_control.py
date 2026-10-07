"""Tests for scripts/emergency_stop_control.py -- the ONLY script that
clears the Polymarket emergency stop, and only when a human runs it
directly with a real identity. Exercises main() directly (argparse +
real EmergencyStopStore against tmp_path), never the real file system
default location.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from scripts.emergency_stop_control import main  # noqa: E402
from src.execution.emergency_stop import EmergencyStopStore  # noqa: E402


def _run(monkeypatch, tmp_path, *args) -> int:
    monkeypatch.setattr(sys, "argv", ["emergency_stop_control.py", *args])
    monkeypatch.setenv("POLYMARKET_EMERGENCY_STOP_FILE", str(tmp_path / "estop.json"))
    monkeypatch.chdir(tmp_path)  # no .env file here to interfere
    return main()


def test_status_on_a_fresh_store_defaults_to_active(monkeypatch, tmp_path, capsys):
    rc = _run(monkeypatch, tmp_path, "status")
    assert rc == 0
    assert "EMERGENCY STOP: ACTIVE" in capsys.readouterr().out


def test_activate_requires_no_authorization(monkeypatch, tmp_path, capsys):
    rc = _run(monkeypatch, tmp_path, "activate", "--reason", "pausing for the night")
    assert rc == 0
    assert "EMERGENCY STOP ACTIVATED" in capsys.readouterr().out
    store = EmergencyStopStore(tmp_path / "estop.json")
    assert store.is_stopped()


def test_clear_rejects_a_system_identity(monkeypatch, tmp_path, capsys):
    rc = _run(monkeypatch, tmp_path, "clear", "--authorized-by", "system:auto", "--reason", "test")
    assert rc == 1
    assert "REFUSING" in capsys.readouterr().out
    store = EmergencyStopStore(tmp_path / "estop.json")
    assert store.is_stopped()  # still active -- the refused clear must not have taken effect


def test_clear_with_a_real_identity_succeeds(monkeypatch, tmp_path, capsys):
    rc = _run(monkeypatch, tmp_path, "clear", "--authorized-by", "Mustafa", "--reason", "cleared for the first $5 live test")
    assert rc == 0
    out = capsys.readouterr().out
    assert "EMERGENCY STOP CLEARED" in out
    store = EmergencyStopStore(tmp_path / "estop.json")
    assert not store.is_stopped()
    state = store.current()
    assert state.set_by == "Mustafa"
    assert state.reason == "cleared for the first $5 live test"


def test_status_after_clear_reflects_the_cleared_state(monkeypatch, tmp_path, capsys):
    _run(monkeypatch, tmp_path, "clear", "--authorized-by", "Mustafa", "--reason", "test")
    capsys.readouterr()
    rc = _run(monkeypatch, tmp_path, "status")
    assert rc == 0
    assert "EMERGENCY STOP: CLEARED" in capsys.readouterr().out


def test_no_action_is_rejected_by_argparse(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["emergency_stop_control.py"])
    with pytest.raises(SystemExit):
        main()


def test_clear_without_authorized_by_is_rejected_by_argparse(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["emergency_stop_control.py", "clear", "--reason", "test"])
    with pytest.raises(SystemExit):
        main()
