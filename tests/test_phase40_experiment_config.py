"""Phase 40, Part 5/31 — experiment configuration: $1,000 initialization,
14-calendar-day minimum duration, immutability, reproducibility."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.paper_trading.experiment_config import (
    ExperimentConfigImmutabilityError,
    ExperimentConfigStore,
    ExperimentStrategyMode,
    MINIMUM_EXPERIMENT_DAYS,
    build_experiment_config,
    strategy_content_hash,
)

NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)


def test_default_starting_capital_is_one_thousand_dollars():
    cfg = build_experiment_config(now=NOW)
    assert cfg.starting_capital_usd == 1000.0


def test_minimum_duration_is_fourteen_calendar_days_by_default():
    assert MINIMUM_EXPERIMENT_DAYS == 14
    cfg = build_experiment_config(now=NOW)
    assert cfg.planned_minimum_end_timestamp == NOW + timedelta(days=14)


def test_rejects_a_planned_end_shorter_than_the_minimum():
    from src.paper_trading.experiment_config import ExperimentConfig

    with pytest.raises(ValueError, match="14-calendar-day minimum"):
        ExperimentConfig(
            experiment_id="exp-x", starting_capital_usd=1000.0, strategy_id="X", strategy_version="1.0",
            strategy_mode=ExperimentStrategyMode.PAPER_EXPERIMENT_ONLY, strategy_content_hash="abc",
            start_timestamp=NOW, planned_minimum_end_timestamp=NOW + timedelta(days=3),
            universe=("SPY",), execution_assumptions={}, risk_configuration={}, data_provenance="test",
        )


def test_strategy_mode_must_be_paper_experiment_only():
    from src.paper_trading.experiment_config import ExperimentConfig

    with pytest.raises(ValueError):
        # Deliberately construct with a value that isn't the enum member,
        # coerced via .value — proves the class actually validates rather
        # than trusting the type hint.
        object.__setattr__  # no-op reference to keep this test explicit
        ExperimentConfig(
            experiment_id="exp-x", starting_capital_usd=1000.0, strategy_id="X", strategy_version="1.0",
            strategy_mode="NOT_A_REAL_MODE", strategy_content_hash="abc", start_timestamp=NOW,
            planned_minimum_end_timestamp=NOW + timedelta(days=14), universe=("SPY",),
            execution_assumptions={}, risk_configuration={}, data_provenance="test",
        )


def test_universe_defaults_to_the_established_12_symbol_universe():
    from src.research_recorder.target_universe import TARGET_UNIVERSE

    cfg = build_experiment_config(now=NOW)
    assert cfg.universe == TARGET_UNIVERSE
    assert len(cfg.universe) == 12


def test_strategy_content_hash_is_reproducible():
    assert strategy_content_hash() == strategy_content_hash()


def test_strategy_id_is_the_frozen_momentum_breakout_spec():
    from src.options.phase35_frozen_strategy_spec import STRATEGY_ID

    cfg = build_experiment_config(now=NOW)
    assert cfg.strategy_id == STRATEGY_ID


def test_config_store_is_write_once_identical_reapproval_is_a_noop():
    with tempfile.TemporaryDirectory() as d:
        store = ExperimentConfigStore(Path(d) / "config.json")
        cfg = build_experiment_config(now=NOW)
        store.approve(cfg)
        store.approve(cfg)  # identical -- no error
        assert store.get().experiment_id == cfg.experiment_id


def test_config_store_refuses_a_conflicting_reapproval():
    with tempfile.TemporaryDirectory() as d:
        store = ExperimentConfigStore(Path(d) / "config.json")
        cfg1 = build_experiment_config(now=NOW, experiment_id="exp-fixed")
        cfg2 = build_experiment_config(now=NOW + timedelta(hours=1), experiment_id="exp-fixed")
        store.approve(cfg1)
        with pytest.raises(ExperimentConfigImmutabilityError):
            store.approve(cfg2)


def test_config_round_trips_through_dict():
    cfg = build_experiment_config(now=NOW)
    restored = type(cfg).from_dict(cfg.to_dict())
    assert restored == cfg


def test_config_records_data_provenance_and_execution_assumptions():
    cfg = build_experiment_config(now=NOW)
    assert "Phase 37" in cfg.data_provenance
    assert "Phase 39" in cfg.data_provenance
    assert "ask" in cfg.execution_assumptions["entry_price_rule"].lower()
    assert "bid" in cfg.execution_assumptions["exit_price_rule"].lower()


def test_aggressive_default_never_imposes_an_arbitrary_conservative_cap():
    """Part 15: the default risk configuration caps a position only by
    real remaining cash and the account's own starting capital, never an
    unrelated conservative dollar figure like the ambient .env's $250."""
    cfg = build_experiment_config(now=NOW)
    assert cfg.risk_configuration["max_position_size_fraction_of_equity"] == 1.0
