"""Tests for BacktestRiskAdapter — proves it genuinely reuses
src.risk.manager.RiskManager (Phase 3, section 12), including the
APPROVE/MODIFY/REJECT behavior the requirement calls for."""

from __future__ import annotations

from datetime import datetime, time, timezone

import pytest

from src.backtesting.risk_adapter import BacktestRiskAdapter
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits

NOW = datetime(2026, 1, 15, 11, 0, tzinfo=timezone.utc)


def _limits(**overrides) -> RiskLimits:
    defaults = dict(
        max_trades_per_day=4,
        max_daily_loss_usd=200.0,
        max_position_size_usd=1000.0,
        cooldown_minutes_after_exit=15,
        stale_data_max_seconds=90,
        max_spread_pct=0.10,
        min_option_volume=50,
        min_option_open_interest=100,
        max_extended_move_pct=0.25,
        entry_cutoff_time=time(15, 30),
    )
    defaults.update(overrides)
    return RiskLimits(**defaults)


def _adapter(**limit_overrides) -> BacktestRiskAdapter:
    return BacktestRiskAdapter(RiskManager(_limits(**limit_overrides)))


def _base_review_kwargs(**overrides) -> dict:
    defaults = dict(
        symbol="AAPL",
        proposed_quantity=5,
        reference_price=100.0,
        bid=99.5,
        ask=100.5,
        volume=1000,
        open_interest=None,
        trades_opened_today=0,
        daily_pnl_usd=0.0,
        open_symbols=[],
        last_exit_time=None,
        now=NOW,
        last_position_size_usd=None,
        last_trade_was_loss=False,
    )
    defaults.update(overrides)
    return defaults


def test_approves_a_reasonable_request():
    adapter = _adapter()
    review = adapter.review(**_base_review_kwargs())
    assert review.decision == "APPROVED"
    assert review.approved_quantity == 5


def test_modifies_when_position_size_exceeds_limit():
    adapter = _adapter(max_position_size_usd=250.0)
    review = adapter.review(**_base_review_kwargs(proposed_quantity=10, reference_price=100.0))  # 1000 > 250
    assert review.decision == "MODIFIED"
    assert review.approved_quantity == 2  # 250 // 100
    assert "Reduced" in review.reason


def test_rejects_when_no_shares_fit_the_limit():
    adapter = _adapter(max_position_size_usd=50.0)
    review = adapter.review(**_base_review_kwargs(proposed_quantity=1, reference_price=100.0))
    assert review.decision == "REJECTED"
    assert review.approved_quantity == 0


def test_rejects_on_duplicate_position():
    adapter = _adapter()
    review = adapter.review(**_base_review_kwargs(open_symbols=["AAPL"]))
    assert review.decision == "REJECTED"
    assert "AAPL" in review.reason


def test_rejects_on_daily_trade_count_limit():
    adapter = _adapter(max_trades_per_day=2)
    review = adapter.review(**_base_review_kwargs(trades_opened_today=2))
    assert review.decision == "REJECTED"


def test_rejects_on_daily_loss_limit_breached():
    adapter = _adapter(max_daily_loss_usd=100.0)
    review = adapter.review(**_base_review_kwargs(daily_pnl_usd=-150.0))
    assert review.decision == "REJECTED"


def test_rejects_after_cutoff_time():
    adapter = _adapter(entry_cutoff_time=time(10, 0))
    review = adapter.review(**_base_review_kwargs(now=NOW))  # NOW is 11:00 UTC, past 10:00 cutoff
    assert review.decision == "REJECTED"


def test_rejects_on_cooldown():
    adapter = _adapter(cooldown_minutes_after_exit=60)
    from datetime import timedelta

    review = adapter.review(**_base_review_kwargs(last_exit_time=NOW - timedelta(minutes=5)))
    assert review.decision == "REJECTED"


def test_rejects_on_no_size_increase_after_loss():
    adapter = _adapter()
    review = adapter.review(**_base_review_kwargs(proposed_quantity=20, reference_price=10.0, last_position_size_usd=50.0, last_trade_was_loss=True))
    # proposed_size_usd = 200 > last_position_size_usd = 50, after a loss -> rejected
    assert review.decision == "REJECTED"


def test_liquidity_check_is_opt_in_and_off_by_default():
    adapter = _adapter()  # enforce_liquidity_check defaults to False
    review = adapter.review(**_base_review_kwargs(volume=None, open_interest=None))
    assert review.decision == "APPROVED"  # would fail liquidity if enforced, since both are None


def test_liquidity_check_when_explicitly_enforced():
    adapter = BacktestRiskAdapter(RiskManager(_limits()), enforce_liquidity_check=True)
    review = adapter.review(**_base_review_kwargs(volume=None, open_interest=None))
    assert review.decision == "REJECTED"


def test_spread_check_is_enforced_by_default_when_bid_ask_given():
    adapter = _adapter(max_spread_pct=0.01)
    review = adapter.review(**_base_review_kwargs(bid=90.0, ask=110.0))  # ~20% spread
    assert review.decision == "REJECTED"


def test_zero_or_negative_proposed_quantity_is_rejected_immediately():
    adapter = _adapter()
    review = adapter.review(**_base_review_kwargs(proposed_quantity=0))
    assert review.decision == "REJECTED"
    assert review.checks == ()
