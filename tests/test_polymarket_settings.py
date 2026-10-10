from __future__ import annotations

import pytest

from src.polymarket.settings import PolymarketConfigError, PolymarketSettings

_VALID_KEY = "0x" + "a" * 64
# base64 of 32 raw bytes -- a fake-but-correctly-shaped Ed25519 seed for
# the US venue, same convention as _VALID_KEY above (verified against the
# installed polymarket_us SDK's real auth.create_auth_headers(), which
# requires exactly 32 or 64 decoded bytes -- see settings.py).
_VALID_US_SECRET = "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="
_VALID_US_SECRET_64 = "YmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYg=="


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
    # $20.00 is the confidence-sizing hard ceiling (entry_confidence.py) --
    # not the everyday value; most trades size well below it.
    assert settings.max_bet_usd <= 20.0
    assert settings.max_daily_loss_usd <= 50.0
    assert settings.max_open_positions == 1


def test_entry_microstructure_defaults_tuned_for_the_btc_15m_market():
    """Adapted specifically for this market's low-priced, fast-moving
    binary contracts -- see risk.py's check_spread() docstring."""
    settings = PolymarketSettings.from_env(env={})
    assert settings.max_spread_pct == pytest.approx(0.05)
    assert settings.max_spread_usd == pytest.approx(0.03)
    assert settings.min_order_book_liquidity_usd == pytest.approx(10.0)


def test_entry_cutoff_setting_no_longer_exists():
    """FIX 8: there is no entry-cutoff restriction any more -- entry
    is allowed at any point while the market is genuinely open."""
    settings = PolymarketSettings.from_env(env={})
    assert not hasattr(settings, "entry_cutoff_seconds_before_close")


def test_take_profit_and_stop_loss_defaults_match_the_governing_spec():
    """Both are configurable settings, never hard-coded constants --
    see take_profit.py. Defaults: +10% take-profit, -20% stop-loss."""
    settings = PolymarketSettings.from_env(env={})
    assert settings.simple_take_profit_pct == pytest.approx(0.10)
    assert settings.simple_stop_loss_pct == pytest.approx(0.20)


def test_take_profit_and_stop_loss_are_configurable_via_env():
    settings = PolymarketSettings.from_env(env={
        "POLYMARKET_SIMPLE_TAKE_PROFIT_PCT": "0.25", "POLYMARKET_SIMPLE_STOP_LOSS_PCT": "0.15",
    })
    assert settings.simple_take_profit_pct == pytest.approx(0.25)
    assert settings.simple_stop_loss_pct == pytest.approx(0.15)


def test_min_entry_edge_and_persistence_defaults_match_the_governing_spec():
    """Change 2/Change 3 of this round: a configurable minimum
    probability edge (default 0.10) and a configurable consecutive-
    observation persistence requirement (default 3), both settings,
    never hard-coded constants -- see simple_entry_signal.py/engine.py."""
    settings = PolymarketSettings.from_env(env={})
    assert settings.simple_min_entry_edge == pytest.approx(0.10)
    assert settings.simple_entry_persistence_required == 3


def test_min_entry_edge_and_persistence_are_configurable_via_env():
    settings = PolymarketSettings.from_env(env={
        "POLYMARKET_SIMPLE_MIN_ENTRY_EDGE": "0.20", "POLYMARKET_SIMPLE_ENTRY_PERSISTENCE_REQUIRED": "5",
    })
    assert settings.simple_min_entry_edge == pytest.approx(0.20)
    assert settings.simple_entry_persistence_required == 5


def test_min_entry_edge_of_zero_is_allowed_disables_the_filter():
    settings = PolymarketSettings.from_env(env={"POLYMARKET_SIMPLE_MIN_ENTRY_EDGE": "0"})
    assert settings.simple_min_entry_edge == pytest.approx(0.0)


def test_min_entry_edge_of_one_or_more_is_rejected():
    with pytest.raises(PolymarketConfigError):
        PolymarketSettings.from_env(env={"POLYMARKET_SIMPLE_MIN_ENTRY_EDGE": "1"})


def test_negative_min_entry_edge_is_rejected():
    with pytest.raises(PolymarketConfigError):
        PolymarketSettings.from_env(env={"POLYMARKET_SIMPLE_MIN_ENTRY_EDGE": "-0.01"})


def test_persistence_required_of_one_is_allowed_disables_the_filter():
    settings = PolymarketSettings.from_env(env={"POLYMARKET_SIMPLE_ENTRY_PERSISTENCE_REQUIRED": "1"})
    assert settings.simple_entry_persistence_required == 1


def test_persistence_required_below_one_is_rejected():
    with pytest.raises(PolymarketConfigError):
        PolymarketSettings.from_env(env={"POLYMARKET_SIMPLE_ENTRY_PERSISTENCE_REQUIRED": "0"})


