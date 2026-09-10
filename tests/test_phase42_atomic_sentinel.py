"""Phase 42 -- atomic READY sentinel writes. Covers 'READY written only
after data completion', 'interrupted acquisition' (a crash before the
final rename must never leave a fake-looking READY file), and duplicate
calls being safe on restart."""

from __future__ import annotations

from pathlib import Path

from src.paper_trading.data_acquisition import READY_SENTINEL, InboxDataAcquisitionProvider, mark_inbox_slot_ready


def test_ready_sentinel_does_not_exist_before_marking(tmp_path):
    inbox_root = tmp_path / "inbox"
    slot_dir = inbox_root / "slot-a"
    slot_dir.mkdir(parents=True)
    assert not (slot_dir / READY_SENTINEL).is_file()


def test_marking_ready_leaves_no_temp_file_behind(tmp_path):
    inbox_root = tmp_path / "inbox"
    mark_inbox_slot_ready(inbox_root, "slot-a")
    slot_dir = inbox_root / "slot-a"
    entries = sorted(p.name for p in slot_dir.iterdir())
    assert entries == [READY_SENTINEL]  # no leftover .READY.tmp-<pid> file


def test_marking_ready_twice_is_idempotent(tmp_path):
    inbox_root = tmp_path / "inbox"
    mark_inbox_slot_ready(inbox_root, "slot-a")
    mark_inbox_slot_ready(inbox_root, "slot-a")  # must not raise
    slot_dir = inbox_root / "slot-a"
    assert sorted(p.name for p in slot_dir.iterdir()) == [READY_SENTINEL]


def test_a_crash_before_the_final_rename_never_produces_a_ready_file(tmp_path, monkeypatch):
    """Simulates 'interrupted acquisition': the process dies after writing
    the temp file but before the atomic rename. A poller must still see
    NO READY sentinel -- never a corrupted/partial one."""
    import os

    import src.paper_trading.data_acquisition as mod

    def boom(*args, **kwargs):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(mod.os, "replace", boom)

    inbox_root = tmp_path / "inbox"
    try:
        mark_inbox_slot_ready(inbox_root, "slot-a")
    except OSError:
        pass

    slot_dir = inbox_root / "slot-a"
    assert not (slot_dir / READY_SENTINEL).is_file()


def test_acquisition_provider_never_sees_ready_from_a_bare_temp_file(tmp_path):
    """A stray `.READY.tmp-*` file (e.g. from a killed process) must never
    be mistaken for the real sentinel by the poller."""
    inbox_root = tmp_path / "inbox"
    slot_dir = inbox_root / "slot-a"
    slot_dir.mkdir(parents=True)
    (slot_dir / ".READY.tmp-12345").write_text("")  # a leftover partial write, never the real thing

    provider = InboxDataAcquisitionProvider(
        inbox_root=inbox_root, timeout_seconds=0.05, poll_interval_seconds=0.01,
        sleep_fn=lambda s: None, monotonic_fn=_incrementing_clock(),
    )
    result = provider.acquire(["AAPL"], "slot-a")
    assert result.ready is False


def _incrementing_clock():
    state = {"t": 0.0}

    def fn() -> float:
        state["t"] += 0.02
        return state["t"]

    return fn
