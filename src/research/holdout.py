"""Phase 6, sections 2-3: determining and enforcing a genuinely untouched
holdout period.

`determine_holdout_split` derives the DEVELOPMENT/HOLDOUT boundary
PROGRAMMATICALLY from the actual set of walk-forward windows Phase 4/5
already ran, rather than a hand-picked date: the boundary is the day after
the LATEST date reached by ANY window's train, validation, OR test span
(test spans reach furthest right, so in practice this is
`max(w.test_end for w in windows) + 1 day`). Everything up to and
including that date has already influenced either parameter selection
(train/validation) or a reported OOS metric (test, which fed the
walk-forward's `aggregated_oos_metrics`, which fed the classification and
the number reported to the user) — so none of it can honestly be called
"unseen." Everything after it has never been loaded into any Phase 4/5
train/validation/test window and is a genuine holdout, by construction,
not by choice of a favorable date.

`assert_no_holdout_leakage` is a runtime guard: it raises if anything
(a parameter sweep, a walk-forward call, a classification input) is ever
given a period that overlaps the holdout. It exists specifically so
Phase 6's own code cannot accidentally violate its own rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence

from src.research.validation import WalkForwardWindow


class HoldoutLeakageError(RuntimeError):
    """Raised when a period that overlaps the holdout is passed somewhere
    that influences strategy/parameter selection."""


@dataclass(frozen=True)
class HoldoutPeriod:
    development_start: date
    development_end: date
    holdout_start: date
    holdout_end: date
    rationale: str

    def __post_init__(self) -> None:
        if not (self.development_start <= self.development_end < self.holdout_start <= self.holdout_end):
            raise ValueError("development and holdout periods must be chronological and non-overlapping")

    def overlaps_holdout(self, start: date, end: date) -> bool:
        return start <= self.holdout_end and end >= self.holdout_start

    def as_dict(self) -> dict:
        return {
            "development_start": self.development_start.isoformat(), "development_end": self.development_end.isoformat(),
            "holdout_start": self.holdout_start.isoformat(), "holdout_end": self.holdout_end.isoformat(),
            "rationale": self.rationale,
        }


def determine_holdout_split(*, windows: Sequence[WalkForwardWindow], full_data_start: date, full_data_end: date) -> HoldoutPeriod:
    """Computes the boundary from the windows actually used to develop and
    validate the frozen strategy, NOT a hand-picked date. If `windows` is
    empty, the entire `full_data_start..full_data_end` range is treated as
    untouched (development period collapses to a single day before
    full_data_start) — callers should treat that as a strong signal
    something upstream is misconfigured rather than a real holdout."""
    if not windows:
        raise ValueError("determine_holdout_split requires at least one walk-forward window that was actually used to develop the strategy")
    last_touched = max(w.test_end for w in windows)
    if last_touched >= full_data_end:
        raise ValueError(
            f"the walk-forward windows already reach the end of available data ({full_data_end}) — "
            "there is no untouched period left; fetch more recent data or shrink the windows before calling this."
        )
    holdout_start = last_touched + timedelta(days=1)
    return HoldoutPeriod(
        development_start=full_data_start, development_end=last_touched,
        holdout_start=holdout_start, holdout_end=full_data_end,
        rationale=(
            f"development_end = max(test_end across all {len(windows)} Phase 4/5 walk-forward windows) = {last_touched}. "
            "Everything up to and including that date appeared in at least one window's train, validation, or test "
            "span (test spans fed the walk-forward's aggregated OOS metric, which fed MR-002's PROMISING "
            "classification) and is therefore development data, not holdout. holdout_start is the very next calendar "
            "day; holdout_end is the last date for which real market data is currently available. This boundary was "
            "computed from the windows, not chosen to make the strategy look better."
        ),
    )


def assert_no_holdout_leakage(*, period_start: date, period_end: date, holdout: HoldoutPeriod, context: str) -> None:
    """Call this from any code path that selects parameters, sweeps a
    grid, or otherwise adapts the strategy — raises if the given period
    touches the holdout at all."""
    if holdout.overlaps_holdout(period_start, period_end):
        raise HoldoutLeakageError(
            f"{context}: period {period_start}..{period_end} overlaps the holdout "
            f"({holdout.holdout_start}..{holdout.holdout_end}) — this is not allowed to influence strategy/"
            "parameter selection."
        )
