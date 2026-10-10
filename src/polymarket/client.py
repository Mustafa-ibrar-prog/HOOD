"""Real network client for Polymarket — the only module that may ever
call the Polymarket API. Wraps the OFFICIAL `polymarket-client` SDK
(PyPI name `polymarket-client`, import name `polymarket`).

Research trail (see the conversation this was built in for the full
primary-source verification — summarized here so the next person
doesn't have to redo it):

  - `py-clob-client` (the SDK the previous version of this file used)
    is ARCHIVED. Its own GitHub README (raw.githubusercontent.com,
    fetched directly, NOT a summarized/rendered page) carries a literal
    warning banner: "This repository has been archived and is no
    longer maintained. The client is no longer functional and should
    not be used for new or existing integrations. Please migrate to
    our new unified SDK: https://github.com/Polymarket/py-sdk". Its
    PyPI long_description does NOT carry this notice (it's stale,
    unrelated to the real GitHub state) — do not trust PyPI's
    long_description alone for a maintenance-status claim; GitHub's
    raw README is the primary source here.
  - `polymarket-client` (PyPI, import `polymarket`) is the real
    successor: published by "Polymarket Engineering
    <engineering@polymarket.com>", actively released (0.3.0b2 through
    0.12.0, July-Sept 2026), `requires_python>=3.11`. Confirmed by
    reading the actual source of github.com/Polymarket/py-sdk (raw
    files, not a summary): `src/polymarket/clients/secure.py`,
    `src/polymarket/models/clob/{order_response,order_book,account,
    orders,api_key}.py`.
  - Order placement: `SecureClient.place_market_order(token_id=,
    side="BUY"/"SELL", amount=(BUY)/shares=(SELL), max_price=/min_price=,
    order_type: MarketOrderType = "FAK")` creates, signs, and posts a
    market order in one call, returning `OrderResponse =
    AcceptedOrder | RejectedOrder` (discriminated by `.ok`).
    `MarketOrderType = Literal["FAK", "FOK"]` — market orders can ONLY
    be FAK or FOK, never resting; this system defaults to FOK (see
    models.OrderRequest's docstring).
  - Fill status is NEVER read from the post-order response's
    making_amount/taking_amount here — get_fill_status() always does a
    fresh, separate lookup via `SecureClient.get_order(order_id=)` ->
    `OpenOrder` (whose `size_matched`/`original_size` fields are this
    system's definition of "actually filled"), per Task 3's explicit
    "never fabricate a fill, inspect the actual API response."
  - Order book: `SecureClient.get_order_book(token_id=) -> OrderBook`
    with `bids`/`asks: tuple[OrderBookLevel, ...]`. Verified SDK
    convention (straight from order_book.py's own repr code): bids
    ascending (best/highest LAST), asks descending (best/lowest LAST).
    This module normalizes both to best-first before handing them to
    models.OrderBookSnapshot, so that convention never leaks past this
    file.
  - Auth: `SecureClient.create(private_key=, wallet=, credentials=)`.
    `private_key` is a REQUIRED keyword even when `credentials` (a
    pre-derived `ApiKeyCreds`) is also supplied — every order is
    EIP-712-signed by the private key regardless of how L2 REST auth is
    established. See settings.py's fail-closed check for this.

NOT independently verified against a LIVE server response: this module
was written in a network-sandboxed environment that cannot reach
polymarket.com (confirmed on both gamma-api.polymarket.com and
clob.polymarket.com — see src/polymarket/__init__.py). Everything above
is verified against the SDK's real, current SOURCE CODE (not
documentation, not a summary, not an assumption) — but no call in this
file has actually executed against the live API. Before trusting this
with real funds, run scripts/verify_polymarket_setup.py somewhere with
network access.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.polymarket.models import (
    BinaryMarket,
    BookLevel,
    FillResult,
    OrderBookSnapshot,
    OrderRequest,
    SubmissionOutcome,
)
from src.polymarket.settings import PolymarketSettings

# Defensive bound on how many trade pages get_fill_status() will scan
# looking for this order's fills — list_account_trades has no order_id
# filter (verified: its real signature only takes asset_id/token_id/id/
# market/maker_address/after/before), so matching is client-side over a
# time-and-token-bounded window. A real fill for a 15-minute market's
# order is always recent; this many pages is already generous.
_MAX_TRADE_PAGES_SCANNED = 5


class PolymarketClientError(RuntimeError):
    pass


class NoActiveMarketError(PolymarketClientError):
    """Raised by find_active_btc_market() when no market matching the
    configured asset/duration is currently open. Callers must treat this
    as "sit this cycle out," never silently fall back to a different
    market than the one actually configured."""


def _sdk():
    """Lazy import of polymarket-client, so pure-logic modules/tests
    (models.py, risk.py, strategy.py, gateway.py, positions.py,
    reconciliation.py, and their tests) never need it installed."""
    try:
        import polymarket
    except ImportError as exc:
        raise PolymarketClientError(
            "polymarket-client is not installed — run `pip install polymarket-client` "
            "(see pyproject.toml). Import name is `polymarket`, NOT `py_clob_client` — "
            "that package is archived; see this module's docstring."
        ) from exc
    return polymarket


class PolymarketClient:
    def __init__(self, settings: PolymarketSettings):
        self._settings = settings
        self._public = None
        self._secure = None

    # --- Client construction, lazy so discovery-only / paper-mode callers
    # never need credentials or the SDK installed at import time -----------
    def _public_client(self):
        if self._public is not None:
            return self._public
        pm = _sdk()
        self._public = pm.PublicClient()
        return self._public

    def _secure_client(self):
        if self._secure is not None:
            return self._secure
        if not self._settings.private_key:
            raise PolymarketClientError(
                "No POLYMARKET_PRIVATE_KEY configured — required for any authenticated call "
                "(order placement, order status, balance). See .env.polymarket.example. "
                "settings.py's fail-closed check should have already caught this for live "
                "mode; reaching here means something constructed a client without going "
                "through PolymarketSettings.from_env()'s validation."
            )
        pm = _sdk()
        credentials = None
        if self._settings.api_key and self._settings.api_secret and self._settings.api_passphrase:
            credentials = pm.ApiKeyCreds(
                key=self._settings.api_key, secret=self._settings.api_secret, passphrase=self._settings.api_passphrase,
            )
        self._secure = pm.SecureClient.create(
            private_key=self._settings.private_key,
            wallet=self._settings.funder_address,
            credentials=credentials,
        )
        return self._secure

    def close(self) -> None:
        if self._secure is not None:
            self._secure.close()
        if self._public is not None:
            self._public.close()

    # --- Market discovery (public data, no credentials needed) ---------------
    def find_active_btc_market(self, *, now: datetime | None = None) -> BinaryMarket:
        """Finds the open market for settings.asset whose duration is
        closest to settings.market_duration_minutes, among markets
        closing within roughly the next 3 target-durations (a window
        wide enough to not miss one near a boundary, narrow enough to
        stay a cheap query).

        UNVERIFIED (see module docstring): list_markets() has no direct
        keyword-search parameter, so "bitcoin" matching is done
        client-side against `market.question`. If this starts raising
        NoActiveMarketError in a real run with bitcoin markets visibly
        live on polymarket.com, check this filter first — not the
        reconciliation/risk logic elsewhere in this package.
        """
        now = now or datetime.now(timezone.utc)
        client = self._public_client()
        target_seconds = self._settings.market_duration_minutes * 60
        window_end = now + timedelta(seconds=target_seconds * 3)

        best = None
        best_diff: float | None = None
        for market in client.list_markets(closed=False, end_date_min=now, end_date_max=window_end, page_size=50):
            question = (market.question or "").lower()
            if self._settings.asset not in question:
                continue
            state = market.state
            if state.start_date is None or state.end_date is None or state.end_date <= now:
                continue
            duration = (state.end_date - state.start_date).total_seconds()
            diff = abs(duration - target_seconds)
            if best_diff is None or diff < best_diff:
                best, best_diff = market, diff

        if best is None:
            raise NoActiveMarketError(
                f"No open {self._settings.asset} market found near "
                f"{self._settings.market_duration_minutes} minutes in duration right now."
            )
        return self._to_binary_market(best, now=now)

    def _to_binary_market(self, market: Any, *, now: datetime) -> BinaryMarket:
        if market.condition_id is None:
            raise PolymarketClientError(f"Market {market.id!r} has no condition_id")
        yes_token = market.outcomes.yes.token_id
        no_token = market.outcomes.no.token_id
        if not yes_token or not no_token:
            raise PolymarketClientError(f"Market {market.condition_id!r} is missing a token_id for one or both outcomes")
        close_time = market.state.end_date
        if close_time is None:
            raise PolymarketClientError(f"Market {market.condition_id!r} has no end_date")

        yes_bid = yes_ask = None
        try:
            book = self.get_order_book(str(yes_token))
            yes_bid, yes_ask = book.best_bid, book.best_ask
        except Exception:  # noqa: BLE001 - this summary price is a convenience for strategy.py's signal only; get_order_book() is the source of truth callers that need it should call directly
            pass

        return BinaryMarket(
            condition_id=str(market.condition_id), question=market.question or "",
            token_id_yes=str(yes_token), token_id_no=str(no_token),
            close_time=close_time, fetched_at=now, yes_bid=yes_bid, yes_ask=yes_ask,
        )

    def refresh(self, market: BinaryMarket) -> BinaryMarket:
        """Re-fetches just the YES order book for an already-known
        market — far cheaper than find_active_btc_market() for a
        strategy polling the same market every poll_interval_seconds."""
        from dataclasses import replace
        book = self.get_order_book(market.token_id_yes)
        return replace(market, yes_bid=book.best_bid, yes_ask=book.best_ask, fetched_at=datetime.now(timezone.utc))

    def get_order_book(self, token_id: str) -> OrderBookSnapshot:
        """Public data — no credentials needed. Normalizes the SDK's
        ascending-bids/descending-asks-with-best-at-index[-1] shape
        into this system's own best-first convention (see module
        docstring) so that detail never leaks past this file."""
        client = self._public_client()
        book = client.get_order_book(token_id=token_id)
        bids = tuple(BookLevel(price=float(lvl.price), size=float(lvl.size)) for lvl in reversed(book.bids))
        asks = tuple(BookLevel(price=float(lvl.price), size=float(lvl.size)) for lvl in reversed(book.asks))
        return OrderBookSnapshot(token_id=token_id, bids=bids, asks=asks, fetched_at=datetime.now(timezone.utc))

    def get_resolution(self, condition_id: str) -> str | None:
        """Returns "YES"/"NO" if this market has resolved, else None.

        Verified fix (found by installing polymarket-client==0.12.0 and
        inspecting its real pydantic models directly, not docs): an
        earlier version of this method called
        `client.get_market(id=condition_id)` — but `Market.id` and
        `Market.condition_id` are TWO DIFFERENT fields
        (`Market.model_fields` confirms `id: NewType` is a required,
        distinct field from the optional `condition_id: NewType | None`,
        aliased from the API's `conditionId`), and `get_market(id=...)`
        builds its request path from that `id`, not `condition_id`. This
        system never learns a market's internal `id` — only its
        `condition_id` (see BinaryMarket) — so the old call could only
        ever 404 or, worse, silently resolve the wrong market if `id`
        and `condition_id` ever collided in format. `list_markets()`
        has a real, correctly-wired `condition_ids` filter (confirmed in
        `polymarket/_internal/actions/gamma.py`), which is the right way
        to look a market up by the identifier this system actually has.

        STILL UNVERIFIED against a live resolved market (see module
        docstring): `state.closed` plus `outcomes.yes/no.price` snapping
        to 0/1 is the best-effort resolution signal available from the
        verified Market model; confirm against a real resolved market
        before relying on it.
        """
        client = self._public_client()
        market = next(iter(client.list_markets(condition_ids=condition_id, page_size=1)), None)
        if market is None or not market.state.closed:
            return None
        yes_price = market.outcomes.yes.price
        if yes_price is None:
            return None
        return "YES" if yes_price >= 0.5 else "NO"

    # --- Order placement (implements gateway.py's PolymarketOrderPlacer) -----
    def place_order(self, order: OrderRequest) -> SubmissionOutcome:
        """Submits an order. Returns a SubmissionOutcome — NOT a fill
        determination; see models.SubmissionOutcome's docstring and
        reconciliation.py. Never raises for a rejection the exchange
        itself reports (ok=False with error_code set); only raises for
        a transport/client-side failure that never reached a real
        accept-or-reject decision."""
        if order.side != "BUY":
            raise PolymarketClientError("SELL is not supported — v1 scope is entries only (see positions.py)")

        client = self._secure_client()
        try:
            response = client.place_market_order(
                token_id=order.token_id, side="BUY", amount=order.size_usd,
                max_price=order.max_price, order_type=order.order_type,
            )
        except Exception as exc:  # noqa: BLE001 - the SDK raises UserInputError/InsufficientLiquidityError/
            # InsufficientAllowanceError/SigningError/RequestRejectedError for failures that
            # never reach an accept-or-reject decision from the exchange at all — there is no
            # exchange_order_id to reconcile in any of those cases.
            return SubmissionOutcome(
                ok=False, exchange_order_id=None, raw_status=None,
                error_code=type(exc).__name__, error_message=str(exc),
            )

        if response.ok:
            return SubmissionOutcome(
                ok=True, exchange_order_id=str(response.order_id), raw_status=str(response.status),
                raw={
                    "making_amount": str(response.making_amount), "taking_amount": str(response.taking_amount),
                    "trade_ids": list(response.trade_ids),
                },
            )
        return SubmissionOutcome(
            ok=False, exchange_order_id=None, raw_status=None,
            error_code=str(response.code), error_message=response.message,
        )

    # --- Reconciliation (the authoritative fill lookup — see Task 3/5) -------
    def get_fill_status(self, exchange_order_id: str) -> FillResult:
        """The ONLY place this system reads "how much actually filled."
        Always a fresh lookup — never derived from place_order()'s own
        response. Returns status="unknown" (never "filled") for
        anything this system can't confidently interpret, per Task 3's
        "fail closed, do not fabricate a fill."
        """
        try:
            client = self._secure_client()
            order = client.get_order(order_id=exchange_order_id)
        except Exception as exc:  # noqa: BLE001 - order-not-found or a transport failure both mean "we don't know" here
            return FillResult(
                order_id=exchange_order_id, status="unknown", requested_shares=0.0,
                filled_shares=0.0, avg_fill_price=None, raw={"lookup_error": str(exc)},
            )

        requested = float(order.original_size)
        filled = float(order.size_matched)
        status_word = (order.status or "").lower()

        if filled <= 0:
            if "cancel" in status_word:
                status = "cancelled"
            elif "expir" in status_word:
                status = "expired"
            elif "live" in status_word or "open" in status_word or "matched" in status_word:
                # "matched" with filled==0 shouldn't happen, but a live/open
                # order genuinely resting unfilled is a real, valid state —
                # see models.OrderRequest's docstring: FOK/FAK should never
                # actually land here (they're never resting), but this path
                # exists for correctness if that assumption is ever wrong.
                status = "resting"
            else:
                status = "unknown"
            return FillResult(
                order_id=exchange_order_id, status=status, requested_shares=requested,
                filled_shares=0.0, avg_fill_price=None, raw={"status": order.status},
            )

        avg_price = self._weighted_avg_fill_price(
            exchange_order_id, token_id=str(order.asset_id), created_at=order.created_at, fallback_price=float(order.price),
        )
        status = "filled" if filled >= requested else "partially_filled"
        return FillResult(
            order_id=exchange_order_id, status=status, requested_shares=requested,
            filled_shares=filled, avg_fill_price=avg_price, raw={"status": order.status},
        )

    def _weighted_avg_fill_price(
        self, exchange_order_id: str, *, token_id: str, created_at: datetime, fallback_price: float,
    ) -> float:
        """Volume-weighted average of this order's own real trades —
        more precise than OpenOrder.price (the order's limit/bound
        price, not necessarily what was actually paid across multiple
        maker counterparties). Falls back to that limit price, clearly
        documented as an approximation, only if no matching trade is
        found despite size_matched > 0 (e.g. settlement-record lag) —
        the FILL itself is still verified via get_order(); only the
        exact price is approximated in that edge case, which is not
        the same as fabricating the fill."""
        client = self._secure_client()
        window_start = (created_at - timedelta(seconds=5)).isoformat()
        total_size = 0.0
        total_notional = 0.0
        pages_scanned = 0
        for trade in client.list_account_trades(token_id=token_id, after=window_start):
            if getattr(trade, "taker_order_id", None) == exchange_order_id:
                total_size += float(trade.size)
                total_notional += float(trade.size) * float(trade.price)
            pages_scanned += 1
            if pages_scanned >= _MAX_TRADE_PAGES_SCANNED * 50:  # Paginator yields items, not pages; bound by item count
                break
        if total_size > 0:
            return round(total_notional / total_size, 6)
        return fallback_price

    def get_balance_usdc(self) -> float:
        """Best-effort USDC collateral balance check before sizing a
        real bet. Callers must not assume this succeeds; a risk check
        that needs a hard balance guarantee should treat an exception
        here as "unknown, don't trade," not "assume funded." Balance is
        returned in base units (6 decimals for USDC) by the SDK."""
        client = self._secure_client()
        balance = client.get_balance_allowance(asset_type="COLLATERAL")
        return balance.balance / 1_000_000


def get_polymarket_client(settings: PolymarketSettings) -> Any:
    """Venue-selecting factory — see settings.py's module docstring on
    POLYMARKET_VENUE. Returns whichever client implementation matches
    settings.venue; both PolymarketClient (this module, international)
    and PolymarketUSClient (us_client.py) expose the identical method
    surface (find_active_btc_market, get_order_book, get_resolution,
    place_order, get_fill_status, get_balance_usdc, refresh, close), so
    every other module in this package — engine.py, gateway.py,
    reconciliation.py — never needs to know or care which one it got.
    Imports us_client lazily to avoid a module-level import cycle (that
    module imports NoActiveMarketError/PolymarketClientError from here)."""
    if settings.is_us_venue:
        from src.polymarket.us_client import PolymarketUSClient
        return PolymarketUSClient(settings)
    return PolymarketClient(settings)
