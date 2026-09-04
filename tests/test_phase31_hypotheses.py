"""Phase 31, Part 1/18 — the options_alpha_round2 preregistered family."""

from __future__ import annotations

from pathlib import Path

from src.options.phase31_hypotheses import (
    FAMILY,
    UNIVERSE,
    build_hypotheses,
    build_preregistrations,
    hypothesis_id,
    register_all,
)
from src.research.hypothesis import HypothesisRegistry
from src.research.preregistration import PreregistrationStore, require_preregistered


def test_exactly_sixteen_hypotheses_registered():
    hypotheses = build_hypotheses()
    assert len(hypotheses) == 16


def test_every_hypothesis_id_unique_and_in_family():
    hypotheses = build_hypotheses()
    ids = [h.hypothesis_id for h in hypotheses]
    assert len(set(ids)) == 16
    assert all(h.family == FAMILY for h in hypotheses)
    assert all(hid.startswith("P31-OPT-") for hid in ids)


def test_every_hypothesis_has_a_valid_expected_direction_and_horizon():
    for h in build_hypotheses():
        assert h.expected_direction in ("positive", "negative", "unsigned")
        assert h.prediction_horizon_bars >= 1


def test_universe_matches_the_real_free_dataset_underlyings():
    assert UNIVERSE == ("AAPL", "FOXA", "GOOG", "NWSA", "SPY", "TWX")
    for h in build_hypotheses():
        assert h.universe == UNIVERSE


def test_every_hypothesis_has_a_distinct_feature_target_pair():
    """No two hypotheses silently retest the exact same relationship."""
    pairs = [(h.required_features[0], h.target_definition) for h in build_hypotheses()]
    assert len(set(pairs)) == 16


def test_residualized_targets_used_only_by_the_intended_hypotheses():
    residualized = [h.hypothesis_id for h in build_hypotheses() if h.target_definition.endswith("_residualized")]
    assert set(residualized) == {hypothesis_id(s) for s in ("006", "007", "008", "010", "013")}


def test_falsification_criteria_present_for_every_hypothesis():
    for h in build_hypotheses():
        assert len(h.falsification_criteria) >= 1


def test_preregistrations_match_hypotheses_one_to_one():
    hypotheses = build_hypotheses()
    preregs = build_preregistrations(hypotheses)
    assert len(preregs) == len(hypotheses)
    for h, p in zip(hypotheses, preregs):
        assert p.hypothesis_id == h.hypothesis_id
        assert p.time_horizon_bars == h.prediction_horizon_bars
        assert p.expected_direction == h.expected_direction
        assert p.target_definition == h.target_definition


def test_register_all_persists_to_append_only_stores(tmp_path: Path):
    registry = HypothesisRegistry(tmp_path / "hypotheses.jsonl")
    prereg_store = PreregistrationStore(tmp_path / "preregistration.jsonl")
    hypotheses = register_all(registry, prereg_store)

    assert len(registry.load_all()) == 16
    assert len(prereg_store.load_all()) == 16
    for h in hypotheses:
        record = require_preregistered(prereg_store, h.hypothesis_id, h.version)
        assert record.hypothesis_id == h.hypothesis_id


def test_register_all_is_idempotent_on_rerun(tmp_path: Path):
    registry = HypothesisRegistry(tmp_path / "hypotheses.jsonl")
    prereg_store = PreregistrationStore(tmp_path / "preregistration.jsonl")
    register_all(registry, prereg_store)
    register_all(registry, prereg_store)  # must not raise or duplicate
    assert len(registry.load_all()) == 16
    assert len(prereg_store.load_all()) == 16


def test_a_hypothesis_missing_preregistration_is_rejected(tmp_path: Path):
    prereg_store = PreregistrationStore(tmp_path / "preregistration.jsonl")
    import pytest
    from src.research.preregistration import PreregistrationError
    with pytest.raises(PreregistrationError):
        require_preregistered(prereg_store, "P31-OPT-999")
