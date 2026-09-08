"""Phase 40, Part 4/24/25/31 — the CREATED/RUNNING/PAUSED/COMPLETED/
ABORTED state machine and the calendar-day vs market-day clock."""

from __future__ import annotations

import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.paper_trading.clock import compute_clock_status, is_trading_weekday
from src.paper_trading.state_machine import (
    ExperimentStateStore,
    ExperimentStatus,
    InvalidExperimentTransitionError,
)

NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)  # Tuesday


def _store(d):
    return ExperimentStateStore(Path(d) / "state.jsonl")


# --- State machine -----------------------------------------------------------------------------


def test_first_transition_must_be_created():
    with tempfile.TemporaryDirectory() as d:
        store = _store(d)
        with pytest.raises(InvalidExperimentTransitionError):
            store.transition(experiment_id="exp-1", to_status=ExperimentStatus.RUNNING, at=NOW, reason="x")


def test_full_lifecycle_created_running_paused_running_completed():
    with tempfile.TemporaryDirectory() as d:
        store = _store(d)
        store.transition(experiment_id="exp-1", to_status=ExperimentStatus.CREATED, at=NOW, reason="start")
        store.transition(experiment_id="exp-1", to_status=ExperimentStatus.RUNNING, at=NOW, reason="start")
        assert store.current_status() == ExperimentStatus.RUNNING
        store.transition(experiment_id="exp-1", to_status=ExperimentStatus.PAUSED, at=NOW, reason="pause")
        assert store.current_status() == ExperimentStatus.PAUSED
        store.transition(experiment_id="exp-1", to_status=ExperimentStatus.RUNNING, at=NOW, reason="resume")
        store.transition(experiment_id="exp-1", to_status=ExperimentStatus.COMPLETED, at=NOW, reason="duration reached")
        assert store.current_status() == ExperimentStatus.COMPLETED


def test_cannot_resume_an_experiment_that_was_never_paused():
    with tempfile.TemporaryDirectory() as d:
        store = _store(d)
        store.transition(experiment_id="exp-1", to_status=ExperimentStatus.CREATED, at=NOW, reason="start")
        with pytest.raises(InvalidExperimentTransitionError):
            # RUNNING -> RUNNING is not a listed transition
            store.transition(experiment_id="exp-1", to_status=ExperimentStatus.RUNNING, at=NOW, reason="x")
            store.transition(experiment_id="exp-1", to_status=ExperimentStatus.RUNNING, at=NOW, reason="resume-without-pause")


def test_completed_and_aborted_are_terminal():
    with tempfile.TemporaryDirectory() as d:
        store = _store(d)
        store.transition(experiment_id="exp-1", to_status=ExperimentStatus.CREATED, at=NOW, reason="start")
        store.transition(experiment_id="exp-1", to_status=ExperimentStatus.ABORTED, at=NOW, reason="stop")
        with pytest.raises(InvalidExperimentTransitionError):
            store.transition(experiment_id="exp-1", to_status=ExperimentStatus.RUNNING, at=NOW, reason="x")


def test_any_non_terminal_state_can_abort():
    with tempfile.TemporaryDirectory() as d:
        store = _store(d)
        store.transition(experiment_id="exp-1", to_status=ExperimentStatus.CREATED, at=NOW, reason="start")
        store.transition(experiment_id="exp-1", to_status=ExperimentStatus.ABORTED, at=NOW, reason="explicit stop")
        assert store.current_status() == ExperimentStatus.ABORTED


def test_current_status_survives_a_restart_fresh_store_instance():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "state.jsonl"
        ExperimentStateStore(path).transition(experiment_id="exp-1", to_status=ExperimentStatus.CREATED, at=NOW, reason="start")
        ExperimentStateStore(path).transition(experiment_id="exp-1", to_status=ExperimentStatus.RUNNING, at=NOW, reason="start")
        # A brand-new store instance, same path -- simulates a process restart.
        fresh = ExperimentStateStore(path)
        assert fresh.current_status() == ExperimentStatus.RUNNING
        assert len(fresh.history()) == 2


def test_paper_experiment_running_is_not_live_autonomous_trading():
    """Part 24: a paper experiment RUNNING must not mean
    LIVE_AUTONOMOUS_TRADING -- the two enums share no values and no code
    path connects them."""
    from src.execution.system_state import SystemState

    paper_values = {s.value for s in ExperimentStatus}
    live_values = {s.value for s in SystemState}
    assert paper_values.isdisjoint(live_values)


# --- Clock ---------------------------------------------------------------------------------------


def test_calendar_days_elapsed_counts_weekends():
    start = NOW
    two_weeks_later = start + timedelta(days=14)
    status = compute_clock_status(
        experiment_start=start, planned_minimum_end=start + timedelta(days=14), now=two_weeks_later, cycle_dates=frozenset(),
    )
    assert status.calendar_days_elapsed == 14
    assert status.minimum_duration_met is True


def test_minimum_duration_not_met_before_fourteen_days():
    start = NOW
    almost = start + timedelta(days=13, hours=23)
    status = compute_clock_status(experiment_start=start, planned_minimum_end=start + timedelta(days=14), now=almost, cycle_dates=frozenset())
    assert status.minimum_duration_met is False


def test_experiment_does_not_terminate_over_a_weekend_clock_keeps_running():
    """Saturday/Sunday must not appear as a special 'stop' condition --
    calendar_days_elapsed keeps counting through them."""
    friday = datetime(2026, 9, 4, 15, 0, tzinfo=timezone.utc)
    monday = datetime(2026, 9, 7, 15, 0, tzinfo=timezone.utc)  # +3 calendar days, 1 weekend
    status = compute_clock_status(experiment_start=friday, planned_minimum_end=friday + timedelta(days=14), now=monday, cycle_dates=frozenset({friday.date()}))
    assert status.calendar_days_elapsed == 3


def test_market_days_observed_counts_only_dates_with_a_real_cycle():
    start = NOW
    cycle_dates = frozenset({date(2026, 9, 8), date(2026, 9, 9)})
    status = compute_clock_status(experiment_start=start, planned_minimum_end=start + timedelta(days=14), now=start + timedelta(days=2), cycle_dates=cycle_dates)
    assert status.market_days_observed == 2


def test_market_closed_dates_include_weekends_and_dateless_gaps():
    start = datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)  # Saturday
    now = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)  # Tuesday, 3 days later
    # Only Tuesday had a real cycle.
    status = compute_clock_status(experiment_start=start, planned_minimum_end=start + timedelta(days=14), now=now, cycle_dates=frozenset({date(2026, 9, 8)}))
    assert date(2026, 9, 5) in status.market_closed_dates  # Saturday
    assert date(2026, 9, 6) in status.market_closed_dates  # Sunday
    assert date(2026, 9, 7) in status.market_closed_dates  # Monday, no cycle recorded
    assert date(2026, 9, 8) not in status.market_closed_dates


def test_is_trading_weekday_excludes_weekends():
    assert is_trading_weekday(date(2026, 9, 8)) is True  # Tuesday
    assert is_trading_weekday(date(2026, 9, 5)) is False  # Saturday
    assert is_trading_weekday(date(2026, 9, 6)) is False  # Sunday
