"""Phase 28, Part 11 — the system-level autonomous-trading state machine.
UPDATED Phase 35, Parts N-O: wired into the real execution gateway, and
the required state list itself is redefined by Phase 35's own explicit
instruction.

Audit finding (Part 1/11's explicit "audit the current trading state
machine" requirement): NO formal, auditable, system-level operational
state machine exists anywhere in this codebase today. What exists
instead is three independent boolean/string settings
(`Settings.trading_mode`, `Settings.live_trading_confirmed`,
`Settings.live_auto_execute` -- see `src/config/settings.py`) checked
directly by `src/execution/gateway.py`'s `LiveExecutionGateway`. This
codebase DOES already have hypothesis-level lifecycle gates
(`src.research.research_gate.ResearchLifecycleStage`,
`src.research.discovery_development_gate.DiscoveryDevelopmentStage`) --
both govern whether ONE STRATEGY/HYPOTHESIS is allowed to trade, neither
governs the SYSTEM AS A WHOLE's operational mode. This module is new,
reusing that exact enum+FORWARD_ORDER+CODE_COMPUTABLE_STAGES pattern
(Part 1: reuse the pattern, don't duplicate the class) for a genuinely
different, system-level purpose those modules were never meant to serve.

A second, more fundamental real finding, stated plainly rather than
smoothed over: this environment's own architecture means NO Python
process in this codebase can call a real HOOD MCP tool on its own (see
`live_bridge.py`'s module docstring, and every phase back to Phase 15
that has repeated this boundary) -- only an agent's own tool-call turn
can. "Fully autonomous" in THIS environment cannot mean a headless
background daemon with zero agent involvement; it can only mean an
AGENT TURN that itself never pauses for a HUMAN's per-trade sign-off --
e.g. a scheduled/routine-triggered agent wake that runs the full cycle
and, when `live_auto_execute=True`, calls `place_option_order` directly
via `LiveExecutionGateway.submit_order()`'s existing auto-execute path
with NO separate approval step (that mechanism ALREADY EXISTS and is
ALREADY TESTED -- see `gateway.py`'s `_place_pending(..., approved_by=
"system:auto_execute")`). What this module adds is the missing piece:
a SYSTEM-LEVEL, auditable authorization layer that governs WHEN it is
legitimate for a human to flip `live_trading_confirmed`/
`live_auto_execute` on in the first place, with a real transition
history and an explicit pause/emergency-stop concept neither existing
settings mechanism has today.

Phase 28-34: this module was DESIGN ONLY -- nothing was wired into
`settings.py`, `gateway.py`, or `orchestrator.py`. Phase 35 Part O does
that wiring for real: `gateway.py`'s `LiveExecutionGateway._place_pending()`
now calls `is_live_trading_authorized(audit_log)` (this module) as one
of the mandatory checks before every real broker call. Phase 35 also
redefines the REQUIRED STATE LIST itself (Part O's explicit instruction):
`PAPER_TRADING`/`PAPER_VALIDATED` are dropped (Part O: "PAPER_TRADING is
NOT a required stage") and replaced by a single `VALIDATED_STRATEGY`
state -- a strategy can now be validated directly through the research/
backtesting framework's own Promising-Finding/Strategy-Gate
classification (see `src.options.phase35_strategy_gate`), with no
live-paper-trading intermediate stage required. This is a deliberate,
phase-instructed structural change, not accidental drift -- every prior
phase's test asserting `len(SystemState) == 7` has been updated
alongside this change to assert the new 6-state count.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class SystemState(Enum):
    """Phase 35 Part O's exact required 6 states. No per-trade-approval
    state exists here (tested explicitly, not merely absent by
    omission) -- per-trade decisions are the RISK ENGINE + EXECUTION
    ENGINE's job, never a system-state gate."""

    RESEARCH = "RESEARCH"
    VALIDATED_STRATEGY = "VALIDATED_STRATEGY"
    HUMAN_LIVE_AUTHORIZATION = "HUMAN_LIVE_AUTHORIZATION"
    LIVE_AUTONOMOUS_TRADING = "LIVE_AUTONOMOUS_TRADING"
    LIVE_PAUSED = "LIVE_PAUSED"
    EMERGENCY_STOP = "EMERGENCY_STOP"


FORWARD_ORDER: tuple[SystemState, ...] = (
    SystemState.RESEARCH, SystemState.VALIDATED_STRATEGY,
    SystemState.HUMAN_LIVE_AUTHORIZATION, SystemState.LIVE_AUTONOMOUS_TRADING,
)

# Code (a deterministic gate function) may compute RESEARCH -> VALIDATED_STRATEGY
# on its own -- the SAME kind of deterministic, evidence-based computation
# `phase35_strategy_gate.classify_strategy` already performs (mirroring
# discovery_development_gate.py's convention for its own code-computable
# stages). Crossing INTO HUMAN_LIVE_AUTHORIZATION, and crossing FROM it
# into LIVE_AUTONOMOUS_TRADING, both still require an explicit human
# action outside this module -- enabling autonomous live trading is a
# singular, deliberate human act, never something code alone may decide.
CODE_COMPUTABLE_STATES = frozenset({SystemState.RESEARCH, SystemState.VALIDATED_STRATEGY})

