"""Regression test for the Phase 1 audit finding, fixed in Phase 2:
MomentumBreakoutStrategy._select_expiration() previously always called the
real system clock directly, instead of accepting an injectable `now` the
way every other time-dependent function in this codebase does. This file
is additive — tests/test_momentum_breakout.py itself is untouched."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.market.data_provider import MarketDataProvider
from src.strategy.momentum_breakout import MomentumBreakoutConfig, MomentumBreakoutStrategy


class _ExpirationsOnlyMarket(MarketDataProvider):
    """Minimal fake MarketDataProvider — only get_option_expirations is
    exercised by _select_expiration(), the method under test here."""

    def __init__(self, expirations: list[date]):
        self._expirations = expirations

    def get_market_snapshot(self, *args, **kwargs):
        raise NotImplementedError

    def get_underlying_snapshot(self, *args, **kwargs):
        raise NotImplementedError

    def get_option_expirations(self, symbol: str) -> list[date]:
        return self._expirations

    def get_option_chain_candidates(self, *args, **kwargs):
        raise NotImplementedError


def test_select_expiration_uses_injected_now_not_real_clock():
    # An expiration 14 days out from an injected "now" far from the real
    # wall clock — this must still land inside the [7, 45] day window
    # relative to the INJECTED now, not the real one.
    injected_now = datetime(2020, 1, 1, tzinfo=timezone.utc)  # deliberately far from real "today"
    expiration = injected_now.date() + timedelta(days=14)
    market = _ExpirationsOnlyMarket([expiration])

    strategy = MomentumBreakoutStrategy(
        MomentumBreakoutConfig(min_days_to_expiration=7, max_days_to_expiration=45),
        now=injected_now,
    )
    selected = strategy._select_expiration(market, "AAPL")
    assert selected == expiration


def test_select_expiration_falls_back_to_real_clock_when_now_not_given():
    # Backward compatibility: omitting `now` must behave exactly as before
    # this fix — relative to the real wall clock.
    real_today = datetime.now(timezone.utc).date()
    expiration = real_today + timedelta(days=14)
    market = _ExpirationsOnlyMarket([expiration])

    strategy = MomentumBreakoutStrategy(MomentumBreakoutConfig(min_days_to_expiration=7, max_days_to_expiration=45))
    selected = strategy._select_expiration(market, "AAPL")
    assert selected == expiration


def test_select_expiration_excludes_dates_outside_window_relative_to_injected_now():
    injected_now = datetime(2020, 1, 1, tzinfo=timezone.utc)
    too_soon = injected_now.date() + timedelta(days=2)  # below min_days_to_expiration=7
    too_far = injected_now.date() + timedelta(days=90)  # above max_days_to_expiration=45
    market = _ExpirationsOnlyMarket([too_soon, too_far])

    strategy = MomentumBreakoutStrategy(
        MomentumBreakoutConfig(min_days_to_expiration=7, max_days_to_expiration=45),
        now=injected_now,
    )
    assert strategy._select_expiration(market, "AAPL") is None
