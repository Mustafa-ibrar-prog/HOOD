"""Phase 41, scheduling component A — market-open detection and
deterministic intraday cadence slots for the automatic paper-trading
scheduler.

Reuses `src.research_recorder.market_hours.is_market_open_for_recording`
(Phase 37, UNMODIFIED) for the actual weekday + time-of-day gate rather
than reimplementing it — the same reuse-not-duplicate rule Phase 40
already followed everywhere. This module adds exactly two things Phase 37
didn't need:

  1. An optional, injectable holiday set. This codebase has NO holiday
     calendar dependency installed and none pre-existed in the repo before
     this phase (grep-confirmed the same way `src/paper_trading/clock.py`'s
     own module docstring already disclosed: "this codebase has NO holiday
     calendar anywhere"). Per the Phase 41 instruction not to hard-code a
     holiday list, `holidays` defaults to an EMPTY frozenset everywhere in
     this module — an honest continuation of that same disclosed
     limitation, not a fabricated calendar. It exists purely as an
     injection point: if a real market-calendar dependency is added to the
     repo later, its output can be passed in here without touching any
     caller's control flow. Until then, a holiday that falls on a weekday
     is not distinguished, IN ADVANCE, from a normal trading day — exactly
     the situation `clock.py` already discloses for the calendar-day
     experiment clock, now shared honestly by the scheduler too.
  2. Deterministic intraday "slots" (`slot_id_for`) — a natural key for
     duplicate-cycle prevention across restarts (see module docstring of
     `src.paper_trading.scheduler`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from src.config.constants import TRADING_WEEKDAYS
from src.research_recorder.market_hours import is_market_open_for_recording

if TYPE_CHECKING:
    from src.config.settings import Settings


def is_trading_day(d: date, holidays: frozenset[date] = frozenset()) -> bool:
    """Weekday-only, matching `TRADING_WEEKDAYS` everywhere else in this
    codebase, minus any real holiday explicitly supplied by the caller
    (empty by default — see module docstring)."""
    return d.weekday() in TRADING_WEEKDAYS and d not in holidays


def is_market_open_now(now: datetime, settings: "Settings", holidays: frozenset[date] = frozenset()) -> bool:
    """True only during regular US market hours on a real trading day.
    Delegates the weekday + time-of-day check entirely to Phase 37's
    `is_market_open_for_recording` (unmodified); only adds the holiday
    exclusion on top."""
    local_tz = ZoneInfo(settings.market_timezone)
    local = now.astimezone(local_tz) if now.tzinfo is not None else now.replace(tzinfo=local_tz)
    if local.date() in holidays:
        return False
    return is_market_open_for_recording(now, settings)


def market_open_instant(d: date, settings: "Settings") -> datetime:
    return datetime.combine(d, settings.market_open_time, tzinfo=ZoneInfo(settings.market_timezone))


def market_close_instant(d: date, settings: "Settings") -> datetime:
    return datetime.combine(d, settings.market_close_time, tzinfo=ZoneInfo(settings.market_timezone))


def next_market_open(
    after: datetime, settings: "Settings", holidays: frozenset[date] = frozenset(), max_lookahead_days: int = 14,
) -> datetime:
    """The next real market-open instant strictly after `after` — walks
    forward day by day applying `is_trading_day` (never assumes every
    calendar day trades, never guesses further than `max_lookahead_days`)."""
    local_tz = ZoneInfo(settings.market_timezone)
    after_local = after.astimezone(local_tz) if after.tzinfo is not None else after.replace(tzinfo=local_tz)
    d = after_local.date()
    for _ in range(max_lookahead_days + 1):
        if is_trading_day(d, holidays):
            candidate = market_open_instant(d, settings)
            if candidate > after_local:
                return candidate
        d += timedelta(days=1)
    raise RuntimeError(f"No trading day found within {max_lookahead_days} days after {after.isoformat()!r}")


def slot_id_for(now: datetime, settings: "Settings", cadence_minutes: int) -> str:
    """Deterministic identity for 'the intraday cadence slot `now` falls
    into', anchored at that calendar day's real market open. A scheduler
    that restarts mid-slot (e.g. market opens 9:30 ET, cadence=15 minutes,
    process restarts at 9:35) computes the SAME slot_id the original 9:30
    wake would have — this is the natural key duplicate-cycle protection
    relies on (see `src.paper_trading.scheduler`'s module docstring).
    Callers must have already confirmed the market is open for `now`
    (via `is_market_open_now`) before calling this."""
    if cadence_minutes <= 0:
        raise ValueError("cadence_minutes must be > 0")
    local_tz = ZoneInfo(settings.market_timezone)
    now_local = now.astimezone(local_tz) if now.tzinfo is not None else now.replace(tzinfo=local_tz)
    open_instant = market_open_instant(now_local.date(), settings)
    elapsed_minutes = max(0.0, (now_local - open_instant).total_seconds() / 60.0)
    slot_index = int(elapsed_minutes // cadence_minutes)
    return f"{now_local.date().isoformat()}-slot{slot_index:04d}"


@dataclass(frozen=True)
class IntradaySlot:
    slot_id: str
    slot_start: datetime


def intraday_slots_for_day(d: date, settings: "Settings", cadence_minutes: int) -> tuple[IntradaySlot, ...]:
    """Every real cadence slot between market open and market close on
    `d`, in order — used only for reporting/inspection (the scheduler
    itself computes slots live via `slot_id_for`, never by pre-planning
    a day's worth in advance)."""
    if cadence_minutes <= 0:
        raise ValueError("cadence_minutes must be > 0")
    open_instant = market_open_instant(d, settings)
    close_instant = market_close_instant(d, settings)
    slots: list[IntradaySlot] = []
    cursor = open_instant
    index = 0
    step = timedelta(minutes=cadence_minutes)
    while cursor <= close_instant:
        slots.append(IntradaySlot(slot_id=f"{d.isoformat()}-slot{index:04d}", slot_start=cursor))
        cursor += step
        index += 1
    return tuple(slots)
