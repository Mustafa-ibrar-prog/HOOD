from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.risk.manager import RiskManager
from tests.conftest import make_position


@pytest.fixture
def manager(risk_limits) -> RiskManager:
    return RiskManager(risk_limits)


def _base_new_trade_kwargs(**overrides):
    now = datetime(2026, 8, 14, 11, 0, tzinfo=timezone.utc)
    defaults = dict(
        candidate_symbol="AAPL",
        candidate_option_id="opt-new",
        proposed_size_usd=100.0,
        trades_opened_today=0,
        daily_pnl_usd=0.0,
        open_positions=[],
        last_exit_time=None,
        data_age_seconds=10.0,
        bid=1.00,
        ask=1.05,
        volume=500,
        open_interest=1000,
        underlying_move_pct=0.02,
        now=now,
        last_position_size_usd=None,
        last_trade_was_loss=False,
    )
    defaults.update(overrides)
    return defaults


def test_all_checks_pass_allows_trade(manager):
    decision = manager.evaluate_new_trade(**_base_new_trade_kwargs())
    assert decision.allowed is True
    assert decision.blocking_reasons == ()


def test_max_trades_per_day_blocks_after_limit(manager):
    decision = manager.evaluate_new_trade(**_base_new_trade_kwargs(trades_opened_today=4))
    assert decision.allowed is False
    assert any("MAX_TRADES_PER_DAY" in r.code for r in decision.results if not r.passed)


def test_max_trades_per_day_allows_below_limit(manager):
    decision = manager.evaluate_new_trade(**_base_new_trade_kwargs(trades_opened_today=3))
    assert decision.allowed is True


def test_daily_loss_limit_blocks(manager):
    decision = manager.evaluate_new_trade(**_base_new_trade_kwargs(daily_pnl_usd=-250.0))
    assert decision.allowed is False
    assert "MAX_DAILY_LOSS" in decision.blocking_reasons[0] or any(
        r.code == "MAX_DAILY_LOSS" for r in decision.results if not r.passed
    )


def test_position_size_limit_blocks(manager):
    decision = manager.evaluate_new_trade(**_base_new_trade_kwargs(proposed_size_usd=1000.0))
    assert decision.allowed is False
    assert any(r.code == "POSITION_SIZE_LIMIT" for r in decision.results if not r.passed)


def test_duplicate_position_blocks(manager):
    existing = make_position(symbol="AAPL")
    decision = manager.evaluate_new_trade(
        **_base_new_trade_kwargs(candidate_symbol="AAPL", open_positions=[existing])
    )
    assert decision.allowed is False
    assert any(r.code == "DUPLICATE_POSITION" for r in decision.results if not r.passed)


def test_no_duplicate_when_different_symbol(manager):
    existing = make_position(symbol="MSFT")
    decision = manager.evaluate_new_trade(
        **_base_new_trade_kwargs(candidate_symbol="AAPL", candidate_option_id="opt-new", open_positions=[existing])
    )
    assert decision.allowed is True


def test_cooldown_blocks_immediately_after_exit(manager):
    now = datetime(2026, 8, 14, 11, 0, tzinfo=timezone.utc)
    last_exit = now - timedelta(minutes=5)  # cooldown limit is 15 min
    decision = manager.evaluate_new_trade(**_base_new_trade_kwargs(now=now, last_exit_time=last_exit))
    assert decision.allowed is False
    assert any(r.code == "COOLDOWN" for r in decision.results if not r.passed)


def test_cooldown_allows_after_window_elapses(manager):
    now = datetime(2026, 8, 14, 11, 0, tzinfo=timezone.utc)
    last_exit = now - timedelta(minutes=20)  # past the 15 min cooldown
    decision = manager.evaluate_new_trade(**_base_new_trade_kwargs(now=now, last_exit_time=last_exit))
    assert decision.allowed is True


def test_stale_data_blocks(manager):
    decision = manager.evaluate_new_trade(**_base_new_trade_kwargs(data_age_seconds=500.0))
    assert decision.allowed is False
    assert any(r.code == "STALE_DATA" for r in decision.results if not r.passed)


def test_wide_spread_blocks(manager):
    # mid=1.0, spread = (1.30-0.70)/1.0 = 60% >> 10% limit
    decision = manager.evaluate_new_trade(**_base_new_trade_kwargs(bid=0.70, ask=1.30))
    assert decision.allowed is False
    assert any(r.code == "WIDE_SPREAD" for r in decision.results if not r.passed)


def test_crossed_quote_blocks_as_wide_spread(manager):
    decision = manager.evaluate_new_trade(**_base_new_trade_kwargs(bid=1.10, ask=1.00))
    assert decision.allowed is False


def test_illiquid_blocks_on_low_volume(manager):
    decision = manager.evaluate_new_trade(**_base_new_trade_kwargs(volume=5, open_interest=1000))
    assert decision.allowed is False
    assert any(r.code == "LIQUIDITY" for r in decision.results if not r.passed)


def test_illiquid_blocks_on_low_open_interest(manager):
    decision = manager.evaluate_new_trade(**_base_new_trade_kwargs(volume=500, open_interest=10))
    assert decision.allowed is False


def test_extended_move_blocks_chasing(manager):
    decision = manager.evaluate_new_trade(**_base_new_trade_kwargs(underlying_move_pct=0.40))
    assert decision.allowed is False
    assert any(r.code == "EXTENDED_MOVE" for r in decision.results if not r.passed)


def test_cutoff_time_blocks_late_entries(manager):
    late = datetime(2026, 8, 14, 15, 45, tzinfo=timezone.utc)  # cutoff is 15:30
    decision = manager.evaluate_new_trade(**_base_new_trade_kwargs(now=late))
    assert decision.allowed is False
    assert any(r.code == "ENTRY_CUTOFF" for r in decision.results if not r.passed)


def test_cutoff_time_allows_before_cutoff(manager):
    early = datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)
    decision = manager.evaluate_new_trade(**_base_new_trade_kwargs(now=early))
    assert decision.allowed is True


def test_never_increase_size_after_loss_blocks_larger_size(manager):
    decision = manager.evaluate_new_trade(
        **_base_new_trade_kwargs(proposed_size_usd=150.0, last_position_size_usd=100.0, last_trade_was_loss=True)
    )
    assert decision.allowed is False
    assert any(r.code == "NO_SIZE_INCREASE_AFTER_LOSS" for r in decision.results if not r.passed)


def test_size_after_loss_allows_equal_or_smaller_size(manager):
    decision = manager.evaluate_new_trade(
        **_base_new_trade_kwargs(proposed_size_usd=100.0, last_position_size_usd=100.0, last_trade_was_loss=True)
    )
    assert decision.allowed is True


def test_size_increase_allowed_when_last_trade_was_a_win(manager):
    decision = manager.evaluate_new_trade(
        **_base_new_trade_kwargs(proposed_size_usd=200.0, last_position_size_usd=100.0, last_trade_was_loss=False)
    )
    assert decision.allowed is True


def test_evaluate_exit_conditions_never_blocks_on_spread_alone(manager):
    # Exiting is a risk-reducing action; a wide spread is a warning, not a
    # block, and should not appear in blocking_reasons.
    decision = manager.evaluate_exit_conditions(data_age_seconds=10.0, bid=0.70, ask=1.30)
    assert decision.allowed is True


def test_evaluate_exit_conditions_flags_stale_data_as_unreliable(manager):
    decision = manager.evaluate_exit_conditions(data_age_seconds=500.0, bid=1.0, ask=1.05)
    assert decision.allowed is False
    assert any(r.code == "STALE_DATA" for r in decision.results if not r.passed)
