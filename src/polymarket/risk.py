"""Deterministic, pre-trade risk checks for the Polymarket BTC system —
mirrors src/risk/manager.py's philosophy: every check is independent,
every one must pass, and the caller gets back every result (not just
the first failure) so a human reviewing a block sees the whole picture.

This module does NOT check TRADING_MODE/LIVE_TRADING_CONFIRMED — that
gate lives in gateway.py, right next to the only code that can place a
real order, exactly like src/execution/gateway.py keeps that check out
of RiskManager too. A RiskDecision here is "this proposed trade is
sized and timed sensibly," never "this system is authorized to go
live."
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from src.polymarket.models import BinaryMarket, OrderBookSnapshot
from src.polymarket.settings import PolymarketSettings
from src.polymarket.state import DailyPnlState


@dataclass(frozen=True)
class RiskCheckResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    results: tuple[RiskCheckResult, ...]

    @property
    def reasons_failed(self) -> tuple[str, ...]:
        return tuple(r.detail for r in self.results if not r.passed)


class PolymarketRiskManager:
    def __init__(self, settings: PolymarketSettings):
        self._settings = settings

    def check_bet_size(self, size_usd: float) -> RiskCheckResult:
        ok = 0 < size_usd <= self._settings.max_bet_usd
        return RiskCheckResult(
            "MAX_BET_SIZE", ok,
            f"Bet size ${size_usd:.2f} within limit ${self._settings.max_bet_usd:.2f}" if ok
            else f"Bet size ${size_usd:.2f} exceeds limit ${self._settings.max_bet_usd:.2f}",
        )

    def check_daily_loss(self, state: DailyPnlState) -> RiskCheckResult:
        ok = state.realized_pnl_usd > -self._settings.max_daily_loss_usd
        return RiskCheckResult(
            "MAX_DAILY_LOSS", ok,
            f"Daily P&L ${state.realized_pnl_usd:.2f} within loss limit -${self._settings.max_daily_loss_usd:.2f}" if ok
            else f"Daily loss limit reached: P&L ${state.realized_pnl_usd:.2f}, limit -${self._settings.max_daily_loss_usd:.2f}",
        )

    def check_open_positions(self, state: DailyPnlState) -> RiskCheckResult:
        ok = state.open_position_count < self._settings.max_open_positions
        return RiskCheckResult(
            "MAX_OPEN_POSITIONS", ok,
            f"{state.open_position_count} open, limit {self._settings.max_open_positions}" if ok
            else f"Already at max open positions ({self._settings.max_open_positions})",
        )

    def check_cooldown(self, state: DailyPnlState, now: datetime) -> RiskCheckResult:
        if state.last_exit_time is None:
            return RiskCheckResult("COOLDOWN", True, "No prior exit today")
        last_exit = datetime.fromisoformat(state.last_exit_time)
        if last_exit.tzinfo is None:
            last_exit = last_exit.replace(tzinfo=timezone.utc)
        elapsed = (now - last_exit).total_seconds()
        ok = elapsed >= self._settings.cooldown_seconds_after_exit
        return RiskCheckResult(
            "COOLDOWN", ok,
            f"{elapsed:.0f}s since last exit, cooldown satisfied" if ok
            else f"Only {elapsed:.0f}s since last exit, cooldown is {self._settings.cooldown_seconds_after_exit}s",
        )

    def check_data_freshness(self, market: BinaryMarket) -> RiskCheckResult:
        age = market.data_age_seconds
        ok = age <= self._settings.stale_data_max_seconds
        return RiskCheckResult(
            "DATA_FRESHNESS", ok,
            f"Market data {age:.1f}s old, within limit {self._settings.stale_data_max_seconds:.0f}s" if ok
            else f"Market data is stale ({age:.1f}s old, limit {self._settings.stale_data_max_seconds:.0f}s)",
        )

    def check_spread(self, market: BinaryMarket) -> RiskCheckResult:
        """Passes on EITHER a tight relative spread (max_spread_pct) OR a
        tight absolute spread (max_spread_usd) -- not just the relative
        one. A binary contract priced near 0 or 1 has a tiny mid, so
        (ask-bid)/mid can read as a huge percentage even when ask-bid
        itself is a perfectly tradeable couple of cents; relative
        percentage alone was rejecting those trades for being "too wide"
        when they were actually fine. This can only ever ADD a passing
        path for a genuinely tight absolute spread -- it can never let
        through a trade that's wide by both measures, because relative
        spread is mathematically >= absolute spread for any mid in
        (0, 1] (dividing by something <= 1 never shrinks it), so
        max_spread_usd is kept small and tight, not a general escape
        hatch. Still fails closed on a crossed book or a missing
        bid/ask -- those are never tradeable regardless of either
        threshold."""
        bid, ask = market.yes_bid, market.yes_ask
        if bid is None or ask is None:
            return RiskCheckResult("MAX_SPREAD", False, "No two-sided quote available to measure spread")
        if ask < bid:
            return RiskCheckResult(
                "MAX_SPREAD", False, f"Crossed book: ask ${ask:.4f} < bid ${bid:.4f} -- not tradeable",
            )
        absolute_spread = round(ask - bid, 4)
        relative_spread = market.yes_spread_pct  # safe: bid/ask presence and ask>=bid already confirmed above
        relative_ok = relative_spread is not None and relative_spread <= self._settings.max_spread_pct
        absolute_ok = absolute_spread <= self._settings.max_spread_usd
        ok = relative_ok or absolute_ok
        relative_str = f"{relative_spread:.1%}" if relative_spread is not None else "n/a"
        return RiskCheckResult(
            "MAX_SPREAD", ok,
            f"Spread {relative_str} (${absolute_spread:.4f}) within relative limit {self._settings.max_spread_pct:.1%} "
            f"or absolute limit ${self._settings.max_spread_usd:.4f}" if ok
            else f"Spread too wide: {relative_str} (${absolute_spread:.4f}), exceeds both the relative limit "
                 f"{self._settings.max_spread_pct:.1%} and the absolute limit ${self._settings.max_spread_usd:.4f}",
        )

    def check_entry_cutoff(self, market: BinaryMarket) -> RiskCheckResult:
        remaining = market.seconds_to_close
        ok = remaining > self._settings.entry_cutoff_seconds_before_close
        return RiskCheckResult(
            "ENTRY_CUTOFF", ok,
            f"{remaining:.0f}s to close, before cutoff" if ok
            else f"Only {remaining:.0f}s to close — past entry cutoff ({self._settings.entry_cutoff_seconds_before_close}s); no new entries this close to resolution",
        )

    def check_order_book_liquidity(
        self, order_book: OrderBookSnapshot, *, side: str, max_price: float,
    ) -> RiskCheckResult:
        """Task 6: refuse entry when the specific side/outcome actually
        being bought can't absorb the order near our own ceiling price.
        `order_book` MUST be the order book of the exact token we're
        about to buy (never an aggregate, never the other outcome, never
        `1 - other_side`) — see OrderBookSnapshot's module docstring and
        executable_liquidity_usd(). An empty, one-sided, or malformed
        (e.g. a level with size 0, or no levels at all) book naturally
        yields 0.0 liquidity here and correctly fails this check, rather
        than raising or silently passing."""
        liquidity = order_book.executable_liquidity_usd(side=side, max_price=max_price)
        threshold = self._settings.min_order_book_liquidity_usd
        ok = liquidity >= threshold
        return RiskCheckResult(
            "ORDER_BOOK_LIQUIDITY", ok,
            f"${liquidity:.2f} executable liquidity at/below ${max_price:.4f} meets ${threshold:.2f} minimum" if ok
            else f"Only ${liquidity:.2f} executable liquidity at/below ${max_price:.4f} — below ${threshold:.2f} minimum",
        )

    def evaluate_new_trade(
        self, *, size_usd: float, market: BinaryMarket, state: DailyPnlState,
        order_book: OrderBookSnapshot, side: str, max_price: float, now: datetime | None = None,
    ) -> RiskDecision:
        now = now or datetime.now(timezone.utc)
        results = (
            self.check_bet_size(size_usd),
            self.check_daily_loss(state),
            self.check_open_positions(state),
            self.check_cooldown(state, now),
            self.check_data_freshness(market),
            self.check_spread(market),
            self.check_entry_cutoff(market),
            self.check_order_book_liquidity(order_book, side=side, max_price=max_price),
        )
        return RiskDecision(allowed=all(r.passed for r in results), results=results)
