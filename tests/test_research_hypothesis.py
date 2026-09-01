"""Tests for the hypothesis registry (Phase 4, section 3)."""

from __future__ import annotations

import pytest

from src.research.hypothesis import Hypothesis, HypothesisRegistry, HypothesisRegistryError


def _hypothesis(**overrides) -> Hypothesis:
    defaults = dict(
        hypothesis_id="TEST-001", name="Test Hypothesis", description="A test.",
        economic_intuition="Because reasons.", mathematical_definition="signal = 1[x > 0]",
        required_data=("daily OHLCV",), required_features=("roc_5",),
        prediction_horizon_bars=5, test_methodology="backtest", expected_direction="positive",
        assumptions=("stationarity",),
    )
    defaults.update(overrides)
    return Hypothesis(**defaults)


def test_hypothesis_rejects_invalid_direction():
    with pytest.raises(ValueError):
        _hypothesis(expected_direction="up")


def test_hypothesis_rejects_non_positive_horizon():
    with pytest.raises(ValueError):
        _hypothesis(prediction_horizon_bars=0)


def test_register_and_load(tmp_path):
    registry = HypothesisRegistry(tmp_path / "hypotheses.jsonl")
    h = _hypothesis()
    registry.register(h)
    loaded = registry.load_all()
    assert len(loaded) == 1
    assert loaded[0] == h


def test_get_by_id(tmp_path):
    registry = HypothesisRegistry(tmp_path / "hypotheses.jsonl")
    registry.register(_hypothesis(hypothesis_id="A"))
    registry.register(_hypothesis(hypothesis_id="B"))
    found = registry.get("B")
    assert found is not None
    assert found.hypothesis_id == "B"
    assert registry.get("C") is None


def test_registering_duplicate_id_raises_never_silently_overwrites(tmp_path):
    registry = HypothesisRegistry(tmp_path / "hypotheses.jsonl")
    registry.register(_hypothesis(hypothesis_id="A", description="original"))
    with pytest.raises(HypothesisRegistryError, match="already registered"):
        registry.register(_hypothesis(hypothesis_id="A", description="rewritten after seeing results"))
    # The original is untouched.
    assert registry.get("A").description == "original"


def test_load_all_on_missing_file_is_empty(tmp_path):
    registry = HypothesisRegistry(tmp_path / "does-not-exist.jsonl")
    assert registry.load_all() == []


def test_corrupted_registry_raises_not_silently_empty(tmp_path):
    path = tmp_path / "hypotheses.jsonl"
    path.write_text("not json\n")
    registry = HypothesisRegistry(path)
    with pytest.raises(HypothesisRegistryError):
        registry.load_all()
