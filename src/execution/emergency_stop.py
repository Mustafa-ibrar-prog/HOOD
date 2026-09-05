"""Phase 35, Part P — a REAL, code-level emergency stop.

Independent of, and in ADDITION to, `system_state.py`'s
`SystemState.EMERGENCY_STOP` (a state within the authorization
narrative) — this module is a simple, dedicated, file-backed kill switch
checked directly by `LiveExecutionGateway._place_pending()` immediately
before every real broker call, so it cannot be bypassed by
`live_auto_execute=True`, by any strategy's own code (strategies never
see this module at all -- they only ever produce a `SetupCandidate`/
`OrderRequest`), or by the human-approval flow (`confirm_and_place`
funnels through the exact same check).

Requirements, verified by `tests/test_phase35_emergency_stop.py`:
  - Defaults to STOPPED (active=True) whenever no record exists yet --
    a brand-new deployment, or a wiped/missing file, is BLOCKED, never
    silently permissive.
  - Survives a process restart (file-backed, like every other store in
    this codebase -- PendingOrderStore, RiskStateStore, ...).
  - `activate()` requires no special authorization (a kill switch must
    be trivially easy to trip, by anyone/anything, including an
    automated risk breach).
  - `clear()` requires a REAL human identity in `authorized_by` (the
    exact same validation `system_state.record_human_authorized_transition`
    already uses -- rejects an empty string or one starting with
    "system:") -- clearing a stop is deliberately harder than tripping
    one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class EmergencyStopState:
    active: bool
    reason: str
    set_at: datetime
    set_by: str

    def to_dict(self) -> dict[str, Any]:
        return {"active": self.active, "reason": self.reason, "set_at": self.set_at.isoformat(), "set_by": self.set_by}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EmergencyStopState":
        return cls(active=bool(data["active"]), reason=data.get("reason", ""), set_at=datetime.fromisoformat(data["set_at"]), set_by=data.get("set_by", ""))


_DEFAULT_STATE = EmergencyStopState(active=True, reason="no emergency-stop record found -- defaults to STOPPED", set_at=datetime.now(timezone.utc), set_by="system:default")


class EmergencyStopStore:
    """File-backed, like every other store in this codebase
    (PendingOrderStore/RiskStateStore/PaperPositionStore) -- fails
    closed on a corrupted file (raises, never silently resets to a
    permissive default)."""

    def __init__(self, path: Path):
        self._path = path

    def current(self) -> EmergencyStopState:
        if not self._path.is_file():
            return _DEFAULT_STATE
        raw = self._path.read_text()
        if not raw.strip():
            return _DEFAULT_STATE
        try:
            return EmergencyStopState.from_dict(json.loads(raw))
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise EmergencyStopStoreError(f"Emergency-stop record is corrupted or unreadable: {exc}") from exc

    def is_stopped(self) -> bool:
        return self.current().active

    def activate(self, *, reason: str, set_by: str = "system:auto") -> EmergencyStopState:
        """No authorization required by design -- a kill switch must be
        trivially easy to trip, including by automated code (a breached
        risk limit, a detected anomaly) or a human, with no special
        identity check."""
        state = EmergencyStopState(active=True, reason=reason, set_at=datetime.now(timezone.utc), set_by=set_by)
        self._write(state)
        return state

    def clear(self, *, authorized_by: str, reason: str) -> EmergencyStopState:
        """The ONLY way to clear an active stop -- requires a real human
        identity, exactly like `system_state.record_human_authorized_transition`.
        Never callable by strategy code (strategies have no reference to
        this store) and never bypassable by live_auto_execute (that
        setting has nothing to do with this check)."""
        if not authorized_by or authorized_by.strip().lower().startswith("system:"):
            raise ValueError("EmergencyStopStore.clear requires a real human identity in authorized_by")
        state = EmergencyStopState(active=False, reason=reason, set_at=datetime.now(timezone.utc), set_by=authorized_by)
        self._write(state)
        return state

    def _write(self, state: EmergencyStopState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True))


class EmergencyStopStoreError(RuntimeError):
    pass
