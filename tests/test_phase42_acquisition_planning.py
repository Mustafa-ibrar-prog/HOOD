"""Phase 42 -- CycleIdentity/strike-task planning. Covers 'all 12
symbols', 'no fabricated data' (plan only, never data), and the planning
half of 'automatic cycle handoff'."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.config.settings import Settings
from src.paper_trading.acquisition_planning import compute_cycle_identity, compute_symbol_strike_tasks
from src.paper_trading.market_calendar import slot_id_for
from src.research_recorder.target_universe import TARGET_UNIVERSE


@pytest.fixture()
def settings() -> Settings:
    return Settings.from_env(env={})


def test_cycle_identity_matches_slot_id_for_directly(settings):
    now = datetime(2026, 9, 8, 13, 30, tzinfo=timezone.utc)
    identity = compute_cycle_identity(now=now, settings=settings, experiment_id="exp-test", cadence_minutes=15)
    assert identity.slot_id == slot_id_for(now, settings, 15)
    assert identity.market_open is True


def test_cycle_identity_defaults_to_the_full_12_symbol_universe(settings):
    now = datetime(2026, 9, 8, 13, 30, tzinfo=timezone.utc)
    identity = compute_cycle_identity(now=now, settings=settings, experiment_id="exp-test", cadence_minutes=15)
    assert identity.universe == TARGET_UNIVERSE
    assert len(identity.universe) == 12


def test_cycle_identity_slot_id_is_none_when_market_closed(settings):
    saturday = datetime(2026, 9, 12, 15, 0, tzinfo=timezone.utc)
    identity = compute_cycle_identity(now=saturday, settings=settings, experiment_id="exp-test", cadence_minutes=15)
    assert identity.market_open is False
    assert identity.slot_id is None


def test_cycle_identity_inbox_dir_is_under_the_experiment_and_includes_slot_id(settings):
    now = datetime(2026, 9, 8, 13, 30, tzinfo=timezone.utc)
    identity = compute_cycle_identity(now=now, settings=settings, experiment_id="exp-abc", cadence_minutes=15)
    path_str = str(identity.inbox_slot_dir)
    assert "exp-abc" in path_str
    assert identity.slot_id in path_str


def test_cycle_identity_respects_explicit_inbox_root_override(settings, tmp_path):
    now = datetime(2026, 9, 8, 13, 30, tzinfo=timezone.utc)
    identity = compute_cycle_identity(
        now=now, settings=settings, experiment_id="exp-abc", cadence_minutes=15, inbox_root=tmp_path,
    )
    assert str(identity.inbox_slot_dir).startswith(str(tmp_path))


def test_cycle_identity_holidays_are_injectable_and_default_empty(settings):
    a_real_weekday = datetime(2026, 9, 8, 13, 30, tzinfo=timezone.utc)
    identity = compute_cycle_identity(now=a_real_weekday, settings=settings, experiment_id="exp-test", cadence_minutes=15)
    assert identity.market_open is True
    from datetime import date

    with_holiday = compute_cycle_identity(
        now=a_real_weekday, settings=settings, experiment_id="exp-test", cadence_minutes=15,
        holidays=frozenset({date(2026, 9, 8)}),
    )
    assert with_holiday.market_open is False


def test_symbol_strike_tasks_cover_every_priced_symbol():
    prices = {"AAPL": 325.4, "MSFT": 491.5, "NVDA": 218.65}
    tasks = compute_symbol_strike_tasks(prices)
    assert {t.symbol for t in tasks} == {"AAPL", "MSFT", "NVDA"}
    assert all(len(t.strikes.strikes) > 0 for t in tasks)


def test_symbol_strike_tasks_never_fabricates_a_task_for_a_missing_price():
    prices = {"AAPL": 325.4, "MSFT": None, "NVDA": 0.0}
    tasks = compute_symbol_strike_tasks(prices)
    assert {t.symbol for t in tasks} == {"AAPL"}  # MSFT/NVDA silently absent, never invented


def test_symbol_strike_tasks_respects_bounds_arguments():
    prices = {"GOOGL": 332.95}
    tasks = compute_symbol_strike_tasks(prices, max_strikes=2)
    assert len(tasks[0].strikes.strikes) <= 2
