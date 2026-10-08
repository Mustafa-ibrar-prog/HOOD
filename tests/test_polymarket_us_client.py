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
from src.polymarket.risk import PolymarketRiskManager
from src.polymarket.settings import PolymarketSettings
from src.polymarket.state import DailyPnlStateStore
from src.polymarket.us_client import (
    PolymarketUSClient,
    PolymarketUSClientError,
    _parse_btc_updown_window_from_slug,
)

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


class _FakeEvents:
    """Keyed by slug, mirroring events.retrieve_by_slug()'s real
    lookup-by-exact-identifier semantics (not a text search)."""

    def __init__(self, responses=None):
        self.responses = responses or {}

    def retrieve_by_slug(self, slug):
        resp = self.responses.get(slug)
        if resp is None:
            raise _NotFoundError(f"no such event {slug}")
        if isinstance(resp, Exception):
            raise resp
        return resp


class _FakeMarkets:
    def __init__(self, *, books=None, settlements=None, details=None, book_exc=None):
        self.books = books or {}
        self.settlements = settlements or {}
        self.details = details or {}
        self.book_exc = book_exc
        self.book_calls: list = []
        self.retrieve_by_slug_calls: list = []

    def book(self, slug):
        self.book_calls.append(slug)
        if self.book_exc:
            raise self.book_exc
        return self.books[slug]

    def settlement(self, slug):
        return self.settlements[slug]

    def retrieve_by_slug(self, slug):
        self.retrieve_by_slug_calls.append(slug)
        if slug not in self.details:
            raise _NotFoundError(f"no such market {slug}")
        return self.details[slug]


class _FakeOrders:
    def __init__(self, *, create_response=None, create_exc=None, retrieve_responses=None,
                 preview_response=None, preview_exc=None, list_response=None, list_exc=None):
        self.create_response = create_response
        self.create_exc = create_exc
        self.retrieve_responses = retrieve_responses or {}
        self.preview_response = preview_response
        self.preview_exc = preview_exc
        self.list_response = list_response if list_response is not None else {"orders": []}
        self.list_exc = list_exc
        self.create_calls: list = []
        self.preview_calls: list = []
        self.list_calls: list = []
        self.retrieve_calls: list = []

    def create(self, params):
        self.create_calls.append(params)
        if self.create_exc:
            raise self.create_exc
        return self.create_response

    def retrieve(self, order_id):
        """`retrieve_responses[order_id]` may be a single response/Exception
        (same result every call -- the common case) OR a LIST of them,
        consumed in order across successive calls to simulate e.g. a
        transient 404 followed by a real FILLED response -- once
        exhausted, the last entry repeats for any further call."""
        self.retrieve_calls.append(order_id)
        resp = self.retrieve_responses.get(order_id)
        if resp is None:
            raise _NotFoundError(f"no such order {order_id}")
        if isinstance(resp, list):
            call_index = self.retrieve_calls.count(order_id) - 1
            resp = resp[min(call_index, len(resp) - 1)]
        if isinstance(resp, Exception):
            raise resp
        return resp

    def list(self, params=None):
        self.list_calls.append(params)
        if self.list_exc:
            raise self.list_exc
        return self.list_response

    def preview(self, params):
        self.preview_calls.append(params)
        if self.preview_exc:
            raise self.preview_exc
        return self.preview_response


class _FakeAccount:
    def __init__(self, response=None, raise_exc=None):
        self.response = response
        self.raise_exc = raise_exc

    def balances(self):
        if self.raise_exc:
            raise self.raise_exc
        return self.response


class _FakePortfolio:
    def __init__(self, *, activities_response=None, activities_exc=None, positions_response=None, positions_exc=None):
        self.activities_response = activities_response if activities_response is not None else {"activities": []}
        self.activities_exc = activities_exc
        self.positions_response = positions_response if positions_response is not None else {"positions": {}}
        self.positions_exc = positions_exc
        self.activities_calls: list = []
        self.positions_calls: list = []

    def activities(self, params=None):
        self.activities_calls.append(params)
        if self.activities_exc:
            raise self.activities_exc
        return self.activities_response

    def positions(self, params=None):
        self.positions_calls.append(params)
        if self.positions_exc:
            raise self.positions_exc
        return self.positions_response


class _FakeSDKClient:
    def __init__(self, *, search=None, events=None, markets=None, orders=None, account=None, portfolio=None):
        self.search = search or _FakeSearch()
        self.events = events or _FakeEvents()
        self.markets = markets or _FakeMarkets()
        self.orders = orders or _FakeOrders()
        self.account = account or _FakeAccount()
        self.portfolio = portfolio or _FakePortfolio()
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


def _btc_15m_slug(window_start: datetime) -> str:
    """The deterministic slug pattern confirmed LIVE by the user
    against the real Polymarket US site (real example:
    btc-updown-15m-2026-10-06-1745z)."""
    return f"btc-updown-15m-{window_start:%Y-%m-%d-%H%M}z"


