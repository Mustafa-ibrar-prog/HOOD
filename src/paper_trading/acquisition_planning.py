"""Phase 42 — the "Process A" acquisition plan: what an agent must fetch,
and where it must write it, for the CURRENT scheduled cycle.

This module computes; it never calls a HOOD MCP tool itself (nothing in
this codebase can — see `src/live_bridge.py`'s module docstring, still
unchanged, still true — and `docs/phase42_data_acquisition_automation_
investigation.md` for why no supported mechanism closes that gap). It
exists purely to remove the error-prone parts of the manual runbook that
Phase 41 already documented (recomputing the slot id and inbox directory
by hand, guessing near-the-money strikes by eye) so the still-required
agent step is fast and correct instead of ad hoc.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.paper_trading.market_calendar import is_market_open_now, slot_id_for
from src.paper_trading.near_the_money import TargetStrikePlan, compute_target_strikes
from src.research_recorder.target_universe import TARGET_UNIVERSE

if TYPE_CHECKING:
    from src.config.settings import Settings


@dataclass(frozen=True)
class CycleIdentity:
    """Stage 1 of the plan -- computable before any real data is fetched."""

    now: datetime
    slot_id: str | None  # None when the market is closed for `now` -- no cycle is due
    market_open: bool
    inbox_slot_dir: Path
    universe: tuple[str, ...]


def compute_cycle_identity(
    *,
    now: datetime,
    settings: "Settings",
    experiment_id: str,
    cadence_minutes: int,
    inbox_root: Path | None = None,
    universe: tuple[str, ...] = TARGET_UNIVERSE,
    holidays: frozenset = frozenset(),
) -> CycleIdentity:
    """The exact slot_id/inbox directory this cycle's data must be written
    to -- reuses `src.paper_trading.market_calendar` (Phase 41, UNMODIFIED)
    rather than recomputing the market-hours/slot logic here."""
    from src.paper_trading.scheduler import SchedulerConfig

    market_open = is_market_open_now(now, settings, holidays)
    slot_id = slot_id_for(now, settings, cadence_minutes) if market_open else None
    resolved_inbox_root = inbox_root or SchedulerConfig(experiment_id=experiment_id).resolved_inbox_root()
    inbox_slot_dir = resolved_inbox_root / slot_id if slot_id else resolved_inbox_root / "market-closed"
    return CycleIdentity(now=now, slot_id=slot_id, market_open=market_open, inbox_slot_dir=inbox_slot_dir, universe=universe)


@dataclass(frozen=True)
class SymbolStrikeTask:
    symbol: str
    underlying_price: float
    strikes: TargetStrikePlan


def compute_symbol_strike_tasks(
    prices: dict[str, float], *, moneyness_band: float = 0.20, max_strikes: int = 6,
) -> tuple[SymbolStrikeTask, ...]:
    """Stage 2 of the plan -- once real equity quotes are in hand
    (`prices`: symbol -> real last/mid price), compute the bounded,
    deterministic set of exact strikes worth querying per symbol (see
    `near_the_money.compute_target_strikes`). Symbols with no price
    (acquisition already failed for them) are simply absent from the
    result -- never a fabricated task."""
    tasks = []
    for symbol, price in prices.items():
        if price is None or price <= 0:
            continue
        plan = compute_target_strikes(price, moneyness_band=moneyness_band, max_strikes=max_strikes)
        tasks.append(SymbolStrikeTask(symbol=symbol, underlying_price=price, strikes=plan))
    return tuple(tasks)
