"""Configuration for the Polymarket BTC 15-minute system, sourced entirely
from environment variables (optionally via a .env file, same minimal
loader convention as src/config/settings.py) — no other module here
should read os.environ directly.

Credentials: Polymarket's CLOB requires an L2 API key (key/secret/
passphrase) derived from a signed message by a Polygon wallet. Two ways
to provide that here:
  - POLYMARKET_API_KEY / POLYMARKET_API_SECRET / POLYMARKET_API_PASSPHRASE
    plus POLYMARKET_FUNDER_ADDRESS, if you've already derived L2 creds
    (py-clob-client's create_or_derive_api_creds, run once, out of band).
  - POLYMARKET_PRIVATE_KEY, if you want this process to derive L2 creds
    itself on startup via py-clob-client. Never paste a real private key
    into a chat session or commit it anywhere — set it as a real
    environment variable or in a local, gitignored .env file only.
Both are optional at the Settings level (None if unset) so from_env()
never raises just because credentials aren't configured yet; client.py
is where a missing credential actually blocks a live call.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

TRADING_MODE_PAPER = "paper"
TRADING_MODE_LIVE = "live"
VALID_TRADING_MODES = frozenset({TRADING_MODE_PAPER, TRADING_MODE_LIVE})


class PolymarketConfigError(ValueError):
    """Raised when Polymarket configuration is missing, malformed, or unsafe."""


def _load_dotenv_into_environ(path: Path) -> None:
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


def _get_optional_str(env: Mapping[str, str], key: str) -> str | None:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return None
    return raw.strip()


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
        raise PolymarketConfigError(f"{key}={raw!r} is not a valid integer") from exc


def _get_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise PolymarketConfigError(f"{key}={raw!r} is not a valid number") from exc


@dataclass(frozen=True)
class PolymarketSettings:
    """Immutable, validated configuration snapshot. Build one with
    PolymarketSettings.from_env(); do not construct it ad hoc."""

    # --- Safety: the same two-independent-switches pattern as
    # src/config/settings.py's TRADING_MODE/LIVE_TRADING_CONFIRMED ---------
    trading_mode: str
    live_trading_confirmed: bool
    # Mirrors settings.live_auto_execute: False (default) means every
    # live order stops at pending-approval; a separate, explicit call to
    # confirm_and_place() is required. True places it immediately once
    # the risk gate clears, with no approval step. gateway.py enforces
    # this, not callers.
    live_auto_execute: bool

    # --- Credentials (see module docstring) ------------------------------
    private_key: str | None
    api_key: str | None
    api_secret: str | None
    api_passphrase: str | None
    funder_address: str | None
    # https://clob.polymarket.com by default; override only for a
    # documented alternate deployment (e.g. a testnet), never to point at
    # something that merely claims to be Polymarket.
    clob_api_url: str
    gamma_api_url: str
    chain_id: int

    # --- Risk controls — deliberately tiny defaults. Read every one of
    # these yourself in .env.polymarket.example before going live; they
    # are placeholders, not a recommendation. ------------------------------
    max_bet_usd: float
    max_daily_loss_usd: float
    max_open_positions: int
    cooldown_seconds_after_exit: int
    stale_data_max_seconds: float
    max_spread_pct: float
    min_order_book_liquidity_usd: float

    # --- Market selection --------------------------------------------------
    # The underlying this system trades. Only "bitcoin" is implemented
    # (see strategy.py's module docstring on why this stays single-asset).
    asset: str
    # Target market duration in minutes. find_active_btc_market() uses
    # this to pick among whatever short-duration crypto markets are
    # actually live — see the module __init__ warning: this has not been
    # verified against the real API from this environment.
    market_duration_minutes: int
    # How close to a market's close time this system still allows a NEW
    # entry — mirrors entry_cutoff_time's spirit (don't open a fresh
    # position seconds before resolution, where there's no time left to
    # be right).
    entry_cutoff_seconds_before_close: int

    # --- Operational ---------------------------------------------------------
    poll_interval_seconds: int
    log_dir: str
    decision_log_file: str
    pending_orders_file: str
    emergency_stop_file: str
    daily_pnl_file: str

    def __post_init__(self) -> None:
        if self.trading_mode not in VALID_TRADING_MODES:
            raise PolymarketConfigError(
                f"POLYMARKET_TRADING_MODE={self.trading_mode!r} is invalid; "
                f"must be one of {sorted(VALID_TRADING_MODES)}"
            )
        if self.max_bet_usd <= 0:
            raise PolymarketConfigError("POLYMARKET_MAX_BET_USD must be > 0")
        if self.max_daily_loss_usd <= 0:
            raise PolymarketConfigError("POLYMARKET_MAX_DAILY_LOSS_USD must be > 0")
        if self.max_open_positions <= 0:
            raise PolymarketConfigError("POLYMARKET_MAX_OPEN_POSITIONS must be > 0")
        if self.stale_data_max_seconds <= 0:
            raise PolymarketConfigError("POLYMARKET_STALE_DATA_MAX_SECONDS must be > 0")
        if not 0 < self.max_spread_pct < 1:
            raise PolymarketConfigError("POLYMARKET_MAX_SPREAD_PCT must be between 0 and 1 (exclusive)")
        if self.min_order_book_liquidity_usd < 0:
            raise PolymarketConfigError("POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD must be >= 0")
        if self.market_duration_minutes <= 0:
            raise PolymarketConfigError("POLYMARKET_MARKET_DURATION_MINUTES must be > 0")
        if self.entry_cutoff_seconds_before_close < 0:
            raise PolymarketConfigError("POLYMARKET_ENTRY_CUTOFF_SECONDS_BEFORE_CLOSE must be >= 0")
        if self.poll_interval_seconds <= 0:
            raise PolymarketConfigError("POLYMARKET_POLL_INTERVAL_SECONDS must be > 0")
        if self.chain_id <= 0:
            raise PolymarketConfigError("POLYMARKET_CHAIN_ID must be > 0")

    @property
    def is_paper(self) -> bool:
        return self.trading_mode == TRADING_MODE_PAPER

    @property
    def is_live(self) -> bool:
        return not self.is_paper

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, dotenv_path: Path | None = None) -> "PolymarketSettings":
        if env is None:
            _load_dotenv_into_environ(dotenv_path or Path(".env"))
            env = os.environ

        return cls(
            trading_mode=_get_str(env, "POLYMARKET_TRADING_MODE", TRADING_MODE_PAPER).lower(),
            live_trading_confirmed=_get_bool(env, "POLYMARKET_LIVE_TRADING_CONFIRMED", False),
            live_auto_execute=_get_bool(env, "POLYMARKET_LIVE_AUTO_EXECUTE", False),
            private_key=_get_optional_str(env, "POLYMARKET_PRIVATE_KEY"),
            api_key=_get_optional_str(env, "POLYMARKET_API_KEY"),
            api_secret=_get_optional_str(env, "POLYMARKET_API_SECRET"),
            api_passphrase=_get_optional_str(env, "POLYMARKET_API_PASSPHRASE"),
            funder_address=_get_optional_str(env, "POLYMARKET_FUNDER_ADDRESS"),
            clob_api_url=_get_str(env, "POLYMARKET_CLOB_API_URL", "https://clob.polymarket.com"),
            gamma_api_url=_get_str(env, "POLYMARKET_GAMMA_API_URL", "https://gamma-api.polymarket.com"),
            chain_id=_get_int(env, "POLYMARKET_CHAIN_ID", 137),  # Polygon mainnet
            max_bet_usd=_get_float(env, "POLYMARKET_MAX_BET_USD", 5.0),
            max_daily_loss_usd=_get_float(env, "POLYMARKET_MAX_DAILY_LOSS_USD", 20.0),
            max_open_positions=_get_int(env, "POLYMARKET_MAX_OPEN_POSITIONS", 1),
            cooldown_seconds_after_exit=_get_int(env, "POLYMARKET_COOLDOWN_SECONDS_AFTER_EXIT", 60),
            stale_data_max_seconds=_get_float(env, "POLYMARKET_STALE_DATA_MAX_SECONDS", 20.0),
            max_spread_pct=_get_float(env, "POLYMARKET_MAX_SPREAD_PCT", 0.05),
            min_order_book_liquidity_usd=_get_float(env, "POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD", 25.0),
            asset=_get_str(env, "POLYMARKET_ASSET", "bitcoin").lower(),
            market_duration_minutes=_get_int(env, "POLYMARKET_MARKET_DURATION_MINUTES", 15),
            entry_cutoff_seconds_before_close=_get_int(env, "POLYMARKET_ENTRY_CUTOFF_SECONDS_BEFORE_CLOSE", 120),
            poll_interval_seconds=_get_int(env, "POLYMARKET_POLL_INTERVAL_SECONDS", 10),
            log_dir=_get_str(env, "POLYMARKET_LOG_DIR", "logs/polymarket"),
            decision_log_file=_get_str(env, "POLYMARKET_DECISION_LOG_FILE", "logs/polymarket/decisions.jsonl"),
            pending_orders_file=_get_str(env, "POLYMARKET_PENDING_ORDERS_FILE", "logs/polymarket/pending_orders.json"),
            emergency_stop_file=_get_str(env, "POLYMARKET_EMERGENCY_STOP_FILE", "logs/polymarket/emergency_stop.json"),
            daily_pnl_file=_get_str(env, "POLYMARKET_DAILY_PNL_FILE", "logs/polymarket/daily_pnl.json"),
        )


_settings_singleton: PolymarketSettings | None = None


def get_settings() -> PolymarketSettings:
    global _settings_singleton
    if _settings_singleton is None:
        _settings_singleton = PolymarketSettings.from_env()
    return _settings_singleton


def reload_settings() -> PolymarketSettings:
    """Force a fresh read from the current environment. Tests only."""
    global _settings_singleton
    _settings_singleton = PolymarketSettings.from_env()
    return _settings_singleton
