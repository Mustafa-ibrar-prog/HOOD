"""Tests for Phase 4's ExperimentStore extensions: querying, and the
already-append-only immutability guarantee applied to failed experiments
too (Phase 4, sections 20-21, and the "failed experiments are preserved"
requirement from section 23)."""

from __future__ import annotations

from pathlib import Path

from src.research.experiment import ExperimentStore


def _record_momentum_pass(store: ExperimentStore):
    return store.record(
        data_version="dv1", feature_version="fv1", symbols=["NIO"], timeframe="day",
        strategy_family="momentum", classification="PROMISING",
        oos_metrics={"sharpe_ratio": 0.8, "trade_count": 30},
        cost_sensitivity={"points": [{"cost_multiplier": 1.0, "viable": True}, {"cost_multiplier": 2.0, "viable": True}]},
        tags=("campaign-1",),
    )


def _record_momentum_fail(store: ExperimentStore):
    return store.record(
        data_version="dv1", feature_version="fv1", symbols=["MARA"], timeframe="day",
        strategy_family="momentum", classification="REJECTED",
        oos_metrics={"sharpe_ratio": -0.3, "trade_count": 25},
        cost_sensitivity={"points": [{"cost_multiplier": 1.0, "viable": False}, {"cost_multiplier": 2.0, "viable": False}]},
        tags=("campaign-1",),
    )


def _record_reversion(store: ExperimentStore):
    return store.record(
        data_version="dv1", feature_version="fv1", symbols=["SOFI"], timeframe="day",
        strategy_family="mean_reversion", classification="FRAGILE",
        oos_metrics={"sharpe_ratio": 0.1, "trade_count": 22},
        cost_sensitivity={"points": [{"cost_multiplier": 1.0, "viable": True}, {"cost_multiplier": 2.0, "viable": False}]},
        tags=("campaign-1",),
    )


def test_query_by_strategy_family(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    _record_momentum_pass(store)
    _record_momentum_fail(store)
    _record_reversion(store)
    momentum = store.query(strategy_family="momentum")
    assert len(momentum) == 2
    assert all(r.strategy_family == "momentum" for r in momentum)


def test_query_by_min_oos_sharpe(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    _record_momentum_pass(store)
    _record_momentum_fail(store)
    _record_reversion(store)
    good = store.query(min_oos_sharpe=0.5)
    assert len(good) == 1
    assert good[0].classification == "PROMISING"


def test_query_failed_at_cost_multiplier(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    _record_momentum_pass(store)
    _record_momentum_fail(store)
    _record_reversion(store)
    failed_at_2x = store.query(failed_at_cost_multiplier=2.0)
    assert len(failed_at_2x) == 2  # the rejected momentum run AND the fragile reversion run


def test_query_by_classification(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    _record_momentum_pass(store)
    _record_momentum_fail(store)
    rejected = store.query(classification="REJECTED")
    assert len(rejected) == 1


def test_query_by_tag(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    _record_momentum_pass(store)
    tagged = store.query(tag="campaign-1")
    assert len(tagged) == 1


def test_query_with_no_filters_returns_everything(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    _record_momentum_pass(store)
    _record_momentum_fail(store)
    assert len(store.query()) == 2


def test_failed_experiments_are_preserved_not_hidden(tmp_path):
    """The store never filters or drops a REJECTED/failed record — it's
    right there in load_all(), same as a PROMISING one."""
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    _record_momentum_fail(store)
    all_records = store.load_all()
    assert len(all_records) == 1
    assert all_records[0].classification == "REJECTED"


def test_a_revised_experiment_supersedes_without_deleting_the_original(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    original = _record_momentum_fail(store)
    revised = store.record(
        data_version="dv2", feature_version="fv1", symbols=["MARA"], timeframe="day",
        strategy_family="momentum", supersedes_experiment_id=original.experiment_id,
        notes="re-run with an extra year of data",
    )
    all_records = store.load_all()
    assert len(all_records) == 2  # both present — nothing was overwritten
    assert store.get(original.experiment_id) is not None
    assert store.get(revised.experiment_id).supersedes_experiment_id == original.experiment_id


def test_new_optional_fields_default_safely_for_phase2_style_records(tmp_path):
    """A record built the Phase-2 way (no Phase 4 kwargs at all) still
    round-trips cleanly with sensible defaults for every new field."""
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    store.record(data_version="dv", feature_version="fv", symbols=["AAPL"], timeframe="day")
    rec = store.load_all()[0]
    assert rec.strategy_family is None
    assert rec.classification is None
    assert rec.oos_metrics == {}
    assert rec.cost_sensitivity == {}
    assert rec.tags == ()
    assert rec.backtest_id is None
    assert rec.supersedes_experiment_id is None
