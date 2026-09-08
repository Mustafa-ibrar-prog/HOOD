"""Phase 40, Part 4 — calendar-day vs market-day experiment clock.

`calendar_days_elapsed` counts real calendar days regardless of weekends
or holidays (Part 4: "Do NOT interpret this as only 14 market days...
The experiment must remain active across weekends, market holidays, and
market-closed periods"). `market_days_observed` counts only the distinct
calendar dates on which at least one real observation cycle actually ran
(a genuine market-open + real-data-fetched day, not a guess).

Honest limitation, stated once here rather than pretended away: this
codebase has NO holiday calendar anywhere (grep-confirmed against
src/config/constants.py and every market-hours module before writing
this) — `is_within_monitoring_window`/`is_market_open_for_recording`
gate on weekday + time-of-day only. A market holiday that falls on a
weekday is therefore not distinguished, IN ADVANCE, from a normal
trading day by this codebase. `market_closed_periods` below is instead
DERIVED, after the fact, from which calendar dates actually had a real
cycle run — a date with zero cycles (whether because it was a weekend,
a holiday, or the agent simply didn't run a cycle that day) is reported
as closed, honestly, rather than the two being conflated at the point of
prediction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from src.config.constants import TRADING_WEEKDAYS


@dataclass(frozen=True)
class ExperimentClockStatus:
    experiment_start: datetime
    now: datetime
    calendar_days_elapsed: int
    planned_minimum_end: datetime
    minimum_duration_met: bool
    market_days_observed: int
    market_closed_dates: tuple[date, ...]  # every calendar date since start with zero real cycles run


def calendar_days_elapsed(start: datetime, now: datetime) -> int:
    return (now.date() - start.date()).days


def is_minimum_duration_met(start: datetime, now: datetime, planned_minimum_end: datetime) -> bool:
    return now >= planned_minimum_end


def compute_clock_status(
    *, experiment_start: datetime, planned_minimum_end: datetime, now: datetime, cycle_dates: frozenset[date],
) -> ExperimentClockStatus:
    """`cycle_dates` — the set of calendar dates on which at least one
    real observation cycle actually ran (caller derives this from the
    real cycle log, e.g. src.research_recorder.storage.CycleLogStore or
    Phase 40's own equity-snapshot store — never guessed)."""
    days_elapsed = calendar_days_elapsed(experiment_start, now)
    market_days = len(cycle_dates)

    closed_dates: list[date] = []
    d = experiment_start.date()
    while d <= now.date():
        if d not in cycle_dates:
            closed_dates.append(d)
        d += timedelta(days=1)

    return ExperimentClockStatus(
        experiment_start=experiment_start, now=now, calendar_days_elapsed=days_elapsed,
        planned_minimum_end=planned_minimum_end,
        minimum_duration_met=is_minimum_duration_met(experiment_start, now, planned_minimum_end),
        market_days_observed=market_days, market_closed_dates=tuple(closed_dates),
    )


def is_trading_weekday(d: date) -> bool:
    return d.weekday() in TRADING_WEEKDAYS
