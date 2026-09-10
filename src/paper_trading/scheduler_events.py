"""Phase 41 — the automatic scheduler's own operational event log.

Append-only JSONL, replayed to derive current state — the SAME
restart-safe convention `src.research_recorder.storage.CycleLogStore` and
`src.paper_trading.state_machine.ExperimentStateStore` already use,
reused here rather than reinvented (never trusted only in memory across a
process restart).

This is ADDITIVE. It never replaces Phase 40's own account/position/
trade/equity persistence (`paper_positions.json`, `trade_journal.jsonl`,
`experiment_trades.jsonl`, `equity_curve.jsonl`) — those remain the
durable account-state truth, reused completely unchanged. This file only
tracks the SCHEDULER's own operational history: which intraday slot ran,
when, with what data-acquisition/cycle outcome — the "last successful
cycle" / "last attempted cycle" / "data acquisition failures" / "scheduler
status" persistence the automatic runner needs, plus the exact
operational log lines requested (PAPER_SCHEDULER_STARTED, MARKET_CLOSED,
WAITING_FOR_MARKET_OPEN, MARKET_OPEN, DATA_COLLECTION_STARTED,
DATA_COLLECTION_PARTIAL, DATA_COLLECTION_FAILED, PAPER_CYCLE_STARTED,
PAPER_CYCLE_COMPLETED, NO_QUALIFIED_OPPORTUNITY, PAPER_ENTRY, PAPER_EXIT,
PAPER_CYCLE_FAILED, EXPERIMENT_COMPLETED).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

PAPER_SCHEDULER_STARTED = "PAPER_SCHEDULER_STARTED"
PAPER_SCHEDULER_STOPPED = "PAPER_SCHEDULER_STOPPED"
MARKET_CLOSED = "MARKET_CLOSED"
WAITING_FOR_MARKET_OPEN = "WAITING_FOR_MARKET_OPEN"
MARKET_OPEN = "MARKET_OPEN"
DATA_COLLECTION_STARTED = "DATA_COLLECTION_STARTED"
DATA_COLLECTION_PARTIAL = "DATA_COLLECTION_PARTIAL"
DATA_COLLECTION_FAILED = "DATA_COLLECTION_FAILED"
PAPER_CYCLE_STARTED = "PAPER_CYCLE_STARTED"
PAPER_CYCLE_COMPLETED = "PAPER_CYCLE_COMPLETED"
NO_QUALIFIED_OPPORTUNITY = "NO_QUALIFIED_OPPORTUNITY"
PAPER_ENTRY = "PAPER_ENTRY"
PAPER_EXIT = "PAPER_EXIT"
PAPER_CYCLE_FAILED = "PAPER_CYCLE_FAILED"
EXPERIMENT_COMPLETED = "EXPERIMENT_COMPLETED"
SLOT_ALREADY_COMPLETED = "SLOT_ALREADY_COMPLETED"  # dedup: logged instead of re-running a completed slot

# A slot is "done" (dedup key, and reportable as the last successful cycle)
# once it produced one of these terminal, non-failing outcomes.
_CYCLE_TERMINAL_EVENTS = frozenset({PAPER_CYCLE_COMPLETED, NO_QUALIFIED_OPPORTUNITY})
_CYCLE_ATTEMPT_EVENTS = frozenset(
    {PAPER_CYCLE_STARTED, PAPER_CYCLE_COMPLETED, NO_QUALIFIED_OPPORTUNITY, PAPER_CYCLE_FAILED, DATA_COLLECTION_FAILED}
)

_FIELDS = (
    "slot_id", "observation_cycle_id", "symbols_attempted", "symbols_collected", "symbols_failed",
    "option_contracts_observed", "outcome", "equity_usd", "open_positions", "option_id", "message",
)


@dataclass(frozen=True)
class SchedulerEvent:
    event: str
    experiment_id: str
    at: datetime
    slot_id: str | None = None
    observation_cycle_id: str | None = None
    symbols_attempted: int | None = None
    symbols_collected: int | None = None
    symbols_failed: int | None = None
    option_contracts_observed: int | None = None
    outcome: str | None = None
    equity_usd: float | None = None
    open_positions: int | None = None
    option_id: str | None = None  # for PAPER_ENTRY / PAPER_EXIT
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"event": self.event, "experiment_id": self.experiment_id, "at": self.at.isoformat()}
        for field_name in _FIELDS:
            value = getattr(self, field_name)
            if value is not None:
                d[field_name] = value
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SchedulerEvent":
        return cls(
            event=data["event"], experiment_id=data["experiment_id"], at=datetime.fromisoformat(data["at"]),
            **{field_name: data.get(field_name) for field_name in _FIELDS},
        )


class SchedulerEventStore:
    """Simple JSONL append -- the same convention
    `ExperimentStateStore`/`CycleLogStore` already use (no separate
    atomic-rename machinery elsewhere in this codebase either; a torn
    trailing line on a hard crash is tolerated the same way those stores
    already tolerate it, by skipping blank/unparseable trailing lines is
    NOT silently done here -- a malformed line raises, surfacing real
    corruption rather than hiding it)."""

    def __init__(self, path: Path):
        self._path = Path(path)

    def append(self, event: SchedulerEvent) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as fh:
            fh.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")

    def load_all(self) -> list[SchedulerEvent]:
        if not self._path.is_file():
            return []
        rows = []
        for line in self._path.read_text().splitlines():
            if line.strip():
                rows.append(SchedulerEvent.from_dict(json.loads(line)))
        return rows

    def completed_slot_ids(self) -> frozenset[str]:
        return frozenset(e.slot_id for e in self.load_all() if e.event in _CYCLE_TERMINAL_EVENTS and e.slot_id)

    def last_successful_cycle(self) -> SchedulerEvent | None:
        matches = [e for e in self.load_all() if e.event in _CYCLE_TERMINAL_EVENTS]
        return matches[-1] if matches else None

    def last_attempted_cycle(self) -> SchedulerEvent | None:
        matches = [e for e in self.load_all() if e.event in _CYCLE_ATTEMPT_EVENTS]
        return matches[-1] if matches else None

    def data_acquisition_failures(self) -> tuple[SchedulerEvent, ...]:
        return tuple(e for e in self.load_all() if e.event == DATA_COLLECTION_FAILED)

    def scheduler_status(self) -> str:
        for event in reversed(self.load_all()):
            if event.event in (PAPER_SCHEDULER_STARTED, PAPER_SCHEDULER_STOPPED):
                return event.event
        return "NEVER_STARTED"
