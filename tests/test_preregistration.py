"""Phase 7, Part 13 & 19: pre-registration enforcement tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.research.hypothesis_generator import generate_hypotheses
from src.research.preregistration import (
    PreregistrationError,
    PreregistrationRecord,
    PreregistrationStore,
    preregistration_from_hypothesis,
    require_preregistered,
)


def _record(hid="H1", version="1.0"):
    return PreregistrationRecord(
        hypothesis_id=hid, hypothesis_version=version, rationale="r", expected_direction="positive", target_definition="t",
        features=("f1",), universe_name="U", time_horizon_bars=5, parameter_ranges={}, validation_methodology="m",
        cost_assumptions="1x", success_criteria=("positive IC",), falsification_criteria=("no IC",),
        registered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_register_then_get_round_trips(tmp_path):
    store = PreregistrationStore(tmp_path / "prereg.jsonl")
    store.register(_record())
    fetched = store.get("H1", "1.0")
    assert fetched is not None
    assert fetched.rationale == "r"


def test_registering_the_same_hypothesis_version_twice_raises(tmp_path):
    store = PreregistrationStore(tmp_path / "prereg.jsonl")
    store.register(_record())
    with pytest.raises(PreregistrationError):
        store.register(_record())


def test_a_new_version_can_be_registered_separately(tmp_path):
    store = PreregistrationStore(tmp_path / "prereg.jsonl")
    store.register(_record(version="1.0"))
    store.register(_record(version="2.0"))
    assert len(store.load_all()) == 2
    assert len(store.all_for_hypothesis("H1")) == 2


def test_require_preregistered_raises_when_missing(tmp_path):
    store = PreregistrationStore(tmp_path / "prereg.jsonl")
    with pytest.raises(PreregistrationError):
        require_preregistered(store, "NEVER-REGISTERED")


def test_require_preregistered_returns_the_record_when_present(tmp_path):
    store = PreregistrationStore(tmp_path / "prereg.jsonl")
    store.register(_record())
    record = require_preregistered(store, "H1")
    assert record.hypothesis_id == "H1"


def test_experiment_runner_pattern_blocked_without_preregistration(tmp_path):
    """Simulates the exact structural protection Part 13 asks for: an
    experiment runner that calls require_preregistered() FIRST cannot run
    against an unregistered hypothesis at all."""
    store = PreregistrationStore(tmp_path / "prereg.jsonl")

    def run_experiment(hypothesis_id):
        require_preregistered(store, hypothesis_id)  # must not raise for this call to proceed
        return "ran"

    with pytest.raises(PreregistrationError):
        run_experiment("UNREGISTERED")

    store.register(_record(hid="REGISTERED"))
    assert run_experiment("REGISTERED") == "ran"


def test_preregistration_from_hypothesis_builds_a_valid_record():
    hyps = generate_hypotheses(["AAPL", "MSFT"])
    record = preregistration_from_hypothesis(
        hyps[0], universe_name="TEST_UNIVERSE", validation_methodology="cross-sectional IC on DISCOVERY_DATA",
        cost_assumptions="not applicable at discovery stage", success_criteria=("IC clearly nonzero",),
    )
    assert record.hypothesis_id == hyps[0].hypothesis_id
    assert record.rationale == hyps[0].economic_intuition
    assert record.falsification_criteria == hyps[0].falsification_criteria
