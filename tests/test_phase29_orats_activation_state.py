"""Phase 29, Part 11/17 — activation state and dataset-role separation."""

from __future__ import annotations

from src.options.orats_activation_state import (
    CURRENT_STATE,
    CURRENT_STATE_NOTE,
    DatasetSourceRole,
    ORATSActivationState,
    dataset_role_for_source,
)


def test_current_state_is_pending_human_path_a():
    assert CURRENT_STATE == ORATSActivationState.ORATS_ACTIVATION_PENDING_HUMAN


def test_current_state_note_confirms_no_credentials_found():
    text = CURRENT_STATE_NOTE.lower()
    assert "no ORATS_API_KEY was found".lower() in text
    assert "no account was created" in text
    assert "no payment was made" in text


def test_three_dataset_roles_exist():
    assert {r.value for r in DatasetSourceRole} == {"free_reference_dataset", "orats_dataset", "other_provider_dataset"}


def test_lean_source_maps_to_free_reference_dataset():
    assert dataset_role_for_source("quantconnect_lean_open_source_sample") == DatasetSourceRole.FREE_REFERENCE_DATASET


def test_orats_source_maps_to_orats_dataset():
    assert dataset_role_for_source("orats") == DatasetSourceRole.ORATS_DATASET


def test_unknown_source_maps_to_other_provider_dataset():
    assert dataset_role_for_source("some_future_vendor") == DatasetSourceRole.OTHER_PROVIDER_DATASET


def test_no_source_ever_maps_to_two_roles():
    """A structural sanity check: no ambiguity in the mapping."""
    sources = ["quantconnect_lean_open_source_sample", "orats", "polygon", "thetadata"]
    roles = [dataset_role_for_source(s) for s in sources]
    assert roles[0] != roles[1]
    assert roles[2] == roles[3] == DatasetSourceRole.OTHER_PROVIDER_DATASET
