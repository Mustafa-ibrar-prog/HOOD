"""Phase 36, Part 5 — the formal ValidationArtifact.

A strategy cannot become VALIDATED by changing one enum value (Part 5's
explicit instruction). `StrategyRegistry.mark_validated()` (registry.py)
REQUIRES a real `ValidationArtifact` matching the strategy_id/version,
and the artifact itself requires the evidence fields below to be
populated with something other than a placeholder -- see
`ValidationArtifact.__post_init__`.

Immutable after approval: `ValidationArtifactStore` is append-only,
exactly like `FrozenStrategyStore` (src/research/frozen_strategy.py,
reused convention) and `HypothesisRegistry`/`ExperimentStore` before it
-- approving twice with different content for the same
(strategy_id, strategy_version) raises.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class ValidationArtifactImmutabilityError(RuntimeError):
    """Raised when re-approving an existing (strategy_id, strategy_version)
    with different content -- an approved artifact is a permanent record,
    not a draft. Mint a new strategy_version instead."""


class IncompleteValidationEvidenceError(ValueError):
    """Raised by ValidationArtifact.__post_init__ when a required evidence
    field is empty/placeholder -- Part 5: 'a strategy cannot become
    VALIDATED by changing one enum.'"""


_PLACEHOLDER_STRINGS = frozenset({"", "n/a", "N/A", "tbd", "TBD", "todo", "TODO"})


@dataclass(frozen=True)
class ValidationArtifact:
    strategy_id: str
    strategy_version: str
    strategy_content_hash: str  # exact strategy version/hash -- e.g. FrozenStrategyDefinition.content_hash()
    research_dataset_version: str
    feature_definitions: str
    target_definitions: str
    backtest_configuration: Mapping[str, Any]
    out_of_sample_results: Mapping[str, Any]
    cost_assumptions: Mapping[str, Any]
    robustness_results: Mapping[str, Any]
    statistical_results: Mapping[str, Any]
    multiple_testing_status: str
    affordability: Mapping[str, Any]
    execution_realism: Mapping[str, Any]
    known_limitations: str
    validation_date: datetime
    validation_decision: str  # e.g. "VALIDATED_CANDIDATE" -- the Strategy Gate vocabulary (src.options.phase35_strategy_gate), not a new one
    approved_by: str

    def __post_init__(self) -> None:
        required_nonempty = {
            "strategy_id": self.strategy_id, "strategy_version": self.strategy_version,
            "strategy_content_hash": self.strategy_content_hash,
            "research_dataset_version": self.research_dataset_version,
            "feature_definitions": self.feature_definitions, "target_definitions": self.target_definitions,
            "multiple_testing_status": self.multiple_testing_status,
            "known_limitations": self.known_limitations, "validation_decision": self.validation_decision,
            "approved_by": self.approved_by,
        }
        for name, value in required_nonempty.items():
            if value is None or str(value).strip() in _PLACEHOLDER_STRINGS:
                raise IncompleteValidationEvidenceError(f"ValidationArtifact.{name} cannot be empty/placeholder")
        required_nonempty_dicts = {
            "backtest_configuration": self.backtest_configuration, "out_of_sample_results": self.out_of_sample_results,
            "cost_assumptions": self.cost_assumptions, "robustness_results": self.robustness_results,
            "statistical_results": self.statistical_results, "affordability": self.affordability,
            "execution_realism": self.execution_realism,
        }
        for name, value in required_nonempty_dicts.items():
            if not value:
                raise IncompleteValidationEvidenceError(f"ValidationArtifact.{name} cannot be empty")

    def content_hash(self) -> str:
        d = asdict(self)
        d.pop("validation_date", None)
        blob = json.dumps(d, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["validation_date"] = self.validation_date.isoformat()
        d["content_hash"] = self.content_hash()
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ValidationArtifact":
        data = dict(data)
        data.pop("content_hash", None)
        data["validation_date"] = datetime.fromisoformat(data["validation_date"])
        return cls(**data)


class ValidationArtifactStore:
    def __init__(self, path: Path):
        self._path = path

    def approve(self, artifact: ValidationArtifact) -> ValidationArtifact:
        existing = self.get(artifact.strategy_id, artifact.strategy_version)
        if existing is not None:
            if existing.content_hash() != artifact.content_hash():
                raise ValidationArtifactImmutabilityError(
                    f"{artifact.strategy_id} {artifact.strategy_version} is already approved with "
                    "different content. Mint a new strategy_version instead."
                )
            return existing  # idempotent re-approval of identical content
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(artifact.to_dict(), sort_keys=True, default=str))
            f.write("\n")
        return artifact

    def load_all(self) -> list[ValidationArtifact]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        return [ValidationArtifact.from_dict(json.loads(line)) for line in raw.splitlines() if line.strip()]

    def get(self, strategy_id: str, strategy_version: str) -> ValidationArtifact | None:
        for rec in self.load_all():
            if rec.strategy_id == strategy_id and rec.strategy_version == strategy_version:
                return rec
        return None
