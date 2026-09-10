"""Phase 41 -- InboxDataAcquisitionProvider: never fabricates, never
reads a partially-written directory as complete, always fails closed on
timeout."""

from __future__ import annotations

from pathlib import Path

from src.live_bridge import save_hood_response_to_data_dir
from src.paper_trading.data_acquisition import InboxDataAcquisitionProvider, mark_inbox_slot_ready


def _fake_clock():
    """A deterministic monotonic clock that advances only when read, and
    a matching no-op sleep -- so a 'timeout' test runs instantly."""
    state = {"t": 0.0}

    def monotonic_fn() -> float:
        return state["t"]

    def sleep_fn(seconds: float) -> None:
        state["t"] += seconds

    return monotonic_fn, sleep_fn


def test_times_out_and_reports_every_symbol_failed_when_nothing_ever_arrives(tmp_path):
    monotonic_fn, sleep_fn = _fake_clock()
    provider = InboxDataAcquisitionProvider(
        inbox_root=tmp_path / "inbox", timeout_seconds=30, poll_interval_seconds=5,
        sleep_fn=sleep_fn, monotonic_fn=monotonic_fn,
    )
    result = provider.acquire(["AAPL", "MSFT"], "2026-09-08-slot0000")
    assert result.ready is False
    assert result.collected_symbols == ()
    assert result.failed_symbols == ("AAPL", "MSFT")
    assert result.reason is not None


def test_a_directory_without_the_ready_sentinel_is_never_treated_as_complete(tmp_path):
    """Files present but READY never written -- must still time out, never
    be read as 'the data for this slot.'"""
    monotonic_fn, sleep_fn = _fake_clock()
    inbox_root = tmp_path / "inbox"
    slot_dir = inbox_root / "2026-09-08-slot0000"
    save_hood_response_to_data_dir(slot_dir, "equity_quotes_AAPL", {"data": {"results": []}})

    provider = InboxDataAcquisitionProvider(
        inbox_root=inbox_root, timeout_seconds=10, poll_interval_seconds=5, sleep_fn=sleep_fn, monotonic_fn=monotonic_fn,
    )
    result = provider.acquire(["AAPL"], "2026-09-08-slot0000")
    assert result.ready is False


def test_ready_sentinel_with_all_symbols_present_reports_full_success(tmp_path):
    inbox_root = tmp_path / "inbox"
    slot_id = "2026-09-08-slot0000"
    slot_dir = inbox_root / slot_id
    save_hood_response_to_data_dir(slot_dir, "equity_quotes_AAPL", {"data": {"results": []}})
    save_hood_response_to_data_dir(slot_dir, "equity_quotes_MSFT", {"data": {"results": []}})
    mark_inbox_slot_ready(inbox_root, slot_id)

    provider = InboxDataAcquisitionProvider(inbox_root=inbox_root, timeout_seconds=1, poll_interval_seconds=0.01)
    result = provider.acquire(["AAPL", "MSFT"], slot_id)
    assert result.ready is True
    assert set(result.collected_symbols) == {"AAPL", "MSFT"}
    assert result.failed_symbols == ()


def test_ready_with_only_some_symbols_present_reports_partial_coverage_honestly(tmp_path):
    """Part 9/10 of the comprehensive test list -- partial symbol failure
    must be reported, never silently ignored or fabricated."""
    inbox_root = tmp_path / "inbox"
    slot_id = "2026-09-08-slot0000"
    slot_dir = inbox_root / slot_id
    save_hood_response_to_data_dir(slot_dir, "equity_quotes_AAPL", {"data": {"results": []}})
    mark_inbox_slot_ready(inbox_root, slot_id)

    provider = InboxDataAcquisitionProvider(inbox_root=inbox_root, timeout_seconds=1, poll_interval_seconds=0.01)
    result = provider.acquire(["AAPL", "MSFT", "NVDA"], slot_id)
    assert result.ready is True
    assert result.collected_symbols == ("AAPL",)
    assert set(result.failed_symbols) == {"MSFT", "NVDA"}


def test_ready_with_no_symbols_present_at_all_reports_zero_collected(tmp_path):
    """All-symbol failure (item 10): the sentinel exists (the agent
    finished its attempt) but nothing usable was actually written."""
    inbox_root = tmp_path / "inbox"
    slot_id = "2026-09-08-slot0000"
    mark_inbox_slot_ready(inbox_root, slot_id)

    provider = InboxDataAcquisitionProvider(inbox_root=inbox_root, timeout_seconds=1, poll_interval_seconds=0.01)
    result = provider.acquire(["AAPL", "MSFT"], slot_id)
    assert result.ready is True
    assert result.collected_symbols == ()
    assert set(result.failed_symbols) == {"AAPL", "MSFT"}


def test_slot_dir_isolates_different_slots(tmp_path):
    provider = InboxDataAcquisitionProvider(inbox_root=tmp_path / "inbox", timeout_seconds=1, poll_interval_seconds=0.01)
    assert provider.slot_dir("slotA") != provider.slot_dir("slotB")


def test_mark_inbox_slot_ready_creates_the_slot_directory_if_missing(tmp_path):
    inbox_root = tmp_path / "inbox"
    path = mark_inbox_slot_ready(inbox_root, "2026-09-08-slot0000")
    assert path.is_file()
    assert path.parent == inbox_root / "2026-09-08-slot0000"
