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

import base64
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

    # --- US venue API resilience: bounded retry/backoff for a 429
    # polymarket_us.errors.RateLimitError on a READ-ONLY call (market
    # discovery, order book, settlement, fill lookup, balance -- never
    # order submission; see us_client.py's _retry_on_rate_limit). A real
    # incident (Cloudflare 1015 on gateway.polymarket.us) crashed
    # run_cycle() via an uncaught RateLimitError out of get_order_book();
    # these three bound exactly how hard this client will retry before
    # giving up and letting the caller degrade safely (no trade this
    # cycle) rather than hammering an already-rate-limited endpoint.
    us_rate_limit_max_retries: int
    us_rate_limit_base_delay_seconds: float
    us_rate_limit_max_delay_seconds: float

    # --- US venue NEW-MARKET BOOK WARMUP: a brand-new BTC 15m market's
    # exact nested market slug can be returned by event discovery
    # (events.retrieve_by_slug) a few seconds before markets.book() for
    # that SAME slug actually indexes it -- confirmed LIVE, twice: a
    # fresh event discovered with time remaining, whose own nested
    # market slug immediately 404'd on markets.book() via
    # polymarket_us.errors.NotFoundError, then returned a healthy book
    # moments later with no other change. This is a GENUINELY DIFFERENT
    # transient condition from a 429 rate limit above (see
    # us_client.py's _retry_on_not_found) -- these three bound exactly
    # how long this client keeps retrying the EXACT same market's own
    # book before giving up and letting the caller degrade safely (no
    # trade this cycle, never a fallback to a different market).
    us_book_warmup_max_retries: int
    us_book_warmup_base_delay_seconds: float
    us_book_warmup_max_delay_seconds: float

    # --- Risk controls — deliberately tiny defaults. Read every one of
    # these yourself in .env.polymarket.example before going live; they
    # are placeholders, not a recommendation. ------------------------------
    # The HARD ceiling risk.py's check_bet_size enforces -- the simple
    # price-based strategy's own entry size (simple_entry_size_usd,
    # below) is validated at load time to never exceed this, so this
    # is the backstop, never the everyday value by itself.
    max_bet_usd: float
    max_daily_loss_usd: float
    max_open_positions: int
    cooldown_seconds_after_exit: int
    stale_data_max_seconds: float
    max_spread_pct: float
    # Companion ABSOLUTE threshold (in price/USD terms, e.g. 0.03 = 3
    # cents) for check_spread(), checked as an alternative to
    # max_spread_pct, not a replacement — see risk.py's check_spread()
    # docstring. A binary contract priced near 0 or 1 has a tiny
    # denominator in (ask-bid)/mid, so an entirely normal few-cent
    # spread can read as a huge relative percentage; this absolute cap
    # rescues that specific case (relative percentage is mathematically
    # guaranteed to be >= the absolute spread for any mid in (0,1], so
    # this can only ever ADD a passing path for a genuinely tight
    # absolute spread, never let through a trade that's wide by both
    # measures). Keep this small and tight — it is not a general
    # escape hatch from max_spread_pct.
    max_spread_usd: float
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

    # --- Simple price-based strategy (see simple_entry_signal.py/
    # take_profit.py) -- the ONLY production entry/exit logic as of
    # this round. Coinbase/Chainlink/confidence/historical-learning
    # modules remain in the codebase (with their own tests) but are no
    # longer called from engine.run_cycle(). Entry is evaluated
    # continuously across the full 15-minute market, at ANY point while
    # it is open -- there is no time-remaining window setting and NO
    # probability-threshold setting any more (see simple_entry_signal.py:
    # direction is simply whichever side the market currently favors).
    # ------------------------------------------------------------------
    # Fixed entry size for every approved trade -- minimum == maximum
    # == $20 (validated below); max_bet_usd (the risk manager's own
    # independent hard ceiling) is never bypassed by this.
    simple_entry_size_usd: float
    # Automatic exit targets (see take_profit.py) -- BOTH configurable,
    # never hard-coded constants, so either can change without touching
    # strategy code. Fractions of the position's own ACTUAL average
    # fill price: target_price = avg_fill_price * (1 + simple_take_profit_pct);
    # stop_loss_price = avg_fill_price * (1 - simple_stop_loss_pct).
    # Defaults match this round's governing spec: +10% / -20%.
    simple_take_profit_pct: float
    simple_stop_loss_pct: float

    # --- Minimum entry edge (see simple_entry_signal.py) -- a SECOND,
    # independent filter layered on top of the threshold-free favored-
    # side rule above, never a reintroduction of the old fixed ">=0.70"
    # gate: that gate was an ABSOLUTE floor on one side's own
    # probability; this is a RELATIVE gap requirement BETWEEN the two
    # sides. edge = abs(yes_implied_probability - no_implied_probability);
    # a candidate is only eligible when edge >= simple_min_entry_edge.
    # Example: YES 60% / NO 40% -> edge 0.20, eligible at the 0.10
    # default. An exact tie or missing book data were ALREADY no-trade
    # before this setting existed (see simple_entry_signal.py) and stay
    # that way regardless of this value.
    simple_min_entry_edge: float
    # --- Entry persistence (see engine.MarketHistory.observe_entry_candidate)
    # -- do not enter on a single snapshot. The SAME favored outcome
    # (already edge-qualified above) must be the chosen candidate on
    # this many CONSECUTIVE strategy evaluations, for the SAME market,
    # before a submission is allowed. The favored side flipping, the
    # edge falling back below simple_min_entry_edge, a tie, or missing
    # book data all reset the counter (collapsed into one "outcome is
    # None this cycle" case -- see simple_entry_signal.py). 1 disables
    # this filter entirely (every qualifying cycle is immediately
    # eligible, the pre-this-round behavior).
    simple_entry_persistence_required: int

    # --- Entry retry guard (see entry_guard.py) — an IDEMPOTENCY/safety
    # gate, not a risk threshold: after a live incident showed
    # auto-execute repeatedly resubmitting a live BUY for the exact same
    # market/outcome every cycle following an unknown/rejected result
    # (order_status_unknown -> rejected -> new pending_order, on loop),
    # this bounds how soon the SAME (condition_id, outcome) may be
    # retried after a failed/unresolved attempt. Never touches
    # max_bet_usd/sizing/spread/liquidity/cutoff, and never blocks a
    # different outcome or a different 15-minute market.
    #
    # How long a recently-FAILED (rejected/expired/failed, or reconciled
    # with no resulting position) attempt blocks a retry on the exact
    # same market/outcome, UNLESS the price has moved by
    # entry_retry_min_price_change in the meantime (see below). An
    # attempt that is still UNRESOLVED (awaiting_approval, or submitted
    # but not yet reconciled) is NEVER time-bounded -- it blocks
    # regardless of this value until it actually reconciles.
    entry_retry_cooldown_seconds: float
    # Minimum absolute move (in price, e.g. 0.02 = 2 cents) in the
    # candidate order's max_price, since a recently-failed attempt's own
    # max_price, required to treat a new attempt as a materially
    # different setup and allow an immediate retry within the cooldown
    # window above.
    entry_retry_min_price_change: float

    # --- Exit retry guard (see exit_retry_guard.py) -- the SAME
    # idempotency/safety philosophy as entry_retry_cooldown_seconds
    # above, applied to automatic EXIT (SELL) resubmission: after a
    # live incident showed a position repeatedly cycling
    # EXIT -> UNKNOWN -> EXPIRED -> EXIT -> UNKNOWN -> EXPIRED -> EXIT
    # with zero cooldown between attempts, this bounds how soon a NEW
    # exit may be resubmitted for the SAME position after a recently-
    # FAILED attempt (an authoritative, no-fill terminal outcome --
    # never the in-flight/UNKNOWN case, which exit_pending_order_id
    # already blocks unconditionally regardless of this value). Never
    # touches max_bet_usd/sizing/BTC evidence scoring/the exit
    # decision's own evidence-gated cascade, and never blocks a exit
    # whose underlying evidence hasn't yet been judged exit-worthy in
    # the first place.
    #
    # How long a recently-FAILED exit attempt blocks a retry on the
    # same position, UNLESS the BTC edge score (exit_manager.
    # EdgeAssessment.btc_points) has moved by exit_retry_min_evidence_change
    # in the meantime (see below).
    exit_retry_cooldown_seconds: float
    # Minimum absolute move (in btc_points, the same continuous
    # evidence/expected-value score evaluate_dynamic_exit's own
    # exit-worthy decision is based on) since a recently-failed exit
    # attempt's own btc_points reading, required to treat a new attempt
    # as materially changed evidence and allow an immediate retry
    # within the cooldown window above.
    exit_retry_min_evidence_change: float

    # --- Order execution -----------------------------------------------------
    # FOK (fill-or-kill) is the default — see models.OrderRequest's
    # docstring for why: it removes the ambiguous "market order partially
    # filled" case for new entries by construction.
    default_order_type: str

    # --- Evidence-gated dynamic exit (see exit_manager.py) ------------------
    # Fraction above the position's ACTUAL average fill price that counts
    # as the SOFT profit target, e.g. 0.20 => avg_fill_price * 1.20. This
    # is deliberately NOT an unconditional sell trigger — see
    # exit_manager.py's module docstring: reaching it is one input to an
    # evidence-gated cascade (BTC momentum/structure/reversal evidence,
    # reusing src/strategy/evidence.py's evaluate_momentum() via
    # btc_intelligence.py), not a sell-by-itself condition.
    profit_target_pct: float
    # A second, independent safety switch (same "deliberately overlapping
    # guards" pattern as live_trading_confirmed/live_auto_execute — see
    # gateway.py's module docstring) specifically for AUTOMATIC exits.
    # False (the default) means check_and_execute_dynamic_exits() never
    # submits a real exit order even if everything else (live mode,
    # live_trading_confirmed, live_auto_execute) is already green — exit
    # automation must be turned on explicitly and separately from entries.
    auto_exit_enabled: bool
    # THE master switch for the entire dynamic-exit feature (both the
    # evidence cascade's decision-making AND any submission, paper or
    # live). False (the default) makes check_and_execute_dynamic_exits()
    # a complete no-op — it never even evaluates a position. Ships
    # disabled; a human must turn this on explicitly once ready to try it,
    # even in paper mode.
    dynamic_exit_enabled: bool
    # How many seconds of fed BTC quote samples (btc_market_data.py) are
    # aggregated into one OHLC bar for the BTC evidence engine. 60
    # (one-minute bars) matches this system's own poll_interval_seconds
    # default order of magnitude — fine enough to accumulate real
    # structure within a 15-minute market, coarse enough that a handful
    # of fed quotes per minute is enough to form a real bar.
    btc_bar_interval_seconds: int
    # The maximum age (seconds) of the NEWEST available BTC bar before
    # it is treated as equivalent to "no data at all" — a dead feed
    # must become INSUFFICIENT_DATA, never keep producing a confident
    # read from arbitrarily old data (see btc_intelligence.assess_btc_market
    # / btc_market_data.compute_feed_status). Default 300s (5 minutes):
    # with 1-minute candles refreshed on every new-minute boundary
    # (BtcFeedRefresher), a healthy feed's newest bar is normally
    # 60-120s old by the time it's read, accounting for refresh timing
    # and processing; 300s gives a generous ~2.5-5x margin above that
    # normal case (so ordinary jitter/a slow API response never
    # triggers a false STALE read) while still catching a genuinely
    # dead feed with most of a 15-minute market's life still left to
    # react to it, rather than only noticing at the very end.
    btc_max_bar_age_seconds: float
    # Minimum corroborating weakening/reversing signals required before
    # an early (below-target) exit is recommended — see
    # exit_manager.DynamicExitConfig. Same default (2) as the proven
    # options-side EvaluatorConfig.min_weakening_signals_for_exit,
    # reused rather than independently re-tuned.
    min_weakening_signals_for_exit: int
    # The ENTRY-side mirror of min_weakening_signals_for_exit above --
    # see btc_entry_signal.py. Minimum fired-signal count required
    # before Coinbase BTC evidence (the PRIMARY entry-direction signal)
    # is treated as materially confirming a bullish or bearish thesis,
    # rather than a single soft indicator being enough to propose a
    # trade. Same default (2) and mechanism, reused rather than
    # independently re-tuned.
    min_strengthening_signals_for_entry: int
    # Where fed BTC quote samples persist (btc_market_data.BtcPriceHistoryStore)
    # — restart-safe, same file-backed convention as every other store here.
    btc_price_history_file: str

    # --- Settlement-aligned reference feed (see reference_divergence.py) ---
    # Coinbase (above) stays the PRIMARY live market-momentum signal;
    # this is a SEPARATE, OPTIONAL feed for whatever source actually
    # settles the traded market (research finding: Polymarket's own
    # 15-minute BTC Up/Down rules cite Chainlink's BTC/USD Data Stream,
    # not CF Benchmarks' BRTI -- see reference_divergence.py's module
    # docstring). Chainlink Data Streams requires a PAID subscription
    # with no free/public tier, so this defaults to disabled -- no live
    # fetcher exists yet; wiring one in later never requires touching
    # engine.py again (same DirectBtcQuoteSource Protocol Coinbase
    # already implements). False/None here reproduces TODAY's exact
    # Coinbase-only behavior, byte for byte.
    reference_feed_enabled: bool
    reference_price_history_file: str
    # Confidence penalty applied ONLY when the reference feed is FRESH
    # and materially disagrees with Coinbase's own chosen direction
    # (reference_divergence.assess_divergence's DIVERGENCE case) --
    # large enough by default to always force a NO_TRADE (see
    # entry_confidence.py's clamp), never merely a soft nudge, per
    # "confidence should decrease OR the trade should be blocked."
    # Never applied when the reference feed is unavailable, stale, or
    # itself non-directional -- those degrade to a zero penalty (no
    # change to Coinbase-only behavior).
    reference_divergence_penalty: float

    # --- Self-learning (see trade_learning.py) ------------------------------
    # Historical performance is a SECONDARY, BOUNDED adjustment to the
    # PRIMARY Coinbase-driven confidence score (entry_confidence.py) --
    # never a second strategy, never able to create a direction or
    # override neutral/stale BTC evidence. See trade_learning.py's
    # module docstring.
    learning_enabled: bool
    # A setup (see trade_learning.build_setup_key) needs at least this
    # many completed, strategy-attributable trades before its historical
    # win rate is allowed to move confidence at full strength --
    # trade_learning.compute_historical_adjustment() shrinks the
    # adjustment toward 0 below this count, so one or two trades can
    # never swing behavior (anti-overfitting requirement).
    learning_min_sample_size: int
    # The bounded adjustment range applied to base_confidence -- never
    # wide enough, even at a huge sample size, to turn a NO_TRADE (base
    # confidence 0, i.e. neutral/insufficient BTC evidence) into an
    # approved trade, or to swing a strong signal into NO_TRADE outright.
    learning_min_adjustment: float
    learning_max_adjustment: float
    # Where completed trades persist (trade_learning.CompletedTradeStore)
    # — restart-safe, same file-backed convention as every other store here.
    completed_trades_file: str

    # --- Market selection --------------------------------------------------
    # The underlying this system trades. Only "bitcoin" is implemented
    # (see strategy.py's module docstring on why this stays single-asset).
    asset: str
    # Target market duration in minutes. find_active_btc_market() uses
    # this to pick among whatever short-duration crypto markets are
    # actually live — see client.py's module docstring: this has not
    # been run against the real API from this environment.
    market_duration_minutes: int

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
        if not 0 < self.max_spread_usd < 1:
            raise PolymarketConfigError("POLYMARKET_MAX_SPREAD_USD must be between 0 and 1 (exclusive)")
        if self.min_order_book_liquidity_usd < 0:
            raise PolymarketConfigError("POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD must be >= 0")
        if not 0 <= self.max_price_slippage_pct < 1:
            raise PolymarketConfigError("POLYMARKET_MAX_PRICE_SLIPPAGE_PCT must be between 0 and 1 (exclusive of 1)")
        if self.simple_take_profit_pct <= 0:
            raise PolymarketConfigError("POLYMARKET_SIMPLE_TAKE_PROFIT_PCT must be > 0")
        if not 0 < self.simple_stop_loss_pct < 1:
            raise PolymarketConfigError(
                "POLYMARKET_SIMPLE_STOP_LOSS_PCT must be between 0 and 1 (exclusive) — a stop-loss price "
                "(avg_fill_price * (1 - pct)) must stay strictly positive"
            )
        if not 0 <= self.simple_min_entry_edge < 1:
            raise PolymarketConfigError(
                "POLYMARKET_SIMPLE_MIN_ENTRY_EDGE must be between 0 (inclusive -- disables the filter) and "
                "1 (exclusive -- a probability gap can never reach 1)"
            )
        if self.simple_entry_persistence_required < 1:
            raise PolymarketConfigError(
                "POLYMARKET_SIMPLE_ENTRY_PERSISTENCE_REQUIRED must be >= 1 (1 disables the filter -- every "
                "qualifying cycle is immediately eligible)"
            )
        if self.simple_entry_size_usd != 20.0:
            raise PolymarketConfigError("POLYMARKET_SIMPLE_ENTRY_SIZE_USD must be exactly $20 (minimum == maximum == $20)")
        # Deliberately NOT cross-validated against max_bet_usd here: a
        # caller is free to configure max_bet_usd below
        # simple_entry_size_usd (e.g. many existing risk.py tests set a
        # tiny max_bet_usd to exercise check_bet_size in isolation) --
        # the risk manager (risk.py), not settings construction, is the
        # right place to enforce that bound AT RUNTIME, by blocking the
        # trade exactly like any other oversized bet. "The risk manager
        # remains the final authority."
        if self.market_duration_minutes <= 0:
            raise PolymarketConfigError("POLYMARKET_MARKET_DURATION_MINUTES must be > 0")
        if self.poll_interval_seconds <= 0:
            raise PolymarketConfigError("POLYMARKET_POLL_INTERVAL_SECONDS must be > 0")
        if self.profit_target_pct <= 0:
            raise PolymarketConfigError("POLYMARKET_PROFIT_TARGET_PCT must be > 0")
        if self.btc_bar_interval_seconds <= 0:
            raise PolymarketConfigError("POLYMARKET_BTC_BAR_INTERVAL_SECONDS must be > 0")
        if self.btc_max_bar_age_seconds <= 0:
            raise PolymarketConfigError("POLYMARKET_BTC_MAX_BAR_AGE_SECONDS must be > 0")
        if self.min_weakening_signals_for_exit <= 0:
            raise PolymarketConfigError("POLYMARKET_MIN_WEAKENING_SIGNALS_FOR_EXIT must be > 0")
        if self.min_strengthening_signals_for_entry <= 0:
            raise PolymarketConfigError("POLYMARKET_MIN_STRENGTHENING_SIGNALS_FOR_ENTRY must be > 0")
        if self.reference_divergence_penalty > 0:
            raise PolymarketConfigError("POLYMARKET_REFERENCE_DIVERGENCE_PENALTY must be <= 0")
        if self.learning_min_sample_size <= 0:
            raise PolymarketConfigError("POLYMARKET_LEARNING_MIN_SAMPLE_SIZE must be > 0")
        if self.learning_min_adjustment > 0:
            raise PolymarketConfigError("POLYMARKET_LEARNING_MIN_ADJUSTMENT must be <= 0")
        if self.learning_max_adjustment < 0:
            raise PolymarketConfigError("POLYMARKET_LEARNING_MAX_ADJUSTMENT must be >= 0")
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
            # Verified directly against the installed polymarket_us==2.3.0
            # package's real auth.create_auth_headers(): it does
            # `base64.b64decode(secret_key)`, then requires EXACTLY 32
            # bytes (or 64, truncated to the first 32) before constructing
            # a nacl.signing.SigningKey -- anything else raises deep inside
            # the SDK's signer, on the first real signed request, not at
            # startup. Checked here instead, at config-construction time,
            # regardless of paper/live (same "fail closed in every mode"
            # posture as the international venue's private_key 0x-prefix
            # check above), so a garbled/truncated secret fails loudly and
            # immediately rather than unpredictably mid-trade.
            if self.us_secret_key is not None:
                try:
                    decoded_len = len(base64.b64decode(self.us_secret_key, validate=True))
                except Exception as exc:
                    raise PolymarketConfigError(
                        "POLYMARKET_US_SECRET_KEY must be valid base64 -- refusing to proceed "
                        "with a value that cannot be a valid Ed25519 secret key, rather than "
                        "let it fail unpredictably later inside the SDK's signer."
                    ) from exc
                if decoded_len not in (32, 64):
                    raise PolymarketConfigError(
                        f"POLYMARKET_US_SECRET_KEY decodes to {decoded_len} bytes; the installed "
                        "SDK's signer requires exactly 32 (an Ed25519 seed) or 64 (truncated to "
                        "the first 32) -- refusing a value that would fail unpredictably later "
                        "inside the SDK's signer instead."
                    )
            # The US venue's base URLs are user-overridable (unlike the
            # international venue's, which the SDK bundles into one fixed
            # Environment object -- see module docstring); an unset env
            # var correctly falls back to DEFAULT_US_API_BASE_URL/
            # DEFAULT_US_GATEWAY_BASE_URL above, but an env var explicitly
            # set to blank/whitespace (e.g. a leftover placeholder line in
            # a .env) would otherwise silently become "" and reach the SDK
            # client construction unchecked -- fail closed on that here
            # instead of trusting the SDK (or whatever HTTP library it
            # uses internally) to handle an empty base URL safely.
            if not self.us_api_base_url:
                raise PolymarketConfigError("POLYMARKET_US_API_BASE_URL must not be blank")
            if not self.us_gateway_base_url:
                raise PolymarketConfigError("POLYMARKET_US_GATEWAY_BASE_URL must not be blank")
        if self.us_rate_limit_max_retries < 0:
            raise PolymarketConfigError("POLYMARKET_US_RATE_LIMIT_MAX_RETRIES must be >= 0")
        if self.us_rate_limit_base_delay_seconds <= 0:
            raise PolymarketConfigError("POLYMARKET_US_RATE_LIMIT_BASE_DELAY_SECONDS must be > 0")
        if self.us_rate_limit_max_delay_seconds < self.us_rate_limit_base_delay_seconds:
            raise PolymarketConfigError(
                "POLYMARKET_US_RATE_LIMIT_MAX_DELAY_SECONDS must be >= POLYMARKET_US_RATE_LIMIT_BASE_DELAY_SECONDS"
            )
        if self.us_book_warmup_max_retries < 0:
            raise PolymarketConfigError("POLYMARKET_US_BOOK_WARMUP_MAX_RETRIES must be >= 0")
        if self.us_book_warmup_base_delay_seconds <= 0:
            raise PolymarketConfigError("POLYMARKET_US_BOOK_WARMUP_BASE_DELAY_SECONDS must be > 0")
        if self.us_book_warmup_max_delay_seconds < self.us_book_warmup_base_delay_seconds:
            raise PolymarketConfigError(
                "POLYMARKET_US_BOOK_WARMUP_MAX_DELAY_SECONDS must be >= POLYMARKET_US_BOOK_WARMUP_BASE_DELAY_SECONDS"
            )
        if self.entry_retry_cooldown_seconds < 0:
            raise PolymarketConfigError("POLYMARKET_ENTRY_RETRY_COOLDOWN_SECONDS must be >= 0")
        if self.entry_retry_min_price_change < 0:
            raise PolymarketConfigError("POLYMARKET_ENTRY_RETRY_MIN_PRICE_CHANGE must be >= 0")
        if self.exit_retry_cooldown_seconds < 0:
            raise PolymarketConfigError("POLYMARKET_EXIT_RETRY_COOLDOWN_SECONDS must be >= 0")
        if self.exit_retry_min_evidence_change < 0:
            raise PolymarketConfigError("POLYMARKET_EXIT_RETRY_MIN_EVIDENCE_CHANGE must be >= 0")

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
            us_rate_limit_max_retries=_get_int(env, "POLYMARKET_US_RATE_LIMIT_MAX_RETRIES", 4),
            us_rate_limit_base_delay_seconds=_get_float(env, "POLYMARKET_US_RATE_LIMIT_BASE_DELAY_SECONDS", 0.5),
            us_rate_limit_max_delay_seconds=_get_float(env, "POLYMARKET_US_RATE_LIMIT_MAX_DELAY_SECONDS", 8.0),
            us_book_warmup_max_retries=_get_int(env, "POLYMARKET_US_BOOK_WARMUP_MAX_RETRIES", 4),
            us_book_warmup_base_delay_seconds=_get_float(env, "POLYMARKET_US_BOOK_WARMUP_BASE_DELAY_SECONDS", 1.0),
            us_book_warmup_max_delay_seconds=_get_float(env, "POLYMARKET_US_BOOK_WARMUP_MAX_DELAY_SECONDS", 2.0),
            max_bet_usd=_get_float(env, "POLYMARKET_MAX_BET_USD", 20.0),
            max_daily_loss_usd=_get_float(env, "POLYMARKET_MAX_DAILY_LOSS_USD", 20.0),
            max_open_positions=_get_int(env, "POLYMARKET_MAX_OPEN_POSITIONS", 1),
            cooldown_seconds_after_exit=_get_int(env, "POLYMARKET_COOLDOWN_SECONDS_AFTER_EXIT", 60),
            stale_data_max_seconds=_get_float(env, "POLYMARKET_STALE_DATA_MAX_SECONDS", 20.0),
            max_spread_pct=_get_float(env, "POLYMARKET_MAX_SPREAD_PCT", 0.05),
            max_spread_usd=_get_float(env, "POLYMARKET_MAX_SPREAD_USD", 0.03),
            min_order_book_liquidity_usd=_get_float(env, "POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD", 10.0),
            max_price_slippage_pct=_get_float(env, "POLYMARKET_MAX_PRICE_SLIPPAGE_PCT", 0.03),
            simple_entry_size_usd=_get_float(env, "POLYMARKET_SIMPLE_ENTRY_SIZE_USD", 20.0),
            simple_take_profit_pct=_get_float(env, "POLYMARKET_SIMPLE_TAKE_PROFIT_PCT", 0.10),
            simple_stop_loss_pct=_get_float(env, "POLYMARKET_SIMPLE_STOP_LOSS_PCT", 0.20),
            simple_min_entry_edge=_get_float(env, "POLYMARKET_SIMPLE_MIN_ENTRY_EDGE", 0.10),
            simple_entry_persistence_required=_get_int(env, "POLYMARKET_SIMPLE_ENTRY_PERSISTENCE_REQUIRED", 3),
            entry_retry_cooldown_seconds=_get_float(env, "POLYMARKET_ENTRY_RETRY_COOLDOWN_SECONDS", 120.0),
            entry_retry_min_price_change=_get_float(env, "POLYMARKET_ENTRY_RETRY_MIN_PRICE_CHANGE", 0.02),
            exit_retry_cooldown_seconds=_get_float(env, "POLYMARKET_EXIT_RETRY_COOLDOWN_SECONDS", 90.0),
            exit_retry_min_evidence_change=_get_float(env, "POLYMARKET_EXIT_RETRY_MIN_EVIDENCE_CHANGE", 2.0),
            default_order_type=_get_str(env, "POLYMARKET_DEFAULT_ORDER_TYPE", "FOK").upper(),
            profit_target_pct=_get_float(env, "POLYMARKET_PROFIT_TARGET_PCT", 0.20),
            auto_exit_enabled=_get_bool(env, "POLYMARKET_AUTO_EXIT_ENABLED", False),
            dynamic_exit_enabled=_get_bool(env, "POLYMARKET_DYNAMIC_EXIT_ENABLED", False),
            btc_bar_interval_seconds=_get_int(env, "POLYMARKET_BTC_BAR_INTERVAL_SECONDS", 60),
            btc_max_bar_age_seconds=_get_float(env, "POLYMARKET_BTC_MAX_BAR_AGE_SECONDS", 300.0),
            min_weakening_signals_for_exit=_get_int(env, "POLYMARKET_MIN_WEAKENING_SIGNALS_FOR_EXIT", 2),
            min_strengthening_signals_for_entry=_get_int(env, "POLYMARKET_MIN_STRENGTHENING_SIGNALS_FOR_ENTRY", 2),
            btc_price_history_file=_get_str(env, "POLYMARKET_BTC_PRICE_HISTORY_FILE", "logs/polymarket/btc_price_history.json"),
            reference_feed_enabled=_get_bool(env, "POLYMARKET_REFERENCE_FEED_ENABLED", False),
            reference_price_history_file=_get_str(
                env, "POLYMARKET_REFERENCE_PRICE_HISTORY_FILE", "logs/polymarket/reference_price_history.json",
            ),
            reference_divergence_penalty=_get_float(env, "POLYMARKET_REFERENCE_DIVERGENCE_PENALTY", -100.0),
            learning_enabled=_get_bool(env, "POLYMARKET_LEARNING_ENABLED", True),
            learning_min_sample_size=_get_int(env, "POLYMARKET_LEARNING_MIN_SAMPLE_SIZE", 20),
            learning_min_adjustment=_get_float(env, "POLYMARKET_LEARNING_MIN_ADJUSTMENT", -10.0),
            learning_max_adjustment=_get_float(env, "POLYMARKET_LEARNING_MAX_ADJUSTMENT", 10.0),
            completed_trades_file=_get_str(env, "POLYMARKET_COMPLETED_TRADES_FILE", "logs/polymarket/completed_trades.json"),
            asset=_get_str(env, "POLYMARKET_ASSET", "bitcoin").lower(),
            market_duration_minutes=_get_int(env, "POLYMARKET_MARKET_DURATION_MINUTES", 15),
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