def _event(*, slug, start: datetime, end: datetime, title="BTC Up or Down 15m",
           market_slug=None, active=True, closed=False) -> dict:
    return {
        "id": 1, "slug": slug, "title": title, "description": "",
        "startTime": start.isoformat(), "endTime": end.isoformat(),
        "active": active, "closed": closed, "archived": False, "featured": False,
        "liquidity": 100.0, "volume": 100.0,
        "markets": [{
            "id": 1, "slug": market_slug or slug, "title": title, "outcome": "YES",
            "active": active, "closed": closed, "liquidity": 100.0, "volume": 100.0,
        }],
        "tags": [], "series": {"id": 1, "slug": "btc-up-or-down-15-minute", "title": "BTC Up or Down (15 Minute)"},
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


# --- 1. Deterministic slug generation (pure functions, no SDK needed) -------

@pytest.mark.parametrize("hour,minute,expected_hhmm", [
    (0, 0, "0000"), (0, 15, "0015"), (0, 30, "0030"), (0, 45, "0045"),
    (0, 7, "0000"),    # mid-window still floors to the window's own start
    (23, 59, "2345"),  # last window of the day
])
def test_current_window_floors_to_the_15_minute_boundary(hour, minute, expected_hhmm):
    client = PolymarketUSClient(_settings())
    now = datetime(2026, 10, 7, hour, minute, 30, tzinfo=timezone.utc)
    window_start, window_end = client._current_window(now)
    assert window_start.strftime("%H%M") == expected_hhmm
    assert window_start.second == 0 and window_start.microsecond == 0
    assert window_end == window_start + timedelta(minutes=15)


def test_expected_slug_matches_the_confirmed_live_example():
    """btc-updown-15m-2026-10-06-1745z -- confirmed by the user directly
    against the real Polymarket US site, not derived or guessed here."""
    client = PolymarketUSClient(_settings())
    now = datetime(2026, 10, 6, 17, 50, tzinfo=timezone.utc)  # inside the 17:45-18:00 window
    window_start, window_end = client._current_window(now)
    assert client._expected_event_slug(window_start) == "btc-updown-15m-2026-10-06-1745z"
    assert window_end == datetime(2026, 10, 6, 18, 0, tzinfo=timezone.utc)


def test_expected_slug_day_rollover():
    """`now` at exactly midnight must produce the NEW day's date."""
    client = PolymarketUSClient(_settings())
    window_start, _ = client._current_window(datetime(2026, 10, 8, 0, 0, tzinfo=timezone.utc))
    assert client._expected_event_slug(window_start) == "btc-updown-15m-2026-10-08-0000z"


def test_expected_slug_month_rollover():
    client = PolymarketUSClient(_settings())
    window_start, _ = client._current_window(datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc))
    assert client._expected_event_slug(window_start) == "btc-updown-15m-2026-11-01-0000z"


def test_expected_slug_year_rollover():
    client = PolymarketUSClient(_settings())
    window_start, _ = client._current_window(datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc))
    assert client._expected_event_slug(window_start) == "btc-updown-15m-2027-01-01-0000z"


def test_expected_slug_raises_for_an_unconfirmed_cadence():
    """Only 15-minute has a confirmed live slug token -- any other
    configured duration must fail closed, never guess a pattern."""
    client = PolymarketUSClient(_settings(POLYMARKET_MARKET_DURATION_MINUTES="60"))
    with pytest.raises(PolymarketUSClientError):
        client._expected_event_slug(_NOW)


# --- 1b. Inverse: deriving the window FROM an event slug (close_time source,
# since the live API doesn't reliably send endTime for this product) -------

def test_parse_btc_updown_window_from_slug_matches_the_confirmed_live_example():
    start, end = _parse_btc_updown_window_from_slug(
        "btc-updown-15m-2026-10-07-2015z", market_duration_minutes=15,
    )
    assert start == datetime(2026, 10, 7, 20, 15, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 7, 20, 30, tzinfo=timezone.utc)


def test_parse_btc_updown_window_from_slug_returns_none_for_a_non_matching_slug():
    assert _parse_btc_updown_window_from_slug("some-unrelated-event-2026", market_duration_minutes=15) is None
    assert _parse_btc_updown_window_from_slug(None, market_duration_minutes=15) is None


def test_parse_btc_updown_window_from_slug_returns_none_for_an_unconfirmed_cadence():
    """The slug matches the pattern but with a cadence token
    (e.g. "1h") this system has no confirmed mapping for -- never
    guess that it means 60 minutes."""
    assert _parse_btc_updown_window_from_slug(
        "btc-updown-1h-2026-10-07-2000z", market_duration_minutes=15,
    ) is None


def test_parse_btc_updown_window_from_slug_rejects_an_invalid_calendar_date():
    assert _parse_btc_updown_window_from_slug(
        "btc-updown-15m-2026-13-07-2015z", market_duration_minutes=15,
    ) is None


# --- 2. Discovery: exact-slug lookup, never a text search ---------------------

