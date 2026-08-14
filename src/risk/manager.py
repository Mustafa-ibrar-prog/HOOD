"""The risk-management framework.

Every control the user asked for maps to exactly one check method here:

  1. Maximum 4 new trades per day        -> check_trade_count
  2. Maximum daily loss                  -> check_daily_loss
  3. Position-size limit                 -> check_position_size
  4. Duplicate-position protection       -> check_duplicate_position
  5. Cooldown after an exit              -> check_cooldown
  6. Stale-data protection               -> check_data_freshness
  7. Wide-spread protection              -> check_spread
  8. Liquidity protection                -> check_liquidity
  9. No chasing extended moves           -> check_extended_move
 10. No new entries after cutoff         -> check_cutoff_time
 11. Never increase risk after a loss    -> check_no_size_increase_after_loss

evaluate_new_trade() runs all eleven and only allows the trade if every one
passes. Exiting a position is a risk-*reducing* action, so it is never
blocked by these checks — evaluate_exit_conditions() only ever returns
warnings (e.g. "spread is wide, use a marketable limit") for the execution
layer to consider, plus the stale-data check, which forces the caller to
treat the evaluation as unreliable rather than act on it blindly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from src.risk.models import HeldPosition, RiskLimits


@dataclass(frozen=True)
class RiskCheckResult:
    passed: bool
    code: str
    message: str


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    results: tuple[RiskCheckResult, ...]

    @property
    def blocking_reasons(self) -> tuple[str, ...]:
        return tuple(r.message for r in self.results if not r.passed)

    @property
    def passed_codes(self) -> tuple[str, ...]:
        return tuple(r.code for r in self.results if r.passed)


class RiskManager:
    def __init__(self, limits: RiskLimits):
        self.limits = limits

    # --- 1. Maximum trades per day -----------------------------------------
    def check_trade_count(self, trades_opened_today: int) -> RiskCheckResult:
        ok = trades_opened_today < self.limits.max_trades_per_day
        return RiskCheckResult(
            ok,
            "MAX_TRADES_PER_DAY",
            f"{trades_opened_today}/{self.limits.max_trades_per_day} trades opened today"
            if ok
            else f"Daily trade limit reached ({trades_opened_today}/{self.limits.max_trades_per_day})",
        )

    # --- 2. Maximum daily loss -----------------------------------------------
    def check_daily_loss(self, daily_pnl_usd: float) -> RiskCheckResult:
        ok = daily_pnl_usd > -abs(self.limits.max_daily_loss_usd)
        return RiskCheckResult(
            ok,
            "MAX_DAILY_LOSS",
            f"Daily P&L ${daily_pnl_usd:.2f} within limit"
            if ok
            else f"Daily loss limit breached (P&L ${daily_pnl_usd:.2f}, limit -${self.limits.max_daily_loss_usd:.2f})",
        )

    # --- 3. Position-size limit -----------------------------------------------
    def check_position_size(self, proposed_size_usd: float) -> RiskCheckResult:
        ok = proposed_size_usd <= self.limits.max_position_size_usd
        return RiskCheckResult(
            ok,
            "POSITION_SIZE_LIMIT",
            f"Proposed size ${proposed_size_usd:.2f} within limit"
            if ok
            else f"Proposed size ${proposed_size_usd:.2f} exceeds limit ${self.limits.max_position_size_usd:.2f}",
        )

    # --- 4. Duplicate-position protection -------------------------------------
    def check_duplicate_position(
        self,
        candidate_symbol: str,
        candidate_option_id: str,
        open_positions: Iterable[HeldPosition],
    ) -> RiskCheckResult:
        duplicate = any(
            p.option_id == candidate_option_id or p.symbol == candidate_symbol for p in open_positions
        )
        return RiskCheckResult(
            not duplicate,
            "DUPLICATE_POSITION",
            "No existing position in this underlying/contract"
            if not duplicate
            else f"Already holding a position in {candidate_symbol}",
        )

    # --- 5. Cooldown after an exit ---------------------------------------------
    def check_cooldown(self, candidate_symbol: str, last_exit_time: datetime | None, now: datetime) -> RiskCheckResult:
        if last_exit_time is None:
            return RiskCheckResult(True, "COOLDOWN", f"No recent exit recorded for {candidate_symbol}")
        elapsed_minutes = (now - last_exit_time).total_seconds() / 60
        ok = elapsed_minutes >= self.limits.cooldown_minutes_after_exit
        return RiskCheckResult(
            ok,
            "COOLDOWN",
            f"{elapsed_minutes:.1f} min since last exit (>= {self.limits.cooldown_minutes_after_exit})"
            if ok
            else f"Cooldown active: only {elapsed_minutes:.1f} min since last exit on {candidate_symbol} "
            f"(need {self.limits.cooldown_minutes_after_exit})",
        )

    # --- 6. Stale-data protection ------------------------------------------------
    def check_data_freshness(self, data_age_seconds: float) -> RiskCheckResult:
        ok = data_age_seconds <= self.limits.stale_data_max_seconds
        return RiskCheckResult(
            ok,
            "STALE_DATA",
            f"Data age {data_age_seconds:.0f}s within limit"
            if ok
            else f"Data is stale ({data_age_seconds:.0f}s old, limit {self.limits.stale_data_max_seconds:.0f}s)",
        )

    # --- 7. Wide-spread protection -----------------------------------------------
    def check_spread(self, bid: float, ask: float) -> RiskCheckResult:
        if bid <= 0 or ask <= 0 or ask < bid:
            return RiskCheckResult(False, "WIDE_SPREAD", f"Invalid or crossed quote (bid={bid}, ask={ask})")
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid
        ok = spread_pct <= self.limits.max_spread_pct
        return RiskCheckResult(
            ok,
            "WIDE_SPREAD",
            f"Spread {spread_pct:.1%} within limit"
            if ok
            else f"Spread too wide ({spread_pct:.1%}, limit {self.limits.max_spread_pct:.1%})",
        )

    # --- 8. Liquidity protection ---------------------------------------------------
    def check_liquidity(self, volume: int | None, open_interest: int | None) -> RiskCheckResult:
        if volume is None or open_interest is None:
            return RiskCheckResult(False, "LIQUIDITY", "Volume/open-interest data unavailable")
        ok = volume >= self.limits.min_option_volume and open_interest >= self.limits.min_option_open_interest
        return RiskCheckResult(
            ok,
            "LIQUIDITY",
            f"Volume {volume}, OI {open_interest} meet minimums"
            if ok
            else f"Insufficient liquidity (volume={volume}, OI={open_interest}; "
            f"need >= {self.limits.min_option_volume}/{self.limits.min_option_open_interest})",
        )

    # --- 9. No chasing extended moves -----------------------------------------------
    def check_extended_move(self, underlying_move_pct: float) -> RiskCheckResult:
        ok = abs(underlying_move_pct) <= self.limits.max_extended_move_pct
        return RiskCheckResult(
            ok,
            "EXTENDED_MOVE",
            f"Underlying move {underlying_move_pct:.1%} within limit"
            if ok
            else f"Underlying already moved {underlying_move_pct:.1%} — refusing to chase "
            f"(limit {self.limits.max_extended_move_pct:.1%})",
        )

    # --- 10. No new entries after cutoff -----------------------------------------------
    def check_cutoff_time(self, now: datetime) -> RiskCheckResult:
        ok = now.time() < self.limits.entry_cutoff_time
        return RiskCheckResult(
            ok,
            "ENTRY_CUTOFF",
            f"Before entry cutoff ({self.limits.entry_cutoff_time})"
            if ok
            else f"Past entry cutoff time ({self.limits.entry_cutoff_time}); no new entries allowed",
        )

    # --- 11. Never increase risk after a loss -----------------------------------------------
    def check_no_size_increase_after_loss(
        self,
        proposed_size_usd: float,
        last_position_size_usd: float | None,
        last_trade_was_loss: bool,
    ) -> RiskCheckResult:
        if not last_trade_was_loss or last_position_size_usd is None:
            return RiskCheckResult(True, "NO_SIZE_INCREASE_AFTER_LOSS", "No prior loss to constrain sizing")
        ok = proposed_size_usd <= last_position_size_usd
        return RiskCheckResult(
            ok,
            "NO_SIZE_INCREASE_AFTER_LOSS",
            f"Proposed size ${proposed_size_usd:.2f} does not exceed last (post-loss) size ${last_position_size_usd:.2f}"
            if ok
            else f"Refusing to size up after a loss (proposed ${proposed_size_usd:.2f} > "
            f"last ${last_position_size_usd:.2f})",
        )

    # --- Aggregate: gate for opening a brand-new trade -----------------------------------
    def evaluate_new_trade(
        self,
        *,
        candidate_symbol: str,
        candidate_option_id: str,
        proposed_size_usd: float,
        trades_opened_today: int,
        daily_pnl_usd: float,
        open_positions: Iterable[HeldPosition],
        last_exit_time: datetime | None,
        data_age_seconds: float,
        bid: float,
        ask: float,
        volume: int | None,
        open_interest: int | None,
        underlying_move_pct: float,
        now: datetime,
        last_position_size_usd: float | None,
        last_trade_was_loss: bool,
    ) -> RiskDecision:
        results = (
            self.check_trade_count(trades_opened_today),
            self.check_daily_loss(daily_pnl_usd),
            self.check_position_size(proposed_size_usd),
            self.check_duplicate_position(candidate_symbol, candidate_option_id, open_positions),
            self.check_cooldown(candidate_symbol, last_exit_time, now),
            self.check_data_freshness(data_age_seconds),
            self.check_spread(bid, ask),
            self.check_liquidity(volume, open_interest),
            self.check_extended_move(underlying_move_pct),
            self.check_cutoff_time(now),
            self.check_no_size_increase_after_loss(proposed_size_usd, last_position_size_usd, last_trade_was_loss),
        )
        return RiskDecision(allowed=all(r.passed for r in results), results=results)

    # --- Advisory-only checks for an exit on an already-open position --------------------
    def evaluate_exit_conditions(self, *, data_age_seconds: float, bid: float, ask: float) -> RiskDecision:
        """Exits are never blocked by risk controls (closing risk is always
        allowed) — but stale data means the *decision that led here* isn't
        trustworthy, so callers should treat `allowed=False` as "don't act
        on this cycle's evaluation, re-fetch and try again," not "the exit
        itself was blocked." Spread is reported as a warning only.
        """
        freshness = self.check_data_freshness(data_age_seconds)
        spread = self.check_spread(bid, ask)
        return RiskDecision(allowed=freshness.passed, results=(freshness, spread))
