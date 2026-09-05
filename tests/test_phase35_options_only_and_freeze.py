"""Phase 35, Parts A/B/T — options-only verification and the
FrozenStrategyStore registration."""

from __future__ import annotations

from pathlib import Path

from src.options.phase35_frozen_strategy_spec import STRATEGY_ID, build_frozen_strategy_definition
from src.options.phase35_options_only_verification import VERIFICATION


def test_options_only_verification_finds_no_blocker():
    assert VERIFICATION.blocker_found is False
    assert VERIFICATION.no_equity_order_leg_possible is True
    assert VERIFICATION.option_id_mandatory is True
    assert VERIFICATION.option_type_explicit is True
    assert VERIFICATION.expiration_explicit is True
    assert VERIFICATION.strike_explicit is True


def test_no_conversion_boundary_documented_because_none_exists():
    assert VERIFICATION.conversion_boundary_exists is False


def test_frozen_definition_registers_into_the_established_store(tmp_path: Path):
    from src.research.frozen_strategy import FrozenStrategyStore

    store = FrozenStrategyStore(tmp_path / "frozen.jsonl")
    definition = build_frozen_strategy_definition(development_universe_name="AAPL,SPY,GOOG")
    stored = store.freeze(definition)
    assert stored.strategy_id == STRATEGY_ID
    assert store.get(STRATEGY_ID, "1.0") is not None


def test_re_freezing_identical_content_is_idempotent(tmp_path: Path):
    from src.research.frozen_strategy import FrozenStrategyStore

    store = FrozenStrategyStore(tmp_path / "frozen.jsonl")
    d1 = build_frozen_strategy_definition(development_universe_name="AAPL,SPY,GOOG", frozen_at=None)
    from datetime import datetime, timezone

    fixed_time = datetime(2026, 9, 4, tzinfo=timezone.utc)
    d1 = build_frozen_strategy_definition(development_universe_name="AAPL,SPY,GOOG", frozen_at=fixed_time)
    d2 = build_frozen_strategy_definition(development_universe_name="AAPL,SPY,GOOG", frozen_at=fixed_time)
    store.freeze(d1)
    store.freeze(d2)  # must not raise -- identical content
    assert len(store.load_all()) == 1


def test_content_hash_is_stable_across_calls():
    from datetime import datetime, timezone

    fixed_time = datetime(2026, 9, 4, tzinfo=timezone.utc)
    d1 = build_frozen_strategy_definition(development_universe_name="AAPL,SPY,GOOG", frozen_at=fixed_time)
    d2 = build_frozen_strategy_definition(development_universe_name="AAPL,SPY,GOOG", frozen_at=fixed_time)
    assert d1.content_hash() == d2.content_hash()
