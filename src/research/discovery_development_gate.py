"""Phase 9, Part 20: a SEPARATE, dedicated research gate for hypotheses
that need a discovery/development split more granular than
src.research.research_gate's 12-stage chain (Phase 7's generic gate,
used for MR-002 and P7-VOLANOM-A-DEV1, is left completely untouched —
same "preserve existing infrastructure" convention every phase has
followed).

    IDEA -> PREREGISTERED -> DISCOVERY_TESTED -> DISCOVERY_SUPPORTED ->
    DEVELOPMENT_PREREGISTERED -> DEVELOPMENT_TESTED -> DEVELOPMENT_SUPPORTED ->
    VALIDATION -> HOLDOUT -> PAPER_TRADING_ELIGIBLE -> HUMAN_APPROVAL ->
    PAPER_TRADING -> LIVE_ELIGIBLE -> LIVE_TRADING

Same rules as the Phase 7 gate: no stage may be skipped; NOT_READY is a
side-state reachable from anywhere (terminal — a new hypothesis_version
is required to try again); CODE_COMPUTABLE_STAGES caps what any function
in this codebase may set programmatically at PAPER_TRADING_ELIGIBLE —
everything from HUMAN_APPROVAL onward requires an action outside this
research code.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class DiscoveryDevelopmentStage(str, Enum):
    IDEA = "IDEA"
    PREREGISTERED = "PREREGISTERED"
    DISCOVERY_TESTED = "DISCOVERY_TESTED"
    DISCOVERY_SUPPORTED = "DISCOVERY_SUPPORTED"
    DEVELOPMENT_PREREGISTERED = "DEVELOPMENT_PREREGISTERED"
    DEVELOPMENT_TESTED = "DEVELOPMENT_TESTED"
    DEVELOPMENT_SUPPORTED = "DEVELOPMENT_SUPPORTED"
    VALIDATION = "VALIDATION"
    HOLDOUT = "HOLDOUT"
    PAPER_TRADING_ELIGIBLE = "PAPER_TRADING_ELIGIBLE"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    PAPER_TRADING = "PAPER_TRADING"
    LIVE_ELIGIBLE = "LIVE_ELIGIBLE"
    LIVE_TRADING = "LIVE_TRADING"
    NOT_READY = "NOT_READY"  # side-state, reachable from anywhere, terminal


FORWARD_ORDER: tuple[DiscoveryDevelopmentStage, ...] = (
    DiscoveryDevelopmentStage.IDEA, DiscoveryDevelopmentStage.PREREGISTERED, DiscoveryDevelopmentStage.DISCOVERY_TESTED,
    DiscoveryDevelopmentStage.DISCOVERY_SUPPORTED, DiscoveryDevelopmentStage.DEVELOPMENT_PREREGISTERED,
    DiscoveryDevelopmentStage.DEVELOPMENT_TESTED, DiscoveryDevelopmentStage.DEVELOPMENT_SUPPORTED,
    DiscoveryDevelopmentStage.VALIDATION, DiscoveryDevelopmentStage.HOLDOUT, DiscoveryDevelopmentStage.PAPER_TRADING_ELIGIBLE,
    DiscoveryDevelopmentStage.HUMAN_APPROVAL, DiscoveryDevelopmentStage.PAPER_TRADING, DiscoveryDevelopmentStage.LIVE_ELIGIBLE,
    DiscoveryDevelopmentStage.LIVE_TRADING,
)

CODE_COMPUTABLE_STAGES = frozenset(FORWARD_ORDER[: FORWARD_ORDER.index(DiscoveryDevelopmentStage.PAPER_TRADING_ELIGIBLE) + 1])


class IllegalStageTransitionError(RuntimeError):
    pass


class StageRequiresHumanActionError(RuntimeError):
    pass


def can_transition(from_stage: DiscoveryDevelopmentStage, to_stage: DiscoveryDevelopmentStage) -> bool:
    if to_stage == DiscoveryDevelopmentStage.NOT_READY:
        return from_stage != DiscoveryDevelopmentStage.NOT_READY
    if from_stage == DiscoveryDevelopmentStage.NOT_READY:
        return False
    try:
        return FORWARD_ORDER.index(to_stage) == FORWARD_ORDER.index(from_stage) + 1
    except ValueError:
        return False


def assert_code_may_set_stage(stage: DiscoveryDevelopmentStage) -> None:
    if stage not in CODE_COMPUTABLE_STAGES and stage != DiscoveryDevelopmentStage.NOT_READY:
        raise StageRequiresHumanActionError(f"{stage.value} requires action outside this research codebase — no function here may set it programmatically.")


@dataclass(frozen=True)
class DiscoveryDevelopmentTransitionRecord:
    hypothesis_id: str
    hypothesis_version: str
    from_stage: DiscoveryDevelopmentStage | None
    to_stage: DiscoveryDevelopmentStage
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
    def from_dict(cls, data: Mapping[str, Any]) -> "DiscoveryDevelopmentTransitionRecord":
        return cls(
            hypothesis_id=data["hypothesis_id"], hypothesis_version=data["hypothesis_version"],
            from_stage=DiscoveryDevelopmentStage(data["from_stage"]) if data.get("from_stage") else None,
            to_stage=DiscoveryDevelopmentStage(data["to_stage"]), reason=data["reason"], evidence_summary=data["evidence_summary"],
            transitioned_at=datetime.fromisoformat(data["transitioned_at"]),
        )


class DiscoveryDevelopmentGateStore:
    def __init__(self, path: Path):
        self._path = path

    def current_stage(self, hypothesis_id: str, hypothesis_version: str = "1.0") -> DiscoveryDevelopmentStage | None:
        records = [r for r in self.load_all() if r.hypothesis_id == hypothesis_id and r.hypothesis_version == hypothesis_version]
        if not records:
            return None
        return sorted(records, key=lambda r: r.transitioned_at)[-1].to_stage

    def transition(self, *, hypothesis_id: str, hypothesis_version: str = "1.0", to_stage: DiscoveryDevelopmentStage, reason: str, evidence_summary: str, now: datetime | None = None) -> DiscoveryDevelopmentTransitionRecord:
        assert_code_may_set_stage(to_stage)
        current = self.current_stage(hypothesis_id, hypothesis_version)
        if current is None:
            if to_stage not in (DiscoveryDevelopmentStage.IDEA, DiscoveryDevelopmentStage.NOT_READY):
                raise IllegalStageTransitionError(f"{hypothesis_id} v{hypothesis_version} has no prior stage — the first transition must be to IDEA (or directly to NOT_READY)")
        elif not can_transition(current, to_stage):
            raise IllegalStageTransitionError(f"{hypothesis_id} v{hypothesis_version}: illegal transition {current.value} -> {to_stage.value} (no stage may be skipped)")

        record = DiscoveryDevelopmentTransitionRecord(
            hypothesis_id=hypothesis_id, hypothesis_version=hypothesis_version, from_stage=current, to_stage=to_stage,
            reason=reason, evidence_summary=evidence_summary, transitioned_at=now or datetime.now(timezone.utc),
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(record.to_dict(), sort_keys=True, default=str))
            f.write("\n")
            f.flush()
        return record

    def load_all(self) -> list[DiscoveryDevelopmentTransitionRecord]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        return [DiscoveryDevelopmentTransitionRecord.from_dict(json.loads(line)) for line in raw.splitlines() if line.strip()]

    def history(self, hypothesis_id: str, hypothesis_version: str = "1.0") -> list[DiscoveryDevelopmentTransitionRecord]:
        records = [r for r in self.load_all() if r.hypothesis_id == hypothesis_id and r.hypothesis_version == hypothesis_version]
        return sorted(records, key=lambda r: r.transitioned_at)
