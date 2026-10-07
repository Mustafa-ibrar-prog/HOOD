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
    [Market...]). A recurring product is modeled as a `Series`
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
     NO") order. This module maps "NO" to ORDER_INTENT_BUY_SHORT with
     the SAME price/quantity/tif construction as "YES" (ORDER_INTENT_
     BUY_LONG) — the most defensible reading of CreateOrderParams'
     shape, but UNVERIFIED. Confirm with orders.preview() before
     trusting this live.
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

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

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


class PolymarketUSClientError(PolymarketClientError):
    pass


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
        """
        now = now or datetime.now(timezone.utc)
        window_start, window_end = self._current_window(now)
        expected_slug = self._expected_event_slug(window_start)

        client = self._client()
        try:
            response = client.events.retrieve_by_slug(expected_slug)
        except Exception as exc:  # noqa: BLE001 - not-found or a transport failure both mean "nothing to trade this cycle"
            raise NoActiveMarketError(
                f"Expected Polymarket US event {expected_slug!r} for the current "
                f"{self._settings.market_duration_minutes}-minute window "
                f"({window_start.isoformat()}–{window_end.isoformat()}) was not found or could not "
                f"be fetched ({type(exc).__name__}: {exc}) — sitting this cycle out rather than "
                "trading a fallback market."
            ) from exc

        event = response.get("event") or {}
        self._verify_expected_event(event, expected_slug=expected_slug, window_start=window_start, window_end=window_end)
        return self._to_binary_market(event, now=now)

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
        the returned event actually IS the one requested, is currently
        open, and is on the exact expected schedule — raising
        NoActiveMarketError (never silently substituting a different
        market) on any mismatch. A few seconds of tolerance on the
        start/end comparison absorbs harmless response-formatting
        precision, not a genuine scheduling mismatch."""
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
        if start is None or end is None:
            raise NoActiveMarketError(f"Event {expected_slug!r} is missing startTime/endTime.")
        if abs((start - window_start).total_seconds()) > 5:
            raise NoActiveMarketError(
                f"Event {expected_slug!r} startTime={start.isoformat()} does not match the expected "
                f"window start {window_start.isoformat()}."
            )
        if abs((end - window_end).total_seconds()) > 5:
            raise NoActiveMarketError(
                f"Event {expected_slug!r} endTime={end.isoformat()} does not match the expected "
                f"window end {window_end.isoformat()}."
            )

    def _to_binary_market(self, event: dict, *, now: datetime) -> BinaryMarket:
        markets = event.get("markets") or []
        if not markets:
            raise PolymarketUSClientError(f"Event {event.get('slug')!r} has no markets")
        market = markets[0]
        slug = market.get("slug")
        if not slug:
            raise PolymarketUSClientError(f"Event {event.get('slug')!r}'s market has no slug")
        close_time = _parse_dt(event.get("endTime"))
        if close_time is None:
            raise PolymarketUSClientError(f"Event {event.get('slug')!r} has no endTime")

        yes_bid = yes_ask = None
        try:
            book = self.get_order_book(slug)
            yes_bid, yes_ask = book.best_bid, book.best_ask
        except Exception:  # noqa: BLE001 - this summary price is a convenience for strategy.py's signal only
            pass

        return BinaryMarket(
            condition_id=slug, question=event.get("title") or market.get("title") or "",
            token_id_yes=slug, token_id_no=slug,
            close_time=close_time, fetched_at=now, yes_bid=yes_bid, yes_ask=yes_ask,
        )

    def refresh(self, market: BinaryMarket) -> BinaryMarket:
        book = self.get_order_book(market.token_id_yes)
        return replace(market, yes_bid=book.best_bid, yes_ask=book.best_ask, fetched_at=datetime.now(timezone.utc))

    def get_order_book(self, token_id: str) -> OrderBookSnapshot:
        """`token_id` is the marketSlug (see class docstring). Re-sorts
        both sides itself — see module docstring item 5 on why this
        never trusts the API's own array ordering."""
        client = self._client()
        raw = client.markets.book(token_id)
        data = raw["marketData"]
        bids = tuple(sorted((_level(lvl) for lvl in data.get("bids") or []), key=lambda lvl: lvl.price, reverse=True))
        asks = tuple(sorted((_level(lvl) for lvl in data.get("offers") or []), key=lambda lvl: lvl.price))
        return OrderBookSnapshot(token_id=token_id, bids=bids, asks=asks, fetched_at=datetime.now(timezone.utc))

    def get_resolution(self, condition_id: str) -> str | None:
        """`condition_id` is the marketSlug. UNVERIFIED (see module
        docstring): markets.settlement(slug)'s scalar `settlement`
        value is assumed to mean 1.0="YES"(long) won, 0.0="NO" won —
        the most natural reading for a single-contract binary market,
        never confirmed against a real resolved market."""
        client = self._client()
        try:
            detail = client.markets.retrieve_by_slug(condition_id)
        except Exception:  # noqa: BLE001 - not-found or a transport failure both mean "don't know yet"
            return None
        market = detail.get("market") or {}
        if not market.get("closed"):
            return None
        try:
            settlement = client.markets.settlement(condition_id)
        except Exception:  # noqa: BLE001 - same as above
            return None
        value = settlement.get("settlement")
        if value is None:
            return None
        return "YES" if float(value) >= 0.5 else "NO"

    # --- Order placement (implements gateway.py's PolymarketOrderPlacer) -----
    def place_order(self, order: OrderRequest) -> SubmissionOutcome:
        """Submits an order. Returns a SubmissionOutcome — NOT a fill
        determination; see models.SubmissionOutcome's docstring and
        reconciliation.py. The response's own `executions` are
        deliberately ignored here for exactly that reason — see module
        docstring: get_fill_status() always re-queries fresh."""
        if order.side != "BUY":
            raise PolymarketUSClientError("SELL is not supported — v1 scope is entries only (see positions.py)")
        intent = _INTENT_FOR_OUTCOME.get(order.outcome)
        if intent is None:
            raise PolymarketUSClientError(f"Unsupported outcome {order.outcome!r} for a Polymarket US order intent")
        tif = _TIF_FOR_ORDER_TYPE.get(order.order_type)
        if tif is None:
            raise PolymarketUSClientError(f"Unsupported order_type {order.order_type!r} for Polymarket US tif mapping")

        # quantity is a CONTRACT COUNT on this venue (unlike the
        # international SDK's USD-notional `amount`) — see module
        # docstring. Floors to whole contracts at the ceiling price, so
        # the actual spend is never more than size_usd.
        quantity = int(order.size_usd // order.max_price)
        if quantity <= 0:
            return SubmissionOutcome(
                ok=False, exchange_order_id=None, raw_status=None, error_code="quantity_too_small",
                error_message=(
                    f"size_usd={order.size_usd} / max_price={order.max_price} rounds down to 0 "
                    "whole contracts — refusing to submit a zero-quantity order."
                ),
            )

        client = self._client()
        try:
            response = client.orders.create({
                "marketSlug": order.token_id,
                "intent": intent,
                "type": "ORDER_TYPE_LIMIT",
                "price": {"value": f"{order.max_price:.2f}", "currency": "USD"},
                "quantity": quantity,
                "tif": tif,
            })
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
            raw={"executions": response.get("executions", [])},
        )

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
            response = client.orders.retrieve(exchange_order_id)
        except Exception as exc:  # noqa: BLE001 - order-not-found or a transport failure both mean "we don't know" here
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
        status = "filled" if cum >= requested else "partially_filled"
        assert status in FILLED_STATUSES  # sanity check against models.py's own vocabulary
        return FillResult(
            order_id=exchange_order_id, status=status, requested_shares=requested,
            filled_shares=cum, avg_fill_price=avg_price, raw={"state": state},
        )

    def get_balance_usdc(self) -> float:
        """Despite the name (kept for interface symmetry with
        client.PolymarketClient — see scripts/verify_polymarket_setup.py),
        Polymarket US balances are plain USD cash, not on-chain USDC;
        there is no wallet/collateral concept on this venue. Returns
        the USD UserBalance entry's currentBalance."""
        client = self._client()
        response = client.account.balances()
        for balance in response.get("balances") or []:
            if balance.get("currency") == "USD":
                return float(balance.get("currentBalance", 0.0))
        raise PolymarketUSClientError("No USD balance entry found in account.balances() response")
