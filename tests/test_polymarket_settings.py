from __future__ import annotations

import pytest

from src.polymarket.settings import PolymarketConfigError, PolymarketSettings

_VALID_KEY = "0x" + "a" * 64


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
    settings = PolymarketSettings.from_env(env=_env(POLYMARKET_TRADING_MODE="live", POLYMARKET_PRIVATE_KEY=_VALID_KEY))
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
    ("POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD", "-1"),
    ("POLYMARKET_MAX_PRICE_SLIPPAGE_PCT", "1.5"),
    ("POLYMARKET_DEFAULT_ORDER_TYPE", "GTC"),
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


# --- Fail-closed credential checks (Task 7) -----------------------------------

def test_live_mode_without_private_key_is_rejected():
    with pytest.raises(PolymarketConfigError, match="PRIVATE_KEY"):
        PolymarketSettings.from_env(env=_env(POLYMARKET_TRADING_MODE="live"))


def test_live_mode_with_private_key_is_accepted():
    settings = PolymarketSettings.from_env(env=_env(POLYMARKET_TRADING_MODE="live", POLYMARKET_PRIVATE_KEY=_VALID_KEY))
    assert settings.is_live
    assert settings.private_key == _VALID_KEY


def test_private_key_must_be_0x_prefixed():
    with pytest.raises(PolymarketConfigError, match="0x"):
        PolymarketSettings.from_env(env=_env(POLYMARKET_PRIVATE_KEY="deadbeef"))


def test_paper_mode_does_not_require_a_private_key():
    settings = PolymarketSettings.from_env(env=_env(POLYMARKET_TRADING_MODE="paper"))
    assert settings.private_key is None  # no error — paper mode never signs anything


@pytest.mark.parametrize("partial", [
    {"POLYMARKET_API_KEY": "k"},
    {"POLYMARKET_API_KEY": "k", "POLYMARKET_API_SECRET": "s"},
    {"POLYMARKET_API_SECRET": "s", "POLYMARKET_API_PASSPHRASE": "p"},
])
def test_partial_api_credential_triple_is_rejected(partial):
    with pytest.raises(PolymarketConfigError, match="all set or all unset"):
        PolymarketSettings.from_env(env=_env(**partial))


def test_full_api_credential_triple_is_accepted():
    settings = PolymarketSettings.from_env(env=_env(
        POLYMARKET_API_KEY="k", POLYMARKET_API_SECRET="s", POLYMARKET_API_PASSPHRASE="p",
    ))
    assert settings.api_key == "k"
    assert settings.api_secret == "s"
    assert settings.api_passphrase == "p"


def test_api_triple_alone_does_not_satisfy_live_mode_private_key_requirement():
    """Verified against SecureClient.create()'s real signature (see
    client.py's module docstring): private_key is required even when
    pre-derived credentials are also supplied — the API triple can
    never substitute for it."""
    with pytest.raises(PolymarketConfigError, match="PRIVATE_KEY"):
        PolymarketSettings.from_env(env=_env(
            POLYMARKET_TRADING_MODE="live",
            POLYMARKET_API_KEY="k", POLYMARKET_API_SECRET="s", POLYMARKET_API_PASSPHRASE="p",
        ))
