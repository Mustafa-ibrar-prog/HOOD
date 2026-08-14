from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.config.settings import Settings
from src.market.models import EquityQuote, MarketSnapshot, OptionQuote, PriceBar
from src.position_manager.models import OpenPosition
from src.risk.models import RiskLimits
from src.strategy.decision import TradeThesis


@pytest.fixture
def paper_settings(tmp_path) -> Settings:
    env = {
        "TRADING_MODE": "paper",
        "MAX_TRADES_PER_DAY": "4",
        "MAX_DAILY_LOSS_USD": "200",
        "MAX_POSITION_SIZE_USD": "250",
        "COOLDOWN_MINUTES_AFTER_EXIT": "15",
        "STALE_DATA_MAX_SECONDS": "90",
        "MAX_SPREAD_PCT": "0.10",
        "MIN_OPTION_VOLUME": "50",
        "MIN_OPTION_OPEN_INTEREST": "100",
        "MAX_EXTENDED_MOVE_PCT": "0.25",
        "ENTRY_CUTOFF_TIME": "15:30",
        "MARKET_OPEN_TIME": "09:30",
        "MARKET_CLOSE_TIME": "16:00",
        "LOG_DIR": str(tmp_path / "logs"),
        "DECISION_LOG_FILE": str(tmp_path / "logs" / "decisions.jsonl"),
        "APP_LOG_FILE": str(tmp_path / "logs" / "app.log"),
        "RISK_STATE_FILE": str(tmp_path / "logs" / "risk_state.json"),
        "PAPER_POSITIONS_FILE": str(tmp_path / "logs" / "paper_positions.json"),
        "ROBINHOOD_ACCOUNT_NUMBER": "987155785",
        "SCAN_UNIVERSE": "SPY,AAPL",
        "MAX_NEW_ENTRIES_PER_CYCLE": "1",
        "SYNCED_POSITION_PROFIT_TARGET_PCT": "0.50",
        "SYNCED_POSITION_STOP_LOSS_PCT": "0.50",
    }
    return Settings.from_env(env=env)


@pytest.fixture
def live_settings(tmp_path) -> Settings:
    env = {
        "TRADING_MODE": "live",
        "LOG_DIR": str(tmp_path / "logs"),
        "DECISION_LOG_FILE": str(tmp_path / "logs" / "decisions.jsonl"),
        "APP_LOG_FILE": str(tmp_path / "logs" / "app.log"),
        "RISK_STATE_FILE": str(tmp_path / "logs" / "risk_state.json"),
        "PAPER_POSITIONS_FILE": str(tmp_path / "logs" / "paper_positions.json"),
    }
    return Settings.from_env(env=env)


@pytest.fixture
def live_confirmed_settings(tmp_path) -> Settings:
    """Both independent live-trading switches on — the only Settings
    LiveExecutionGateway will actually construct against."""
    env = {
        "TRADING_MODE": "live",
        "LIVE_TRADING_CONFIRMED": "true",
        "LOG_DIR": str(tmp_path / "logs"),
        "DECISION_LOG_FILE": str(tmp_path / "logs" / "decisions.jsonl"),
        "APP_LOG_FILE": str(tmp_path / "logs" / "app.log"),
        "RISK_STATE_FILE": str(tmp_path / "logs" / "risk_state.json"),
        "PAPER_POSITIONS_FILE": str(tmp_path / "logs" / "paper_positions.json"),
        "PENDING_ORDERS_FILE": str(tmp_path / "logs" / "pending_orders.json"),
        "LIVE_BOT_POSITIONS_FILE": str(tmp_path / "logs" / "live_bot_positions.json"),
        "PENDING_ORDER_EXPIRY_MINUTES": "15",
    }
    return Settings.from_env(env=env)


@pytest.fixture
def risk_limits(paper_settings) -> RiskLimits:
    return RiskLimits.from_settings(paper_settings)


def make_thesis(direction: str = "bullish", **overrides) -> TradeThesis:
    defaults = dict(
        setup_name="test-breakout",
        direction=direction,
        catalyst="broke above 20-bar resistance on volume",
        invalidation="closes back below breakout level",
        profit_target_usd=20.0,
        stop_loss_usd=15.0,
    )
    defaults.update(overrides)
    return TradeThesis(**defaults)


def make_position(**overrides) -> OpenPosition:
    defaults = dict(
        symbol="AAPL",
        option_id="11111111-1111-1111-1111-111111111111",
        option_description="AAPL 2026-09-18 C 230",
        side="long_call",
        quantity=1,
        entry_price=0.95,
        entry_time=datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc),
        thesis=make_thesis(),
        profit_target_usd=20.0,
        stop_loss_usd=15.0,
        expiration=date(2026, 9, 18),
    )
    defaults.update(overrides)
    return OpenPosition(**defaults)


def make_bars(closes: list[float], volumes: list[int] | None = None, start: datetime | None = None) -> list[PriceBar]:
    start = start or datetime(2026, 8, 14, 9, 30, tzinfo=timezone.utc)
    volumes = volumes or [1000] * len(closes)
    bars = []
    prev_close = closes[0]
    for i, (close, vol) in enumerate(zip(closes, volumes)):
        # high/low anchored to this bar's own close (not blended with the
        # previous bar) so a test's intended close-price pattern (e.g. an
        # up-down-up zigzag) is reflected directly in the high series that
        # structure-detection functions actually read.
        bars.append(
            PriceBar(
                start_time=start + timedelta(minutes=i),
                open=prev_close,
                high=close + 0.01,
                low=close - 0.01,
                close=close,
                volume=vol,
            )
        )
        prev_close = close
    return bars


def make_market_snapshot(**overrides) -> MarketSnapshot:
    now = datetime.now(timezone.utc)
    defaults = dict(
        option=OptionQuote(
            instrument_id="11111111-1111-1111-1111-111111111111",
            bid_price=1.03,
            ask_price=1.07,
            last_trade_price=1.05,
            previous_close=0.90,
            volume=500,
            open_interest=1000,
            as_of=now,
        ),
        underlying=EquityQuote(symbol="AAPL", last_trade_price=231.0, previous_close=228.0, as_of=now),
        option_bars=tuple(make_bars([0.95, 0.98, 1.00, 1.03, 1.05])),
        underlying_bars=tuple(make_bars([228.0, 229.0, 229.5, 230.5, 231.0])),
        rsi=60.0,
        rsi_prev=55.0,
        macd_histogram=0.05,
        macd_histogram_prev=0.03,
        ema_fast=230.5,
        ema_slow=229.0,
        vwap=229.8,
        volume_ratio=1.3,
        fetched_at=now,
    )
    defaults.update(overrides)
    return MarketSnapshot(**defaults)
