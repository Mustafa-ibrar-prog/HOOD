"""Phase 41, scheduling component B — Robinhood data acquisition for the
automatic scheduler.

Nothing in this codebase can call a HOOD MCP tool from Python — this is
still the same honest architectural fact `src/live_bridge.py`'s module
docstring documents, and this module does not pretend otherwise. It does
NOT invent a fake MCP client. Instead it defines the seam
(`DataAcquisitionProvider`) the scheduler acquires real per-cycle data
through, and ONE concrete implementation that matches the ALREADY
ESTABLISHED manual-runbook convention:

`InboxDataAcquisitionProvider` polls a per-slot "inbox" directory
(`<inbox_root>/<slot_id>/`) for real, agent-fetched HOOD tool responses
saved with `src.live_bridge.save_hood_response_to_data_dir`'s exact
existing file-naming convention, plus a `READY` sentinel file the agent
writes (via `mark_inbox_slot_ready` below) only once every response it
intends to supply for that slot has actually been written. The scheduler
never reads a directory as "the data for this slot" until that sentinel
exists — it never treats a partially-written directory as complete, and
it never fabricates a quote, interpolates a missing one, or substitutes
historical data for live data when a symbol's files never arrive.

If nothing appears within `timeout_seconds`, `acquire()` reports the slot
as failed (ready=False) and the scheduler runs no cycle for it at all —
fail closed, exactly as instructed.

This IS the entire "automatic" story for data acquisition that is
honestly possible in this codebase today: the orchestrating agent still
fetches the real tool responses (as it always has, per the manual
runbook), but now drops them into a scheduler-known location instead of
being separately told to "RUN" a specific cycle command — the scheduler
takes over deciding WHEN a cycle is due, waiting for that data to show
up, and executing the cycle without a human re-issuing each command.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, Sequence

READY_SENTINEL = "READY"


@dataclass(frozen=True)
class AcquisitionResult:
    ready: bool  # False => timed out waiting for the READY sentinel; no data may be used
    data_dir: Path
    collected_symbols: tuple[str, ...]  # symbols with a real equity_quotes_<SYMBOL>.json present
    failed_symbols: tuple[str, ...]  # requested symbols with no equity_quotes_<SYMBOL>.json present
    reason: str | None = None


class DataAcquisitionProvider(Protocol):
    def acquire(self, symbols: Sequence[str], slot_id: str) -> AcquisitionResult: ...


@dataclass(frozen=True)
class InboxDataAcquisitionProvider:
    """See module docstring. `sleep_fn`/`monotonic_fn` are injectable so
    tests never depend on real wall-clock waiting."""

    inbox_root: Path
    timeout_seconds: float = 600.0
    poll_interval_seconds: float = 15.0
    sleep_fn: Callable[[float], None] = field(default=time.sleep)
    monotonic_fn: Callable[[], float] = field(default=time.monotonic)

    def slot_dir(self, slot_id: str) -> Path:
        return Path(self.inbox_root) / slot_id

    def acquire(self, symbols: Sequence[str], slot_id: str) -> AcquisitionResult:
        directory = self.slot_dir(slot_id)
        deadline = self.monotonic_fn() + self.timeout_seconds
        while not (directory / READY_SENTINEL).is_file():
            if self.monotonic_fn() >= deadline:
                return AcquisitionResult(
                    ready=False, data_dir=directory, collected_symbols=(), failed_symbols=tuple(symbols),
                    reason=f"No {READY_SENTINEL!r} sentinel found in {directory} within {self.timeout_seconds}s",
                )
            self.sleep_fn(self.poll_interval_seconds)

        collected: list[str] = []
        failed: list[str] = []
        for symbol in symbols:
            if (directory / f"equity_quotes_{symbol}.json").is_file():
                collected.append(symbol)
            else:
                failed.append(symbol)
        return AcquisitionResult(
            ready=True, data_dir=directory, collected_symbols=tuple(collected), failed_symbols=tuple(failed),
        )


def mark_inbox_slot_ready(inbox_root: Path, slot_id: str) -> Path:
    """The last step of populating one slot's real data for
    `InboxDataAcquisitionProvider` — call this AFTER every real HOOD
    response intended for this slot has already been written via
    `src.live_bridge.save_hood_response_to_data_dir(inbox_root/slot_id,
    ...)`. Writing this sentinel is the ONLY signal the provider accepts
    that a slot's directory is complete rather than still being written.

    Phase 42: writes atomically (temp file + `os.replace`, same
    directory/filesystem) rather than a direct `write_text` — a reader
    polling concurrently (`InboxDataAcquisitionProvider.acquire`) can
    never observe a partially-written sentinel; it either doesn't exist
    yet or exists complete. `os.replace` is POSIX-atomic within one
    filesystem, which every path this function is called with is (the
    experiment's own `logs/paper_experiments/...` tree)."""
    directory = Path(inbox_root) / slot_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / READY_SENTINEL
    tmp_path = directory / f".{READY_SENTINEL}.tmp-{os.getpid()}"
    tmp_path.write_text("")
    os.replace(tmp_path, path)
    return path