def test_discovery_finds_the_exact_expected_event(tmp_path):
    now = datetime(2026, 10, 7, 12, 3, tzinfo=timezone.utc)  # inside the 12:00-12:15 window
    window_start = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 10, 7, 12, 15, tzinfo=timezone.utc)
    slug = _btc_15m_slug(window_start)
    event = _event(slug=slug, start=window_start, end=window_end, market_slug=slug)
    sdk = _FakeSDKClient(events=_FakeEvents({slug: {"event": event}}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)

    market = client.find_active_btc_market(now=now)
    assert market.condition_id == slug
    assert market.token_id_yes == market.token_id_no == slug
    assert market.close_time == window_end
    assert market.question == "BTC Up or Down 15m"


def test_discovery_raises_when_the_exact_event_does_not_exist(tmp_path):
    now = datetime(2026, 10, 7, 12, 3, tzinfo=timezone.utc)
    sdk = _FakeSDKClient(events=_FakeEvents({}))  # nothing registered -> 404 on lookup
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    with pytest.raises(NoActiveMarketError):
        client.find_active_btc_market(now=now)


def test_discovery_never_falls_back_to_search_even_if_it_would_find_something(tmp_path):
    """search.query() is debug-only now -- even if it WOULD return the
    right event, discovery must never consult it."""
    now = datetime(2026, 10, 7, 12, 3, tzinfo=timezone.utc)
    window_start = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 10, 7, 12, 15, tzinfo=timezone.utc)
    slug = _btc_15m_slug(window_start)
    event = _event(slug=slug, start=window_start, end=window_end, market_slug=slug)
    search = _FakeSearch({"events": [event]})  # would "find" it via text search...
    sdk = _FakeSDKClient(search=search, events=_FakeEvents({}))  # ...but the exact lookup 404s
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    with pytest.raises(NoActiveMarketError):
        client.find_active_btc_market(now=now)
    assert search.calls == []  # never even consulted


