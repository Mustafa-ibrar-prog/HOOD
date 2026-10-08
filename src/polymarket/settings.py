"""Configuration for the Polymarket BTC 15-minute system, sourced entirely
from environment variables (optionally via a .env file, same minimal
loader convention as src/config/settings.py) — no other module here
should read os.environ directly.

Credentials (verified against polymarket-client's real
SecureClient.create() signature — see client.py's module docstring for
the research trail):

  - POLYMARKET_PRIVATE_KEY is ALWAYS required for live trading. Every
    order is an EIP-712 signature from this wallet; there is no
    credential-only path that skips it, unlike the old (archived)
    py-clob-client, where some flows could get away with just an API
    key. Never paste a real private key into a chat session or commit
    it anywhere — set it as a real environment variable or in a local,
    gitignored .env file only.
  - POLYMARKET_API_KEY / POLYMARKET_API_SECRET / POLYMARKET_API_PASSPHRASE
    are OPTIONAL. If all three are set, they're passed as pre-derived
    L2 API credentials (skips re-deriving them via a signed request on
    every process start). If unset, the SDK derives them itself from
    the private key at startup. Providing only SOME of the three is a
    configuration mistake, not a valid partial state — see
    __post_init__, which fails closed on it rather than guessing which
    one you meant to set.
  - POLYMARKET_FUNDER_ADDRESS is optional: the wallet to trade on behalf
    of, when it differs from the private key's own address (e.g. a
    Polymarket-issued proxy/Safe wallet). Maps to SecureClient.create()'s
    `wallet` parameter.

This module intentionally does NOT expose clob_api_url/gamma_api_url/
chain_id as independent settings (an earlier version did). The SDK
bundles those together as one `Environment` object (only `PRODUCTION`
is currently used — see client.py); letting them be set independently
risked a real, dangerous mismatch (e.g. a overridden host paired with
the wrong chain_id). There is currently no supported way to point this
system at anything other than real, production Polymarket.

VENUE (verified by installing polymarket-us==2.3.0 from PyPI and
inspecting its real source/types directly — see us_client.py's module
docstring for the full trail): Polymarket US (traded via QCX LLC, a
CFTC-regulated Designated Contract Market) is a GENUINELY DIFFERENT
venue from international polymarket.com — different base URLs, a
different official SDK (`polymarket-us`, not `polymarket-client`), and
a completely different credential model (an Ed25519 API key_id +
secret_key pair, NOT an EVM private key — there is no wallet/funder
concept on this venue at all). POLYMARKET_VENUE selects between them:

  - "international" (THE DEFAULT, for backward compatibility with any
    existing deployment/test that predates the US venue work and never
    sets this variable): uses client.PolymarketClient and the
    PRIVATE_KEY/API_KEY/API_SECRET/API_PASSPHRASE/FUNDER_ADDRESS fields
    below exactly as documented.
  - "us": uses us_client.PolymarketUSClient and the
    POLYMARKET_US_KEY_ID/POLYMARKET_US_SECRET_KEY fields instead. A
    US-based trader should set POLYMARKET_VENUE=us explicitly in their
    own .env — see .env.polymarket.example.

Never log POLYMARKET_PRIVATE_KEY, POLYMARKET_API_SECRET,
POLYMARKET_US_SECRET_KEY, or any other credential value — this module
only ever reads them into memory for client construction; nothing in
this package writes a credential value to a log, and that must stay
true for anything added here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

TRADING_MODE_PAPER = "paper"
TRADING_MODE_LIVE = "live"
VALID_TRADING_MODES = frozenset({TRADING_MODE_PAPER, TRADING_MODE_LIVE})
VALID_ORDER_TYPES = frozenset({"FOK", "FAK"})

VENUE_INTERNATIONAL = "international"
VENUE_US = "us"
VALID_VENUES = frozenset({VENUE_INTERNATIONAL, VENUE_US})
DEFAULT_US_API_BASE_URL = "https://api.polymarket.us"
DEFAULT_US_GATEWAY_BASE_URL = "https://gateway.polymarket.us"


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

    # --- Venue selection (see module docstring) ---------------------------
    venue: str

    # --- Credentials, international venue (see module docstring) --------
    private_key: str | None
    api_key: str | None
    api_secret: str | None
    api_passphrase: str | None
    funder_address: str | None

    # --- Credentials, US venue (see module docstring) ---------------------
    us_key_id: str | None
    us_secret_key: str | None
    us_api_base_url: str
    us_gateway_base_url: str

    # --- Manual market override (US venue only), see us_client.py's
    # find_active_btc_market()/manual-override docstring. TEMPORARY,
    # test-only: when set, find_active_btc_market() retrieves ONLY this
    # exact market/event by slug -- never a search, never "closest
    # available," never a silent fallback to BTC 15m discovery. Unset
    # (the default) leaves BTC 15m discovery completely unaffected.
    us_market_slug: str | None

    # --- Risk controls — deliberately tiny defaults. Read every one of
    # these yourself in .env.polymarket.example before going live; they
    # are placeholders, not a recommendation. ------------------------------
    max_bet_usd: float
    max_daily_loss_usd: float
    max_open_positions: int
    cooldown_seconds_after_exit: int
    stale_data_max_seconds: float
    max_spread_pct: float
    # Minimum EXECUTABLE liquidity (USD notional, price x size, summed
    # across book levels at or better than the order's max_price) on the
    # side of the book a new entry would consume. See
    # models.OrderBookSnapshot.executable_liquidity_usd and risk.py's
    # check_order_book_liquidity — this has a single, precise meaning
    # and is evaluated against the SPECIFIC outcome token being bought,
    # never an aggregate across both sides or both outcomes.
    min_order_book_liquidity_usd: float
    # How far (as a fraction of the reference price) a market order's
    # max_price ceiling is allowed to sit above the current best ask
    # (BUY) — bounds slippage on a FOK/FAK order beyond just "the order
    # either fills at an acceptable price or doesn't happen."
    max_price_slippage_pct: float

    # --- Order execution -----------------------------------------------------
    # FOK (fill-or-kill) is the default — see models.OrderRequest's
    # docstring for why: it removes the ambiguous "market order partially
    # filled" case for new entries by construction.
    default_order_type: str

    # --- Automatic profit-target exit (see exit_manager.py) ----------------
    # Fraction above the position's ACTUAL average fill price at which an
    # open position becomes eligible to exit, e.g. 0.20 => exit once the
    # live best BID reaches avg_fill_price * 1.20. Gross-price trigger —
    # see exit_manager.compute_target_price's docstring for why this is
    # intentionally distinct from the NET-of-fees realized P&L that gets
    # recorded once a fill actually happens.
    profit_target_pct: float
    # A second, independent safety switch (same "deliberately overlapping
    # guards" pattern as live_trading_confirmed/live_auto_execute — see
    # gateway.py's module docstring) specifically for AUTOMATIC exits.
    # False (the default) means check_and_execute_profit_target_exits()
    # never submits a real exit order even if everything else (live mode,
    # live_trading_confirmed, live_auto_execute) is already green — exit
    # automation must be turned on explicitly and separately from entries.
    auto_exit_enabled: bool

    # --- Market selection --------------------------------------------------
    # The underlying this system trades. Only "bitcoin" is implemented
    # (see strategy.py's module docstring on why this stays single-asset).
    asset: str
    # Target market duration in minutes. find_active_btc_market() uses
    # this to pick among whatever short-duration crypto markets are
    # actually live — see client.py's module docstring: this has not
    # been run against the real API from this environment.
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
    positions_file: str

    def __post_init__(self) -> None:
        if self.trading_mode not in VALID_TRADING_MODES:
            raise PolymarketConfigError(
                f"POLYMARKET_TRADING_MODE={self.trading_mode!r} is invalid; "
                f"must be one of {sorted(VALID_TRADING_MODES)}"
            )
        if self.default_order_type not in VALID_ORDER_TYPES:
            raise PolymarketConfigError(
                f"POLYMARKET_DEFAULT_ORDER_TYPE={self.default_order_type!r} is invalid; "
                f"must be one of {sorted(VALID_ORDER_TYPES)}"
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
        if not 0 <= self.max_price_slippage_pct < 1:
            raise PolymarketConfigError("POLYMARKET_MAX_PRICE_SLIPPAGE_PCT must be between 0 and 1 (exclusive of 1)")
        if self.market_duration_minutes <= 0:
            raise PolymarketConfigError("POLYMARKET_MARKET_DURATION_MINUTES must be > 0")
        if self.entry_cutoff_seconds_before_close < 0:
            raise PolymarketConfigError("POLYMARKET_ENTRY_CUTOFF_SECONDS_BEFORE_CLOSE must be >= 0")
        if self.poll_interval_seconds <= 0:
            raise PolymarketConfigError("POLYMARKET_POLL_INTERVAL_SECONDS must be > 0")
        if self.profit_target_pct <= 0:
            raise PolymarketConfigError("POLYMARKET_PROFIT_TARGET_PCT must be > 0")
        if self.venue not in VALID_VENUES:
            raise PolymarketConfigError(
                f"POLYMARKET_VENUE={self.venue!r} is invalid; must be one of {sorted(VALID_VENUES)}"
            )

        # --- Fail-closed credential checks (Task 7) --------------------------
        # The API-key triple is all-or-nothing, in EITHER mode: a partial
        # triple is always a configuration mistake (e.g. a typo'd env var
        # name), never a valid "use 2 of 3" state, so it's rejected
        # regardless of paper/live, and regardless of venue (a stale
        # partial triple left in a .env is still worth catching even if
        # the active venue happens to be "us") — catching it here is
        # strictly earlier and clearer than letting client.py discover it
        # mid-request.
        api_parts = (self.api_key, self.api_secret, self.api_passphrase)
        if any(api_parts) and not all(api_parts):
            raise PolymarketConfigError(
                "POLYMARKET_API_KEY/POLYMARKET_API_SECRET/POLYMARKET_API_PASSPHRASE must be "
                "all set or all unset -- a partial set is never valid (verified against "
                "polymarket-client's ApiKeyCreds, which requires all three)."
            )

        if self.venue == VENUE_INTERNATIONAL:
            # private_key is required for ANY live trading on the
            # international venue — verified against SecureClient.create()'s
            # real signature: private_key is a required keyword argument
            # there even when pre-derived `credentials` are also supplied,
            # because signing an order always needs the private key
            # regardless of how L2 REST auth is established. This is
            # checked here, at config-construction time, specifically so a
            # misconfigured deployment fails before ever reaching the
            # network, not with an opaque error from inside client.py.
            if self.is_live and not self.private_key:
                raise PolymarketConfigError(
                    "POLYMARKET_TRADING_MODE=live with POLYMARKET_VENUE=international "
                    "requires POLYMARKET_PRIVATE_KEY to be set — every order is signed by "
                    "this wallet; the API key triple alone cannot substitute for it. "
                    "See .env.polymarket.example."
                )
            if self.private_key is not None and not self.private_key.startswith("0x"):
                raise PolymarketConfigError(
                    "POLYMARKET_PRIVATE_KEY must be a 0x-prefixed hex string — refusing to "
                    "proceed with a value that cannot be a valid EVM private key, rather than "
                    "let it fail unpredictably later inside the SDK's signer."
                )
        elif self.venue == VENUE_US:
            # Polymarket US has NO private-key/wallet concept at all —
            # verified by inspecting the installed polymarket-us SDK's
            # real PolymarketUS.__init__ and auth.create_auth_headers():
            # authentication is a UUID key_id plus a base64-encoded
            # Ed25519 secret_key, signed per-request over
            # f"{timestamp}{method}{path}". The two must be all-or-nothing
            # (a lone key_id or secret_key is always a mistake), and BOTH
            # are required before live trading — there is no partial
            # credential state that can validly sign a real order here.
            us_parts = (self.us_key_id, self.us_secret_key)
            if any(us_parts) and not all(us_parts):
                raise PolymarketConfigError(
                    "POLYMARKET_US_KEY_ID and POLYMARKET_US_SECRET_KEY must be all set or "
                    "all unset -- a partial pair can never authenticate."
                )
            if self.is_live and not all(us_parts):
                raise PolymarketConfigError(
                    "POLYMARKET_TRADING_MODE=live with POLYMARKET_VENUE=us requires both "
                    "POLYMARKET_US_KEY_ID and POLYMARKET_US_SECRET_KEY to be set. "
                    "See .env.polymarket.example."
                )

    @property
    def is_paper(self) -> bool:
        return self.trading_mode == TRADING_MODE_PAPER

    @property
    def is_live(self) -> bool:
        return not self.is_paper

    @property
    def is_us_venue(self) -> bool:
        return self.venue == VENUE_US

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, dotenv_path: Path | None = None) -> "PolymarketSettings":
        if env is None:
            _load_dotenv_into_environ(dotenv_path or Path(".env"))
            env = os.environ

        return cls(
            trading_mode=_get_str(env, "POLYMARKET_TRADING_MODE", TRADING_MODE_PAPER).lower(),
            live_trading_confirmed=_get_bool(env, "POLYMARKET_LIVE_TRADING_CONFIRMED", False),
            live_auto_execute=_get_bool(env, "POLYMARKET_LIVE_AUTO_EXECUTE", False),
            # Defaults to "international" for backward compatibility with
            # any existing deployment/test that predates the US venue and
            # never sets this — see module docstring. A US-based trader
            # must set POLYMARKET_VENUE=us explicitly.
            venue=_get_str(env, "POLYMARKET_VENUE", VENUE_INTERNATIONAL).lower(),
            private_key=_get_optional_str(env, "POLYMARKET_PRIVATE_KEY"),
            api_key=_get_optional_str(env, "POLYMARKET_API_KEY"),
            api_secret=_get_optional_str(env, "POLYMARKET_API_SECRET"),
            api_passphrase=_get_optional_str(env, "POLYMARKET_API_PASSPHRASE"),
            funder_address=_get_optional_str(env, "POLYMARKET_FUNDER_ADDRESS"),
            us_key_id=_get_optional_str(env, "POLYMARKET_US_KEY_ID"),
            us_secret_key=_get_optional_str(env, "POLYMARKET_US_SECRET_KEY"),
            us_api_base_url=_get_str(env, "POLYMARKET_US_API_BASE_URL", DEFAULT_US_API_BASE_URL),
            us_gateway_base_url=_get_str(env, "POLYMARKET_US_GATEWAY_BASE_URL", DEFAULT_US_GATEWAY_BASE_URL),
            us_market_slug=_get_optional_str(env, "POLYMARKET_US_MARKET_SLUG"),
            max_bet_usd=_get_float(env, "POLYMARKET_MAX_BET_USD", 5.0),
            max_daily_loss_usd=_get_float(env, "POLYMARKET_MAX_DAILY_LOSS_USD", 20.0),
            max_open_positions=_get_int(env, "POLYMARKET_MAX_OPEN_POSITIONS", 1),
            cooldown_seconds_after_exit=_get_int(env, "POLYMARKET_COOLDOWN_SECONDS_AFTER_EXIT", 60),
            stale_data_max_seconds=_get_float(env, "POLYMARKET_STALE_DATA_MAX_SECONDS", 20.0),
            max_spread_pct=_get_float(env, "POLYMARKET_MAX_SPREAD_PCT", 0.05),
            min_order_book_liquidity_usd=_get_float(env, "POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD", 25.0),
            max_price_slippage_pct=_get_float(env, "POLYMARKET_MAX_PRICE_SLIPPAGE_PCT", 0.03),
            default_order_type=_get_str(env, "POLYMARKET_DEFAULT_ORDER_TYPE", "FOK").upper(),
            profit_target_pct=_get_float(env, "POLYMARKET_PROFIT_TARGET_PCT", 0.20),
            auto_exit_enabled=_get_bool(env, "POLYMARKET_AUTO_EXIT_ENABLED", False),
            asset=_get_str(env, "POLYMARKET_ASSET", "bitcoin").lower(),
            market_duration_minutes=_get_int(env, "POLYMARKET_MARKET_DURATION_MINUTES", 15),
            entry_cutoff_seconds_before_close=_get_int(env, "POLYMARKET_ENTRY_CUTOFF_SECONDS_BEFORE_CLOSE", 120),
            poll_interval_seconds=_get_int(env, "POLYMARKET_POLL_INTERVAL_SECONDS", 10),
            log_dir=_get_str(env, "POLYMARKET_LOG_DIR", "logs/polymarket"),
            decision_log_file=_get_str(env, "POLYMARKET_DECISION_LOG_FILE", "logs/polymarket/decisions.jsonl"),
            pending_orders_file=_get_str(env, "POLYMARKET_PENDING_ORDERS_FILE", "logs/polymarket/pending_orders.json"),
            emergency_stop_file=_get_str(env, "POLYMARKET_EMERGENCY_STOP_FILE", "logs/polymarket/emergency_stop.json"),
            daily_pnl_file=_get_str(env, "POLYMARKET_DAILY_PNL_FILE", "logs/polymarket/daily_pnl.json"),
            positions_file=_get_str(env, "POLYMARKET_POSITIONS_FILE", "logs/polymarket/open_positions.json"),
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
