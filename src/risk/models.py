"""Risk-control configuration and lightweight structural types.

RiskLimits is deliberately decoupled from Settings (config/settings.py) so
the risk manager can be constructed and unit-tested with arbitrary limits
without touching environment variables. RiskLimits.from_settings() is the
normal way to build one in the running application.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.config.settings import Settings


class HeldPosition(Protocol):
    """Structural type for duplicate-position checks. OpenPosition (in
    position_manager.models) satisfies this without risk needing to import
    position_manager, avoiding a circular dependency."""

    symbol: str
    option_id: str


@dataclass(frozen=True)
class RiskLimits:
    max_trades_per_day: int
    max_daily_loss_usd: float
    max_position_size_usd: float
    cooldown_minutes_after_exit: int
    stale_data_max_seconds: float
    max_spread_pct: float
    min_option_volume: int
    min_option_open_interest: int
    max_extended_move_pct: float
    entry_cutoff_time: time

    @classmethod
    def from_settings(cls, settings: "Settings") -> "RiskLimits":
        return cls(
            max_trades_per_day=settings.max_trades_per_day,
            max_daily_loss_usd=settings.max_daily_loss_usd,
            max_position_size_usd=settings.max_position_size_usd,
            cooldown_minutes_after_exit=settings.cooldown_minutes_after_exit,
            stale_data_max_seconds=settings.stale_data_max_seconds,
            max_spread_pct=settings.max_spread_pct,
            min_option_volume=settings.min_option_volume,
            min_option_open_interest=settings.min_option_open_interest,
            max_extended_move_pct=settings.max_extended_move_pct,
            entry_cutoff_time=settings.entry_cutoff_time,
        )
