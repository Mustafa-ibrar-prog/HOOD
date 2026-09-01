"""Tests for Phase 6, section 1's strategy-freezing mechanism (section 22:
"frozen strategy cannot be modified during holdout evaluation")."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.research.frozen_strategy import (
    FrozenStrategyImmutabilityError,
    FrozenStrategyStore,
    build_mr002_frozen_definition,
    build_strategy_from_frozen,
)


def test_freeze_then_get_round_trips(tmp_path):
    store = FrozenStrategyStore(tmp_path / "frozen.jsonl")
    definition = build_mr002_frozen_definition(development_universe_name="US_DIVERSIFIED", frozen_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    store.freeze(definition)
    fetched = store.get("MR-002", "1.0")
    assert fetched is not None
    assert fetched.lookback == 20
    assert fetched.entry_threshold == -1.5
    assert fetched.content_hash() == definition.content_hash()


def test_refreezing_identical_content_is_idempotent(tmp_path):
    store = FrozenStrategyStore(tmp_path / "frozen.jsonl")
    at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    definition = build_mr002_frozen_definition(development_universe_name="US_DIVERSIFIED", frozen_at=at)
    store.freeze(definition)
    store.freeze(build_mr002_frozen_definition(development_universe_name="US_DIVERSIFIED", frozen_at=at))
    # no new line was written — still exactly one record for this (id, version)
    assert len(store.load_all()) == 1


def test_refreezing_with_different_content_raises(tmp_path):
    store = FrozenStrategyStore(tmp_path / "frozen.jsonl")
    definition = build_mr002_frozen_definition(development_universe_name="US_DIVERSIFIED")
    store.freeze(definition)

    # A "modified" MR-002 (different lookback) but the SAME strategy_version
    # is exactly the mistake freezing is meant to prevent.
    from dataclasses import replace

    tampered = replace(definition, lookback=25)
    with pytest.raises(FrozenStrategyImmutabilityError):
        store.freeze(tampered)

    # the store still only has the original, untouched record
    assert len(store.load_all()) == 1
    assert store.get("MR-002", "1.0").lookback == 20


def test_a_parameter_change_requires_a_new_strategy_version(tmp_path):
    """The escape hatch is a NEW strategy_version (e.g. 'MR-002-V2'), never
    an edit to the frozen one."""
    store = FrozenStrategyStore(tmp_path / "frozen.jsonl")
    v1 = build_mr002_frozen_definition(development_universe_name="US_DIVERSIFIED")
    store.freeze(v1)

    from dataclasses import replace

    v2 = replace(v1, strategy_version="2.0", lookback=25)
    store.freeze(v2)  # different strategy_version -> allowed, doesn't touch v1

    assert len(store.load_all()) == 2
    assert store.get("MR-002", "1.0").lookback == 20
    assert store.get("MR-002", "2.0").lookback == 25


def test_build_strategy_from_frozen_matches_the_frozen_parameters():
    definition = build_mr002_frozen_definition(development_universe_name="US_DIVERSIFIED")
    strategy = build_strategy_from_frozen(definition, ["AAPL", "MSFT"])
    assert strategy.lookback == 20
    assert strategy.entry_z == -1.5
    assert strategy.exit_z == 0.0
    assert strategy.spec.holding_period_bars == 5
    assert strategy.spec.prediction_horizon_bars == 5
    assert strategy.spec.universe == ("AAPL", "MSFT")


def test_content_hash_is_stable_across_reconstruction():
    """Rebuilding the same frozen definition twice (e.g. across two script
    runs) must produce an IDENTICAL hash — this is what lets
    FrozenStrategyStore.freeze() detect a genuine accidental drift."""
    a = build_mr002_frozen_definition(development_universe_name="US_DIVERSIFIED", frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    b = build_mr002_frozen_definition(development_universe_name="US_DIVERSIFIED", frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert a.content_hash() == b.content_hash()


def test_content_hash_ignores_frozen_at_timestamp():
    """Two freezes with the SAME parameters but different timestamps are
    the same content — freezing isn't about when, it's about what."""
    a = build_mr002_frozen_definition(development_universe_name="US_DIVERSIFIED", frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    b = build_mr002_frozen_definition(development_universe_name="US_DIVERSIFIED", frozen_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert a.content_hash() == b.content_hash()
