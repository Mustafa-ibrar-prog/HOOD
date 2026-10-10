"""U.S.-venue network client — Polymarket US (traded via QCX LLC, a
CFTC-regulated Designated Contract Market) is a GENUINELY DIFFERENT
system from international polymarket.com, not a regional variant of the
same CLOB. This module is the ONLY place that may call the Polymarket
US API, and implements the exact same method surface as
client.PolymarketClient (find_active_btc_market, get_order_book,
get_resolution, place_order, get_fill_status, get_balance_usdc,
refresh, close) so engine.py/gateway.py/reconciliation.py need ZERO
changes — both clients are duck-typed against gateway.py's
PolymarketOrderPlacer Protocol and engine.py's plain attribute access,
never a shared base class.

Research trail (this sandbox cannot reach polymarket.us or
docs.polymarket.us — confirmed via repeated curl AND WebFetch tests,
both returning policy-level blocks, not a response from Polymarket
itself; see src/polymarket/__init__.py). Everything below is verified
by installing the REAL, OFFICIAL `polymarket-us` package from PyPI
(latest at the time of writing: 2.3.0) and inspecting its actual
source, type definitions, and bundled README directly — not docs, not
a blog post, not memory:

  - PyPI package `polymarket-us` (import name `polymarket_us`).
    Author "Polymarket Team"; Repository/Documentation project URLs
    point to github.com/Polymarket/polymarket-us-python and
    docs.polymarket.us. requires_python>=3.10. Dependencies are
    httpx/pynacl/websockets — notably NO eth-account/eth-abi/eth-utils
    (the EVM-signing libraries international `polymarket-client`
    depends on). This alone is a strong structural signal that this
    venue does not use wallet/private-key order signing at all.
  - Auth: `PolymarketUS(key_id=, secret_key=)`. `auth.create_auth_headers()`
    signs `f"{timestamp}{method}{path}"` with an Ed25519 key (pynacl)
    and sends `X-PM-Access-Key` (key_id, a UUID) / `X-PM-Timestamp` /
    `X-PM-Signature` (base64) headers. There is no wallet/funder
    concept anywhere in this SDK.
  - Base URLs (verified via `inspect.signature(PolymarketUS.__init__)`):
    `api_base_url="https://api.polymarket.us"` (authenticated),
    `gateway_base_url="https://gateway.polymarket.us"` (public).
  - Market model: ONE tradeable contract per `marketSlug`
    (`markets.retrieve_by_slug(slug) -> MarketDetail`: id, slug, title,
    outcome, liquidity, volume, eventSlug — confirmed NO
    token_id/condition_id/outcomes-pair concept anywhere in the
    installed package). Direction is expressed as BUY_LONG ("YES") vs
    BUY_SHORT ("NO") on that SAME contract via `CreateOrderParams.intent`
    — not as two separate ERC-1155 tokens with their own order books.
    Schedule/timing lives on the EVENT, not the market
    (`events.list()/retrieve() -> Event`: startTime, endTime, markets:
    [Market...]) per the SDK's own type definitions — but CONFIRMED
    LIVE, a real event response does not reliably include `endTime` at
    all (one real btc-updown-15m-... event came back with no endTime
    key whatsoever, only startTime); see find_active_btc_market()'s and
    _to_binary_market()'s docstrings for how close_time is derived
    instead for this product. ALSO CONFIRMED LIVE: an event's own slug
    and its nested market's slug are NOT the same string — a real
    event slugged `btc-updown-15m-2026-10-07-2015z` contains a nested
    market slugged `cpc-btc-updown-15m-2026-10-07-2015z` — never
    assume a manually-provided or deterministically-constructed BTC
    slug is directly a market slug; it is the EVENT's slug, and the
    tradeable market must be read from that event's own `markets[0]`.
    A recurring product is modeled as a `Series`
    (`recurrence: str`) generating many Events — this is the SDK's own
    structural pattern for e.g. a daily/weekly game schedule, and is
    the most plausible home for a recurring 15-minute window product,
    but this has NOT been confirmed live (see NOT VERIFIED below).
  - Discovery: CONFIRMED LIVE (by the user, directly against the real
    Polymarket US site, not guessed) — the recurring 15-minute BTC
    Up/Down product's event slugs follow a fixed, predictable pattern:
    `btc-updown-15m-YYYY-MM-DD-HHMMz`, where HHMM is the UTC start of
    the 15-minute window (confirmed real example:
    `btc-updown-15m-2026-10-06-1745z`). find_active_btc_market() below
    computes the current window from `now` and looks up that EXACT
    event via `events.retrieve_by_slug(slug)` — never a text search,
    never "closest available." `search.query({"query": ...})` (the
    SDK's own documented topic-search method, used by an earlier
    version of this method) remains available as a read-only debug tool
    (scripts/verify_polymarket_setup.py --debug-discovery) but is no
    longer part of the trading discovery path at all.
  - Order book: `markets.book(slug) -> MarketBook(bids, offers:
    [OrderBookLevel(px: Amount, qty: str)], state: Literal[...])`. This
    module does NOT trust the API's own bid/offer array ordering (not
    documented anywhere found) — it explicitly re-sorts both sides
    itself (bids descending, offers ascending) before handing them to
    models.OrderBookSnapshot, which requires best-first.
  - Order construction: `orders.create(CreateOrderParams)` —
    marketSlug, intent (ORDER_INTENT_BUY_LONG/SELL_LONG/BUY_SHORT/
    SELL_SHORT), type (ORDER_TYPE_LIMIT/MARKET), price (Amount, a
    {value: str, currency: "USD"} struct), quantity (int — a CONTRACT
    COUNT, unlike the international SDK's `amount` which is a USD
    notional), tif (TIME_IN_FORCE_..., including
    TIME_IN_FORCE_FILL_OR_KILL — FOK is a time-in-force here, not a
    separate order_type enum). The response already includes
    `executions`, but per this codebase's "submission != fill" rule
    (reconciliation.py), that response is used ONLY for
    SubmissionOutcome — get_fill_status() always re-queries
    orders.retrieve() fresh, never trusting the submission response.
    CreateOrderParams ALSO has `synchronousExecution: bool` and
    `maxBlockTime: str` fields (confirmed in the installed SDK's own
    types.orders.CreateOrderParams) that _build_create_order_params()
    below does NOT set — meaning order creation is asynchronous by
    default: orders.create() returns once the order is ACCEPTED for
    processing, not once it reaches a terminal state. A live incident
    (order D0EEB7H1AZ7J: submitted, immediately read back via
    get_fill_status() as "unknown," only later resolved FILLED by a
    subsequent sweep) is consistent with this: an immediate
    orders.retrieve() call races the exchange's own async matching/
    kill decision for a FOK order and can land mid-flight. This is a
    RECOMMENDATION, not yet applied: setting synchronousExecution=True
    on the BUY path is a plausible fix for the immediate-UNKNOWN
    window specifically, but it changes real order-submission behavior
    and has not been verified live (this sandbox cannot reach
    polymarket.us) — confirm with orders.preview()/a careful live test
    before enabling it, exactly per this module's own "unverified"
    conventions below.
  - Cancellation: `orders.cancel(order_id, CancelOrderParams)` IS a
    real, documented endpoint (confirmed in the installed SDK's
    resources.orders.Orders.cancel — POST /v1/order/{id}/cancel,
    requiring just `marketSlug`) — see cancel_order() below. NOT part
    of the automated engine.py/gateway.py path as of this writing.
  - Order status: `Order.state` is a real, closed FIX-protocol-style
    enum (ORDER_STATE_NEW/PENDING_NEW/PARTIALLY_FILLED/FILLED/CANCELED/
    REJECTED/EXPIRED/...) with avgPx/cumQuantity/leavesQuantity fields
    — a better-typed authoritative-fill source than the international
    SDK's free-form OpenOrder.status string.
  - Settlement: `markets.settlement(slug) -> {slug, settlement: float}`
    — a single scalar (there is only one contract per market here, so
    there is no yes/no price PAIR to read the way international
    Polymarket's Market.outcomes.yes/no.price works).
  - `orders.preview(PreviewOrderParams)` exists and is a genuine,
    documented, order-SAFE dry run (never places anything) — use it
    (not implemented as a PolymarketClient-interface method yet, since
    neither venue's interface currently exposes a preview call) from
    scripts/verify_polymarket_setup.py or by hand to confirm pricing
    before ever trusting a BUY_SHORT ("NO") order live.

NOT independently verified against a live server (this sandbox cannot
reach polymarket.us at all — see module docstring above and
src/polymarket/__init__.py). Most importantly:
  1. Whether the deterministic slug pattern above holds for EVERY
     window, indefinitely (confirmed for one real, specific window by
     the user; not re-derived or guessed by this codebase). If
     Polymarket US ever changes this pattern, find_active_btc_market()
     will raise NoActiveMarketError (events.retrieve_by_slug() 404s) —
     treat that as "re-confirm the live pattern," never as a reason to
     fall back to a text search for trading.
  2. The exact book-side/pricing mechanics of a BUY_SHORT ("betting
     NO") order. RESOLVED BY REASONING, STILL NOT LIVE-CONFIRMED: this
     venue's MarketBook/MarketBBO types (polymarket_us.types.markets)
     have exactly ONE bids/offers (bid/ask) pair — there is no second,
     independent "NO" book or price field anywhere in the installed
     SDK's schema. The only coherent reading is that `price` is ALWAYS
     expressed on that one YES axis, for EVERY intent. _build_create_
     order_params() therefore converts a NO order's price via
     `1 - order.max_price` before submission (BUY_SHORT/SELL_SHORT),
     and get_fill_status() converts avgPx back the same way for a NO
     fill (reading the response's own `intent` to know which to do —
     see _OUTCOME_FOR_INTENT). This is NOT the same as the earlier,
     now-superseded assumption that NO reused YES's RAW price
     unconverted — that was wrong, and is exactly the class of
     latent bug a live orders.preview() call against a real NO
     candidate would have caught. STILL CONFIRM with orders.preview()
     before ever trusting this live — this sandbox cannot reach
     polymarket.us/docs.polymarket.us to verify it against a real
     response.
  3. Whether a retail API key_id/secret_key grants direct order-
     placement rights at all, versus Polymarket US's "intermediated
     access via futures commission merchants/brokerages" regulatory
     model (reported in the news around its CFTC relaunch) requiring a
     broker intermediary instead. The SDK's own bundled README shows
     orders.create() being called directly by a key_id/secret_key
     client with no broker step, which suggests this is at least
     possible for some account types — but this project has no live
     Polymarket US account to confirm which account type that is.
  4. The exact decimal/tick-size convention for `price.value` (this
     module formats to 2 decimal places, matching a standard
     cents-denominated event contract, but that precision has not been
     confirmed against a real order).
  5. Whether the bids/offers array in markets.book()'s response is
     already best-first (this module does not rely on this — see
     above — but the ASSUMPTION that `bids`/`offers` mean "buy-side"/
     "sell-side" at all, rather than some other convention, is still a
     reading of the type's field names, not a confirmed live response).
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, TypeVar

from src.polymarket.client import NoActiveMarketError, PolymarketClientError
from src.polymarket.models import (
    FILLED_STATUSES,
    BinaryMarket,
    BookLevel,
    FillResult,
    OrderBookSnapshot,
    OrderRequest,
    SubmissionOutcome,
)
from src.polymarket.settings import PolymarketSettings

# CreateOrderParams.intent for a BUY on each of our two outcomes — see
# module docstring item 2 for why the "NO"/BUY_SHORT mapping is the
# best-inferred, not confirmed, reading.
_INTENT_FOR_OUTCOME = {"YES": "ORDER_INTENT_BUY_LONG", "NO": "ORDER_INTENT_BUY_SHORT"}

# CreateOrderParams.intent for CLOSING an existing position in each
# outcome — i.e. a SELL (exit_manager.py's profit-target exit is the
# only caller). Confirmed directly from the installed polymarket-us
# SDK's own OrderIntent Literal (polymarket_us.types.orders), not
# guessed: closing a YES/LONG position is ORDER_INTENT_SELL_LONG;
# closing a NO/SHORT position is ORDER_INTENT_SELL_SHORT. These are
# full closes of what BUY_LONG/BUY_SHORT opened above — never a naked
# short (there is no path in this codebase that submits a SELL without
# an existing OpenPosition behind it — see exit_manager.py).
_CLOSE_INTENT_FOR_OUTCOME = {"YES": "ORDER_INTENT_SELL_LONG", "NO": "ORDER_INTENT_SELL_SHORT"}

# OrderRequest.order_type -> CreateOrderParams.tif. FOK/FAK are both
# real TimeInForce values on this venue (TIME_IN_FORCE_FILL_OR_KILL /
# TIME_IN_FORCE_IMMEDIATE_OR_CANCEL), confirmed in
# polymarket_us.types.orders.CreateOrderParams's own Literal.
_TIF_FOR_ORDER_TYPE = {"FOK": "TIME_IN_FORCE_FILL_OR_KILL", "FAK": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL"}

# Market discovery (see find_active_btc_market's docstring): the
# recurring BTC Up/Down product's fixed slug prefix, confirmed LIVE by
# the user against the real Polymarket US site (real example:
# btc-updown-15m-2026-10-06-1745z) — not derived from settings.asset
# ("bitcoin"), which is a different string.
_BTC_UPDOWN_SLUG_PREFIX = "btc-updown"

# settings.market_duration_minutes -> the slug's cadence token. ONLY
# 15 ("15m") has been confirmed live. Do not add another entry (e.g.
# 60 -> "1h") by guessing/analogy -- confirm the real slug for that
# cadence the same way first (events.retrieve_by_slug on a hand-built
# guess will 404 harmlessly if wrong, which is how 15m's pattern
# should be re-confirmed too if Polymarket US ever changes it).
_SLUG_CADENCE_TOKENS: dict[int, str] = {
    15: "15m",
}

# Inverse of _expected_event_slug's f-string, for _parse_btc_updown_window_from_slug
# below: btc-updown-<cadence>-YYYY-MM-DD-HHMMz. Confirmed LIVE (real example:
# btc-updown-15m-2026-10-07-2015z) -- this is the SAME pattern _BTC_UPDOWN_SLUG_PREFIX/
# _SLUG_CADENCE_TOKENS already encode, just parsed instead of built.
_BTC_UPDOWN_SLUG_RE = re.compile(
    rf"^{re.escape(_BTC_UPDOWN_SLUG_PREFIX)}-(?P<cadence>[a-z0-9]+)-"
    rf"(?P<year>\d{{4}})-(?P<month>\d{{2}})-(?P<day>\d{{2}})-(?P<hhmm>\d{{4}})z$"
)

# Order.state -> this system's FillStatus vocabulary (models.py). Only
# states with cumQuantity > 0 may map to "filled"/"partially_filled" —
# get_fill_status() enforces that itself rather than trusting this map
# alone, per Task 3's "never fabricate a fill."
_TERMINAL_NON_FILL_STATE = {
    "ORDER_STATE_CANCELED": "cancelled",
    "ORDER_STATE_REJECTED": "rejected",
    "ORDER_STATE_EXPIRED": "expired",
}
_RESTING_STATES = frozenset({
    "ORDER_STATE_NEW", "ORDER_STATE_PENDING_NEW", "ORDER_STATE_PENDING_REPLACE",
    "ORDER_STATE_PENDING_CANCEL", "ORDER_STATE_PENDING_RISK", "ORDER_STATE_REPLACED",
})

# Inverse of _INTENT_FOR_OUTCOME/_CLOSE_INTENT_FOR_OUTCOME above -- used
# by get_fill_status() to know whether a fill's avgPx (always reported
# on this venue's single YES axis -- see _build_create_order_params's
# docstring) needs converting back into this system's own NO-terms
# convention before it is ever stored as OpenPosition.avg_fill_price.
_OUTCOME_FOR_INTENT = {
    "ORDER_INTENT_BUY_LONG": "YES", "ORDER_INTENT_SELL_LONG": "YES",
    "ORDER_INTENT_BUY_SHORT": "NO", "ORDER_INTENT_SELL_SHORT": "NO",
}


class PolymarketUSClientError(PolymarketClientError):
    pass


class _OrderTooSmallError(PolymarketUSClientError):
    """Internal signal from _build_create_order_params() — caught by
    place_order() and converted into a SubmissionOutcome(ok=False);
    left to propagate from preview_order() since that method's whole
    contract is "raise if this order could never actually be placed."
    """


def _sdk():
    """Lazy import of polymarket-us, so pure-logic modules/tests never
    need it installed — same convention as client.py's _sdk()."""
    try:
        import polymarket_us
    except ImportError as exc:
        raise PolymarketUSClientError(
            "polymarket-us is not installed — run `pip install polymarket-us` "
            "(see pyproject.toml's `polymarket-us` extra). Import name is "
            "`polymarket_us` — a completely different package from the "
            "international `polymarket`/`polymarket-client` SDK; see this "
            "module's docstring."
        ) from exc
    return polymarket_us


