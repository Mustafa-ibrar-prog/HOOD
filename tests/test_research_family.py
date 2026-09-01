"""Phase 7, Part 2 & 19: research-family accounting tests."""

from __future__ import annotations

from src.research.experiment import ExperimentStore
from src.research.research_family import prior_experiments_in_family, summarize_research_family


def test_summarize_empty_family(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    summary = summarize_research_family(store, "FAM-NONE")
    assert summary.experiment_count == 0


def test_summarize_counts_experiments_and_distinct_params(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    store.record(data_version="v1", feature_version="v1", symbols=["AAPL"], timeframe="day", research_family_id="FAM-MOM", hypothesis_id="MOM-A", strategy_family="momentum", parameters={"lookback": 10})
    store.record(data_version="v1", feature_version="v1", symbols=["AAPL"], timeframe="day", research_family_id="FAM-MOM", hypothesis_id="MOM-B", strategy_family="momentum", parameters={"lookback": 20})
    store.record(data_version="v1", feature_version="v1", symbols=["AAPL"], timeframe="day", research_family_id="FAM-MOM", hypothesis_id="MOM-C", strategy_family="momentum", parameters={"lookback": 20})  # duplicate params -> same combo

    summary = summarize_research_family(store, "FAM-MOM")
    assert summary.experiment_count == 3
    assert summary.distinct_parameter_combinations == 2  # 10 and 20 — the duplicate 20 doesn't add a new combo
    assert set(summary.hypothesis_ids) == {"MOM-A", "MOM-B", "MOM-C"}


def test_families_are_isolated_from_each_other(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    store.record(data_version="v1", feature_version="v1", symbols=["AAPL"], timeframe="day", research_family_id="FAM-A", hypothesis_id="A1")
    store.record(data_version="v1", feature_version="v1", symbols=["AAPL"], timeframe="day", research_family_id="FAM-B", hypothesis_id="B1")

    summary_a = summarize_research_family(store, "FAM-A")
    summary_b = summarize_research_family(store, "FAM-B")
    assert summary_a.experiment_count == 1
    assert summary_b.experiment_count == 1
    assert summary_a.hypothesis_ids == ("A1",)


def test_prior_experiments_in_family_answers_how_many_already_tried(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    for i in range(6):
        store.record(data_version=f"v{i}", feature_version="v1", symbols=["AAPL"], timeframe="day", research_family_id="FAM-MOM", hypothesis_id=f"MOM-{i}")
    prior = prior_experiments_in_family(store, "FAM-MOM")
    assert len(prior) == 6  # "how many materially similar hypotheses have we already tried?"


def test_prior_experiments_before_a_given_experiment_excludes_later_ones(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    recs = [store.record(data_version=f"v{i}", feature_version="v1", symbols=["AAPL"], timeframe="day", research_family_id="FAM-MOM", hypothesis_id=f"MOM-{i}") for i in range(4)]
    prior = prior_experiments_in_family(store, "FAM-MOM", before_experiment_id=recs[2].experiment_id)
    assert len(prior) == 2  # only the two recorded strictly before recs[2]
