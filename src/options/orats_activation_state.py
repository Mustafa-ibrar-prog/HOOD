"""Phase 29 — the final activation state, and Part 11's strict dataset-
separation vocabulary.
"""

from __future__ import annotations

import enum


class ORATSActivationState(enum.Enum):
    """This phase's own required Path A / Path B outcome vocabulary."""

    ORATS_ACTIVATION_PENDING_HUMAN = "orats_activation_pending_human"  # Path A -- no credentials, adapter built and stopped
    ORATS_ACTIVE_SAMPLE_RETRIEVED = "orats_active_sample_retrieved"  # Path B -- would be set only once real credentials existed and a real sample was retrieved


class DatasetSourceRole(enum.Enum):
    """Part 11's exact 3-way separation. Never combined without
    retaining source identity, provenance, original identifiers, and
    source timestamps, and recording any conflict (Part 11's own
    explicit merge rules) -- enforced structurally by every ORATS
    module in this phase reusing `OptionDataProvenance.source="orats"`
    (orats_schema_mapping.py) as a permanent, per-observation label,
    distinct from `"quantconnect_lean_open_source_sample"` (Phase 26/27,
    unchanged)."""

    FREE_REFERENCE_DATASET = "free_reference_dataset"
    ORATS_DATASET = "orats_dataset"
    OTHER_PROVIDER_DATASET = "other_provider_dataset"


# This phase's real, current state -- no ORATS_API_KEY was found in the
# environment (checked directly, nothing printed) and no .env file
# defines one. Path A applies.
CURRENT_STATE = ORATSActivationState.ORATS_ACTIVATION_PENDING_HUMAN

CURRENT_STATE_NOTE = (
    "No ORATS_API_KEY was found in this environment's process environment or any .env file this phase "
    "(checked directly via os.environ, nothing printed or logged). Per Path A: the adapter (Parts 1-10) was "
    "built and fully tested against real-schema-derived and clearly-labeled synthetic fixtures, and this "
    "phase stopped before any call that would require a real credential. No account was created, no payment "
    "was made, no API key was requested, entered, or stored anywhere in this repository."
)


def dataset_role_for_source(source: str) -> DatasetSourceRole:
    """A single, real, testable mapping from a `OptionDataProvenance.
    source` string to its dataset role -- the enforcement point a future
    merge layer (Part 11) must consult before ever combining two
    sources."""
    if source == "quantconnect_lean_open_source_sample":
        return DatasetSourceRole.FREE_REFERENCE_DATASET
    if source == "orats":
        return DatasetSourceRole.ORATS_DATASET
    return DatasetSourceRole.OTHER_PROVIDER_DATASET
