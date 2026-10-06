from __future__ import annotations

import pytest

from src.polymarket.settings import PolymarketConfigError, PolymarketSettings


def _env(**overrides: str) -> dict[str, str]:
    base = {}
    base.update(overrides)
    return base


def test_defaults_are_paper_and_unconfirmed():
    settings = PolymarketSettings.from_env(env={})
    assert settings.is_paper
    assert not settings.is_live
    assert settings.live_trading_confirmed is False
    assert settings.live_auto_execute is False


def test_live_mode_requires_explicit_opt_in():
    settings = PolymarketSettings.from_env(env=_env(POLYMARKET_TRADING_MODE="live"))
    assert settings.is_live
    assert settings.live_trading_confirmed is False  # still false even though trading_mode flipped


def test_invalid_trading_mode_rejected():
    with pytest.raises(PolymarketConfigError):
        PolymarketSettings.from_env(env=_env(POLYMARKET_TRADING_MODE="yolo"))


@pytest.mark.parametrize("key,value", [
    ("POLYMARKET_MAX_BET_USD", "0"),
    ("POLYMARKET_MAX_DAILY_LOSS_USD", "-5"),
    ("POLYMARKET_MAX_OPEN_POSITIONS", "0"),
    ("POLYMARKET_STALE_DATA_MAX_SECONDS", "0"),
    ("POLYMARKET_MAX_SPREAD_PCT", "1.5"),
    ("POLYMARKET_MARKET_DURATION_MINUTES", "0"),
    ("POLYMARKET_POLL_INTERVAL_SECONDS", "-1"),
])
def test_unsafe_risk_values_rejected(key, value):
    with pytest.raises(PolymarketConfigError):
        PolymarketSettings.from_env(env=_env(**{key: value}))


def test_credentials_default_to_none():
    settings = PolymarketSettings.from_env(env={})
    assert settings.private_key is None
    assert settings.api_key is None
    assert settings.funder_address is None


def test_risk_defaults_are_conservative_placeholders():
    settings = PolymarketSettings.from_env(env={})
    assert settings.max_bet_usd <= 10.0
    assert settings.max_daily_loss_usd <= 50.0
    assert settings.max_open_positions == 1
