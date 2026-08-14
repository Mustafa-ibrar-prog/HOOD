"""Central configuration for the trading system.

Everything is sourced from environment variables (optionally loaded from a
.env file — see `_load_dotenv_into_environ`), with the safe defaults from
.env.example applied when a variable is unset. There is no other place in
this codebase that should read os.environ directly for trading behavior —
route new config through here so it stays auditable in one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Mapping

from src.config.constants import (
    DEFAULT_MARKET_TIMEZONE,
    TRADING_MODE_PAPER,
    VALID_TRADING_MODES,
)


class ConfigError(ValueError):
    """Raised when configuration is missing, malformed, or unsafe."""


def _load_dotenv_into_environ(path: Path) -> None:
    """Minimal .env loader (no external dependency).

    Only sets a variable if it is not already present in os.environ, so
    real environment variables (e.g. set by a process manager or CI) always
    take precedence over a .env file.
    """
    if not path.is_file():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _get_str(env: Mapping[str, str], key: str, default: str) -> str:
    return env.get(key, default).strip()


def _get_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key}={raw!r} is not a valid integer") from exc


def _get_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key}={raw!r} is not a valid number") from exc


def _get_time(env: Mapping[str, str], key: str, default: str) -> time:
    raw = _get_str(env, key, default)
    try:
        hour_str, minute_str = raw.split(":")
        return time(hour=int(hour_str), minute=int(minute_str))
    except (ValueError, IndexError) as exc:
        raise ConfigError(f"{key}={raw!r} must be HH:MM 24-hour time") from exc


def _get_optional_str(env: Mapping[str, str], key: str) -> str | None:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return None
    return raw.strip()


def _get_str_tuple(env: Mapping[str, str], key: str, default: str) -> tuple[str, ...]:
    raw = _get_str(env, key, default)
    return tuple(s.strip().upper() for s in raw.split(",") if s.strip())


@dataclass(frozen=True)
class Settings:
    """Immutable, validated configuration snapshot.

    Build one with Settings.from_env(); do not construct it ad hoc from
    scattered os.environ reads elsewhere in the codebase.
    """

    # --- Safety -----------------------------------------------------------
    trading_mode: str
    live_trading_confirmed: bool

    # --- Risk controls ------------------------------------------------------
    max_trades_per_day: int
    max_daily_loss_usd: float
    max_position_size_usd: float
    cooldown_minutes_after_exit: int
    stale_data_max_seconds: float
    max_spread_pct: float
    min_option_volume: int
    min_option_open_interest: int
    max_extended_move_pct: float
    entry_cutoff_time: time

    # --- Market hours -------------------------------------------------------
    market_open_time: time
    market_close_time: time
    market_timezone: str

    # --- Monitoring (documentation only; see monitor.py) ---------------------
    monitor_interval_minutes: int

    # --- Logging / state ------------------------------------------------------
    log_dir: str
    decision_log_file: str
    app_log_file: str
    risk_state_file: str
    paper_positions_file: str
    pending_orders_file: str
    live_bot_positions_file: str
    peak_prices_file: str

    # --- Brokerage account / scanning ------------------------------------------
    # account_number is intentionally never auto-selected from get_accounts by
    # code — per that tool's own guidance, an ambiguous choice must come from
    # the user. This is the one place it's configured, explicitly.
    account_number: str | None
    scan_universe: tuple[str, ...]
    max_new_entries_per_cycle: int

    # --- Defaults applied to positions synced from the real Robinhood account
    # (opened by the user outside this system, so there's no known thesis or
    # trader-set target/stop to sync) — see position_manager/hood_sync.py.
    synced_position_profit_target_pct: float
    synced_position_stop_loss_pct: float

    # --- Live execution (see src/execution/gateway.py). Unused while
    # TRADING_MODE=paper.
    pending_order_expiry_minutes: int
    # False (default): submit_order() always stops at a pending approval —
    # a human (or the agent, per the operational runbook) must take a
    # separate, explicit action to actually place it.
    # True: the execution layer places an order the instant it clears every
    # deterministic risk check, with no conversational approval step —
    # RiskManager + PositionEvaluator's rules are the only gate. Only takes
    # effect together with TRADING_MODE=live and LIVE_TRADING_CONFIRMED=true.
    live_auto_execute: bool

    # --- Dynamic/trailing exit (see position_manager/evaluator.py) ------------
    # Once an open position's unrealized gain reaches this fraction of the
    # distance from entry to its profit target, trailing protection "arms".
    # 0.5 with entry=$0.95/target=$1.15 arms at $1.05 (the documented
    # example).
    trailing_arm_fraction: float
    # Once armed, an EXIT triggers if price gives back this fraction of the
    # gain made from entry to the position's peak price so far — rather
    # than waiting for the original target or a momentum-evidence signal.
    trailing_giveback_fraction: float

    def __post_init__(self) -> None:
        if self.trading_mode not in VALID_TRADING_MODES:
            raise ConfigError(
                f"TRADING_MODE={self.trading_mode!r} is invalid; "
                f"must be one of {sorted(VALID_TRADING_MODES)}"
            )
        if self.max_trades_per_day < 0:
            raise ConfigError("MAX_TRADES_PER_DAY must be >= 0")
        if self.max_daily_loss_usd <= 0:
            raise ConfigError("MAX_DAILY_LOSS_USD must be > 0")
        if self.max_position_size_usd <= 0:
            raise ConfigError("MAX_POSITION_SIZE_USD must be > 0")
        if not 0 < self.max_spread_pct < 1:
            raise ConfigError("MAX_SPREAD_PCT must be between 0 and 1 (exclusive)")
        if not 0 < self.max_extended_move_pct < 1:
            raise ConfigError("MAX_EXTENDED_MOVE_PCT must be between 0 and 1 (exclusive)")
        if self.max_new_entries_per_cycle < 0:
            raise ConfigError("MAX_NEW_ENTRIES_PER_CYCLE must be >= 0")
        if self.synced_position_profit_target_pct <= 0:
            raise ConfigError("SYNCED_POSITION_PROFIT_TARGET_PCT must be > 0")
        if self.synced_position_stop_loss_pct <= 0:
            raise ConfigError("SYNCED_POSITION_STOP_LOSS_PCT must be > 0")
        if self.pending_order_expiry_minutes <= 0:
            raise ConfigError("PENDING_ORDER_EXPIRY_MINUTES must be > 0")
        if not 0 < self.trailing_arm_fraction < 1:
            raise ConfigError("TRAILING_ARM_FRACTION must be between 0 and 1 (exclusive)")
        if not 0 < self.trailing_giveback_fraction < 1:
            raise ConfigError("TRAILING_GIVEBACK_FRACTION must be between 0 and 1 (exclusive)")

    @property
    def is_paper(self) -> bool:
        return self.trading_mode == TRADING_MODE_PAPER

    @property
    def is_live(self) -> bool:
        return not self.is_paper

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, dotenv_path: Path | None = None) -> "Settings":
        """Build Settings from process environment (plus an optional .env file).

        Pass an explicit `env` mapping in tests instead of mutating
        os.environ, to keep tests hermetic.
        """
        if env is None:
            _load_dotenv_into_environ(dotenv_path or Path(".env"))
            env = os.environ

        return cls(
            trading_mode=_get_str(env, "TRADING_MODE", TRADING_MODE_PAPER).lower(),
            live_trading_confirmed=_get_bool(env, "LIVE_TRADING_CONFIRMED", False),
            max_trades_per_day=_get_int(env, "MAX_TRADES_PER_DAY", 4),
            max_daily_loss_usd=_get_float(env, "MAX_DAILY_LOSS_USD", 200.0),
            max_position_size_usd=_get_float(env, "MAX_POSITION_SIZE_USD", 250.0),
            cooldown_minutes_after_exit=_get_int(env, "COOLDOWN_MINUTES_AFTER_EXIT", 15),
            stale_data_max_seconds=_get_float(env, "STALE_DATA_MAX_SECONDS", 90.0),
            max_spread_pct=_get_float(env, "MAX_SPREAD_PCT", 0.10),
            min_option_volume=_get_int(env, "MIN_OPTION_VOLUME", 50),
            min_option_open_interest=_get_int(env, "MIN_OPTION_OPEN_INTEREST", 100),
            max_extended_move_pct=_get_float(env, "MAX_EXTENDED_MOVE_PCT", 0.25),
            entry_cutoff_time=_get_time(env, "ENTRY_CUTOFF_TIME", "15:30"),
            market_open_time=_get_time(env, "MARKET_OPEN_TIME", "09:30"),
            market_close_time=_get_time(env, "MARKET_CLOSE_TIME", "16:00"),
            market_timezone=_get_str(env, "MARKET_TIMEZONE", DEFAULT_MARKET_TIMEZONE),
            monitor_interval_minutes=_get_int(env, "MONITOR_INTERVAL_MINUTES", 5),
            log_dir=_get_str(env, "LOG_DIR", "logs"),
            decision_log_file=_get_str(env, "DECISION_LOG_FILE", "logs/decisions.jsonl"),
            app_log_file=_get_str(env, "APP_LOG_FILE", "logs/app.log"),
            risk_state_file=_get_str(env, "RISK_STATE_FILE", "logs/risk_state.json"),
            paper_positions_file=_get_str(env, "PAPER_POSITIONS_FILE", "logs/paper_positions.json"),
            pending_orders_file=_get_str(env, "PENDING_ORDERS_FILE", "logs/pending_orders.json"),
            live_bot_positions_file=_get_str(env, "LIVE_BOT_POSITIONS_FILE", "logs/live_bot_positions.json"),
            peak_prices_file=_get_str(env, "PEAK_PRICES_FILE", "logs/peak_prices.json"),
            account_number=_get_optional_str(env, "ROBINHOOD_ACCOUNT_NUMBER"),
            scan_universe=_get_str_tuple(env, "SCAN_UNIVERSE", "SPY,QQQ,AAPL,MSFT,NVDA"),
            max_new_entries_per_cycle=_get_int(env, "MAX_NEW_ENTRIES_PER_CYCLE", 1),
            synced_position_profit_target_pct=_get_float(env, "SYNCED_POSITION_PROFIT_TARGET_PCT", 0.50),
            synced_position_stop_loss_pct=_get_float(env, "SYNCED_POSITION_STOP_LOSS_PCT", 0.50),
            pending_order_expiry_minutes=_get_int(env, "PENDING_ORDER_EXPIRY_MINUTES", 15),
            live_auto_execute=_get_bool(env, "LIVE_AUTO_EXECUTE", False),
            trailing_arm_fraction=_get_float(env, "TRAILING_ARM_FRACTION", 0.5),
            trailing_giveback_fraction=_get_float(env, "TRAILING_GIVEBACK_FRACTION", 0.3),
        )


_settings_singleton: Settings | None = None


def get_settings() -> Settings:
    """Process-wide cached Settings instance, built from the environment."""
    global _settings_singleton
    if _settings_singleton is None:
        _settings_singleton = Settings.from_env()
    return _settings_singleton


def reload_settings() -> Settings:
    """Force a fresh Settings read from the current environment. Tests only."""
    global _settings_singleton
    _settings_singleton = Settings.from_env()
    return _settings_singleton