_T = TypeVar("_T")
_logger = logging.getLogger(__name__)


def _retry_on_rate_limit(
    action: Callable[[], _T], *, endpoint: str, max_retries: int, base_delay_seconds: float,
    max_delay_seconds: float, sleep: Callable[[float], None] | None = None,
) -> _T:
    """Calls `action()` (a zero-arg callable wrapping ONE read-only
    polymarket_us SDK call) and transparently retries ONLY on
    polymarket_us.errors.RateLimitError (a 429 — the real incident
    this exists for was a Cloudflare 1015 "You are being rate limited"
    response from gateway.polymarket.us that reached
    engine.run_cycle() as an UNCAUGHT exception via get_order_book()
    and crashed the bot), with BOUNDED exponential backoff and full
    jitter. Every OTHER exception type propagates immediately,
    unretried and unchanged — a NotFoundError/AuthenticationError/etc.
    means something else is wrong, and this function has no business
    deciding how a caller's EXISTING handling for that should behave.

    Backoff is `min(max_delay_seconds, base_delay_seconds * 2**attempt)`,
    then the ACTUAL sleep is a uniformly random jitter in [0, that]
    (AWS's well-known "full jitter" algorithm) — bounded by
    max_delay_seconds regardless of how many retries have already
    happened, and never a synchronized retry storm across multiple
    cycles/processes hammering the same already-rate-limited endpoint
    (requirement: never retry immediately, never increase request
    frequency).

    Never retries more than `max_retries` times. If the LAST attempt
    still raises RateLimitError, RE-RAISES it — this function never
    invents a "no data" result on its own; callers (get_order_book(),
    find_active_btc_market(), etc.) are responsible for degrading
    safely from there, exactly as they already do for any other
    exception a read-only call can raise (see each method's own
    docstring).

    Every attempt is logged via the standard `logging` module —
    endpoint, that a rate limit was detected, the retry number, and
    the backoff — deliberately keeping this low-level client decoupled
    from PolymarketDecisionLogger (see module docstring). The FINAL
    degraded outcome, once retries exhaust, is logged by whichever
    caller actually decides how to degrade (engine.py/exit_manager.py),
    since only they know what "no trade"/"skip this position" means
    for that specific call site.

    If polymarket_us itself is not installed, this degrades to a pure
    passthrough (calls `action()` once, propagates whatever it raises,
    unchanged) rather than raising on the attempt to even look up the
    real RateLimitError class — preserving this module's test contract
    (see test_polymarket_us_client.py's own docstring: these tests
    exercise a FAKE sdk_client and must never require the real SDK
    package to be installed just to run)."""
    try:
        rate_limit_error: type[BaseException] | tuple[()] = _sdk().errors.RateLimitError
    except PolymarketUSClientError:
        rate_limit_error = ()  # SDK not installed -- nothing can ever match a real RateLimitError; never retry
    sleep = sleep or time.sleep  # resolved at CALL time, not binding time -- lets tests monkeypatch module-level time.sleep
    attempt = 0
    while True:
        try:
            result = action()
        except rate_limit_error as exc:
            if attempt >= max_retries:
                _logger.warning(
                    "polymarket_us %s: rate limited -- exhausted all %d retries, giving up (%s)",
                    endpoint, max_retries, exc,
                )
                raise
            delay = min(max_delay_seconds, base_delay_seconds * (2 ** attempt))
            backoff = random.uniform(0, delay)
            attempt += 1
            _logger.warning(
                "polymarket_us %s: rate limited (retry %d/%d), backing off %.2fs before retrying (%s)",
                endpoint, attempt, max_retries, backoff, exc,
            )
            sleep(backoff)
            continue
        if attempt > 0:
            _logger.info("polymarket_us %s: succeeded after %d retry/retries", endpoint, attempt)
        return result


