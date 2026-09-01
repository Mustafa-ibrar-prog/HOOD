"""Phase 6, section 22: "experiment IDs remain immutable" — recording a
new Phase 6 holdout result must never touch, renumber, or overwrite any
prior record, including ones with the same hypothesis_id/universe_name."""

from __future__ import annotations

from pathlib import Path

from src.research.experiment import ExperimentStore


def test_two_records_with_the_same_hypothesis_get_distinct_ids_and_neither_is_overwritten(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    first = store.record(
        data_version="v1", feature_version="v1", symbols=["AAPL"], timeframe="day",
        hypothesis_id="MR-002", universe_name="US_DIVERSIFIED", classification="PROMISING", tags=("phase5-campaign",),
    )
    second = store.record(
        data_version="v2", feature_version="v2", symbols=["META"], timeframe="day",
        hypothesis_id="MR-002", universe_name="US_DIVERSIFIED", classification="INCONCLUSIVE", tags=("phase6-holdout", "primary-temporal-holdout"),
    )
    assert first.experiment_id != second.experiment_id

    all_records = store.load_all()
    assert len(all_records) == 2
    reloaded_first = store.get(first.experiment_id)
    assert reloaded_first is not None
    assert reloaded_first.classification == "PROMISING"  # untouched by the second record
    assert reloaded_first.data_version == "v1"


def test_recording_a_phase6_holdout_result_does_not_mutate_a_phase5_record_on_disk(tmp_path):
    path = tmp_path / "experiments.jsonl"
    store = ExperimentStore(path)
    phase5 = store.record(data_version="phase5", feature_version="phase5", symbols=["AAPL"], timeframe="day", hypothesis_id="MR-002", universe_name="US_DIVERSIFIED", classification="PROMISING")
    before = path.read_text()
    store.record(data_version="phase6", feature_version="phase6", symbols=["META"], timeframe="day", hypothesis_id="MR-002", universe_name="US_DIVERSIFIED_SECONDARY", classification="PROMISING", tags=("phase6-holdout",))
    after = path.read_text()
    assert before in after  # the Phase 5 line is still there, byte-for-byte, as a prefix
    assert store.get(phase5.experiment_id).universe_name == "US_DIVERSIFIED"


def test_experiment_ids_are_unique_across_many_records(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    ids = {store.record(data_version=f"v{i}", feature_version="v1", symbols=["AAPL"], timeframe="day").experiment_id for i in range(20)}
    assert len(ids) == 20
