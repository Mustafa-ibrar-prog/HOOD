"""Phase 7, Part 1 & 19: research-data lifecycle partitioning tests."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.research.partition import (
    PartitionAccessError,
    PartitionLifecycleStage,
    PartitionStore,
    ResearchDatasetPartition,
    assert_no_partition_overlap,
    assert_stage_allows_parameter_selection,
    determine_lifecycle_partitions,
    filter_rows_by_partition,
)


def _partitions():
    return determine_lifecycle_partitions(
        universe_name="TEST_UNIVERSE", full_start=date(2021, 1, 1), full_end=date(2025, 12, 31),
        source_version="v1", data_version="dv1", feature_version="fv1",
    )


def test_four_partitions_are_chronological_and_non_overlapping():
    discovery, development, validation, holdout = _partitions()
    assert discovery.end_date < development.start_date
    assert development.end_date < validation.start_date
    assert validation.end_date < holdout.start_date
    assert_no_partition_overlap([discovery, development, validation, holdout])


def test_holdout_is_the_most_recent_slice():
    discovery, development, validation, holdout = _partitions()
    assert holdout.end_date == date(2025, 12, 31)
    assert holdout.start_date > validation.end_date


def test_dates_come_from_the_actual_range_not_hand_picked():
    """Same inputs -> the exact same boundary, every time — nothing here
    is chosen to flatter a result."""
    a = _partitions()
    b = _partitions()
    for pa, pb in zip(a, b):
        assert pa.start_date == pb.start_date
        assert pa.end_date == pb.end_date


def test_fractions_that_leave_no_room_for_holdout_raise():
    with pytest.raises(ValueError):
        determine_lifecycle_partitions(
            universe_name="U", full_start=date(2021, 1, 1), full_end=date(2025, 12, 31),
            source_version="v1", data_version="dv1", feature_version="fv1",
            discovery_fraction=0.5, development_fraction=0.3, validation_fraction=0.25,
        )


def test_too_short_a_range_raises():
    with pytest.raises(ValueError):
        determine_lifecycle_partitions(universe_name="U", full_start=date(2021, 1, 1), full_end=date(2021, 1, 5), source_version="v1", data_version="dv1", feature_version="fv1")


# --- access guard: the core structural protection ------------------------------------------


def test_parameter_selection_allowed_from_discovery_and_development():
    discovery, development, validation, holdout = _partitions()
    assert_stage_allows_parameter_selection(discovery, context="test")
    assert_stage_allows_parameter_selection(development, context="test")


def test_parameter_selection_blocked_from_validation():
    _, _, validation, _ = _partitions()
    with pytest.raises(PartitionAccessError):
        assert_stage_allows_parameter_selection(validation, context="a parameter sweep")


def test_parameter_selection_blocked_from_final_holdout():
    _, _, _, holdout = _partitions()
    with pytest.raises(PartitionAccessError):
        assert_stage_allows_parameter_selection(holdout, context="a walk-forward window")


def test_overlapping_partitions_are_detected():
    discovery, development, validation, holdout = _partitions()
    tampered_development = ResearchDatasetPartition(
        dataset_id=development.dataset_id, universe_name=development.universe_name, start_date=discovery.end_date,  # deliberately overlaps discovery
        end_date=development.end_date, partition_type=development.partition_type, created_at=development.created_at,
        source_version=development.source_version, data_version=development.data_version, feature_version=development.feature_version,
        status="ACTIVE", immutable=True,
    )
    with pytest.raises(PartitionAccessError):
        assert_no_partition_overlap([discovery, tampered_development])


def test_filter_rows_by_partition_only_keeps_rows_inside_the_range():
    discovery, _, _, holdout = _partitions()
    rows = [
        {"timestamp": datetime.combine(discovery.start_date, datetime.min.time(), tzinfo=timezone.utc), "value": 1},
        {"timestamp": datetime.combine(holdout.start_date, datetime.min.time(), tzinfo=timezone.utc), "value": 2},
    ]
    filtered = filter_rows_by_partition(rows, discovery)
    assert len(filtered) == 1
    assert filtered[0]["value"] == 1


# --- PartitionStore: append-only ------------------------------------------------------------


def test_partition_store_round_trips(tmp_path):
    store = PartitionStore(tmp_path / "partitions.jsonl")
    discovery, development, validation, holdout = _partitions()
    for p in (discovery, development, validation, holdout):
        store.record(p)
    assert len(store.load_all()) == 4
    assert store.get(holdout.dataset_id).partition_type == PartitionLifecycleStage.FINAL_HOLDOUT


def test_partition_store_active_by_stage(tmp_path):
    store = PartitionStore(tmp_path / "partitions.jsonl")
    for p in _partitions():
        store.record(p)
    holdouts = store.active_by_stage(PartitionLifecycleStage.FINAL_HOLDOUT)
    assert len(holdouts) == 1


def test_final_holdout_cannot_be_used_where_discovery_data_should_go():
    """Simulates the exact contamination scenario Part 1 warns about:
    code that's about to select a parameter must reject FINAL_HOLDOUT_DATA
    even if a caller passes it in by mistake."""
    _, _, _, holdout = _partitions()

    def select_best_lookback(partition: ResearchDatasetPartition, candidates):
        assert_stage_allows_parameter_selection(partition, context="select_best_lookback")
        return candidates[0]

    with pytest.raises(PartitionAccessError):
        select_best_lookback(holdout, [5, 10, 20])
