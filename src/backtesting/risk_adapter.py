"""Backtest risk integration (Phase 3, section 12) — genuinely reuses
src.risk.manager.RiskManager, unmodified, rather than reimplementing risk
logic here. RiskManager was already designed decoupled from live broker
state (see its own module docstring: "deliberately decoupled from
Settings... can be constructed and unit-tested with arbitrary limits") —
so it needs no adapter for its core logic, only a translation layer for
the two places its origin (options trading) and this phase's target
(equity backtesting) don't line up:

  1. check_liquidity() requires BOTH volume and open_interest — the latter
     is an options-only concept with no equity equivalent. Rather than
     fabricate an open_interest value (this codebase's established
     "never fabricate real market data" convention), the adapter makes
     this check OPT-IN (`enforce_liquidity_check`, default False for
     equities) rather than silently skipping or silently faking it.
  2. check_data_freshness() (staleness vs. the real wall clock) is a
     live-only concern — a historical replay has no "how many seconds ago
     was this fetched" question to ask. It is intentionally never called
     here.
  3. RiskManager's checks are pass/fail only — there is no built-in
     "reduce the size to fit" behavior. The MODIFY behavior this phase
     asks for (approve a smaller size than requested, when only the
     position-size limit is the blocker) is implemented HERE, in the
     adapter, by clipping the proposed quantity and re-running the size
     check — RiskManager.check_position_size itself is called unchanged,
     just against the adjusted number.

risk/manager.py is not imported for its source, only as a library —
zero lines of it are duplicated or modified.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.risk.manager import RiskCheckResult, RiskManager


@dataclass(frozen=True)
class _HeldPosition:
    """Structurally satisfies risk.models.HeldPosition's Protocol (symbol,
    option_id) for an equity backtest, where there is no separate
    option_id concept — the symbol stands in for both, which is exactly
    what check_duplicate_position needs to detect "already holding a
    position in this symbol"."""

    symbol: str
    option_id: str


@dataclass(frozen=True)
class RiskReview:
    decision: str  # "APPROVED" | "MODIFIED" | "REJECTED"
    approved_quantity: int
    reason: str
    checks: tuple[RiskCheckResult, ...]


class BacktestRiskAdapter:
    def __init__(self, risk_manager: RiskManager, *, enforce_liquidity_check: bool = False, enforce_spread_check: bool = True):
        self._rm = risk_manager
        self._enforce_liquidity = enforce_liquidity_check
        self._enforce_spread = enforce_spread_check

    def review(
        self,
        *,
        symbol: str,
        proposed_quantity: int,
        reference_price: float,
        bid: float | None,
        ask: float | None,
        volume: int | None,
        open_interest: int | None,
        trades_opened_today: int,
        daily_pnl_usd: float,
        open_symbols: list[str],
        last_exit_time: datetime | None,
        now: datetime,
        last_position_size_usd: float | None,
        last_trade_was_loss: bool,
        underlying_move_pct: float = 0.0,
    ) -> RiskReview:
        if proposed_quantity <= 0:
            return RiskReview("REJECTED", 0, "proposed_quantity must be > 0", ())

        checks: list[RiskCheckResult] = []
        quantity = proposed_quantity
        modified = False

        proposed_size_usd = quantity * reference_price
        size_check = self._rm.check_position_size(proposed_size_usd)
        if not size_check.passed:
            max_affordable_qty = int(self._rm.limits.max_position_size_usd // reference_price) if reference_price > 0 else 0
            if max_affordable_qty <= 0:
                checks.append(size_check)
                return RiskReview("REJECTED", 0, size_check.message, tuple(checks))
            quantity = max_affordable_qty
            proposed_size_usd = quantity * reference_price
            modified = True
            size_check = self._rm.check_position_size(proposed_size_usd)
        checks.append(size_check)

        open_positions = tuple(_HeldPosition(symbol=s, option_id=s) for s in open_symbols)
        checks.append(self._rm.check_trade_count(trades_opened_today))
        checks.append(self._rm.check_daily_loss(daily_pnl_usd))
        checks.append(self._rm.check_duplicate_position(symbol, symbol, open_positions))
        checks.append(self._rm.check_cooldown(symbol, last_exit_time, now))
        checks.append(self._rm.check_cutoff_time(now))
        checks.append(self._rm.check_no_size_increase_after_loss(proposed_size_usd, last_position_size_usd, last_trade_was_loss))
        checks.append(self._rm.check_extended_move(underlying_move_pct))
        if self._enforce_spread and bid is not None and ask is not None:
            checks.append(self._rm.check_spread(bid, ask))
        if self._enforce_liquidity:
            checks.append(self._rm.check_liquidity(volume, open_interest))

        blocking = [c for c in checks if not c.passed]
        if blocking:
            return RiskReview("REJECTED", 0, "; ".join(c.message for c in blocking), tuple(checks))

        decision = "MODIFIED" if modified else "APPROVED"
        reason = (
            f"Reduced from {proposed_quantity} to {quantity} shares to fit MAX_POSITION_SIZE_USD"
            if modified
            else "All risk checks passed"
        )
        return RiskReview(decision, quantity, reason, tuple(checks))
