"""Phase 7, Part 18: experiment-fingerprint computation.

ExperimentStore (src.research.experiment) has been append-only since
Phase 2 — no function on it can ever overwrite a prior record. What this
module adds is the AUDIT layer on top of that immutability: a stable hash
over exactly the dimensions Part 18 lists as requiring a NEW
experiment/version if changed (feature definition, parameter range,
universe, target, execution model, cost model, validation methodology).
Two experiment records with different fingerprints are, by construction,
not comparable as "the same experiment, re-run" — and two records that
SHOULD have different fingerprints but don't indicates a real bug
upstream (a change that should have produced a new record didn't).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ExperimentDimensions:
    feature_definition: str
    parameter_range: Mapping[str, Any]
    universe_name: str
    target_definition: str
    execution_model: str
    cost_model: str
    validation_methodology: str


def compute_experiment_fingerprint(dimensions: ExperimentDimensions) -> str:
    payload = {
        "feature_definition": dimensions.feature_definition,
        "parameter_range": dimensions.parameter_range,
        "universe_name": dimensions.universe_name,
        "target_definition": dimensions.target_definition,
        "execution_model": dimensions.execution_model,
        "cost_model": dimensions.cost_model,
        "validation_methodology": dimensions.validation_methodology,
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fingerprints_differ(a: ExperimentDimensions, b: ExperimentDimensions) -> bool:
    return compute_experiment_fingerprint(a) != compute_experiment_fingerprint(b)


def which_dimensions_changed(a: ExperimentDimensions, b: ExperimentDimensions) -> tuple[str, ...]:
    """Human-readable diff of exactly which Part-18 dimension(s) changed
    between two experiment configurations — used to explain WHY a new
    experiment/version was required, not just that it was."""
    changed = []
    for field_name in ExperimentDimensions.__dataclass_fields__:
        if getattr(a, field_name) != getattr(b, field_name):
            changed.append(field_name)
    return tuple(changed)