# From LIVE_AUTONOMOUS_TRADING, pausing is the SAFE direction -- the system
# may pause itself (a stale-data condition, a risk-limit brush, end of
# trading hours) without waiting for a human, and may resume from a routine
# pause the same way (Part 11: "the system operates independently"; requiring
# a human to bless every next-morning resume would silently reintroduce a
# per-cycle approval gate, which Part 11 forbids as clearly as a per-trade one).
CODE_COMPUTABLE_PAUSE_TRANSITIONS = frozenset({
    (SystemState.LIVE_AUTONOMOUS_TRADING, SystemState.LIVE_PAUSED),
    (SystemState.LIVE_PAUSED, SystemState.LIVE_AUTONOMOUS_TRADING),
})

# EMERGENCY_STOP is reachable, autonomously, from ANY non-terminal state (a
# kill-switch condition must never wait on a human to trigger) -- but NEVER
# autonomously reachable AWAY FROM once tripped. Clearing it requires a fresh
# explicit human act, routed back through HUMAN_LIVE_AUTHORIZATION.
EMERGENCY_STOP_REACHABLE_FROM = frozenset(s for s in SystemState if s != SystemState.EMERGENCY_STOP)


class IllegalSystemStateTransitionError(RuntimeError):
    pass


class StateRequiresHumanActionError(RuntimeError):
    pass


class SystemStateAuditLogError(RuntimeError):
    pass


def can_transition(from_state: SystemState, to_state: SystemState) -> bool:
    if to_state == SystemState.EMERGENCY_STOP:
        return from_state in EMERGENCY_STOP_REACHABLE_FROM
    if from_state == SystemState.EMERGENCY_STOP:
        # Clearing an emergency stop is never a bare state-machine transition
        # -- it always requires assert_human_action_state below to be invoked
        # explicitly with a real human actor, exactly like reaching
        # HUMAN_LIVE_AUTHORIZATION the first time.
        return to_state == SystemState.HUMAN_LIVE_AUTHORIZATION
    if (from_state, to_state) in CODE_COMPUTABLE_PAUSE_TRANSITIONS:
        return True
    try:
        return FORWARD_ORDER.index(to_state) == FORWARD_ORDER.index(from_state) + 1
    except ValueError:
        return False


def assert_code_may_set_state(state: SystemState, *, from_state: SystemState | None = None) -> None:
    """Raises StateRequiresHumanActionError for any transition that isn't
    pure code-computable forward progress or an autonomous pause/resume/
    emergency-stop transition. Reaching HUMAN_LIVE_AUTHORIZATION, or
    crossing from it into LIVE_AUTONOMOUS_TRADING, or clearing
    EMERGENCY_STOP, all raise here -- a caller must use
    `record_human_authorized_transition` instead."""
    if state in CODE_COMPUTABLE_STATES:
        return
    if from_state is not None and (from_state, state) in CODE_COMPUTABLE_PAUSE_TRANSITIONS:
        return
    if from_state is not None and state == SystemState.EMERGENCY_STOP and from_state in EMERGENCY_STOP_REACHABLE_FROM:
        return
    raise StateRequiresHumanActionError(
        f"{state.value} requires an explicit human-authorized transition (see "
        f"record_human_authorized_transition) -- code may not set it on its own"
    )


@dataclass(frozen=True)
class SystemStateTransition:
    from_state: SystemState
    to_state: SystemState
    timestamp: datetime
    authorized_by: str  # "system:code" for a code-computable transition; a real human identifier otherwise
    reason: str

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["from_state"] = self.from_state.value
        d["to_state"] = self.to_state.value
        d["timestamp"] = self.timestamp.isoformat()
        return d


def record_code_transition(from_state: SystemState, to_state: SystemState, *, reason: str, now: datetime | None = None) -> SystemStateTransition:
    if not can_transition(from_state, to_state):
        raise IllegalSystemStateTransitionError(f"{from_state.value} -> {to_state.value} is not a legal transition")
    assert_code_may_set_state(to_state, from_state=from_state)
    return SystemStateTransition(from_state, to_state, now or datetime.now(timezone.utc), "system:code", reason)


def record_human_authorized_transition(from_state: SystemState, to_state: SystemState, *, authorized_by: str, reason: str, now: datetime | None = None) -> SystemStateTransition:
    """The ONLY way to reach HUMAN_LIVE_AUTHORIZATION, cross from it into
    LIVE_AUTONOMOUS_TRADING, or clear an EMERGENCY_STOP. `authorized_by`
    must be a real, non-empty human identifier -- never "system:code" or
    similarly automated-looking (enforced)."""
    if not can_transition(from_state, to_state):
        raise IllegalSystemStateTransitionError(f"{from_state.value} -> {to_state.value} is not a legal transition")
    if not authorized_by or authorized_by.strip().lower().startswith("system:"):
        raise ValueError("record_human_authorized_transition requires a real human identifier in authorized_by")
    return SystemStateTransition(from_state, to_state, now or datetime.now(timezone.utc), authorized_by, reason)


