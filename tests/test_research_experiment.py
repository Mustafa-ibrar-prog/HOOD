"""Tests for ExperimentStore: append-only persistence, round-trips, and
the reproducibility guarantee (deterministic data_version/feature_version
recorded on every experiment, even though experiment_id itself is a
random uniqueness token, not a content hash)."""

from __future__ import annotations

from pathlib import Path

from src.data.versioning import compute_data_version
from src.research.experiment import ExperimentStore


def test_record_and_load_round_trip(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    rec = store.record(
        data_version="dv1",
        feature_version="fv1",
        symbols=["AAPL", "SOFI"],
        timeframe="day",
        prediction_horizon=5,
        train_period=("2023-01-01", "2023-12-31"),
        validation_period=("2024-01-01", "2024-06-30"),
        test_period=("2024-07-01", "2024-12-31"),
        parameters={"window": 20},
        metrics={"correlation": 0.42},
        notes="first pass",
    )
    loaded = store.load_all()
    assert len(loaded) == 1
    assert loaded[0].experiment_id == rec.experiment_id
    assert loaded[0].symbols == ("AAPL", "SOFI")
    assert loaded[0].metrics == {"correlation": 0.42}
    assert loaded[0].train_period == ("2023-01-01", "2023-12-31")


def test_experiments_are_appended_not_overwritten(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    store.record(data_version="dv1", feature_version="fv1", symbols=["AAPL"], timeframe="day")
    store.record(data_version="dv2", feature_version="fv2", symbols=["SOFI"], timeframe="5minute")
    assert len(store.load_all()) == 2


def test_get_finds_by_experiment_id(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    rec = store.record(data_version="dv1", feature_version="fv1", symbols=["AAPL"], timeframe="day")
    found = store.get(rec.experiment_id)
    assert found is not None
    assert found.data_version == "dv1"
    assert store.get("does-not-exist") is None


def test_experiment_ids_are_unique_across_records(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    rec1 = store.record(data_version="dv1", feature_version="fv1", symbols=["AAPL"], timeframe="day")
    rec2 = store.record(data_version="dv1", feature_version="fv1", symbols=["AAPL"], timeframe="day")
    assert rec1.experiment_id != rec2.experiment_id


def test_reproducibility_comes_from_deterministic_data_and_feature_versions(tmp_path):
    """The experiment_id is a uniqueness token, not a reproducibility
    token — reproducibility comes from data_version/feature_version being
    deterministic content hashes that can be recomputed and compared."""
    dv = compute_data_version(source="hood", symbol="AAPL", timeframe="day", start="2023-01-01", end="2024-01-01")
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    rec = store.record(data_version=dv, feature_version="fv1", symbols=["AAPL"], timeframe="day")
    recomputed_dv = compute_data_version(source="hood", symbol="AAPL", timeframe="day", start="2023-01-01", end="2024-01-01")
    assert rec.data_version == recomputed_dv


def test_load_all_on_missing_file_is_empty(tmp_path):
    store = ExperimentStore(tmp_path / "does-not-exist.jsonl")
    assert store.load_all() == []
