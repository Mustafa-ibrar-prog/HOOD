"""Phase 36, Part 2 — the full input a production strategy receives.

`StrategySnapshot` bundles exactly what Part 2 lists: timestamp, account
state, underlying market state, option-chain state, live option quotes,
existing positions, risk state, configuration. Every piece reuses an
existing, real dataclass where one already exists (`UnderlyingSnapshot`
from src/market/models.py, `OpenPosition` from
src/position_manager/models.py, `Settings` from src/config/settings.py)
rather than redefining it -- only `AccountState` and `RiskStateSnapshot`
are new, because nothing in this codebase already models "the read-only
account/risk state a strategy should see" as its own object (the closest
existing things -- `RiskLimits`, and the loose kwargs
`RiskManager.evaluate_new_trade` takes -- are configuration and
call-parameters, not a snapshot of current state).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping

from src.production.live_snapshot import LiveMarketSnapshot

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.market.models import UnderlyingSnapshot
    from src.position_manager.models import OpenPosition
    from src.risk.models import RiskLimits


@dataclass(frozen=True)
class AccountState:
    """Read-only. Sourced, in a real deployment, from get_accounts/
    get_portfolio (never fabricated) -- see the Robinhood compatibility
    audit in the final report for exactly which fields those tools can
    supply today."""

    account_number: str | None
    buying_power_usd: float | None
    equity_usd: float | None
    as_of: datetime


@dataclass(frozen=True)
class RiskStateSnapshot:
    """The mutable, day-scoped state RiskManager's checks need, distinct
    from RiskLimits (static configuration). Mirrors the exact kwargs
    RiskManager.evaluate_new_trade already takes for 'current state' --
    this dataclass just bundles them into one reusable, testable object
    instead of five loose parameters threaded through the pipeline."""

    trades_opened_today: int
    daily_pnl_usd: float
    last_exit_time: datetime | None
    last_position_size_usd: float | None
    last_trade_was_loss: bool


@dataclass(frozen=True)
class StrategySnapshot:
    timestamp: datetime
    account: AccountState
    underlying: "UnderlyingSnapshot"
    option_chain: tuple[Mapping[str, Any], ...]  # raw candidate rows, same loose shape MarketDataProvider.get_option_chain_candidates already returns -- not redefined here
    option_quotes: Mapping[str, LiveMarketSnapshot]  # keyed by option_id
    positions: tuple["OpenPosition", ...]
    risk_state: RiskStateSnapshot
    risk_limits: "RiskLimits"
    settings: "Settings"
