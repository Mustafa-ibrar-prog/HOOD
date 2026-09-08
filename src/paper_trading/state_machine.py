"""Phase 40, Part 24-25 — the experiment status state machine.

`ExperimentStatus` is a Phase-40-LOCAL enum, structurally distinct from
`src.execution.system_state`'s production authorization states
(RESEARCH / VALIDATED_STRATEGY / HUMAN_LIVE_AUTHORIZATION /
LIVE_AUTONOMOUS_TRADING / LIVE_PAUSED / EMERGENCY_STOP) — a paper
experiment being RUNNING has no relationship to, and cannot set,
anything in that other state machine (verified by
`tests/test_phase40_safety.py::test_no_paper_trading_module_touches_system_state`).

Append-only transition log (the same restart-safe convention Phase 37's
`CycleLogStore` and Phase 36's `SystemStateAuditLog` already use):
current status is always derived by replaying the log, never held only
in memory, so a process restart mid-experiment recovers the exact same
state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class ExperimentStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class InvalidExperimentTransitionError(RuntimeError):
    """Raised when a requested transition is not reachable from the
    experiment's current status -- e.g. resuming an experiment that was
    never paused, or starting one that is already COMPLETED."""


# CREATED -> RUNNING -> PAUSED -> RUNNING -> COMPLETED
#                    \-> COMPLETED
#         (any non-terminal state) -> ABORTED
_ALLOWED_TRANSITIONS: dict[ExperimentStatus, frozenset[ExperimentStatus]] = {
    ExperimentStatus.CREATED: frozenset({ExperimentStatus.RUNNING, ExperimentStatus.ABORTED}),
    ExperimentStatus.RUNNING: frozenset({ExperimentStatus.PAUSED, ExperimentStatus.COMPLETED, ExperimentStatus.ABORTED}),
    ExperimentStatus.PAUSED: frozenset({ExperimentStatus.RUNNING, ExperimentStatus.COMPLETED, ExperimentStatus.ABORTED}),
    ExperimentStatus.COMPLETED: frozenset(),  # terminal
    ExperimentStatus.ABORTED: frozenset(),  # terminal
}


@dataclass(frozen=True)
class ExperimentStateTransition:
    experiment_id: str
    from_status: ExperimentStatus | None  # None for the very first (CREATED) transition
    to_status: ExperimentStatus
    at: datetime
    reason: str

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "from_status": self.from_status.value if self.from_status else None,
            "to_status": self.to_status.value,
            "at": self.at.isoformat(),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExperimentStateTransition":
        return cls(
            experiment_id=data["experiment_id"],
            from_status=ExperimentStatus(data["from_status"]) if data.get("from_status") else None,
            to_status=ExperimentStatus(data["to_status"]),
            at=datetime.fromisoformat(data["at"]),
            reason=data["reason"],
        )


class ExperimentStateStore:
    """Append-only JSONL transition log. `current_status()` replays the
    whole file every time (Phase 37/38's own append-only convention) --
    never trusts an in-memory cache across a restart."""

    def __init__(self, path: Path):
        self._path = Path(path)

    def _load_all(self) -> list[ExperimentStateTransition]:
        if not self._path.is_file():
            return []
        rows = []
        for line in self._path.read_text().splitlines():
            if line.strip():
                rows.append(ExperimentStateTransition.from_dict(json.loads(line)))
        return rows

    def current_status(self) -> ExperimentStatus | None:
        rows = self._load_all()
        return rows[-1].to_status if rows else None

    def history(self) -> tuple[ExperimentStateTransition, ...]:
        return tuple(self._load_all())

    def transition(self, *, experiment_id: str, to_status: ExperimentStatus, at: datetime, reason: str) -> ExperimentStateTransition:
        current = self.current_status()
        if current is None:
            if to_status != ExperimentStatus.CREATED:
                raise InvalidExperimentTransitionError(
                    f"First transition for a new experiment must be CREATED, got {to_status.value}"
                )
        else:
            allowed = _ALLOWED_TRANSITIONS[current]
            if to_status not in allowed:
                raise InvalidExperimentTransitionError(
                    f"Cannot transition {current.value} -> {to_status.value}. Allowed from {current.value}: "
                    f"{sorted(s.value for s in allowed) or '(none — terminal state)'}"
                )
        record = ExperimentStateTransition(experiment_id=experiment_id, from_status=current, to_status=to_status, at=at, reason=reason)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as fh:
            fh.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
        return record


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
