"""Phase 37, Part 6 — market-hours gating for the recorder.

Deliberately does NOT import `src.position_manager.monitor.is_within_
monitoring_window`, even though that function's logic is exactly what's
needed here, for one hard structural reason: that module also imports
`src.execution.gateway` (`PositionMonitor.run_once` routes exits through
it), so importing anything from `position_manager.monitor` -- even just
this one pure function -- would pull `src.execution.gateway` into this
package's import graph, which Part 2 requires to be structurally
impossible. This function reimplements the SAME primitives
(`TRADING_WEEKDAYS`, `Settings.market_open_time`/`market_close_time`/
`market_timezone`) instead of the function itself;
`tests/test_phase37_market_hours.py::test_matches_is_within_monitoring_window_semantics`
verifies the two stay behaviorally identical.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from src.config.constants import TRADING_WEEKDAYS

if TYPE_CHECKING:
    from src.config.settings import Settings


def is_market_open_for_recording(now: datetime, settings: "Settings") -> bool:
    """True only during regular US market hours on a trading weekday, in
    the configured market timezone. Part 6: 'Do NOT collect premarket or
    after-hours unless explicitly configured later' -- there is no
    premarket/after-hours branch here at all."""
    if now.tzinfo is not None:
        now = now.astimezone(ZoneInfo(settings.market_timezone))
    if now.weekday() not in TRADING_WEEKDAYS:
        return False
    return settings.market_open_time <= now.time() <= settings.market_close_time
