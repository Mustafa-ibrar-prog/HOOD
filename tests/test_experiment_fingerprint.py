"""Phase 7, Part 18 & 19: experiment-fingerprint / immutability tests."""

from __future__ import annotations

from src.research.experiment import ExperimentStore
from src.research.experiment_fingerprint import ExperimentDimensions, compute_experiment_fingerprint, fingerprints_differ, which_dimensions_changed


def _dims(**overrides):
    base = dict(
        feature_definition="zscore(close,20)", parameter_range={"lookback": [20]}, universe_name="US_DIVERSIFIED",
        target_definition="future_return_5bar", execution_model="next_bar_open_delay_1", cost_model="per_share_0.005",
        validation_methodology="walk_forward",
    )
    base.update(overrides)
    return ExperimentDimensions(**base)


def test_identical_dimensions_produce_identical_fingerprint():
    a = _dims()
    b = _dims()
    assert compute_experiment_fingerprint(a) == compute_experiment_fingerprint(b)
    assert fingerprints_differ(a, b) is False


def test_changing_the_feature_definition_changes_the_fingerprint():
    a = _dims()
    b = _dims(feature_definition="zscore(close,25)")
    assert fingerprints_differ(a, b) is True
    assert "feature_definition" in which_dimensions_changed(a, b)


def test_changing_the_universe_changes_the_fingerprint():
    a = _dims()
    b = _dims(universe_name="US_DIVERSIFIED_SECONDARY")
    assert fingerprints_differ(a, b) is True
    assert which_dimensions_changed(a, b) == ("universe_name",)


def test_changing_multiple_dimensions_reports_all_of_them():
    a = _dims()
    b = _dims(execution_model="next_bar_open_delay_2", cost_model="per_share_0.01")
    changed = which_dimensions_changed(a, b)
    assert set(changed) == {"execution_model", "cost_model"}


def test_no_change_reports_empty_diff():
    a = _dims()
    b = _dims()
    assert which_dimensions_changed(a, b) == ()


# --- integration with ExperimentStore -------------------------------------------------


def test_experiment_store_carries_the_fingerprint_field_and_never_overwrites(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    dims_v1 = _dims()
    fp1 = compute_experiment_fingerprint(dims_v1)
    rec1 = store.record(data_version="v1", feature_version="v1", symbols=["AAPL"], timeframe="day", experiment_fingerprint=fp1)

    dims_v2 = _dims(feature_definition="zscore(close,25)")  # a genuine change -> new fingerprint -> new record, old one untouched
    fp2 = compute_experiment_fingerprint(dims_v2)
    assert fp2 != fp1
    rec2 = store.record(data_version="v2", feature_version="v1", symbols=["AAPL"], timeframe="day", experiment_fingerprint=fp2)

    assert rec1.experiment_id != rec2.experiment_id
    reloaded = store.get(rec1.experiment_id)
    assert reloaded.experiment_fingerprint == fp1  # untouched by the later record