def test_non_positive_take_profit_pct_rejected():
    with pytest.raises(PolymarketConfigError, match="TAKE_PROFIT_PCT"):
        PolymarketSettings.from_env(env=_env(POLYMARKET_SIMPLE_TAKE_PROFIT_PCT="0"))


@pytest.mark.parametrize("value", ["0", "1", "-0.01", "1.5"])
def test_stop_loss_pct_outside_0_1_exclusive_rejected(value):
    with pytest.raises(PolymarketConfigError, match="STOP_LOSS_PCT"):
        PolymarketSettings.from_env(env=_env(POLYMARKET_SIMPLE_STOP_LOSS_PCT=value))


@pytest.mark.parametrize("value", ["0", "1", "-0.01"])
def test_non_positive_or_too_large_max_spread_usd_rejected(value):
    with pytest.raises(PolymarketConfigError, match="MAX_SPREAD_USD"):
        PolymarketSettings.from_env(env=_env(POLYMARKET_MAX_SPREAD_USD=value))


def test_max_spread_usd_is_configurable():
    settings = PolymarketSettings.from_env(env=_env(POLYMARKET_MAX_SPREAD_USD="0.10"))
    assert settings.max_spread_usd == pytest.approx(0.10)


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


# --- Fail-closed credential checks, US venue ----------------------------------
# Polymarket US has NO wallet/private-key concept at all (see settings.py's
# module docstring) -- these mirror the international venue's own checks
# above, one for one, so neither venue's credential story can silently drift
# weaker than the other's.

@pytest.mark.parametrize("partial", [
    {"POLYMARKET_US_KEY_ID": "k"},
    {"POLYMARKET_US_SECRET_KEY": _VALID_US_SECRET},
])
def test_partial_us_credential_pair_is_rejected(partial):
    with pytest.raises(PolymarketConfigError, match="all set or all unset"):
        PolymarketSettings.from_env(env=_env(POLYMARKET_VENUE="us", **partial))


def test_live_us_mode_without_credentials_is_rejected():
    with pytest.raises(PolymarketConfigError, match="POLYMARKET_US_KEY_ID"):
        PolymarketSettings.from_env(env=_env(POLYMARKET_VENUE="us", POLYMARKET_TRADING_MODE="live"))


def test_live_us_mode_with_credentials_is_accepted():
    settings = PolymarketSettings.from_env(env=_env(
        POLYMARKET_VENUE="us", POLYMARKET_TRADING_MODE="live",
        POLYMARKET_US_KEY_ID="key-1", POLYMARKET_US_SECRET_KEY=_VALID_US_SECRET,
    ))
    assert settings.is_live
    assert settings.us_key_id == "key-1"
    assert settings.us_secret_key == _VALID_US_SECRET


def test_paper_us_mode_does_not_require_credentials():
    settings = PolymarketSettings.from_env(env=_env(POLYMARKET_VENUE="us", POLYMARKET_TRADING_MODE="paper"))
    assert settings.us_key_id is None
    assert settings.us_secret_key is None  # no error -- paper mode never signs anything


def test_us_secret_key_must_be_valid_base64():
    with pytest.raises(PolymarketConfigError, match="base64"):
        PolymarketSettings.from_env(env=_env(
            POLYMARKET_VENUE="us", POLYMARKET_US_KEY_ID="k", POLYMARKET_US_SECRET_KEY="not-valid-base64!!!",
        ))


@pytest.mark.parametrize("bad_secret", [
    "c2hvcnQ=",  # valid base64, decodes to 5 bytes -- not 32 or 64
    "YQ==",      # valid base64, decodes to 1 byte
])
def test_us_secret_key_wrong_decoded_length_is_rejected(bad_secret):
    with pytest.raises(PolymarketConfigError, match="decodes to"):
        PolymarketSettings.from_env(env=_env(
            POLYMARKET_VENUE="us", POLYMARKET_US_KEY_ID="k", POLYMARKET_US_SECRET_KEY=bad_secret,
        ))


@pytest.mark.parametrize("good_secret", [_VALID_US_SECRET, _VALID_US_SECRET_64])
def test_us_secret_key_correct_decoded_length_is_accepted(good_secret):
    settings = PolymarketSettings.from_env(env=_env(
        POLYMARKET_VENUE="us", POLYMARKET_US_KEY_ID="k", POLYMARKET_US_SECRET_KEY=good_secret,
    ))
    assert settings.us_secret_key == good_secret


