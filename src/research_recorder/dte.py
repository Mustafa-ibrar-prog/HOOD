"""Phase 37, Part 18 — DTE (days to expiration), computed only from
information available at observation time.

Timezone assumption, documented explicitly (Part 18's instruction):
`expiration` is a calendar `date` (option contracts expire at end of a
trading day, not a specific instant); `observation_timestamp` is
converted to the given `market_timezone` (matching every other
market-hours calculation in this codebase, e.g.
`src.research_recorder.market_hours`) before taking its `.date()`. DTE
is then a plain calendar-day difference in that timezone -- never
computed from a raw UTC date, which could be off by one near midnight
UTC (a trading day in US markets never aligns with UTC midnight).
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

DTE_VERSION = "phase37-dte-v1"


def compute_dte(*, expiration: date, observation_timestamp: datetime, market_timezone: str) -> int:
    """Returns a possibly-negative integer -- a negative DTE means the
    contract had already expired as of the observation timestamp (the
    caller, e.g. contract_selection.py/quote_quality.py, decides what to
    do with that; this function never clamps or hides it)."""
    if observation_timestamp.tzinfo is not None:
        local_dt = observation_timestamp.astimezone(ZoneInfo(market_timezone))
    else:
        local_dt = observation_timestamp  # already assumed local, matching market_hours.py's own convention
    return (expiration - local_dt.date()).days
