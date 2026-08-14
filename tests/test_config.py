from __future__ import annotations

import pytest

from src.config.settings import ConfigError, Settings


def test_trading_mode_defaults_to_paper():
    settings = Settings.from_env(env={})
    assert settings.trading_mode == "paper"
    assert settings.is_paper is True
    assert settings.is_live is False


def test_explicit_live_mode_parses_but_is_just_a_flag():
    settings = Settings.from_env(env={"TRADING_MODE": "live"})
    assert settings.trading_mode == "live"
    assert settings.is_live is True
    # Parsing "live" does not, by itself, do anything unsafe — see
    # test_execution_guard.py for proof the execution layer still refuses.


def test_invalid_trading_mode_raises():
    with pytest.raises(ConfigError):
        Settings.from_env(env={"TRADING_MODE": "yolo"})


def test_trading_mode_is_case_insensitive():
    settings = Settings.from_env(env={"TRADING_MODE": "PAPER"})
    assert settings.trading_mode == "paper"


def test_numeric_settings_parsed_from_env_strings():
    settings = Settings.from_env(env={"MAX_TRADES_PER_DAY": "7", "MAX_DAILY_LOSS_USD": "500.5"})
    assert settings.max_trades_per_day == 7
    assert settings.max_daily_loss_usd == 500.5


def test_invalid_numeric_setting_raises():
    with pytest.raises(ConfigError):
        Settings.from_env(env={"MAX_TRADES_PER_DAY": "not-a-number"})


def test_invalid_time_setting_raises():
    with pytest.raises(ConfigError):
        Settings.from_env(env={"ENTRY_CUTOFF_TIME": "not-a-time"})


def test_entry_cutoff_time_parses():
    settings = Settings.from_env(env={"ENTRY_CUTOFF_TIME": "14:45"})
    assert settings.entry_cutoff_time.hour == 14
    assert settings.entry_cutoff_time.minute == 45


def test_max_daily_loss_must_be_positive():
    with pytest.raises(ConfigError):
        Settings.from_env(env={"MAX_DAILY_LOSS_USD": "0"})


def test_live_trading_confirmed_defaults_false():
    settings = Settings.from_env(env={})
    assert settings.live_trading_confirmed is False


def test_live_trading_confirmed_parses_truthy_strings():
    settings = Settings.from_env(env={"LIVE_TRADING_CONFIRMED": "true"})
    assert settings.live_trading_confirmed is True
