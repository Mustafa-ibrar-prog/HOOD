"""Phase 7, Part 13: pre-registration.

A Hypothesis (src.research.hypothesis) already captures the economic
claim itself. A PreregistrationRecord captures the RESEARCH PLAN around
that claim — which data partition, which validation methodology, what
counts as success or failure — written and stored BEFORE any experiment
touching that hypothesis runs. The enforcement this module adds:
require_preregistered() raises if a hypothesis_id has no matching
preregistration record, so "run the experiment first, decide what counts
as success after seeing the number" is structurally blocked, not just
discouraged in a docstring.

If a hypothesis is modified after results are observed, PreregistrationStore
requires a NEW hypothesis_version — the original is never overwritten,
same append-only convention as every other Store in this codebase.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


class PreregistrationError(RuntimeError):
    """Raised when an experiment is about to run against a hypothesis
    that has no matching preregistration record, or when an attempt is
    made to overwrite one."""


@dataclass(frozen=True)
class PreregistrationRecord:
    hypothesis_id: str
    hypothesis_version: str
    rationale: str
    expected_direction: str
    target_definition: str
    features: tuple[str, ...]
    universe_name: str
    time_horizon_bars: int
    parameter_ranges: Mapping[str, Any]  # documents what WILL be explored later (e.g. a robustness sweep), not what was already tried
    validation_methodology: str
    cost_assumptions: str
    success_criteria: tuple[str, ...]
    falsification_criteria: tuple[str, ...]
    registered_at: datetime

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["registered_at"] = self.registered_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PreregistrationRecord":
        return cls(
            hypothesis_id=data["hypothesis_id"], hypothesis_version=data["hypothesis_version"], rationale=data["rationale"],
            expected_direction=data["expected_direction"], target_definition=data["target_definition"], features=tuple(data.get("features", ())),
            universe_name=data["universe_name"], time_horizon_bars=int(data["time_horizon_bars"]), parameter_ranges=dict(data.get("parameter_ranges", {})),
            validation_methodology=data["validation_methodology"], cost_assumptions=data["cost_assumptions"],
            success_criteria=tuple(data.get("success_criteria", ())), falsification_criteria=tuple(data.get("falsification_criteria", ())),
            registered_at=datetime.fromisoformat(data["registered_at"]),
        )


class PreregistrationStore:
    """Append-only, same convention as HypothesisRegistry/ExperimentStore/
    FrozenStrategyStore. A (hypothesis_id, hypothesis_version) pair may be
    registered exactly once — re-registering it (even with identical
    content) raises, since a genuine re-registration always means a new
    version."""

    def __init__(self, path: Path):
        self._path = path

    def register(self, record: PreregistrationRecord) -> PreregistrationRecord:
        existing = self.get(record.hypothesis_id, record.hypothesis_version)
        if existing is not None:
            raise PreregistrationError(
                f"{record.hypothesis_id} v{record.hypothesis_version} is already preregistered "
                f"(at {existing.registered_at.isoformat()}) — mint a new hypothesis_version for a genuinely revised plan."
            )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(record.to_dict(), sort_keys=True, default=str))
            f.write("\n")
            f.flush()
        return record

    def load_all(self) -> list[PreregistrationRecord]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        return [PreregistrationRecord.from_dict(json.loads(line)) for line in raw.splitlines() if line.strip()]

    def get(self, hypothesis_id: str, hypothesis_version: str = "1.0") -> PreregistrationRecord | None:
        for r in self.load_all():
            if r.hypothesis_id == hypothesis_id and r.hypothesis_version == hypothesis_version:
                return r
        return None

    def all_for_hypothesis(self, hypothesis_id: str) -> list[PreregistrationRecord]:
        return [r for r in self.load_all() if r.hypothesis_id == hypothesis_id]


def require_preregistered(store: PreregistrationStore, hypothesis_id: str, hypothesis_version: str = "1.0") -> PreregistrationRecord:
    """The enforcement hook: call this at the START of any experiment
    runner, before touching data. Raises PreregistrationError if no
    matching record exists — "run first, decide success criteria after"
    is not representable as a valid call sequence."""
    record = store.get(hypothesis_id, hypothesis_version)
    if record is None:
        raise PreregistrationError(
            f"{hypothesis_id} v{hypothesis_version} has no preregistration record — write one with "
            "PreregistrationStore.register() BEFORE running any experiment against this hypothesis."
        )
    return record


def preregistration_from_hypothesis(
    hypothesis, *, universe_name: str, validation_methodology: str, cost_assumptions: str, success_criteria: Sequence[str], now: datetime | None = None,
) -> PreregistrationRecord:
    """Builds a PreregistrationRecord directly from a
    src.research.hypothesis.Hypothesis's own fields (Phase 7's extended
    ones especially — falsification_criteria, target_definition,
    required_features) so a hypothesis generated by
    src.research.hypothesis_generator can be preregistered without
    re-typing its content."""
    return PreregistrationRecord(
        hypothesis_id=hypothesis.hypothesis_id, hypothesis_version=hypothesis.version, rationale=hypothesis.economic_intuition,
        expected_direction=hypothesis.expected_direction, target_definition=hypothesis.target_definition or "",
        features=hypothesis.required_features, universe_name=universe_name, time_horizon_bars=hypothesis.prediction_horizon_bars,
        parameter_ranges={}, validation_methodology=validation_methodology, cost_assumptions=cost_assumptions,
        success_criteria=tuple(success_criteria), falsification_criteria=hypothesis.falsification_criteria,
        registered_at=now or datetime.now(timezone.utc),
    )