@pytest.mark.parametrize("key", ["POLYMARKET_US_API_BASE_URL", "POLYMARKET_US_GATEWAY_BASE_URL"])
def test_blank_us_base_url_is_rejected(key):
    """An env var explicitly set to blank (e.g. a leftover placeholder
    line in a .env) must fail closed, not silently become an empty
    string that reaches SDK client construction unchecked."""
    with pytest.raises(PolymarketConfigError, match="must not be blank"):
        PolymarketSettings.from_env(env=_env(POLYMARKET_VENUE="us", **{key: "   "}))


def test_unset_us_base_urls_use_the_real_production_defaults():
    """Unset (never blanked) is the normal, safe case -- distinct from
    the blank-string rejection above."""
    settings = PolymarketSettings.from_env(env=_env())
    assert settings.us_api_base_url == "https://api.polymarket.us"
    assert settings.us_gateway_base_url == "https://gateway.polymarket.us"


# --- Venue dispatch: no fallback to another venue or to wallet auth ----------

def test_get_polymarket_client_dispatches_us_venue_to_the_us_client():
    from src.polymarket.client import get_polymarket_client
    from src.polymarket.us_client import PolymarketUSClient

    settings = PolymarketSettings.from_env(env=_env(
        POLYMARKET_VENUE="us", POLYMARKET_US_KEY_ID="k", POLYMARKET_US_SECRET_KEY=_VALID_US_SECRET,
    ))
    client = get_polymarket_client(settings)
    assert isinstance(client, PolymarketUSClient)


def test_get_polymarket_client_defaults_to_the_international_client():
    from src.polymarket.client import PolymarketClient, get_polymarket_client

    settings = PolymarketSettings.from_env(env=_env())  # POLYMARKET_VENUE unset
    client = get_polymarket_client(settings)
    assert isinstance(client, PolymarketClient)


def test_us_venue_dispatch_is_unaffected_by_a_stray_international_private_key():
    """Proves there is no "fall back to whichever credentials happen to
    be set" behavior: venue=us dispatches to PolymarketUSClient even
    when an international-venue private_key is ALSO present (e.g. a
    leftover from switching venues in the same .env) -- venue selection
    is driven only by POLYMARKET_VENUE, never by credential presence."""
    from src.polymarket.client import get_polymarket_client
    from src.polymarket.us_client import PolymarketUSClient

    settings = PolymarketSettings.from_env(env=_env(
        POLYMARKET_VENUE="us", POLYMARKET_US_KEY_ID="k", POLYMARKET_US_SECRET_KEY=_VALID_US_SECRET,
        POLYMARKET_PRIVATE_KEY=_VALID_KEY,
    ))
    client = get_polymarket_client(settings)
    assert isinstance(client, PolymarketUSClient)


# --- Automatic profit-target exit settings ------------------------------------

def test_profit_target_pct_defaults_to_twenty_percent():
    settings = PolymarketSettings.from_env(env={})
    assert settings.profit_target_pct == pytest.approx(0.20)


def test_auto_exit_enabled_defaults_to_false():
    """A separate, exit-specific switch from live_auto_execute (the
    entry-only flag) -- off by default, same conservative posture."""
    settings = PolymarketSettings.from_env(env={})
    assert settings.auto_exit_enabled is False


def test_profit_target_pct_is_configurable():
    settings = PolymarketSettings.from_env(env=_env(POLYMARKET_PROFIT_TARGET_PCT="0.10"))
    assert settings.profit_target_pct == pytest.approx(0.10)


def test_auto_exit_enabled_is_configurable():
    settings = PolymarketSettings.from_env(env=_env(POLYMARKET_AUTO_EXIT_ENABLED="true"))
    assert settings.auto_exit_enabled is True


@pytest.mark.parametrize("value", ["0", "-0.1"])
def test_non_positive_profit_target_pct_rejected(value):
    with pytest.raises(PolymarketConfigError):
        PolymarketSettings.from_env(env=_env(POLYMARKET_PROFIT_TARGET_PCT=value))


# --- BTC feed staleness setting ------------------------------------------------

def test_btc_max_bar_age_seconds_defaults_to_five_minutes():
    settings = PolymarketSettings.from_env(env={})
    assert settings.btc_max_bar_age_seconds == pytest.approx(300.0)


def test_btc_max_bar_age_seconds_is_configurable():
    settings = PolymarketSettings.from_env(env=_env(POLYMARKET_BTC_MAX_BAR_AGE_SECONDS="120"))
    assert settings.btc_max_bar_age_seconds == pytest.approx(120.0)


@pytest.mark.parametrize("value", ["0", "-10"])
def test_non_positive_btc_max_bar_age_seconds_rejected(value):
    with pytest.raises(PolymarketConfigError):
        PolymarketSettings.from_env(env=_env(POLYMARKET_BTC_MAX_BAR_AGE_SECONDS=value))


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
