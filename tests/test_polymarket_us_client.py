"""Tests for the Polymarket US adapter (us_client.py). Mocks ONLY the
network boundary — a fake object shaped like polymarket_us.PolymarketUS's
resource API (search/events/markets/orders/account) — so these tests run
without the real `polymarket-us` package installed, exactly like every
other test in this package never needs the real SDK (see client.py's
_sdk()/us_client.py's _sdk() lazy-import convention).

Response dict shapes below mirror polymarket_us's real TypedDicts
(verified by installing polymarket-us==2.3.0 and inspecting
typing.get_type_hints() directly — see us_client.py's module
docstring), not guessed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.polymarket import reconciliation
from src.polymarket.client import NoActiveMarketError
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import OrderRequest, PendingLiveOrder
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import PolymarketPositionStore
from src.polymarket.settings import PolymarketSettings
from src.polymarket.state import DailyPnlStateStore
from src.polymarket.us_client import PolymarketUSClient, PolymarketUSClientError

_NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


# --- Fakes: only the network boundary ----------------------------------------

class _FakeSearch:
    def __init__(self, response=None, raise_exc=None):
        self.response = response if response is not None else {"events": []}
        self.raise_exc = raise_exc
        self.calls: list = []

    def query(self, params=None):
        self.calls.append(params)
        if self.raise_exc:
            raise self.raise_exc
        return self.response


class _FakeMarkets:
    def __init__(self, *, books=None, settlements=None, details=None, book_exc=None):
        self.books = books or {}
        self.settlements = settlements or {}
        self.details = details or {}
        self.book_exc = book_exc

    def book(self, slug):
        if self.book_exc:
            raise self.book_exc
        return self.books[slug]

    def settlement(self, slug):
        return self.settlements[slug]

    def retrieve_by_slug(self, slug):
        if slug not in self.details:
            raise _NotFoundError(f"no such market {slug}")
        return self.details[slug]


class _FakeOrders:
    def __init__(self, *, create_response=None, create_exc=None, retrieve_responses=None):
        self.create_response = create_response
        self.create_exc = create_exc
        self.retrieve_responses = retrieve_responses or {}
        self.create_calls: list = []

    def create(self, params):
        self.create_calls.append(params)
        if self.create_exc:
            raise self.create_exc
        return self.create_response

    def retrieve(self, order_id):
        resp = self.retrieve_responses.get(order_id)
        if resp is None:
            raise _NotFoundError(f"no such order {order_id}")
        if isinstance(resp, Exception):
            raise resp
        return resp


class _FakeAccount:
    def __init__(self, response=None, raise_exc=None):
        self.response = response
        self.raise_exc = raise_exc

    def balances(self):
        if self.raise_exc:
            raise self.raise_exc
        return self.response


class _FakeSDKClient:
    def __init__(self, *, search=None, markets=None, orders=None, account=None):
        self.search = search or _FakeSearch()
        self.markets = markets or _FakeMarkets()
        self.orders = orders or _FakeOrders()
        self.account = account or _FakeAccount()
        self.closed = False

    def close(self):
        self.closed = True


class _AuthenticationError(Exception):
    pass


class _RateLimitError(Exception):
    pass


class _APITimeoutError(Exception):
    pass


class _NotFoundError(Exception):
    pass


# --- Fixture builders, mirroring polymarket_us's real TypedDict shapes ------

def _amount(value) -> dict:
    return {"value": str(value), "currency": "USD"}


def _book_level(price, qty) -> dict:
    return {"px": _amount(price), "qty": str(qty)}


def _book_response(bids, offers, state="MARKET_STATE_OPEN") -> dict:
    return {"marketData": {
        "marketSlug": "x", "bids": bids, "offers": offers, "state": state,
        "stats": None, "transactTime": None,
    }}


def _event(*, slug="btc-updown-15m", title="Bitcoin Up or Down (15 min)", minutes=15, market_slug=None, now=_NOW) -> dict:
    start = now
    end = now + timedelta(minutes=minutes)
    return {
        "id": 1, "slug": slug, "title": title, "description": "",
        "startTime": start.isoformat(), "endTime": end.isoformat(),
        "active": True, "closed": False, "archived": False, "featured": False,
        "liquidity": 100.0, "volume": 100.0,
        "markets": [{
            "id": 1, "slug": market_slug or slug, "title": title, "outcome": "YES",
            "active": True, "closed": False, "liquidity": 100.0, "volume": 100.0,
        }],
        "tags": [], "series": {"id": 1, "slug": "btc-15min", "title": "BTC 15min"},
    }


def _order_response(state, *, quantity=10, cum=0, avg_px=None, order_id="ord-1") -> dict:
    return {"order": {
        "id": order_id, "marketSlug": "btc-updown-15m", "side": "ORDER_SIDE_BUY", "type": "ORDER_TYPE_LIMIT",
        "price": _amount("0.55"), "quantity": quantity, "cumQuantity": cum, "leavesQuantity": quantity - cum,
        "tif": "TIME_IN_FORCE_FILL_OR_KILL", "goodTillTime": None, "intent": "ORDER_INTENT_BUY_LONG",
        "marketMetadata": {}, "state": state, "avgPx": _amount(avg_px) if avg_px is not None else None,
        "cashOrderQty": None, "insertTime": "", "createTime": "", "commissionNotionalTotalCollected": None,
        "commissionsBasisPoints": "", "makerCommissionsBasisPoints": "",
    }}


def _settings(**overrides) -> PolymarketSettings:
    env = {"POLYMARKET_VENUE": "us"}
    env.update(overrides)
    return PolymarketSettings.from_env(env=env)


def _order_request(**overrides) -> OrderRequest:
    defaults = dict(
        condition_id="btc-updown-15m", token_id="btc-updown-15m", outcome="YES", side="BUY",
        size_usd=5.0, max_price=0.55, close_time=_NOW + timedelta(minutes=10), reason="test",
    )
    defaults.update(overrides)
    return OrderRequest(**defaults)


# --- 1. Market discovery ------------------------------------------------------

def test_market_discovery_finds_an_active_event(tmp_path):
    sdk = _FakeSDKClient(search=_FakeSearch({"events": [_event()]}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    market = client.find_active_btc_market(now=_NOW)
    assert market.condition_id == "btc-updown-15m"
    assert market.question == "Bitcoin Up or Down (15 min)"
    assert sdk.search.calls[0]["query"] == "bitcoin"


def test_market_discovery_raises_when_nothing_matches(tmp_path):
    sdk = _FakeSDKClient(search=_FakeSearch({"events": []}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    with pytest.raises(NoActiveMarketError):
        client.find_active_btc_market(now=_NOW)


# --- 2. BTC 15-minute discovery: closest-duration selection ------------------

def test_discovery_picks_the_event_closest_to_the_target_duration(tmp_path):
    events = [
        _event(slug="btc-updown-60m", minutes=60, market_slug="btc-updown-60m"),
        _event(slug="btc-updown-15m", minutes=15, market_slug="btc-updown-15m"),
        _event(slug="btc-updown-5m", minutes=5, market_slug="btc-updown-5m"),
    ]
    sdk = _FakeSDKClient(search=_FakeSearch({"events": events}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    market = client.find_active_btc_market(now=_NOW)
    assert market.condition_id == "btc-updown-15m"


def test_discovery_ignores_events_whose_title_does_not_match_asset(tmp_path):
    events = [_event(slug="super-bowl", title="Who wins the Super Bowl?", market_slug="super-bowl")]
    sdk = _FakeSDKClient(search=_FakeSearch({"events": events}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    with pytest.raises(NoActiveMarketError):
        client.find_active_btc_market(now=_NOW)


def test_discovery_ignores_events_already_closed(tmp_path):
    past_event = _event(now=_NOW - timedelta(minutes=30), minutes=15)  # ended 15 min ago
    sdk = _FakeSDKClient(search=_FakeSearch({"events": [past_event]}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    with pytest.raises(NoActiveMarketError):
        client.find_active_btc_market(now=_NOW)


# --- 3. Outcome identifiers ----------------------------------------------------

def test_outcome_identifiers_are_the_same_slug_for_both_sides(tmp_path):
    """Polymarket US has ONE contract per market -- YES/NO is expressed
    via order intent (BUY_LONG/BUY_SHORT), not via two separate tokens."""
    sdk = _FakeSDKClient(search=_FakeSearch({"events": [_event()]}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    market = client.find_active_btc_market(now=_NOW)
    assert market.token_id_yes == market.token_id_no == "btc-updown-15m"
    assert market.token_id_for("YES") == market.token_id_for("NO")


# --- 4. Order book + liquidity -------------------------------------------------

def test_order_book_is_sorted_best_first_regardless_of_input_order(tmp_path):
    # Deliberately unsorted input -- the client must never trust array order.
    bids = [_book_level("0.40", "50"), _book_level("0.48", "100"), _book_level("0.45", "10")]
    offers = [_book_level("0.60", "20"), _book_level("0.52", "100"), _book_level("0.55", "10")]
    sdk = _FakeSDKClient(markets=_FakeMarkets(books={"btc-updown-15m": _book_response(bids, offers)}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    book = client.get_order_book("btc-updown-15m")
    assert [lvl.price for lvl in book.bids] == [0.48, 0.45, 0.40]  # descending
    assert [lvl.price for lvl in book.asks] == [0.52, 0.55, 0.60]  # ascending
    assert book.best_bid == 0.48
    assert book.best_ask == 0.52


def test_order_book_empty_sides_do_not_crash(tmp_path):
    sdk = _FakeSDKClient(markets=_FakeMarkets(books={"x": _book_response([], [])}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    book = client.get_order_book("x")
    assert book.best_bid is None and book.best_ask is None


def test_executable_liquidity_through_the_real_book(tmp_path):
    offers = [_book_level("0.50", "100")]  # $50 notional
    sdk = _FakeSDKClient(markets=_FakeMarkets(books={"x": _book_response([], offers)}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    book = client.get_order_book("x")
    assert book.executable_liquidity_usd(side="BUY", max_price=0.55) == pytest.approx(50.0)


def test_order_book_malformed_missing_keys_defaults_to_empty_not_a_crash(tmp_path):
    """Malformed response: marketData present but bids/offers keys absent."""
    sdk = _FakeSDKClient(markets=_FakeMarkets(books={"x": {"marketData": {"marketSlug": "x", "state": "MARKET_STATE_OPEN"}}}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    book = client.get_order_book("x")
    assert book.bids == () and book.asks == ()


# --- 5. FOK order construction + max price -----------------------------------

def test_fok_buy_long_order_construction(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(create_response={"id": "ord-1", "executions": []}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request(outcome="YES", size_usd=5.0, max_price=0.50, order_type="FOK")
    outcome = client.place_order(order)
    assert outcome.ok is True
    assert outcome.exchange_order_id == "ord-1"
    params = sdk.orders.create_calls[0]
    assert params["intent"] == "ORDER_INTENT_BUY_LONG"
    assert params["tif"] == "TIME_IN_FORCE_FILL_OR_KILL"
    assert params["type"] == "ORDER_TYPE_LIMIT"
    assert params["price"] == {"value": "0.50", "currency": "USD"}
    assert params["quantity"] == 10  # floor(5.0 / 0.50)


def test_fok_buy_short_order_construction_for_no_outcome(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(create_response={"id": "ord-2", "executions": []}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request(outcome="NO", size_usd=5.0, max_price=0.50, order_type="FOK")
    client.place_order(order)
    assert sdk.orders.create_calls[0]["intent"] == "ORDER_INTENT_BUY_SHORT"


def test_fak_order_maps_to_immediate_or_cancel(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(create_response={"id": "ord-3", "executions": []}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request(order_type="FAK")
    client.place_order(order)
    assert sdk.orders.create_calls[0]["tif"] == "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL"


def test_max_price_enforced_via_quantity_floor_not_overspend(tmp_path):
    """$5 at a $0.97 ceiling must floor to 5 contracts (not 5.15), so
    actual spend never exceeds size_usd."""
    sdk = _FakeSDKClient(orders=_FakeOrders(create_response={"id": "ord-4", "executions": []}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request(size_usd=5.0, max_price=0.97)
    client.place_order(order)
    assert sdk.orders.create_calls[0]["quantity"] == 5


def test_quantity_rounding_to_zero_refuses_to_submit(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(create_response={"id": "should-not-be-used"}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request(size_usd=0.40, max_price=0.97)  # floor(0.40/0.97) == 0
    outcome = client.place_order(order)
    assert outcome.ok is False
    assert outcome.error_code == "quantity_too_small"
    assert sdk.orders.create_calls == []  # never actually submitted


def test_sell_side_is_not_supported(tmp_path):
    sdk = _FakeSDKClient()
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request(side="SELL")
    with pytest.raises(PolymarketUSClientError):
        client.place_order(order)


# --- 6. Submission response vs. authoritative fill (Task 3) ------------------

def test_submission_response_never_treated_as_a_fill(tmp_path):
    """Even though orders.create() returns `executions` directly, place_order()
    must never surface a FillResult -- only SubmissionOutcome."""
    sdk = _FakeSDKClient(orders=_FakeOrders(create_response={
        "id": "ord-5", "executions": [{"type": "EXECUTION_TYPE_FILL", "lastShares": "10"}],
    }))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    outcome = client.place_order(_order_request())
    assert outcome.ok is True
    # SubmissionOutcome has no fill-determination fields at all -- this is
    # enforced by the type itself (see models.SubmissionOutcome), not just this test.
    assert not hasattr(outcome, "filled_shares")


def test_rejection_from_the_exchange_has_no_exchange_order_id(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(create_exc=_AuthenticationError("invalid signature")))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    outcome = client.place_order(_order_request())
    assert outcome.ok is False
    assert outcome.exchange_order_id is None
    assert outcome.error_code == "_AuthenticationError"


def test_no_order_id_in_response_is_treated_as_a_failed_submission(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(create_response={"id": None, "executions": []}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    outcome = client.place_order(_order_request())
    assert outcome.ok is False
    assert outcome.error_code == "no_order_id"


# --- 7. API timeout / rate limit (Task 8's explicit asks) --------------------

def test_api_timeout_during_submission_is_a_failed_submission_not_a_crash(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(create_exc=_APITimeoutError("timed out")))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    outcome = client.place_order(_order_request())
    assert outcome.ok is False
    assert outcome.error_code == "_APITimeoutError"


def test_rate_limit_response_during_submission_is_a_failed_submission(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(create_exc=_RateLimitError("too many requests")))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    outcome = client.place_order(_order_request())
    assert outcome.ok is False
    assert outcome.error_code == "_RateLimitError"


def test_api_authentication_failure_on_balance_lookup_propagates(tmp_path):
    """get_balance_usdc() does not swallow auth failures -- callers (e.g.
    verify_polymarket_setup.py) must see this, never silently 'assume funded'."""
    sdk = _FakeSDKClient(account=_FakeAccount(raise_exc=_AuthenticationError("bad key")))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    with pytest.raises(_AuthenticationError):
        client.get_balance_usdc()


def test_authentication_succeeds_returns_usd_balance(tmp_path):
    sdk = _FakeSDKClient(account=_FakeAccount({"balances": [
        {"currency": "USD", "currentBalance": 123.45, "buyingPower": 123.45},
    ]}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    assert client.get_balance_usdc() == pytest.approx(123.45)


def test_no_usd_balance_entry_raises(tmp_path):
    sdk = _FakeSDKClient(account=_FakeAccount({"balances": [{"currency": "OTHER", "currentBalance": 1.0}]}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    with pytest.raises(PolymarketUSClientError):
        client.get_balance_usdc()


# --- 8. Actual fill / partial fill / rejection / cancellation / unknown ------

def test_fill_status_fully_filled(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={
        "ord-1": _order_response("ORDER_STATE_FILLED", quantity=10, cum=10, avg_px="0.52"),
    }))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    fill = client.get_fill_status("ord-1")
    assert fill.status == "filled"
    assert fill.filled_shares == 10.0
    assert fill.avg_fill_price == 0.52
    assert fill.is_fill


def test_fill_status_partially_filled(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={
        "ord-1": _order_response("ORDER_STATE_PARTIALLY_FILLED", quantity=10, cum=4, avg_px="0.52"),
    }))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    fill = client.get_fill_status("ord-1")
    assert fill.status == "partially_filled"
    assert fill.filled_shares == 4.0
    assert fill.is_fill


def test_fill_status_rejected(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={
        "ord-1": _order_response("ORDER_STATE_REJECTED", quantity=10, cum=0),
    }))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    fill = client.get_fill_status("ord-1")
    assert fill.status == "rejected"
    assert not fill.is_fill


def test_fill_status_cancelled(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={
        "ord-1": _order_response("ORDER_STATE_CANCELED", quantity=10, cum=0),
    }))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    fill = client.get_fill_status("ord-1")
    assert fill.status == "cancelled"
    assert not fill.is_fill


def test_fill_status_resting_pending_state(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={
        "ord-1": _order_response("ORDER_STATE_NEW", quantity=10, cum=0),
    }))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    fill = client.get_fill_status("ord-1")
    assert fill.status == "resting"
    assert not fill.is_fill


def test_fill_status_unrecognized_state_is_unknown(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={
        "ord-1": _order_response("ORDER_STATE_SOMETHING_NEW_WE_DONT_KNOW", quantity=10, cum=0),
    }))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    fill = client.get_fill_status("ord-1")
    assert fill.status == "unknown"
    assert not fill.is_fill


def test_fill_status_lookup_failure_is_unknown_not_a_crash(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={}))  # order_id not found -> raises
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    fill = client.get_fill_status("does-not-exist")
    assert fill.status == "unknown"
    assert not fill.is_fill


def test_fill_status_malformed_response_missing_avg_px_is_unknown(tmp_path):
    """Malformed/inconsistent response: cumQuantity > 0 (claims a fill)
    but no avgPx -- must fail closed, never fabricate a price."""
    broken = _order_response("ORDER_STATE_FILLED", quantity=10, cum=10, avg_px=None)
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={"ord-1": broken}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    fill = client.get_fill_status("ord-1")
    assert fill.status == "unknown"
    assert fill.filled_shares == 0.0


def test_fill_status_malformed_nonzero_cum_with_unexpected_state_is_unknown(tmp_path):
    """Defensive case: cumQuantity > 0 but state is neither FILLED nor
    PARTIALLY_FILLED -- an internally inconsistent response. Fail closed."""
    broken = _order_response("ORDER_STATE_NEW", quantity=10, cum=5, avg_px="0.5")
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={"ord-1": broken}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    fill = client.get_fill_status("ord-1")
    assert fill.status == "unknown"
    assert fill.filled_shares == 0.0


# --- 9. Settlement / resolution -----------------------------------------------

def test_resolution_yes_wins(tmp_path):
    sdk = _FakeSDKClient(markets=_FakeMarkets(
        details={"btc-updown-15m": {"market": {"id": 1, "slug": "btc-updown-15m", "closed": True}}},
        settlements={"btc-updown-15m": {"slug": "btc-updown-15m", "settlement": 1.0}},
    ))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    assert client.get_resolution("btc-updown-15m") == "YES"


def test_resolution_no_wins(tmp_path):
    sdk = _FakeSDKClient(markets=_FakeMarkets(
        details={"btc-updown-15m": {"market": {"id": 1, "slug": "btc-updown-15m", "closed": True}}},
        settlements={"btc-updown-15m": {"slug": "btc-updown-15m", "settlement": 0.0}},
    ))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    assert client.get_resolution("btc-updown-15m") == "NO"


def test_resolution_none_while_still_open(tmp_path):
    sdk = _FakeSDKClient(markets=_FakeMarkets(
        details={"btc-updown-15m": {"market": {"id": 1, "slug": "btc-updown-15m", "closed": False}}},
    ))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    assert client.get_resolution("btc-updown-15m") is None


def test_resolution_not_found_returns_none_not_a_crash(tmp_path):
    sdk = _FakeSDKClient(markets=_FakeMarkets(details={}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    assert client.get_resolution("does-not-exist") is None


# --- 10. Duplicate reconciliation (idempotency), via the real reconciliation.py

def test_duplicate_reconciliation_cannot_create_two_positions(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={
        "ord-us-1": _order_response("ORDER_STATE_FILLED", quantity=10, cum=10, avg_px="0.5"),
    }))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)

    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    decision_logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)

    pending = PendingLiveOrder.new(order=_order_request(), expiry_seconds=600)
    pending = pending.with_status("submitted", exchange_order_id="ord-us-1")
    pending_store.add(pending)

    first = reconciliation.reconcile_order(
        pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    reconciled = pending_store.get(pending.id)
    second = reconciliation.reconcile_order(
        reconciled, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    assert first is not None
    assert second is None  # already reconciled -- no-op
    assert len(position_store.load()) == 1
    assert state_store.load().trades_opened == 1


# --- close() --------------------------------------------------------------

def test_close_closes_the_underlying_sdk_client(tmp_path):
    sdk = _FakeSDKClient()
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    client.close()
    assert sdk.closed is True
