"""Phase 7, Part 17: the formal research->live-trading state machine.

    IDEA -> PREREGISTERED -> DISCOVERY_TESTED -> DEVELOPMENT_VALIDATED ->
    STATISTICALLY_SUPPORTED -> INDEPENDENT_HOLDOUT -> HOLDOUT_VALIDATED ->
    PAPER_TRADING_ELIGIBLE -> HUMAN_APPROVAL -> PAPER_TRADING ->
    LIVE_ELIGIBLE -> LIVE_TRADING

No stage may be skipped — `can_transition` only permits moving to the
IMMEDIATE next stage in this chain (or into the side-state NOT_READY,
reachable from anywhere, representing "this hypothesis/version is
concluded not ready" — a fresh hypothesis_version is required to try
again, never a resurrection of a NOT_READY record).

CODE_COMPUTABLE_STAGES caps what ANY function in this codebase is allowed
to set programmatically at PAPER_TRADING_ELIGIBLE — HUMAN_APPROVAL,
PAPER_TRADING, LIVE_ELIGIBLE, and LIVE_TRADING are not stages this (or any
future) automated research code may grant; assert_code_may_set_stage
enforces that as a hard boundary, not a convention.

Phase 6 already built a narrower, MR-002-specific gate
(src.research.paper_trading_gate.ResearchGateStage — RESEARCHED /
HOLDOUT_VALIDATED / PAPER_TRADING_ELIGIBLE / NOT_READY) which is left
completely untouched (immutable historical infrastructure — Part 5/18's
"preserve existing infrastructure, never overwrite historical results").
This module is the general, 12-stage successor for all FUTURE research;
MR-002 gets exactly one record here (see
scripts/phase7_step5_record_mr002_gate_state.py) that maps Phase 6's
already-immutable NOT_READY finding into this new vocabulary, and never
advances it further.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class ResearchLifecycleStage(str, Enum):
    IDEA = "IDEA"
    PREREGISTERED = "PREREGISTERED"
    DISCOVERY_TESTED = "DISCOVERY_TESTED"
    DEVELOPMENT_VALIDATED = "DEVELOPMENT_VALIDATED"
    STATISTICALLY_SUPPORTED = "STATISTICALLY_SUPPORTED"
    INDEPENDENT_HOLDOUT = "INDEPENDENT_HOLDOUT"
    HOLDOUT_VALIDATED = "HOLDOUT_VALIDATED"
    PAPER_TRADING_ELIGIBLE = "PAPER_TRADING_ELIGIBLE"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    PAPER_TRADING = "PAPER_TRADING"
    LIVE_ELIGIBLE = "LIVE_ELIGIBLE"
    LIVE_TRADING = "LIVE_TRADING"
    NOT_READY = "NOT_READY"  # side-state, reachable from anywhere, not part of the forward chain


FORWARD_ORDER: tuple[ResearchLifecycleStage, ...] = (
    ResearchLifecycleStage.IDEA, ResearchLifecycleStage.PREREGISTERED, ResearchLifecycleStage.DISCOVERY_TESTED,
    ResearchLifecycleStage.DEVELOPMENT_VALIDATED, ResearchLifecycleStage.STATISTICALLY_SUPPORTED,
    ResearchLifecycleStage.INDEPENDENT_HOLDOUT, ResearchLifecycleStage.HOLDOUT_VALIDATED,
    ResearchLifecycleStage.PAPER_TRADING_ELIGIBLE, ResearchLifecycleStage.HUMAN_APPROVAL,
    ResearchLifecycleStage.PAPER_TRADING, ResearchLifecycleStage.LIVE_ELIGIBLE, ResearchLifecycleStage.LIVE_TRADING,
)

# The hard boundary: no function in this codebase may programmatically
# set a stage beyond this set. HUMAN_APPROVAL and everything after it
# requires an action OUTSIDE this research code (a human, and eventually
# the live/paper trading systems this phase explicitly does not touch).
CODE_COMPUTABLE_STAGES = frozenset(FORWARD_ORDER[: FORWARD_ORDER.index(ResearchLifecycleStage.PAPER_TRADING_ELIGIBLE) + 1])


class IllegalStageTransitionError(RuntimeError):
    pass


class StageRequiresHumanActionError(RuntimeError):
    pass


def can_transition(from_stage: ResearchLifecycleStage, to_stage: ResearchLifecycleStage) -> bool:
    if to_stage == ResearchLifecycleStage.NOT_READY:
        return from_stage != ResearchLifecycleStage.NOT_READY  # NOT_READY reachable from anywhere except itself (no-op)
    if from_stage == ResearchLifecycleStage.NOT_READY:
        return False  # a NOT_READY record is terminal — start a new hypothesis_version instead
    try:
        from_idx = FORWARD_ORDER.index(from_stage)
        to_idx = FORWARD_ORDER.index(to_stage)
    except ValueError:
        return False
    return to_idx == from_idx + 1


def assert_code_may_set_stage(stage: ResearchLifecycleStage) -> None:
    if stage not in CODE_COMPUTABLE_STAGES and stage != ResearchLifecycleStage.NOT_READY:
        raise StageRequiresHumanActionError(
            f"{stage.value} requires action outside this research codebase (a human, or a live/paper-trading system "
            "this phase does not touch) — no function here may set it programmatically."
        )


@dataclass(frozen=True)
class GateTransitionRecord:
    hypothesis_id: str
    hypothesis_version: str
    from_stage: ResearchLifecycleStage | None  # None for the very first record (IDEA)
    to_stage: ResearchLifecycleStage
    reason: str
    evidence_summary: str
    transitioned_at: datetime

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["from_stage"] = self.from_stage.value if self.from_stage else None
        d["to_stage"] = self.to_stage.value
        d["transitioned_at"] = self.transitioned_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GateTransitionRecord":
        return cls(
            hypothesis_id=data["hypothesis_id"], hypothesis_version=data["hypothesis_version"],
            from_stage=ResearchLifecycleStage(data["from_stage"]) if data.get("from_stage") else None,
            to_stage=ResearchLifecycleStage(data["to_stage"]), reason=data["reason"], evidence_summary=data["evidence_summary"],
            transitioned_at=datetime.fromisoformat(data["transitioned_at"]),
        )


class ResearchGateStore:
    """Append-only transition log — same convention as every other Store
    in this codebase. Never edits or removes a prior transition; a
    mistaken transition gets a NEW record moving to NOT_READY (or
    wherever is legal next) rather than being erased."""

    def __init__(self, path: Path):
        self._path = path

    def current_stage(self, hypothesis_id: str, hypothesis_version: str = "1.0") -> ResearchLifecycleStage | None:
        records = [r for r in self.load_all() if r.hypothesis_id == hypothesis_id and r.hypothesis_version == hypothesis_version]
        if not records:
            return None
        return sorted(records, key=lambda r: r.transitioned_at)[-1].to_stage

    def transition(self, *, hypothesis_id: str, hypothesis_version: str = "1.0", to_stage: ResearchLifecycleStage, reason: str, evidence_summary: str, now: datetime | None = None) -> GateTransitionRecord:
        assert_code_may_set_stage(to_stage)
        current = self.current_stage(hypothesis_id, hypothesis_version)
        from_stage = current if current is not None else None
        if from_stage is None:
            if to_stage != ResearchLifecycleStage.IDEA and to_stage != ResearchLifecycleStage.NOT_READY:
                raise IllegalStageTransitionError(f"{hypothesis_id} v{hypothesis_version} has no prior stage — the first transition must be to IDEA (or directly to NOT_READY)")
        elif not can_transition(from_stage, to_stage):
            raise IllegalStageTransitionError(f"{hypothesis_id} v{hypothesis_version}: illegal transition {from_stage.value} -> {to_stage.value} (no stage may be skipped)")

        record = GateTransitionRecord(
            hypothesis_id=hypothesis_id, hypothesis_version=hypothesis_version, from_stage=from_stage, to_stage=to_stage,
            reason=reason, evidence_summary=evidence_summary, transitioned_at=now or datetime.now(timezone.utc),
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(record.to_dict(), sort_keys=True, default=str))
            f.write("\n")
            f.flush()
        return record

    def load_all(self) -> list[GateTransitionRecord]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        return [GateTransitionRecord.from_dict(json.loads(line)) for line in raw.splitlines() if line.strip()]

    def history(self, hypothesis_id: str, hypothesis_version: str = "1.0") -> list[GateTransitionRecord]:
        records = [r for r in self.load_all() if r.hypothesis_id == hypothesis_id and r.hypothesis_version == hypothesis_version]
        return sorted(records, key=lambda r: r.transitioned_at)