def test_discovery_rejects_a_response_with_a_mismatched_slug(tmp_path):
    """Defense in depth: even if the API returns something other than
    the exact event requested, never trade it."""
    now = datetime(2026, 10, 7, 12, 3, tzinfo=timezone.utc)
    window_start = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 10, 7, 12, 15, tzinfo=timezone.utc)
    expected_slug = _btc_15m_slug(window_start)
    wrong_event = _event(slug="some-other-event-entirely", start=window_start, end=window_end)
    sdk = _FakeSDKClient(events=_FakeEvents({expected_slug: {"event": wrong_event}}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    with pytest.raises(NoActiveMarketError):
        client.find_active_btc_market(now=now)


def test_discovery_rejects_an_inactive_or_closed_event(tmp_path):
    now = datetime(2026, 10, 7, 12, 3, tzinfo=timezone.utc)
    window_start = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 10, 7, 12, 15, tzinfo=timezone.utc)
    slug = _btc_15m_slug(window_start)
    closed_event = _event(slug=slug, start=window_start, end=window_end, market_slug=slug, active=False, closed=True)
    sdk = _FakeSDKClient(events=_FakeEvents({slug: {"event": closed_event}}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    with pytest.raises(NoActiveMarketError):
        client.find_active_btc_market(now=now)


def test_discovery_rejects_an_event_on_the_wrong_schedule(tmp_path):
    """Right slug, but its own startTime/endTime don't match the
    window we computed -- never trust the response blindly."""
    now = datetime(2026, 10, 7, 12, 3, tzinfo=timezone.utc)
    window_start = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    expected_slug = _btc_15m_slug(window_start)
    off_schedule = _event(
        slug=expected_slug, start=datetime(2026, 10, 7, 12, 5, tzinfo=timezone.utc),
        end=datetime(2026, 10, 7, 12, 20, tzinfo=timezone.utc), market_slug=expected_slug,
    )
    sdk = _FakeSDKClient(events=_FakeEvents({expected_slug: {"event": off_schedule}}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    with pytest.raises(NoActiveMarketError):
        client.find_active_btc_market(now=now)


def test_discovery_unrelated_bitcoin_market_never_interferes(tmp_path):
    """A generic Bitcoin price-target market registered under some
    other slug must have zero effect -- discovery only ever looks up
    the one exact slug it computed."""
    now = datetime(2026, 10, 7, 12, 3, tzinfo=timezone.utc)
    window_start = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 10, 7, 12, 15, tzinfo=timezone.utc)
    expected_slug = _btc_15m_slug(window_start)
    real_event = _event(slug=expected_slug, start=window_start, end=window_end, market_slug=expected_slug)
    unrelated = _event(
        slug="bitcoin-price-eoy-2026", title="Bitcoin price at the end of 2026",
        start=datetime(2026, 1, 1, tzinfo=timezone.utc), end=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    sdk = _FakeSDKClient(events=_FakeEvents({expected_slug: {"event": real_event}, "bitcoin-price-eoy-2026": {"event": unrelated}}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    market = client.find_active_btc_market(now=now)
    assert market.condition_id == expected_slug


def test_discovery_multiple_simultaneous_updown_events_still_picks_the_exact_slug(tmp_path):
    """A simultaneously-open "BTC Up or Down 1h" sibling (confirmed to
    exist on the real homepage too) must have zero effect: there is no
    "closest candidate" selection anymore, only the one exact slug."""
    now = datetime(2026, 10, 7, 12, 3, tzinfo=timezone.utc)
    window_start = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 10, 7, 12, 15, tzinfo=timezone.utc)
    fifteen_min_slug = _btc_15m_slug(window_start)
    fifteen_min = _event(slug=fifteen_min_slug, start=window_start, end=window_end, market_slug=fifteen_min_slug)
    one_hour_slug = "btc-updown-1h-2026-10-07-1200z"
    one_hour = _event(
        slug=one_hour_slug, title="BTC Up or Down 1h", start=window_start,
        end=datetime(2026, 10, 7, 13, 0, tzinfo=timezone.utc), market_slug=one_hour_slug,
    )
    sdk = _FakeSDKClient(events=_FakeEvents({fifteen_min_slug: {"event": fifteen_min}, one_hour_slug: {"event": one_hour}}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    market = client.find_active_btc_market(now=now)
    assert market.condition_id == fifteen_min_slug


def test_discovery_rolls_over_to_the_next_window_automatically(tmp_path):
    """The next cycle's `now` lands in the NEXT 15-minute window and
    must look up a DIFFERENT, independently-registered exact slug --
    no caching or stickiness to the previous window's event."""
    window_1200 = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    window_1215 = datetime(2026, 10, 7, 12, 15, tzinfo=timezone.utc)
    window_1230 = datetime(2026, 10, 7, 12, 30, tzinfo=timezone.utc)
    slug_1200 = _btc_15m_slug(window_1200)
    slug_1215 = _btc_15m_slug(window_1215)
    event_1200 = _event(slug=slug_1200, start=window_1200, end=window_1215, market_slug=slug_1200)
    event_1215 = _event(slug=slug_1215, start=window_1215, end=window_1230, market_slug=slug_1215)
    sdk = _FakeSDKClient(events=_FakeEvents({slug_1200: {"event": event_1200}, slug_1215: {"event": event_1215}}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)

    first = client.find_active_btc_market(now=datetime(2026, 10, 7, 12, 3, tzinfo=timezone.utc))
    assert first.condition_id == slug_1200
    second = client.find_active_btc_market(now=datetime(2026, 10, 7, 12, 17, tzinfo=timezone.utc))
    assert second.condition_id == slug_1215


# --- 2b. Manual market override (POLYMARKET_US_MARKET_SLUG) -----------------

def test_manual_override_unset_leaves_btc_discovery_unaffected(tmp_path):
    """No POLYMARKET_US_MARKET_SLUG -> the existing deterministic BTC
    15m path runs exactly as before; the manual-override machinery is
    never even consulted."""
    now = datetime(2026, 10, 7, 12, 3, tzinfo=timezone.utc)
    window_start = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 10, 7, 12, 15, tzinfo=timezone.utc)
    slug = _btc_15m_slug(window_start)
    event = _event(slug=slug, start=window_start, end=window_end, market_slug=slug)
    sdk = _FakeSDKClient(events=_FakeEvents({slug: {"event": event}}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)  # no POLYMARKET_US_MARKET_SLUG
    market = client.find_active_btc_market(now=now)
    assert market.condition_id == slug


def test_manual_override_treats_the_slug_as_an_event_slug(tmp_path):
    """CONFIRMED LIVE: a slug copied from the Polymarket US app is an
    EVENT slug, and its nested TRADEABLE market has its own, different
    slug (a real event btc-updown-15m-2026-10-07-2015z's nested market
    is cpc-btc-updown-15m-2026-10-07-2015z) -- never assumed equal.
    Only events.retrieve_by_slug() is called; markets.retrieve_by_slug()
    is never consulted for this path at all."""
    event_slug = "some-arbitrary-event-2026"
    market_slug = "cpc-some-arbitrary-event-2026"  # deliberately NOT equal to event_slug
    start = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 7, 9, 30, tzinfo=timezone.utc)
    event = _event(slug=event_slug, title="Some Arbitrary Event", start=start, end=end, market_slug=market_slug)
    markets = _FakeMarkets()
    sdk = _FakeSDKClient(markets=markets, events=_FakeEvents({event_slug: {"event": event}}))
    client = PolymarketUSClient(_settings(POLYMARKET_US_MARKET_SLUG=event_slug), sdk_client=sdk)

    market = client.find_active_btc_market()

    assert market.condition_id == event_slug  # the EVENT slug
    assert market.token_id_yes == market.token_id_no == market_slug  # the NESTED market's own slug
    assert market.close_time == end
    assert market.question == "Some Arbitrary Event"
    assert markets.retrieve_by_slug_calls == []  # markets.retrieve_by_slug never consulted


def test_manual_override_never_searches(tmp_path):
    """No search.query() call of any kind for the manual-override path
    -- an exact events.retrieve_by_slug() lookup only."""
    event_slug = "evt"
    market_slug = "cpc-evt"
    event = _event(slug=event_slug, start=_NOW, end=_NOW + timedelta(minutes=30), market_slug=market_slug)
    search = _FakeSearch({"events": [event]})
    sdk = _FakeSDKClient(search=search, events=_FakeEvents({event_slug: {"event": event}}))
    client = PolymarketUSClient(_settings(POLYMARKET_US_MARKET_SLUG=event_slug), sdk_client=sdk)
    client.find_active_btc_market()
    assert search.calls == []


def test_manual_override_rejects_a_missing_event(tmp_path):
    sdk = _FakeSDKClient(events=_FakeEvents({}))
    client = PolymarketUSClient(_settings(POLYMARKET_US_MARKET_SLUG="does-not-exist"), sdk_client=sdk)
    with pytest.raises(NoActiveMarketError):
        client.find_active_btc_market()


def test_manual_override_rejects_a_mismatched_event_slug(tmp_path):
    """events.retrieve_by_slug() returns a DIFFERENT slug than
    requested (a malformed/stale response) -- never trusted."""
    slug = "requested-slug"
    wrong_event = _event(slug="totally-different-slug", start=_NOW, end=_NOW + timedelta(minutes=15))
    sdk = _FakeSDKClient(events=_FakeEvents({slug: {"event": wrong_event}}))
    client = PolymarketUSClient(_settings(POLYMARKET_US_MARKET_SLUG=slug), sdk_client=sdk)
    with pytest.raises(NoActiveMarketError):
        client.find_active_btc_market()


def test_manual_override_rejects_an_inactive_or_closed_event(tmp_path):
    slug = "some-event"
    closed_event = _event(slug=slug, start=_NOW, end=_NOW + timedelta(minutes=15), active=False, closed=True)
    sdk = _FakeSDKClient(events=_FakeEvents({slug: {"event": closed_event}}))
    client = PolymarketUSClient(_settings(POLYMARKET_US_MARKET_SLUG=slug), sdk_client=sdk)
    with pytest.raises(NoActiveMarketError):
        client.find_active_btc_market()


def test_manual_override_rejects_an_inactive_or_closed_nested_market(tmp_path):
    """The event itself is open, but its one nested market is not --
    refuse rather than trade a closed market."""
    slug = "some-event"
    event = _event(slug=slug, start=_NOW, end=_NOW + timedelta(minutes=15))
    event["markets"][0]["active"] = False
    event["markets"][0]["closed"] = True
    sdk = _FakeSDKClient(events=_FakeEvents({slug: {"event": event}}))
    client = PolymarketUSClient(_settings(POLYMARKET_US_MARKET_SLUG=slug), sdk_client=sdk)
    with pytest.raises(NoActiveMarketError):
        client.find_active_btc_market()


def test_manual_override_rejects_an_event_with_no_markets(tmp_path):
    slug = "some-event"
    event = _event(slug=slug, start=_NOW, end=_NOW + timedelta(minutes=15))
    event["markets"] = []
    sdk = _FakeSDKClient(events=_FakeEvents({slug: {"event": event}}))
    client = PolymarketUSClient(_settings(POLYMARKET_US_MARKET_SLUG=slug), sdk_client=sdk)
    with pytest.raises(NoActiveMarketError):
        client.find_active_btc_market()


# --- 2c. Regression: the EXACT live response shape (no top-level endTime,
# nested market slugged differently from its event) -------------------------

def test_manual_override_matches_the_real_observed_response_shape(tmp_path):
    """Sanitized regression fixture matching the LIVE response shape
    observed for event btc-updown-15m-2026-10-07-2015z: no endTime key
    AT ALL on the event (only startTime), and a nested market slugged
    cpc-btc-updown-15m-2026-10-07-2015z (NOT the event's own slug).
    Reproduces the exact live failure this fixes: close_time must be
    derived from the event slug's own embedded YYYY-MM-DD-HHMM, never
    from a missing endTime."""
    event_slug = "btc-updown-15m-2026-10-07-2015z"
    market_slug = "cpc-btc-updown-15m-2026-10-07-2015z"
    event = {
        "id": 1, "slug": event_slug, "title": "BTC Up or Down 15m", "description": "",
        "startTime": "2026-10-07T20:15:00Z",  # no "endTime" key at all -- the real observed shape
        "active": True, "closed": False, "archived": False, "featured": False,
        "liquidity": 100.0, "volume": 100.0,
        "markets": [{
            "id": 1, "slug": market_slug, "title": "BTC Up or Down 15m", "outcome": "YES",
            "active": True, "closed": False, "liquidity": 100.0, "volume": 100.0,
        }],
        "tags": [], "series": {"id": 1, "slug": "btc-up-or-down-15-minute", "title": "BTC Up or Down (15 Minute)"},
    }
    book = _book_response([_book_level("0.54", 100)], [_book_level("0.55", 100)])
    markets = _FakeMarkets(books={market_slug: book})
    sdk = _FakeSDKClient(markets=markets, events=_FakeEvents({event_slug: {"event": event}}))
    client = PolymarketUSClient(_settings(POLYMARKET_US_MARKET_SLUG=event_slug), sdk_client=sdk)

    market = client.find_active_btc_market()  # 1. event lookup succeeds; BinaryMarket is created (3/6)

    assert "endTime" not in event  # the fixture genuinely omits it -- not a lenient parse of a present key
    assert market.condition_id == event_slug  # 4. event slug is verified/used as condition_id
    assert market.token_id_yes == market.token_id_no == market_slug  # 5. nested market slug extracted
    assert market.close_time == datetime(2026, 10, 7, 20, 30, tzinfo=timezone.utc)  # derived from the slug, not endTime (2/6)
    assert markets.book_calls == [market_slug]  # 7. order-book lookup used the nested market's slug, not the event slug


def test_automatic_discovery_extracts_the_nested_market_slug_never_synthesizes_it(tmp_path):
    """Regression for the real NotFoundError observed live: automatic
    BTC 15m discovery (no POLYMARKET_US_MARKET_SLUG override) for event
    btc-updown-15m-2026-10-07-2145z. The nested market's slug here is
    DELIBERATELY something that has nothing to do with "cpc-" + the
    event slug -- if find_active_btc_market() ever started building
    the market slug by string concatenation instead of reading
    event["markets"][0]["slug"] verbatim, this test would fail by
    asserting the wrong value. It passes precisely because
    _to_binary_market() never does that -- see its own module
    docstring note on this."""
    event_slug = "btc-updown-15m-2026-10-07-2145z"
    window_start = datetime(2026, 10, 7, 21, 45, tzinfo=timezone.utc)
    window_end = datetime(2026, 10, 7, 22, 0, tzinfo=timezone.utc)
    real_nested_market_slug = "totally-unrelated-internal-market-id-999"  # NOT "cpc-" + event_slug
    event = _event(slug=event_slug, start=window_start, end=window_end, market_slug=real_nested_market_slug)
    markets = _FakeMarkets(books={real_nested_market_slug: _book_response([_book_level("0.54", 100)], [_book_level("0.55", 100)])})
    sdk = _FakeSDKClient(markets=markets, events=_FakeEvents({event_slug: {"event": event}}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)  # no override -- automatic discovery

    market = client.find_active_btc_market(now=datetime(2026, 10, 7, 21, 47, tzinfo=timezone.utc))

    assert market.condition_id == event_slug  # the EVENT's own slug
    assert market.token_id_yes == market.token_id_no == real_nested_market_slug  # read verbatim, not synthesized
    assert markets.book_calls == [real_nested_market_slug]  # markets.book() called with the REAL nested slug
    assert markets.retrieve_by_slug_calls == []  # never even calls markets.retrieve_by_slug() in this path


# --- 3. Outcome identifiers ----------------------------------------------------

def test_outcome_identifiers_are_the_same_slug_for_both_sides(tmp_path):
    """Polymarket US has ONE contract per market -- YES/NO is expressed
    via order intent (BUY_LONG/BUY_SHORT), not via two separate tokens."""
    now = datetime(2026, 10, 7, 12, 3, tzinfo=timezone.utc)
    window_start = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 10, 7, 12, 15, tzinfo=timezone.utc)
    slug = _btc_15m_slug(window_start)
    event = _event(slug=slug, start=window_start, end=window_end, market_slug=slug)
    sdk = _FakeSDKClient(events=_FakeEvents({slug: {"event": event}}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    market = client.find_active_btc_market(now=now)
    assert market.token_id_yes == market.token_id_no == slug
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


# --- 4b. Order book -> risk integration (spread / liquidity through the real
# parsing path, end to end via find_active_btc_market) -----------------------
# Verifies, against the SAME get_order_book()/_to_binary_market() parsing
# used live: (1) best bid, (2) best ask, (3) spread, (4) executable liquidity,
# (5) an empty book fails closed, (6) a one-sided book fails MAX_SPREAD, and
# (7) a two-sided book within the configured limit passes MAX_SPREAD.

def _discover_with_book(bids, offers, *, slug="btc-updown-15m-2026-10-07-2015z") -> tuple:
    """Builds a manual-override market through the real client, with its
    nested market's order book set to exactly `bids`/`offers` -- returns
    (market, order_book), both fetched through the production parsing path
    (get_order_book()/_to_binary_market()), never constructed by hand."""
    market_slug = f"cpc-{slug}"
    now = datetime(2026, 10, 7, 20, 15, 30, tzinfo=timezone.utc)
    event = _event(slug=slug, start=now, end=now + timedelta(minutes=15), market_slug=market_slug)
    sdk = _FakeSDKClient(
        events=_FakeEvents({slug: {"event": event}}),
        markets=_FakeMarkets(books={market_slug: _book_response(bids, offers)}),
    )
    client = PolymarketUSClient(_settings(POLYMARKET_US_MARKET_SLUG=slug), sdk_client=sdk)
    market = client.find_active_btc_market(now=now)
    order_book = client.get_order_book(market.token_id_yes)
    return market, order_book


def test_integration_best_bid_best_ask_and_spread_are_parsed_correctly(tmp_path):
    """(1) best bid, (2) best ask, (3) spread -- through the real parser."""
    market, order_book = _discover_with_book([_book_level("0.54", 100)], [_book_level("0.55", 100)])
    assert order_book.best_bid == 0.54
    assert order_book.best_ask == 0.55
    assert order_book.spread_pct == pytest.approx((0.55 - 0.54) / 0.545, abs=1e-4)
    assert market.yes_bid == 0.54  # BinaryMarket's own summary, populated the same way
    assert market.yes_ask == 0.55


def test_integration_executable_liquidity_matches_the_parsed_asks(tmp_path):
    """(4) executable liquidity -- must never be nonzero when best_ask is
    None (there is no level for it to have summed), and must exactly equal
    price*size for levels at/below max_price otherwise."""
    market, order_book = _discover_with_book([_book_level("0.54", 100)], [_book_level("0.55", 100)])
    liquidity = order_book.executable_liquidity_usd(side="BUY", max_price=0.99)
    assert liquidity == pytest.approx(0.55 * 100)
    if order_book.best_ask is None:
        assert liquidity == 0.0  # the invariant this task is guarding: never nonzero with no ask


def test_integration_empty_book_fails_closed_on_spread_and_liquidity(tmp_path):
    """(5) an empty book -- no bids, no asks -- must fail BOTH MAX_SPREAD
    (no two-sided quote) and ORDER_BOOK_LIQUIDITY (zero liquidity), never
    silently pass either."""
    market, order_book = _discover_with_book([], [])
    assert order_book.best_bid is None and order_book.best_ask is None
    risk = PolymarketRiskManager(_settings())
    spread_result = risk.check_spread(market)
    liquidity_result = risk.check_order_book_liquidity(order_book, side="BUY", max_price=0.60)
    assert not spread_result.passed
    assert not liquidity_result.passed
    assert liquidity_result.detail.startswith("Only $0.00")


def test_integration_one_sided_book_fails_max_spread(tmp_path):
    """(6) a one-sided book (asks only, no bids) -- a real, nonzero
    executable liquidity must NOT be mistaken for a two-sided quote;
    MAX_SPREAD must still fail."""
    market, order_book = _discover_with_book([], [_book_level("0.55", 100)])
    assert order_book.best_bid is None
    assert order_book.best_ask == 0.55
    liquidity = order_book.executable_liquidity_usd(side="BUY", max_price=0.99)
    assert liquidity == pytest.approx(55.0)  # real, nonzero liquidity...
    risk = PolymarketRiskManager(_settings())
    spread_result = risk.check_spread(market)
    assert not spread_result.passed  # ...but still correctly fails MAX_SPREAD (one-sided)
    assert "No two-sided quote" in spread_result.detail


def test_integration_two_sided_book_within_limit_passes_max_spread(tmp_path):
    """(7) a two-sided book within the configured POLYMARKET_MAX_SPREAD_PCT
    passes MAX_SPREAD (default limit is 5%; this book's spread is ~1.8%)."""
    market, order_book = _discover_with_book([_book_level("0.54", 100)], [_book_level("0.55", 100)])
    risk = PolymarketRiskManager(_settings())
    spread_result = risk.check_spread(market)
    assert spread_result.passed
    liquidity_result = risk.check_order_book_liquidity(order_book, side="BUY", max_price=0.60)
    assert liquidity_result.passed


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


def test_place_order_preserves_the_complete_create_response_in_raw(tmp_path):
    """Regression: a real incident showed an order submitted
    successfully (ok=True, a real exchange_order_id) whose later
    orders.retrieve() 404'd -- the ONLY diagnostic trail left is
    whatever was captured from orders.create()'s own response at
    submission time, since that process has since exited. SubmissionOutcome.raw
    must preserve the response verbatim, not just a hand-picked subset
    (e.g. "executions") that happens to omit fields that could matter."""
    create_response = {"id": "ord-1", "executions": [], "someFutureFieldNotYetInOurTypeStub": "value"}
    sdk = _FakeSDKClient(orders=_FakeOrders(create_response=create_response))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request(outcome="YES", size_usd=5.0, max_price=0.50, order_type="FOK")
    outcome = client.place_order(order)
    assert outcome.raw == create_response  # the WHOLE response, not a subset


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


def test_sell_without_quantity_is_refused(tmp_path):
    """A SELL (exit) order must always carry an explicit share count —
    see OrderRequest.quantity's docstring on why this is never derived
    from size_usd/max_price for a SELL. exit_manager.py always sets
    this; a SELL order reaching here without it is a caller bug, not
    an exchange rejection, so this raises rather than returning a
    SubmissionOutcome(ok=False)."""
    sdk = _FakeSDKClient()
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request(side="SELL", quantity=None)
    with pytest.raises(PolymarketUSClientError, match="quantity"):
        client.place_order(order)
    assert sdk.orders.create_calls == []


def test_sell_yes_uses_sell_long_closing_intent(tmp_path):
    """Confirmed directly from the installed polymarket-us SDK's own
    OrderIntent Literal (polymarket_us.types.orders) -- closing a
    YES/LONG position is ORDER_INTENT_SELL_LONG, never guessed."""
    sdk = _FakeSDKClient(orders=_FakeOrders(create_response={"id": "exit-1", "executions": []}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request(side="SELL", outcome="YES", max_price=0.432, quantity=5)
    outcome = client.place_order(order)
    assert outcome.ok is True
    params = sdk.orders.create_calls[0]
    assert params["intent"] == "ORDER_INTENT_SELL_LONG"
    assert params["quantity"] == 5  # the EXACT requested quantity -- never re-derived from size_usd/max_price
    assert params["price"]["value"] == "0.43"


def test_sell_no_uses_sell_short_closing_intent(tmp_path):
    """Closing a NO/SHORT position is ORDER_INTENT_SELL_SHORT --
    confirmed the same way as the YES case above."""
    sdk = _FakeSDKClient(orders=_FakeOrders(create_response={"id": "exit-2", "executions": []}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request(side="SELL", outcome="NO", max_price=0.60, quantity=7)
    outcome = client.place_order(order)
    assert outcome.ok is True
    assert sdk.orders.create_calls[0]["intent"] == "ORDER_INTENT_SELL_SHORT"
    assert sdk.orders.create_calls[0]["quantity"] == 7


def test_sell_quantity_bypasses_the_buy_side_floor_division(tmp_path):
    """A SELL's quantity must come from OrderRequest.quantity verbatim,
    never from floor(size_usd / max_price) the way a BUY's does -- a
    mismatched size_usd/max_price pair must not silently change how
    many shares are offered to close."""
    sdk = _FakeSDKClient(orders=_FakeOrders(create_response={"id": "exit-3", "executions": []}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    # floor(1.00 / 0.43) would be 2 -- but the real position is 5 shares.
    order = _order_request(side="SELL", outcome="YES", size_usd=1.00, max_price=0.43, quantity=5)
    client.place_order(order)
    assert sdk.orders.create_calls[0]["quantity"] == 5


def test_sell_order_uses_fok_or_fak_tif_never_gtc(tmp_path):
    """Requirement: an exit must use an IOC/FOK-style closing order so
    the bot never leaves an unintended resting sell order."""
    sdk = _FakeSDKClient(orders=_FakeOrders(create_response={"id": "exit-4", "executions": []}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request(side="SELL", outcome="YES", max_price=0.432, quantity=5, order_type="FAK")
    client.place_order(order)
    assert sdk.orders.create_calls[0]["tif"] == "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL"


def test_preview_sell_order_uses_the_exact_same_params_as_place_order(tmp_path):
    sdk = _FakeSDKClient(
        orders=_FakeOrders(preview_response={"order": {}}, create_response={"id": "exit-5", "executions": []}),
    )
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request(side="SELL", outcome="YES", max_price=0.432, quantity=5)
    client.preview_order(order)
    client.place_order(order)
    assert sdk.orders.preview_calls[0]["request"] == sdk.orders.create_calls[0]


# --- Exit fee parsing (requirement: NET realized P&L, never assumed from
# gross price alone) --------------------------------------------------------

def test_get_fill_status_parses_reported_commission_into_fee_usd(tmp_path):
    order_id = "ord-fee-1"
    response = _order_response("ORDER_STATE_FILLED", quantity=5, cum=5, avg_px="0.432", order_id=order_id)
    response["order"]["commissionNotionalTotalCollected"] = _amount("0.02")
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={order_id: response}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    fill = client.get_fill_status(order_id)
    assert fill.status == "filled"
    assert fill.fee_usd == pytest.approx(0.02)


def test_get_fill_status_fee_usd_is_none_when_not_reported(tmp_path):
    """None means "not reported," never a fabricated 0.0 -- a caller
    computing net P&L must be able to tell the two apart."""
    order_id = "ord-fee-2"
    response = _order_response("ORDER_STATE_FILLED", quantity=5, cum=5, avg_px="0.432", order_id=order_id)
    assert response["order"]["commissionNotionalTotalCollected"] is None
    sdk = _FakeSDKClient(orders=_FakeOrders(retrieve_responses={order_id: response}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    fill = client.get_fill_status(order_id)
    assert fill.fee_usd is None


# --- 5b. Order preview (orders.preview() -- never places anything) ----------

def test_preview_order_succeeds_and_never_calls_create(tmp_path):
    preview_order_detail = {
        "id": "preview-only", "marketSlug": "btc-updown-15m", "state": "ORDER_STATE_NEW",
        "price": _amount("0.55"), "quantity": 9, "avgPx": None,
    }
    sdk = _FakeSDKClient(orders=_FakeOrders(preview_response={"order": preview_order_detail}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request(size_usd=5.0, max_price=0.55)
    result = client.preview_order(order)
    assert result == preview_order_detail
    assert sdk.orders.create_calls == []  # preview never places anything


def test_preview_order_uses_the_exact_same_params_as_place_order(tmp_path):
    """Preview and a real submission must request identically-shaped
    parameters -- otherwise a 'successful' preview wouldn't mean anything."""
    sdk = _FakeSDKClient(
        orders=_FakeOrders(preview_response={"order": {}}, create_response={"id": "ord-1", "executions": []}),
    )
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request(outcome="NO", size_usd=5.0, max_price=0.60, order_type="FOK")
    client.preview_order(order)
    client.place_order(order)
    preview_params = sdk.orders.preview_calls[0]["request"]
    create_params = sdk.orders.create_calls[0]
    assert preview_params == create_params


def test_preview_order_raises_for_a_too_small_order(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(preview_response={"order": {}}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request(size_usd=0.40, max_price=0.97)  # floor(0.40/0.97) == 0
    with pytest.raises(PolymarketUSClientError):
        client.preview_order(order)
    assert sdk.orders.preview_calls == []  # never even attempted


def test_preview_order_propagates_a_failure(tmp_path):
    sdk = _FakeSDKClient(orders=_FakeOrders(preview_exc=_AuthenticationError("no credentials")))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    order = _order_request()
    with pytest.raises(_AuthenticationError):
        client.preview_order(order)


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
    """get_resolution() takes the EVENT slug (same as
    BinaryMarket/OpenPosition.condition_id -- see _to_binary_market),
    looks up the event, and checks its NESTED market's own
    closed/settlement state -- the market slug (cpc-...) differs from
    the event slug and is never passed in directly."""
    event_slug = "btc-updown-15m-2026-10-07-2015z"
    market_slug = "cpc-btc-updown-15m-2026-10-07-2015z"
    event = _event(slug=event_slug, start=_NOW, end=_NOW, market_slug=market_slug, closed=True, active=False)
    sdk = _FakeSDKClient(
        events=_FakeEvents({event_slug: {"event": event}}),
        markets=_FakeMarkets(settlements={market_slug: {"slug": market_slug, "settlement": 1.0}}),
    )
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    assert client.get_resolution(event_slug) == "YES"


def test_resolution_no_wins(tmp_path):
    event_slug, market_slug = "evt-closed", "cpc-evt-closed"
    event = _event(slug=event_slug, start=_NOW, end=_NOW, market_slug=market_slug, closed=True, active=False)
    sdk = _FakeSDKClient(
        events=_FakeEvents({event_slug: {"event": event}}),
        markets=_FakeMarkets(settlements={market_slug: {"slug": market_slug, "settlement": 0.0}}),
    )
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    assert client.get_resolution(event_slug) == "NO"


def test_resolution_none_while_still_open(tmp_path):
    event_slug, market_slug = "evt-open", "cpc-evt-open"
    event = _event(slug=event_slug, start=_NOW, end=_NOW, market_slug=market_slug, closed=False, active=True)
    sdk = _FakeSDKClient(events=_FakeEvents({event_slug: {"event": event}}))
    client = PolymarketUSClient(_settings(), sdk_client=sdk)
    assert client.get_resolution(event_slug) is None


def test_resolution_not_found_returns_none_not_a_crash(tmp_path):
    sdk = _FakeSDKClient(events=_FakeEvents({}))
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
