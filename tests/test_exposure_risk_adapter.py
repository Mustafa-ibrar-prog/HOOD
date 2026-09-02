"""Phase 11: ExposureRiskAdapter tests — proves the bug this adapter
fixes (src.backtesting.risk_adapter.BacktestRiskAdapter's
check_duplicate_position silently ratchets a continuously-rebalanced
exposure strategy's position DOWN forever, since every exposure INCREASE
after the first entry gets rejected as a "duplicate position" while every
DECREASE is never risk-blocked) and that ExposureRiskAdapter does not
have this problem, while still enforcing position-size and daily-loss
limits.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.backtesting.risk_adapter import BacktestRiskAdapter
from src.research.exposure_risk_adapter import ExposureRiskAdapter
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits

NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _limits(**overrides) -> RiskLimits:
    base = dict(max_trades_per_day=25, max_daily_loss_usd=1_000_000.0, max_position_size_usd=1_000_000.0, cooldown_minutes_after_exit=0,
                stale_data_max_seconds=10**9, max_spread_pct=1.0, min_option_volume=0, min_option_open_interest=0, max_extended_move_pct=100.0,
                entry_cutoff_time=datetime(2024, 1, 1, 23, 59).time())
    base.update(overrides)
    return RiskLimits(**base)


def test_the_bug_backtest_risk_adapter_blocks_increasing_an_existing_position():
    """Confirms the actual bug found via a smoke test before this fix
    existed: once a position is held, BacktestRiskAdapter rejects any
    further BUY (increase) for that same symbol as a "duplicate
    position" — fatal for a continuously-rebalanced exposure strategy."""
    adapter = BacktestRiskAdapter(RiskManager(_limits()))
    first = adapter.review(
        symbol="SPY", proposed_quantity=100, reference_price=400.0, bid=None, ask=None, volume=1_000_000, open_interest=None,
        trades_opened_today=0, daily_pnl_usd=0.0, open_symbols=[], last_exit_time=None, now=NOW, last_position_size_usd=None, last_trade_was_loss=False,
    )
    assert first.decision == "APPROVED"

    # now simulate we already hold SPY and want to INCREASE the position (a routine rebalance)
    second = adapter.review(
        symbol="SPY", proposed_quantity=20, reference_price=400.0, bid=None, ask=None, volume=1_000_000, open_interest=None,
        trades_opened_today=1, daily_pnl_usd=0.0, open_symbols=["SPY"], last_exit_time=None, now=NOW, last_position_size_usd=40_000.0, last_trade_was_loss=False,
    )
    assert second.decision == "REJECTED"
    assert "already holding a position" in second.reason.lower()


def test_exposure_risk_adapter_allows_increasing_an_existing_position():
    adapter = ExposureRiskAdapter(RiskManager(_limits()))
    first = adapter.review(symbol="SPY", proposed_quantity=100, reference_price=400.0, daily_pnl_usd=0.0)
    assert first.decision == "APPROVED"

    second = adapter.review(symbol="SPY", proposed_quantity=20, reference_price=400.0, daily_pnl_usd=0.0)
    assert second.decision == "APPROVED"


def test_exposure_risk_adapter_still_enforces_position_size_limit():
    adapter = ExposureRiskAdapter(RiskManager(_limits(max_position_size_usd=10_000.0)))
    review = adapter.review(symbol="SPY", proposed_quantity=100, reference_price=400.0, daily_pnl_usd=0.0)  # 100*400=40,000 > 10,000 limit
    assert review.decision == "MODIFIED"
    assert review.approved_quantity == 25  # 10,000 // 400


def test_exposure_risk_adapter_still_enforces_daily_loss_limit():
    adapter = ExposureRiskAdapter(RiskManager(_limits(max_daily_loss_usd=100.0)))
    review = adapter.review(symbol="SPY", proposed_quantity=10, reference_price=100.0, daily_pnl_usd=-500.0)
    assert review.decision == "REJECTED"


def test_exposure_risk_adapter_rejects_non_positive_quantity():
    adapter = ExposureRiskAdapter(RiskManager(_limits()))
    assert adapter.review(symbol="SPY", proposed_quantity=0, reference_price=100.0, daily_pnl_usd=0.0).decision == "REJECTED"


def test_exposure_risk_adapter_ignores_unrelated_kwargs_the_engine_passes():
    """The BacktestEngine always calls review() with the full kwarg set
    (bid, ask, volume, open_interest, trades_opened_today, open_symbols,
    last_exit_time, now, last_position_size_usd, last_trade_was_loss) —
    ExposureRiskAdapter must accept and ignore all of them without error."""
    adapter = ExposureRiskAdapter(RiskManager(_limits()))
    review = adapter.review(
        symbol="SPY", proposed_quantity=10, reference_price=100.0, daily_pnl_usd=0.0,
        bid=99.9, ask=100.1, volume=1000, open_interest=None, trades_opened_today=3,
        open_symbols=["SPY"], last_exit_time=None, now=NOW, last_position_size_usd=5000.0, last_trade_was_loss=True,
    )
    assert review.decision == "APPROVED"
