"""Tests for multiple-hypothesis accounting (Phase 5, section 16)."""

from __future__ import annotations

from src.research.experiment import ExperimentStore
from src.research.search_space import compute_search_space_summary


def test_search_space_counts_distinct_hypotheses_and_universes(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    store.record(data_version="dv", feature_version="fv", symbols=["AAPL"], timeframe="day", hypothesis_id="MOM-001", universe_name="US_DIVERSIFIED", parameters={"lookback": 5}, strategy_family="momentum", prediction_horizon=5)
    store.record(data_version="dv", feature_version="fv", symbols=["AAPL"], timeframe="day", hypothesis_id="MOM-001", universe_name="US_DIVERSIFIED", parameters={"lookback": 10}, strategy_family="momentum", prediction_horizon=5)
    store.record(data_version="dv", feature_version="fv", symbols=["AAPL"], timeframe="day", hypothesis_id="MR-001", universe_name="US_SMALL_CAP_VOLATILE", parameters={"lookback": 5}, strategy_family="mean_reversion", prediction_horizon=5)

    summary = compute_search_space_summary(store.load_all())
    assert summary.total_experiments == 3
    assert summary.total_hypotheses == 2
    assert summary.total_strategy_families == 2
    assert summary.total_universes == 2
    assert summary.total_prediction_horizons == 1
    assert summary.total_parameter_combinations == 3  # 2 distinct MOM-001 combos + 1 MR-001 combo


def test_search_space_empty_store_is_safe(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    summary = compute_search_space_summary(store.load_all())
    assert summary.total_experiments == 0
    assert summary.bonferroni_alpha_per_test is None


def test_search_space_bonferroni_shrinks_with_more_experiments(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    for i in range(10):
        store.record(data_version="dv", feature_version="fv", symbols=["AAPL"], timeframe="day", hypothesis_id=f"H-{i}")
    summary = compute_search_space_summary(store.load_all())
    assert summary.bonferroni_alpha_per_test == 0.005


def test_search_space_render_includes_all_fields(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    store.record(data_version="dv", feature_version="fv", symbols=["AAPL"], timeframe="day", hypothesis_id="MOM-001")
    summary = compute_search_space_summary(store.load_all())
    text = summary.render()
    assert "Total experiments run: 1" in text
    assert "Bonferroni" in text