def _retry_on_not_found(
    action: Callable[[], _T], *, endpoint: str, max_retries: int, base_delay_seconds: float,
    max_delay_seconds: float, sleep: Callable[[float], None] | None = None,
) -> _T:
    """Calls `action()` (a zero-arg callable wrapping ONE read-only
    polymarket_us SDK call against a SPECIFIC, already-known market
    slug — never a search, never a fallback) and transparently retries
    ONLY on polymarket_us.errors.NotFoundError, with bounded
    exponential backoff and full jitter — the NEW-MARKET BOOK WARMUP
    RACE: live evidence (twice) showed a brand-new BTC 15m market's
    exact nested market slug, already confirmed present on its own
    freshly-discovered event with real time remaining, 404 on
    markets.book() for a few seconds before the SAME exact slug
    returned a healthy order book with no other change. This is a
    GENUINELY DIFFERENT transient condition from a 429 rate limit
    (_retry_on_rate_limit above) — it is about this one market's own
    book not being indexed YET, never about request volume — so it is
    its own function with its own settings bounds
    (us_book_warmup_max_retries/base_delay_seconds/max_delay_seconds),
    never conflated with the rate-limit retry's bounds.

    Every OTHER exception type (including a GENUINE 404 for a market
    that was never going to exist, which this function cannot tell
    apart from a warmup race by the exception alone) still only gets
    retried up to `max_retries` times within a SHORT bounded window
    (a few seconds total at the configured defaults) before this
    re-raises — never an infinite loop, never a silent fallback to a
    different market, and never a reason for find_active_btc_market()
    to search for or substitute something else. The caller (engine.py,
    via get_order_book()'s own propagation) is responsible for
    degrading to a safe no-trade/skip-this-cycle outcome once this
    gives up, exactly as it already does for any other exception a
    read-only call can raise.

    Logged via the standard `logging` module, like
    _retry_on_rate_limit — `endpoint` is expected to carry the EXACT
    market slug this attempt is for (e.g. "markets.book(cpc-btc-
    updown-15m-2026-10-10-1845z)"), so every retry/recovery/give-up
    line is independently traceable to the exact market, without this
    function needing its own slug parameter.

    If polymarket_us itself is not installed, this degrades to a pure
    passthrough (calls `action()` once, propagates whatever it raises,
    unchanged) — same convention as _retry_on_rate_limit, and for the
    same reason (this module's tests exercise a FAKE sdk_client and
    must never require the real SDK package to be installed)."""
    try:
        not_found_error: type[BaseException] | tuple[()] = _sdk().errors.NotFoundError
    except PolymarketUSClientError:
        not_found_error = ()  # SDK not installed -- nothing can ever match a real NotFoundError; never retry
    sleep = sleep or time.sleep  # resolved at CALL time, not binding time -- lets tests monkeypatch module-level time.sleep
    attempt = 0
    while True:
        try:
            result = action()
        except not_found_error as exc:
            if attempt >= max_retries:
                _logger.warning(
                    "polymarket_us %s: book still unavailable after %d warmup retries, giving up (%s)",
                    endpoint, max_retries, exc,
                )
                raise
            delay = min(max_delay_seconds, base_delay_seconds * (2 ** attempt))
            backoff = random.uniform(0, delay)
            attempt += 1
            _logger.info(
                "polymarket_us %s: book temporarily unavailable (new-market warmup, retry %d/%d), "
                "retrying in %.2fs (%s)",
                endpoint, attempt, max_retries, backoff, exc,
            )
            sleep(backoff)
            continue
        if attempt > 0:
            _logger.info("polymarket_us %s: book became available after %d warmup retry/retries", endpoint, attempt)
        return result


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_btc_updown_window_from_slug(
    slug: str | None, *, market_duration_minutes: int,
) -> tuple[datetime, datetime] | None:
    """Confirmed LIVE: for this product, the event slug itself IS the
    schedule (btc-updown-15m-YYYY-MM-DD-HHMMz, HHMM = UTC window
    start) -- the inverse of _expected_event_slug's construction.
    Used as the close-time source for this product's events because
    the live API's own endTime field is confirmed ABSENT on at least
    one real event response (see _to_binary_market's module docstring
    note) -- deriving from the slug avoids requiring a field the API
    doesn't reliably send, without guessing at a different field name
    instead.

    Returns None (never raises) for any slug that doesn't match the
    pattern, or whose cadence token isn't the one currently configured
    -- callers fall back to endTime for those, since this function has
    no basis to assume non-BTC-15m products follow the same scheme."""
    if not slug:
        return None
    match = _BTC_UPDOWN_SLUG_RE.match(slug)
    if match is None:
        return None
    cadence_token = _SLUG_CADENCE_TOKENS.get(market_duration_minutes)
    if cadence_token is None or match.group("cadence") != cadence_token:
        return None
    try:
        start = datetime(
            int(match.group("year")), int(match.group("month")), int(match.group("day")),
            int(match.group("hhmm")[:2]), int(match.group("hhmm")[2:]), tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    return start, start + timedelta(minutes=market_duration_minutes)


def _parse_amount(amount: Any) -> float | None:
    if not amount:
        return None
    value = amount.get("value") if isinstance(amount, dict) else None
    if value is None:
        return None
    return float(value)


def _level(raw: dict) -> BookLevel:
    price = _parse_amount(raw.get("px"))
    size = float(raw.get("qty", 0) or 0)
    return BookLevel(price=price if price is not None else 0.0, size=size)


def _parse_str_float(raw: Any) -> float | None:
    """MarketStats.sharesTraded/openInterest are plain numeric strings
    (not an Amount struct, unlike lastTradePx/highPx/lowPx) — confirmed
    in the installed SDK's types.markets.MarketStats. Returns None for
    anything missing/blank rather than a fabricated 0.0."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    return float(raw)


class PolymarketUSClient:
    """Implements client.PolymarketClient's method surface for the US
    venue. Structurally duck-typed, not a subclass — see module
    docstring. `token_id`/`condition_id` throughout this class are
    always the US venue's `marketSlug`: there is only one order book
    per contract here, so BinaryMarket.token_id_yes == token_id_no ==
    the same slug (direction comes from OrderRequest.outcome, mapped
    to BUY_LONG/BUY_SHORT below — see _INTENT_FOR_OUTCOME)."""

    def __init__(self, settings: PolymarketSettings, *, sdk_client: Any = None):
        self._settings = settings
        # sdk_client: test injection point for a fake polymarket_us.PolymarketUS
        # -- production callers always leave this None and let _client()
        # build the real one lazily.
        self._client_override = sdk_client
        self._client_instance: Any = None

    def _client(self):
        if self._client_override is not None:
            return self._client_override
        if self._client_instance is not None:
            return self._client_instance
        pm = _sdk()
        self._client_instance = pm.PolymarketUS(
            key_id=self._settings.us_key_id,
            secret_key=self._settings.us_secret_key,
            api_base_url=self._settings.us_api_base_url,
            gateway_base_url=self._settings.us_gateway_base_url,
        )
        return self._client_instance

    def close(self) -> None:
        client = self._client_override or self._client_instance
        if client is not None:
            client.close()

    def _retry(self, action: Callable[[], _T], *, endpoint: str) -> _T:
        """Bound convenience wrapper over _retry_on_rate_limit() using
        this client's own settings.us_rate_limit_* bounds — every
        READ-ONLY call site below goes through this, never
        place_order() (order submission is never automatically
        retried — see place_order's own docstring)."""
        return _retry_on_rate_limit(
            action, endpoint=endpoint, max_retries=self._settings.us_rate_limit_max_retries,
            base_delay_seconds=self._settings.us_rate_limit_base_delay_seconds,
            max_delay_seconds=self._settings.us_rate_limit_max_delay_seconds,
        )

    def _retry_book_warmup(self, action: Callable[[], _T], *, endpoint: str) -> _T:
        """Bound convenience wrapper over _retry_on_not_found() using
        this client's own settings.us_book_warmup_* bounds — ONLY
        get_order_book() goes through this (see its own docstring);
        never place_order() or any other read-only call, since this is
        specifically the NEW-MARKET BOOK WARMUP RACE, not a general
        "retry any 404" policy."""
        return _retry_on_not_found(
            action, endpoint=endpoint, max_retries=self._settings.us_book_warmup_max_retries,
            base_delay_seconds=self._settings.us_book_warmup_base_delay_seconds,
            max_delay_seconds=self._settings.us_book_warmup_max_delay_seconds,
        )

    # --- Market discovery (public data, no credentials needed) ---------------
    def find_active_btc_market(self, *, now: datetime | None = None) -> BinaryMarket:
        """Deterministic discovery — CONFIRMED LIVE by the user against
        the real Polymarket US site (not guessed, not inferred): the
        recurring BTC Up/Down product's event slugs follow a fixed
        pattern, `btc-updown-15m-YYYY-MM-DD-HHMMz` (real example:
        btc-updown-15m-2026-10-06-1745z), where HHMM is the UTC start
        of the current 15-minute window.

        Computes that exact slug for the CURRENT window from `now` and
        looks it up directly via events.retrieve_by_slug() — never a
        text search, never "closest available," never a fallback to a
        different market. An earlier version of this method used
        search.query() with title/pattern heuristics; that approach is
        retired from the trading path entirely (search.query() remains
        available only as a read-only debug tool — see
        scripts/verify_polymarket_setup.py --debug-discovery).

        If the exact expected event doesn't exist, isn't open, or
        doesn't verify as being on the expected schedule (see
        _verify_expected_event), this sits the cycle out
        (NoActiveMarketError) rather than trading anything else —
        "no trade" is always a safe outcome; a wrong market never is.

        MANUAL OVERRIDE: when settings.us_market_slug is set (TEMPORARY,
        test-only — see settings.py's module docstring), this method
        retrieves ONLY that exact market/event instead, via
        _get_manual_override_market() — BTC 15m discovery below is
        completely bypassed, not just de-prioritized. Unsetting
        us_market_slug restores the exact behavior documented above
        with zero other change.
        """
        now = now or datetime.now(timezone.utc)
        if self._settings.us_market_slug:
            return self._get_manual_override_market(self._settings.us_market_slug, now=now)

        window_start, window_end = self._current_window(now)
        expected_slug = self._expected_event_slug(window_start)

        client = self._client()
        try:
            response = self._retry(lambda: client.events.retrieve_by_slug(expected_slug), endpoint="events.retrieve_by_slug")
        except Exception as exc:  # noqa: BLE001 - not-found, a transport failure, or exhausted rate-limit retries all mean "nothing to trade this cycle"
            raise NoActiveMarketError(
                f"Expected Polymarket US event {expected_slug!r} for the current "
                f"{self._settings.market_duration_minutes}-minute window "
                f"({window_start.isoformat()}–{window_end.isoformat()}) was not found or could not "
                f"be fetched ({type(exc).__name__}: {exc}) — sitting this cycle out rather than "
                "trading a fallback market."
            ) from exc

        event = response.get("event") or {}
        self._verify_expected_event(event, expected_slug=expected_slug, window_start=window_start, window_end=window_end)
        markets = event.get("markets") or []
        if not markets:
            raise PolymarketUSClientError(f"Event {expected_slug!r} has no markets")
        return self._to_binary_market(event, markets[0], now=now)

    def _get_manual_override_market(self, slug: str, *, now: datetime) -> BinaryMarket:
        """TEMPORARY, test-only exact-market override (see settings.py's
        module docstring on POLYMARKET_US_MARKET_SLUG). Retrieves ONLY
        this exact slug — no search, no "closest available," no
        fallback to BTC 15m discovery.

        `slug` is treated as an EVENT slug — CONFIRMED LIVE: a slug
        copied from the Polymarket US app's event URL (e.g.
        btc-updown-15m-2026-10-07-2015z) is an event slug, and the
        nested TRADEABLE market it contains has its OWN, different
        slug (confirmed live: a "cpc-" prefixed internal slug, e.g.
        cpc-btc-updown-15m-2026-10-07-2015z) — never assumed equal to
        the event slug. events.retrieve_by_slug() is the one call made
        here; the event's own slug/active/closed fields, and then the
        nested market's own active/closed fields, are verified before
        either is trusted — anything that doesn't resolve and verify
        cleanly raises NoActiveMarketError rather than silently
        falling back to something else.
        """
        client = self._client()
        try:
            event_response = self._retry(lambda: client.events.retrieve_by_slug(slug), endpoint="events.retrieve_by_slug")
        except Exception as exc:  # noqa: BLE001
            raise NoActiveMarketError(
                f"POLYMARKET_US_MARKET_SLUG={slug!r} could not be retrieved as an event "
                f"(events.retrieve_by_slug): {type(exc).__name__}: {exc}. Verify the exact "
                "event slug from the Polymarket US app."
            ) from exc

        event = event_response.get("event")
        if event is None or event.get("slug") != slug:
            raise NoActiveMarketError(
                f"POLYMARKET_US_MARKET_SLUG={slug!r}: events.retrieve_by_slug() returned a "
                "mismatched or empty event — refusing to trade it."
            )
        if not event.get("active") or event.get("closed"):
            raise NoActiveMarketError(f"Event {slug!r} exists but is not active/open right now.")

        markets = event.get("markets") or []
        if not markets:
            raise NoActiveMarketError(f"Event {slug!r} has no markets to trade.")
        market = markets[0]
        if not market.get("active") or market.get("closed"):
            raise NoActiveMarketError(f"Market {market.get('slug')!r} exists but is not active/open right now.")

        return self._to_binary_market(event, market, now=now)

    def _current_window(self, now: datetime) -> tuple[datetime, datetime]:
        """Floors `now` to the start of the current
        market_duration_minutes-wide UTC window."""
        minutes = self._settings.market_duration_minutes
        floored_minute = (now.minute // minutes) * minutes
        window_start = now.replace(minute=floored_minute, second=0, microsecond=0)
        window_end = window_start + timedelta(minutes=minutes)
        return window_start, window_end

    def _expected_event_slug(self, window_start: datetime) -> str:
        cadence_token = _SLUG_CADENCE_TOKENS.get(self._settings.market_duration_minutes)
        if cadence_token is None:
            raise PolymarketUSClientError(
                f"No confirmed Polymarket US slug cadence token for "
                f"POLYMARKET_MARKET_DURATION_MINUTES={self._settings.market_duration_minutes} — only "
                f"15 ('15m', confirmed live: {_BTC_UPDOWN_SLUG_PREFIX}-15m-2026-10-06-1745z) is "
                "currently supported. Add a new entry to _SLUG_CADENCE_TOKENS only after confirming "
                "the real slug pattern for that cadence live — never by guessing/analogy."
            )
        return f"{_BTC_UPDOWN_SLUG_PREFIX}-{cadence_token}-{window_start:%Y-%m-%d-%H%M}z"

    def _verify_expected_event(
        self, event: dict, *, expected_slug: str, window_start: datetime, window_end: datetime,
    ) -> None:
        """Defense in depth: even though the slug was constructed
        deterministically, never trust the response blindly. Verifies
        the returned event actually IS the one requested and is
        currently open — raising NoActiveMarketError (never silently
        substituting a different market) on any mismatch.

        startTime/endTime are cross-checked against the expected
        window ONLY WHEN PRESENT: CONFIRMED LIVE, the real API's
        response for this product does not reliably include endTime
        at all (a real btc-updown-15m-... event was returned
        successfully with no endTime key), so their absence is never
        itself a rejection reason — the slug match above (which
        deterministically encodes the same window — see
        _parse_btc_updown_window_from_slug) is this check's primary
        defense. A few seconds of tolerance on the start/end
        comparison absorbs harmless response-formatting precision, not
        a genuine scheduling mismatch."""
        actual_slug = event.get("slug")
        if actual_slug != expected_slug:
            raise NoActiveMarketError(
                f"Expected event slug {expected_slug!r} but the API returned {actual_slug!r} — "
                "refusing to trade a mismatched event."
            )
        if not event.get("active") or event.get("closed"):
            raise NoActiveMarketError(f"Event {expected_slug!r} exists but is not active/open right now.")

        start = _parse_dt(event.get("startTime"))
        end = _parse_dt(event.get("endTime"))
        if start is not None and abs((start - window_start).total_seconds()) > 5:
            raise NoActiveMarketError(
                f"Event {expected_slug!r} startTime={start.isoformat()} does not match the expected "
                f"window start {window_start.isoformat()}."
            )
        if end is not None and abs((end - window_end).total_seconds()) > 5:
            raise NoActiveMarketError(
                f"Event {expected_slug!r} endTime={end.isoformat()} does not match the expected "
                f"window end {window_end.isoformat()}."
            )

    def _to_binary_market(self, event: dict, market: dict, *, now: datetime) -> BinaryMarket:
        """CONFIRMED LIVE: the event's own slug and its nested market's
        slug are NOT the same string -- a real response for event
        btc-updown-15m-2026-10-07-2015z contains a nested market
        slugged cpc-btc-updown-15m-2026-10-07-2015z. condition_id uses
        the EVENT's slug (the stable, human-meaningful identifier the
        rest of this system and the trader both deal in); token_id_yes/
        token_id_no use the nested MARKET's own slug (the id
        markets.book()/orders.create() actually need -- see
        get_order_book()/_build_create_order_params()). Never assume
        these are equal.

        close_time: ALSO confirmed live, the API does not reliably
        include endTime on this product's event responses at all (a
        real event came back with no endTime key whatsoever). For an
        event slug matching the confirmed btc-updown-<cadence>-
        YYYY-MM-DD-HHMMz pattern, the window end is derived directly
        from the slug itself (_parse_btc_updown_window_from_slug) --
        the slug IS the schedule for this product. Only for a
        non-matching slug (a manually-overridden non-BTC market, where
        no such pattern is confirmed) does this fall back to endTime;
        if that is ALSO absent, this raises rather than guess at a
        different field name (expirationTime/closeTime/endDate/etc)."""
        event_slug = event.get("slug")
        if not event_slug:
            raise PolymarketUSClientError("Event has no slug")
        market_slug = market.get("slug")
        if not market_slug:
            raise PolymarketUSClientError(f"Event {event_slug!r}'s market has no slug")
        _logger.info("polymarket_us: market discovered event=%s nested_market_slug=%s", event_slug, market_slug)

        window = _parse_btc_updown_window_from_slug(
            event_slug, market_duration_minutes=self._settings.market_duration_minutes,
        )
        if window is not None:
            close_time = window[1]
        else:
            close_time = _parse_dt(event.get("endTime"))
            if close_time is None:
                raise PolymarketUSClientError(
                    f"Event {event_slug!r} has no endTime, and its slug does not match the confirmed "
                    f"{_BTC_UPDOWN_SLUG_PREFIX}-<cadence>-YYYY-MM-DD-HHMMz pattern to derive a close "
                    "time from instead -- refusing to guess a different field name. Run "
                    "scripts/verify_polymarket_setup.py --market-slug <slug> --debug-exact-slug to "
                    "see the real response shape."
                )

        yes_bid = yes_ask = None
        try:
            book = self.get_order_book(market_slug)
            yes_bid, yes_ask = book.best_bid, book.best_ask
        except Exception:  # noqa: BLE001 - this summary price is a convenience for strategy.py's signal only
            pass

        return BinaryMarket(
            condition_id=event_slug, question=event.get("title") or market.get("title") or "",
            token_id_yes=market_slug, token_id_no=market_slug,
            close_time=close_time, fetched_at=now, yes_bid=yes_bid, yes_ask=yes_ask,
        )

    def refresh(self, market: BinaryMarket) -> BinaryMarket:
        book = self.get_order_book(market.token_id_yes)
        return replace(market, yes_bid=book.best_bid, yes_ask=book.best_ask, fetched_at=datetime.now(timezone.utc))

    def get_order_book(self, token_id: str) -> OrderBookSnapshot:
        """`token_id` is the marketSlug (see class docstring). Re-sorts
        both sides itself — see module docstring item 5 on why this
        never trusts the API's own array ordering.

        Also parses `marketData.stats` (MarketStats: lastTradePx,
        sharesTraded, highPx, lowPx, openInterest) into
        OrderBookSnapshot's additive stats fields — real data this
        SAME call already returns, previously parsed and discarded.
        `stats` itself, or any field within it, may legitimately be
        absent (confirmed optional in the SDK's own MarketBook/
        MarketStats TypedDicts) — every field defaults to None in that
        case, never a fabricated value. See btc_intelligence.py's
        assess_polymarket_microstructure() for how these feed a real
        (if coarse) executed-trade/activity signal.

        TWO independent, bounded retry layers wrap this call, nested
        with the book-warmup retry OUTSIDE the rate-limit retry (each
        full rate-limit-resilient attempt counts as ONE book-warmup
        attempt):
          - A polymarket_us.errors.RateLimitError (429 — a real
            incident saw a Cloudflare 1015 "You are being rate
            limited" response from gateway.polymarket.us here
            specifically) is retried with bounded backoff via
            _retry().
          - A polymarket_us.errors.NotFoundError for THIS exact slug
            is retried with its OWN bounded backoff via
            _retry_book_warmup() — the NEW-MARKET BOOK WARMUP RACE
            (live evidence, twice: a brand-new market's exact nested
            slug, already confirmed present on its own freshly-
            discovered event, 404s on markets.book() for a few
            seconds before the SAME exact slug returns a healthy
            book). `endpoint` is parameterized with `token_id` here
            specifically (unlike the rate-limit retry's generic
            "markets.book") so every warmup retry/recovery/give-up
            log line is traceable to the EXACT market slug.
        If either retry exhausts, this still RAISES — callers
        (engine.py's entry path, take_profit.py's exit sweep) are
        responsible for catching that and degrading to a safe no-
        trade/skip-this-position outcome, exactly as they already do
        for any other exception this call can raise. NEVER retries
        order SUBMISSION, and never substitutes a different market —
        only this exact token_id's own book is ever retried.
        """
        client = self._client()
        raw = self._retry_book_warmup(
            lambda: self._retry(lambda: client.markets.book(token_id), endpoint="markets.book"),
            endpoint=f"markets.book({token_id})",
        )
        data = raw["marketData"]
        bids = tuple(sorted((_level(lvl) for lvl in data.get("bids") or []), key=lambda lvl: lvl.price, reverse=True))
        asks = tuple(sorted((_level(lvl) for lvl in data.get("offers") or []), key=lambda lvl: lvl.price))
        stats = data.get("stats") or {}
        return OrderBookSnapshot(
            token_id=token_id, bids=bids, asks=asks, fetched_at=datetime.now(timezone.utc),
            last_trade_price=_parse_amount(stats.get("lastTradePx")),
            shares_traded=_parse_str_float(stats.get("sharesTraded")),
            session_high=_parse_amount(stats.get("highPx")),
            session_low=_parse_amount(stats.get("lowPx")),
            open_interest=_parse_str_float(stats.get("openInterest")),
        )

    def get_resolution(self, condition_id: str) -> str | None:
        """`condition_id` is this market's EVENT slug — the same
        identifier BinaryMarket.condition_id/OpenPosition.condition_id
        carry (see _to_binary_market) — NOT the nested market's own
        slug, which is confirmed to differ (e.g. event
        btc-updown-15m-2026-10-07-2015z's nested market is
        cpc-btc-updown-15m-2026-10-07-2015z). Looks the EVENT up via
        events.retrieve_by_slug() (the confirmed-working call — see
        _get_manual_override_market), takes its nested market, and
        checks THAT market's own closed/settlement state — never
        assumes the event slug is itself a queryable market slug via
        markets.retrieve_by_slug().

        UNVERIFIED (see module docstring): markets.settlement(slug)'s
        scalar `settlement` value is assumed to mean 1.0="YES"(long)
        won, 0.0="NO" won — the most natural reading for a
        single-contract binary market, never confirmed against a real
        resolved market."""
        client = self._client()
        try:
            event_response = self._retry(lambda: client.events.retrieve_by_slug(condition_id), endpoint="events.retrieve_by_slug")
        except Exception:  # noqa: BLE001 - not-found, a transport failure, or exhausted rate-limit retries all mean "don't know yet"
            return None
        event = event_response.get("event") or {}
        markets = event.get("markets") or []
        if not markets:
            return None
        market_slug = markets[0].get("slug")
        if not market_slug or not markets[0].get("closed"):
            return None
        try:
            settlement = self._retry(lambda: client.markets.settlement(market_slug), endpoint="markets.settlement")
        except Exception:  # noqa: BLE001 - same as above
            return None
        value = settlement.get("settlement")
        if value is None:
            return None
        return "YES" if float(value) >= 0.5 else "NO"

    def _build_create_order_params(self, order: OrderRequest) -> dict:
        """Shared by place_order() and preview_order() so a preview
        reflects EXACTLY what a real submission would send — never two
        independent constructions that could silently diverge.

        BUY (entry) and SELL (exit_manager.py's profit-target exit) are
        built from genuinely different fields, on purpose:
          - BUY derives `quantity` from size_usd/max_price (a USD
            budget, floored to whole contracts at the ceiling price).
          - SELL uses `order.quantity` VERBATIM — an exact share count
            exit_manager.py set from the position's own filled_shares.
            Deriving it the BUY way instead (from a synthesized size_usd)
            was tried and rejected: a 100k-trial randomized check found
            floor-division reconstruction mismatches the intended share
            count roughly half the time under ordinary floating-point
            imprecision, which is unacceptable for closing an exact
            position size.
        `order.max_price` is ALWAYS in the OUTCOME'S OWN probability/
        cost terms — for YES that's the real YES-axis price directly;
        for NO it's the real price a NO buyer/holder pays or receives
        (computed by the caller from single_book.to_no_perspective()'s
        derived book — see engine.py/take_profit.py), never the raw
        YES-axis number. This venue has exactly ONE real order book,
        priced entirely on the YES axis — there is no separate "NO
        price" field in CreateOrderParams, so a NO order's price must
        be converted to the corresponding YES-axis value before it is
        ever sent: api_price = 1 - order.max_price. This is the ONLY
        coherent reading of the single order book/single price-field
        schema (MarketBook has exactly one bids/offers pair, never a
        second "NO" pair — confirmed in the installed polymarket-us
        SDK's own types.markets.MarketBook) and matches exactly how
        this system's own NO-side math already works: going short
        (BUY_SHORT) by crossing the real YES bid at price P is
        economically identical to a NO buyer paying (1 - P); closing a
        NO/short position (SELL_SHORT) by crossing the real YES ask at
        price P realizes NO proceeds of (1 - P) for the holder. NOT
        independently confirmed against a live order (this sandbox
        cannot reach polymarket.us/docs.polymarket.us) — confirm with
        orders.preview() before this is ever relied on live, per this
        module's own "unverified" conventions above.

        Applies uniformly to BUY and SELL: for a BUY (entry),
        order.max_price is the outcome's own ceiling; for a SELL
        (exit_manager.py's profit-target exit) it is read as the
        outcome's own FLOOR (the minimum acceptable sale price, i.e.
        the position's own profit-target price). The conversion only
        ever touches the FINAL `price` field sent to the exchange —
        `quantity` (a contract count, sized from size_usd/order.max_price
        for a BUY) is computed from the SAME outcome-own-terms
        max_price, since cost-per-contract is correctly expressed in
        that same axis either way.
        """
        tif = _TIF_FOR_ORDER_TYPE.get(order.order_type)
        if tif is None:
            raise PolymarketUSClientError(f"Unsupported order_type {order.order_type!r} for Polymarket US tif mapping")

        if order.side == "BUY":
            intent = _INTENT_FOR_OUTCOME.get(order.outcome)
            if intent is None:
                raise PolymarketUSClientError(f"Unsupported outcome {order.outcome!r} for a Polymarket US order intent")
            # quantity is a CONTRACT COUNT on this venue (unlike the
            # international SDK's USD-notional `amount`) — see module
            # docstring. Floors to whole contracts at the ceiling price, so
            # the actual spend is never more than size_usd.
            quantity = int(order.size_usd // order.max_price)
            if quantity <= 0:
                raise _OrderTooSmallError(
                    f"size_usd={order.size_usd} / max_price={order.max_price} rounds down to 0 whole "
                    "contracts — refusing to submit a zero-quantity order."
                )
        elif order.side == "SELL":
            intent = _CLOSE_INTENT_FOR_OUTCOME.get(order.outcome)
            if intent is None:
                raise PolymarketUSClientError(f"Unsupported outcome {order.outcome!r} for a Polymarket US closing order intent")
            if not order.quantity:
                raise PolymarketUSClientError(
                    "A SELL (exit) order requires OrderRequest.quantity to be set explicitly to the "
                    "exact share count being closed — exit_manager.py must always set this from the "
                    "position's own filled_shares; it is never derived from size_usd/max_price for a SELL."
                )
            quantity = order.quantity
        else:
            raise PolymarketUSClientError(f"Unsupported side {order.side!r}")

        # Convert to this venue's single YES-axis price convention --
        # see this method's own docstring above. YES needs no
        # conversion (the outcome's own terms ARE the YES axis); NO
        # does, unconditionally, since this venue always has exactly
        # one book.
        api_price = round(1 - order.max_price, 4) if order.outcome == "NO" else order.max_price

        return {
            "marketSlug": order.token_id, "intent": intent, "type": "ORDER_TYPE_LIMIT",
            "price": {"value": f"{api_price:.2f}", "currency": "USD"},
            "quantity": quantity, "tif": tif,
        }

    # --- Order placement (implements gateway.py's PolymarketOrderPlacer) -----
    def place_order(self, order: OrderRequest) -> SubmissionOutcome:
        """Submits a BUY (entry) or SELL (exit_manager.py's
        profit-target exit — see _build_create_order_params) order.
        Returns a SubmissionOutcome — NOT a fill determination; see
        models.SubmissionOutcome's docstring and reconciliation.py. The
        response's own `executions` are
        deliberately IGNORED for fill purposes (see module docstring:
        get_fill_status() always re-queries fresh) but the COMPLETE raw
        response is preserved verbatim in `raw` regardless -- a real
        incident (an order submitted successfully, whose exchange_order_id
        then 404'd on orders.retrieve()) showed that discarding anything
        beyond `executions` means that diagnostic information is gone
        forever the moment this process exits, with no way to
        investigate afterward.

        Deliberately NEVER goes through _retry()/_retry_on_rate_limit():
        this is the one SDK call that actually SUBMITS something.
        Automatically retrying a RateLimitError here could resubmit an
        order the exchange may have already accepted before the 429
        was returned — see the module docstring's note on
        AuthenticationError/BadRequestError/RateLimitError/etc. already
        being treated uniformly as "no exchange_order_id, nothing to
        reconcile" below, which is the correct, safe degrade for ANY of
        those, including a rate limit, with zero risk of a duplicate
        submission."""
        try:
            params = self._build_create_order_params(order)
        except _OrderTooSmallError as exc:
            return SubmissionOutcome(
                ok=False, exchange_order_id=None, raw_status=None,
                error_code="quantity_too_small", error_message=str(exc),
            )

        client = self._client()
        try:
            response = client.orders.create(params)
        except Exception as exc:  # noqa: BLE001 - the SDK raises AuthenticationError/BadRequestError/
            # RateLimitError/NotFoundError/APITimeoutError/APIConnectionError/PermissionDeniedError/
            # InternalServerError for failures that never reach an accept-or-reject decision from the
            # exchange at all — there is no exchange_order_id to reconcile in any of those cases.
            return SubmissionOutcome(
                ok=False, exchange_order_id=None, raw_status=None,
                error_code=type(exc).__name__, error_message=str(exc),
            )

        order_id = response.get("id")
        if not order_id:
            return SubmissionOutcome(
                ok=False, exchange_order_id=None, raw_status=None, error_code="no_order_id",
                error_message="orders.create() returned no order id — treating as a failed submission.",
            )
        return SubmissionOutcome(
            ok=True, exchange_order_id=str(order_id), raw_status="submitted",
            raw=dict(response),  # the COMPLETE orders.create() response, not just a subset
        )

    def preview_order(self, order: OrderRequest) -> dict:
        """Read-only dry run via orders.preview() — a genuine,
        documented, order-safe endpoint distinct from orders.create();
        NEVER places anything. Uses the EXACT SAME parameter
        construction as place_order() (_build_create_order_params), so
        a preview reflects precisely what a real submission would
        send. Returns the raw PreviewOrderResponse's `order` dict (the
        SDK's own projected Order shape) for a caller to inspect — this
        is a manual-test/diagnostic helper (see
        scripts/manual_polymarket_us_test.py), not part of the
        automated engine.py/gateway.py path, which is why it returns a
        raw dict rather than a models.py type. Raises on an invalid or
        too-small order — never silently "previews" something that
        could never actually be submitted."""
        params = self._build_create_order_params(order)
        client = self._client()
        response = self._retry(lambda: client.orders.preview({"request": params}), endpoint="orders.preview")
        return response.get("order") or {}

    def cancel_order(self, exchange_order_id: str, market_slug: str) -> bool:
        """Cancels a resting order via orders.cancel() — CONFIRMED a
        real, documented endpoint in the installed polymarket-us SDK
        (POST /v1/order/{order_id}/cancel, CancelOrderParams requiring
        just marketSlug), verified directly from
        polymarket_us.resources.orders.Orders.cancel's own source
        rather than assumed. NOT part of the automated engine.py/
        gateway.py path as of this writing — added as a tested,
        available capability (same "built, not yet wired in" status
        preview_order() already has above) for a live incident's own
        market-close question: whether a still-unresolved entry order
        can be proactively canceled once its market's close_time
        arrives, rather than left to resolve on its own time (see
        reconciliation.py's STALE-ENTRY SAFETY NET for how a late fill
        is handled if this is never called).

        Best-effort and NEVER raises: cancelling an order that has
        already reached a terminal state (filled/canceled/rejected/
        expired) is an expected, harmless outcome on most venues, not
        a bug in the caller — and this system must never treat "the
        cancel attempt itself failed" as a reason to skip the
        authoritative fill lookup that always follows it (a genuine
        fill must still be reconciled regardless of whether a cancel
        was also attempted). Returns True only on a confirmed
        successful cancel; False for every other outcome (already
        terminal, not found, transport failure, ...) — callers that
        care about the real end state must still call get_fill_status()
        afterward, exactly as they already do today."""
        client = self._client()
        try:
            client.orders.cancel(exchange_order_id, {"marketSlug": market_slug})
        except Exception as exc:  # noqa: BLE001 - any failure here (already terminal, not found, transport) is a safe, expected no-op
            _logger.info(
                "polymarket_us orders.cancel: order %s on %s could not be canceled (%s: %s) -- "
                "treating as a no-op; the next fill-status lookup remains authoritative",
                exchange_order_id, market_slug, type(exc).__name__, exc,
            )
            return False
        return True

    # --- Reconciliation (the authoritative fill lookup — see Task 3/5) -------
    def get_fill_status(self, exchange_order_id: str) -> FillResult:
        """The ONLY place this system reads "how much actually filled"
        for a US-venue order. Always a fresh orders.retrieve() lookup —
        never derived from place_order()'s own response. Returns
        status="unknown" for anything this system can't confidently
        interpret, per Task 3's "fail closed, do not fabricate a fill."
        """
        client = self._client()
        try:
            response = self._retry(lambda: client.orders.retrieve(exchange_order_id), endpoint="orders.retrieve")
        except Exception as exc:  # noqa: BLE001 - order-not-found, a transport failure, or exhausted rate-limit retries all mean "we don't know" here
            return FillResult(
                order_id=exchange_order_id, status="unknown", requested_shares=0.0,
                filled_shares=0.0, avg_fill_price=None, raw={"lookup_error": str(exc)},
            )

        order = response.get("order") or {}
        state = order.get("state")
        requested = float(order.get("quantity", 0) or 0)
        cum = float(order.get("cumQuantity", 0) or 0)

        if cum <= 0:
            if state in _TERMINAL_NON_FILL_STATE:
                status = _TERMINAL_NON_FILL_STATE[state]
            elif state in _RESTING_STATES:
                status = "resting"
            else:
                status = "unknown"
            return FillResult(
                order_id=exchange_order_id, status=status, requested_shares=requested,
                filled_shares=0.0, avg_fill_price=None, raw={"state": state},
            )

        if state not in ("ORDER_STATE_FILLED", "ORDER_STATE_PARTIALLY_FILLED"):
            # Defensive: a nonzero cumQuantity should only ever appear with
            # FILLED/PARTIALLY_FILLED. If the exchange ever reports otherwise,
            # fail closed rather than guess — see FillResult's own validation,
            # which would reject filled_shares>0 on a non-fill status anyway.
            return FillResult(
                order_id=exchange_order_id, status="unknown", requested_shares=requested,
                filled_shares=0.0, avg_fill_price=None, raw={"state": state, "unexpected_cum_quantity": cum},
            )

        avg_price = _parse_amount(order.get("avgPx"))
        if avg_price is None:
            return FillResult(
                order_id=exchange_order_id, status="unknown", requested_shares=requested,
                filled_shares=0.0, avg_fill_price=None, raw={"state": state, "missing_avg_px": True},
            )
        # avgPx is ALWAYS reported on this venue's single YES axis,
        # regardless of intent (see _build_create_order_params's
        # docstring) -- a NO (BUY_SHORT/SELL_SHORT) fill's own
        # avg_fill_price, in THIS system's outcome-own-terms convention,
        # is the complement. Fails closed (status="unknown") rather
        # than guess if the response's own intent is missing or
        # unrecognized -- never silently store a YES-axis price as a
        # NO position's cost basis, which would corrupt every
        # downstream take_profit.py target/P&L computation for it.
        outcome = _OUTCOME_FOR_INTENT.get(order.get("intent"))
        if outcome is None:
            return FillResult(
                order_id=exchange_order_id, status="unknown", requested_shares=requested,
                filled_shares=0.0, avg_fill_price=None, raw={"state": state, "unrecognized_intent": order.get("intent")},
            )
        if outcome == "NO":
            avg_price = round(1 - avg_price, 4)
        status = "filled" if cum >= requested else "partially_filled"
        assert status in FILLED_STATUSES  # sanity check against models.py's own vocabulary
        # Order.commissionNotionalTotalCollected (confirmed in the
        # installed SDK's types.orders.Order) is this order's actual,
        # cumulative exchange commission in USD, when reported — used by
        # exit_manager.py to compute NET realized P&L on a profit-target
        # exit rather than assuming the gross price move alone was
        # profitable (see its docstring). _parse_amount() already
        # returns None (never a fabricated 0.0) when the field is absent.
        fee_usd = _parse_amount(order.get("commissionNotionalTotalCollected"))
        return FillResult(
            order_id=exchange_order_id, status=status, requested_shares=requested,
            filled_shares=cum, avg_fill_price=avg_price, raw={"state": state}, fee_usd=fee_usd,
        )

    def get_balance_usdc(self) -> float:
        """Despite the name (kept for interface symmetry with
        client.PolymarketClient — see scripts/verify_polymarket_setup.py),
        Polymarket US balances are plain USD cash, not on-chain USDC;
        there is no wallet/collateral concept on this venue. Returns
        the USD UserBalance entry's currentBalance."""
        client = self._client()
        response = self._retry(lambda: client.account.balances(), endpoint="account.balances")
        for balance in response.get("balances") or []:
            if balance.get("currency") == "USD":
                return float(balance.get("currentBalance", 0.0))
        raise PolymarketUSClientError("No USD balance entry found in account.balances() response")
