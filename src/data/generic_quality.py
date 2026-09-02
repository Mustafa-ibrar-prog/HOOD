"""Phase 15, Part 15 — generic, source-agnostic quality checks.

src/data/quality.py's `validate_bars` is deliberately Bar-specific (OHLC
relationships, volume sign, etc. only make sense for a price bar). The
checks below operate on bare timestamps or on `EventTimestamps` (Phase
15's new src/data/timestamp_model.py) instead, so the SAME function
works for a future FundamentalStore/EarningsStore/OptionsStore/
MacroStore record without writing a bespoke duplicate-timestamp checker
per source. Per Part 15's explicit instruction ("Do not implement
unnecessary data-source-specific pipelines yet. Build only generic
architecture if needed"), this module implements only the checks that
are genuinely generic across any timestamped observation — corporate-
action/adjustment-consistency/ticker-mapping checks stay source-specific
(as src/data/quality.py's SUSPICIOUS_GAP/MISSING_INTERVAL already are)
and are deferred to whichever future phase actually integrates a new
source.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from src.data.timestamp_model import CausalTimestampPolicy, EventTimestamps


def find_duplicate_timestamps(timestamps: Sequence[datetime]) -> dict[datetime, int]:
    """Returns {timestamp: count} for every timestamp appearing more than
    once. Empty dict means no duplicates."""
    counts: dict[datetime, int] = {}
    for ts in timestamps:
        counts[ts] = counts.get(ts, 0) + 1
    return {ts: n for ts, n in counts.items() if n > 1}


def find_out_of_order_indices(timestamps: Sequence[datetime]) -> list[int]:
    """Indices i (i >= 1) where timestamps[i] < timestamps[i - 1] — i.e.
    the series is not sorted ascending. Equal consecutive timestamps are
    NOT flagged here (that's find_duplicate_timestamps' job)."""
    return [i for i in range(1, len(timestamps)) if timestamps[i] < timestamps[i - 1]]


def find_timezone_naive_indices(timestamps: Sequence[datetime]) -> list[int]:
    """Indices of any timestamp missing tzinfo or not normalized to UTC —
    same convention Bar.__post_init__ already enforces, generalized."""
    out: list[int] = []
    for i, ts in enumerate(timestamps):
        if ts.tzinfo is None:
            out.append(i)
        elif ts.utcoffset() is not None and ts.utcoffset().total_seconds() != 0:
            out.append(i)
    return out


def find_publication_time_violations(
    observations: Sequence[EventTimestamps], *, policy: CausalTimestampPolicy, as_of: datetime
) -> list[int]:
    """Indices of any observation that is NOT knowable at `as_of` under
    `policy` — either its causal-timestamp field is missing (source isn't
    point-in-time-safe for this policy) or it lies strictly in the future
    relative to as_of. This is the generic form of Part 19's "safety
    against future publication dates" test: a future concrete store can
    run every record it's about to hand to a backtest through this check
    before the backtest ever sees it."""
    out: list[int] = []
    for i, obs in enumerate(observations):
        causal = obs.causal_timestamp(policy)
        if causal is None or causal > as_of:
            out.append(i)
    return out