# ---------------------------------------------------------------------------
# Part 11's own preamble: separate, explicit SYSTEM-LEVEL AUTHORIZATION EVENTS
# beyond the state machine itself -- "changing major risk parameters,"
# "changing the approved strategy version," "changing the approved broker,"
# "changing the historical data provider," "disabling the system." These are
# not states (Part 11 lists exactly 7 states, none of these among them) --
# they are auditable EVENTS that can occur while already in
# LIVE_AUTONOMOUS_TRADING, tracked on their own trail.
# ---------------------------------------------------------------------------

class AuthorizationEventType(Enum):
    ACTIVATE_LIVE_AUTONOMOUS_TRADING = "ACTIVATE_LIVE_AUTONOMOUS_TRADING"
    CHANGE_RISK_PARAMETERS = "CHANGE_RISK_PARAMETERS"
    CHANGE_STRATEGY_VERSION = "CHANGE_STRATEGY_VERSION"
    CHANGE_BROKER = "CHANGE_BROKER"
    CHANGE_HISTORICAL_DATA_PROVIDER = "CHANGE_HISTORICAL_DATA_PROVIDER"
    DISABLE_SYSTEM = "DISABLE_SYSTEM"


@dataclass(frozen=True)
class SystemAuthorizationEvent:
    event_type: AuthorizationEventType
    authorized_by: str
    timestamp: datetime
    detail: str

    def __post_init__(self) -> None:
        if not self.authorized_by or self.authorized_by.strip().lower().startswith("system:"):
            raise ValueError("SystemAuthorizationEvent requires a real human identifier in authorized_by")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value, "authorized_by": self.authorized_by,
            "timestamp": self.timestamp.isoformat(), "detail": self.detail,
        }


class SystemStateAuditLog:
    """An append-only, real (file-backed when a path is given) log of every
    state transition and authorization event -- the audit trail neither
    existing settings mechanism (a bare boolean with no history) has today.
    Purely additive; nothing in this class touches `settings.py`."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._transitions: list[SystemStateTransition] = []
        self._events: list[SystemAuthorizationEvent] = []
        if self._path is not None and self._path.is_file():
            self._load_existing()

    def _load_existing(self) -> None:
        """Phase 35, Part P/O -- 'survives process restart.' A fresh
        instance pointed at an existing log file must recover the real
        persisted state, not silently return None/RESEARCH as if nothing
        had ever happened. Each line is either a transition record (has
        `to_state`) or an authorization-event record (has `event_type`);
        malformed lines fail loudly rather than being silently skipped,
        matching this codebase's fail-closed convention for every other
        file-backed store."""
        assert self._path is not None
        raw = self._path.read_text()
        for line_no, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemStateAuditLogError(f"line {line_no} of {self._path} is corrupted: {exc}") from exc
            if "to_state" in record:
                self._transitions.append(SystemStateTransition(
                    from_state=SystemState(record["from_state"]), to_state=SystemState(record["to_state"]),
                    timestamp=datetime.fromisoformat(record["timestamp"]),
                    authorized_by=record["authorized_by"], reason=record["reason"],
                ))
            elif "event_type" in record:
                self._events.append(SystemAuthorizationEvent(
                    event_type=AuthorizationEventType(record["event_type"]), authorized_by=record["authorized_by"],
                    timestamp=datetime.fromisoformat(record["timestamp"]), detail=record["detail"],
                ))
            else:
                raise SystemStateAuditLogError(f"line {line_no} of {self._path} is neither a transition nor an event record")

    def append_transition(self, transition: SystemStateTransition) -> None:
        self._transitions.append(transition)
        self._persist(transition.to_json_dict())

    def append_event(self, event: SystemAuthorizationEvent) -> None:
        self._events.append(event)
        self._persist(event.to_json_dict())

    def _persist(self, record: Mapping[str, Any]) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(dict(record)) + "\n")

    def transitions(self) -> tuple[SystemStateTransition, ...]:
        return tuple(self._transitions)

    def events(self) -> tuple[SystemAuthorizationEvent, ...]:
        return tuple(self._events)

    def current_state(self) -> SystemState | None:
        return self._transitions[-1].to_state if self._transitions else None


def is_live_trading_authorized(audit_log: SystemStateAuditLog) -> bool:
    """Phase 35, Part O -- the single question `LiveExecutionGateway`
    asks before ever considering a real broker call: 'until explicit
    authorization exists, NO ORDER MAY BE SUBMITTED.' True if and only
    if the audit log's current (persisted, restart-surviving) state is
    exactly LIVE_AUTONOMOUS_TRADING -- RESEARCH, VALIDATED_STRATEGY,
    HUMAN_LIVE_AUTHORIZATION (authorization requested but not yet the
    live-trading state itself), LIVE_PAUSED, EMERGENCY_STOP, and no
    record at all (a brand-new deployment) are ALL unauthorized. There
    is deliberately no per-trade variant of this check -- once
    LIVE_AUTONOMOUS_TRADING is reached, individual entries/exits do not
    ask this question again per Part O ('no per-trade approval state')."""
    return audit_log.current_state() == SystemState.LIVE_AUTONOMOUS_TRADING
