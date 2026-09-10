"""Phase 41 -- market-open detection + deterministic intraday slots.

Covers scheduler-runner items 1 (weekend), 2 (market-open detection),
3 (pre-market), 4 (market-closed), 6 (holiday behavior, via the
injectable `holidays` parameter)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.config.settings import Settings
from src.paper_trading.market_calendar import (
    intraday_slots_for_day,
    is_market_open_now,
    is_trading_day,
    market_close_instant,
    market_open_instant,
    next_market_open,
    slot_id_for,
)

ET = "America/New_York"


@pytest.fixture()
def settings() -> Settings:
    return Settings.from_env(env={})


# --- weekend / pre-market / closed / open -------------------------------------------------


def test_saturday_is_not_a_trading_day(settings):
    saturday = date(2026, 9, 12)
    assert saturday.weekday() == 5
    assert is_trading_day(saturday) is False


def test_sunday_is_not_a_trading_day(settings):
    sunday = date(2026, 9, 13)
    assert sunday.weekday() == 6
    assert is_trading_day(sunday) is False


def test_weekday_with_no_holiday_supplied_is_a_trading_day(settings):
    tuesday = date(2026, 9, 8)
    assert is_trading_day(tuesday) is True


def test_market_closed_on_a_weekend_even_during_normal_open_hours(settings):
    saturday_1030am_et = datetime(2026, 9, 12, 14, 30, tzinfo=timezone.utc)  # 10:30am ET
    assert is_market_open_now(saturday_1030am_et, settings) is False


def test_premarket_before_930am_et_is_closed(settings):
    premarket = datetime(2026, 9, 8, 13, 0, tzinfo=timezone.utc)  # 9:00am ET, a Tuesday
    assert is_market_open_now(premarket, settings) is False


def test_930am_et_is_open(settings):
    at_open = datetime(2026, 9, 8, 13, 30, tzinfo=timezone.utc)  # 9:30am ET
    assert is_market_open_now(at_open, settings) is True


def test_after_close_is_closed(settings):
    after_hours = datetime(2026, 9, 8, 21, 30, tzinfo=timezone.utc)  # 5:30pm ET
    assert is_market_open_now(after_hours, settings) is False


def test_mid_session_is_open(settings):
    midday = datetime(2026, 9, 8, 18, 0, tzinfo=timezone.utc)  # 2:00pm ET
    assert is_market_open_now(midday, settings) is True


# --- holiday injection (Part 6) -------------------------------------------------------------


def test_no_holidays_by_default_so_an_otherwise_normal_weekday_trades(settings):
    """Honest disclosure carried over from src/paper_trading/clock.py:
    this codebase has no holiday-calendar dependency. `holidays` defaults
    to empty everywhere -- never a hard-coded guess."""
    a_real_weekday = date(2026, 9, 8)
    assert is_trading_day(a_real_weekday, holidays=frozenset()) is True


def test_an_injected_holiday_date_is_excluded():
    fake_holiday = date(2026, 9, 8)  # a real Tuesday, injected as a holiday for this test only
    assert is_trading_day(fake_holiday, holidays=frozenset({fake_holiday})) is False


def test_market_is_closed_on_an_injected_holiday_even_at_normal_open_hours(settings):
    fake_holiday = date(2026, 9, 8)
    at_open_on_that_day = datetime(2026, 9, 8, 13, 30, tzinfo=timezone.utc)
    assert is_market_open_now(at_open_on_that_day, settings, holidays=frozenset({fake_holiday})) is False


def test_an_injected_holiday_does_not_affect_other_days(settings):
    fake_holiday = date(2026, 9, 8)
    another_real_open_tuesday = datetime(2026, 9, 15, 13, 30, tzinfo=timezone.utc)
    assert is_market_open_now(another_real_open_tuesday, settings, holidays=frozenset({fake_holiday})) is True


# --- next_market_open ------------------------------------------------------------------------


def test_next_market_open_from_friday_after_close_skips_the_weekend(settings):
    friday_after_close = datetime(2026, 9, 11, 22, 0, tzinfo=timezone.utc)  # Friday 6pm ET
    nxt = next_market_open(friday_after_close, settings)
    assert nxt.date() == date(2026, 9, 14)  # Monday
    assert nxt.time() == settings.market_open_time


def test_next_market_open_from_mid_session_is_the_following_trading_day(settings):
    tuesday_midday = datetime(2026, 9, 8, 18, 0, tzinfo=timezone.utc)
    nxt = next_market_open(tuesday_midday, settings)
    assert nxt.date() == date(2026, 9, 9)  # Wednesday


def test_next_market_open_skips_an_injected_holiday(settings):
    monday = date(2026, 9, 14)
    friday_after_close = datetime(2026, 9, 11, 22, 0, tzinfo=timezone.utc)
    nxt = next_market_open(friday_after_close, settings, holidays=frozenset({monday}))
    assert nxt.date() == date(2026, 9, 15)  # Tuesday, Monday skipped


# --- deterministic intraday slots (duplicate-cycle protection) ---------------------------------


def test_slot_id_for_market_open_instant_is_slot_zero(settings):
    at_open = datetime(2026, 9, 8, 13, 30, tzinfo=timezone.utc)
    assert slot_id_for(at_open, settings, cadence_minutes=15) == "2026-09-08-slot0000"


def test_slot_id_for_five_minutes_after_open_is_still_slot_zero_at_15min_cadence(settings):
    five_minutes_in = datetime(2026, 9, 8, 13, 35, tzinfo=timezone.utc)
    assert slot_id_for(five_minutes_in, settings, cadence_minutes=15) == "2026-09-08-slot0000"


def test_a_restart_five_minutes_late_computes_the_same_slot_id_as_the_original_wake(settings):
    """The exact scenario named in the Phase 41 DUPLICATE PROTECTION
    requirement: 'a scheduler restart at 9:35 AM must not accidentally
    create duplicate observations for the same intended cycle.'"""
    original_wake = datetime(2026, 9, 8, 13, 30, tzinfo=timezone.utc)
    restart_at_935 = datetime(2026, 9, 8, 13, 35, tzinfo=timezone.utc)
    assert slot_id_for(original_wake, settings, cadence_minutes=15) == slot_id_for(restart_at_935, settings, cadence_minutes=15)


def test_slot_id_advances_to_the_next_slot_after_the_cadence_elapses(settings):
    sixteen_minutes_in = datetime(2026, 9, 8, 13, 46, tzinfo=timezone.utc)
    assert slot_id_for(sixteen_minutes_in, settings, cadence_minutes=15) == "2026-09-08-slot0001"


def test_slot_ids_differ_across_calendar_days(settings):
    day1 = datetime(2026, 9, 8, 13, 30, tzinfo=timezone.utc)
    day2 = datetime(2026, 9, 9, 13, 30, tzinfo=timezone.utc)
    assert slot_id_for(day1, settings, cadence_minutes=15) != slot_id_for(day2, settings, cadence_minutes=15)


def test_cadence_minutes_must_be_positive(settings):
    now = datetime(2026, 9, 8, 13, 30, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        slot_id_for(now, settings, cadence_minutes=0)


def test_intraday_slots_for_day_starts_at_open_and_stays_within_the_session(settings):
    slots = intraday_slots_for_day(date(2026, 9, 8), settings, cadence_minutes=60)
    assert slots[0].slot_start == market_open_instant(date(2026, 9, 8), settings)
    assert all(s.slot_start <= market_close_instant(date(2026, 9, 8), settings) for s in slots)
    assert len(slots) >= 2  # a 6.5-hour session at 60-minute cadence has several slots
