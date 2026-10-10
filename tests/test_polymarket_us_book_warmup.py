"""Tests for the NEW-MARKET BOOK WARMUP retry/backoff path
(us_client._retry_on_not_found / PolymarketUSClient._retry_book_warmup
/ get_order_book) added after LIVE EVIDENCE, observed twice, showed a
brand-new BTC 15m market's EXACT nested market slug -- already
confirmed present on its own freshly-discovered, active/open event --
404 on markets.book() for a few seconds before the SAME exact slug
returned a healthy order book with no other change:

    EVENT: btc-updown-15m-2026-10-10-1845z (active, 858s remaining)
    NESTED MARKET: cpc-btc-updown-15m-2026-10-10-1845z
    markets.book("cpc-btc-updown-15m-2026-10-10-1845z") -> NotFoundError
    (moments later, same exact slug) -> a healthy order book

This is a GENUINELY DIFFERENT transient condition from the 429 rate
limit covered by test_polymarket_us_rate_limit.py -- it is about one
specific market's own book not being indexed YET, never about request
volume -- so it has its own dedicated retry function, its own
settings bounds, and its own tests here.

Real polymarket_us.errors.NotFoundError instances are constructed
throughout (never the local placeholder exception classes
test_polymarket_us_client.py otherwise uses), because the production
retry logic type-checks on that exact class.

time.sleep is monkeypatched to a no-op recorder everywhere here: these
tests assert on the NUMBER of attempts/backoffs, never actually wait
for them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from polymarket_us.errors import NotFoundError

import src.polymarket.us_client as us_client_module
from src.polymarket.client import NoActiveMarketError
from src.polymarket.engine import MarketHistory, run_cycle
from src.polymarket.gateway import PaperPolymarketGateway
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import BinaryMarket, OrderBookSnapshot
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import PolymarketPositionStore
from src.polymarket.risk import PolymarketRiskManager
from src.polymarket.single_book import is_single_book_market, to_no_perspective
from src.polymarket.state import DailyPnlStateStore
from src.polymarket.strategy import BtcMomentumStrategy
from src.polymarket.us_client import PolymarketUSClient, _retry_on_not_found
from tests.test_polymarket_us_client import (
    _FakeEvents,
    _FakeMarkets,
    _FakeSDKClient,
    _book_level,
    _book_response,
    _event,
    _settings,
)


def _not_found_error(message: str = "market not found") -> NotFoundError:
    request = httpx.Request("GET", "https://gateway.polymarket.us/fake")
    response = httpx.Response(404, request=request, text='{"error": "not found"}')
    return NotFoundError(message, response=response)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    calls: list[float] = []
    monkeypatch.setattr(us_client_module.time, "sleep", lambda seconds: calls.append(seconds))
    return calls


# --- _retry_on_not_found: the retry/backoff mechanics themselves -----------

def test_1_first_call_not_found_second_succeeds():
    """Requirement 1: first book call raises NotFoundError, second
    succeeds."""
    attempts = {"n": 0}

    def action():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _not_found_error()
        return "ok"

    result = _retry_on_not_found(
        action, endpoint="markets.book(slug-1)", max_retries=4, base_delay_seconds=0.5, max_delay_seconds=2.0,
        sleep=lambda s: None,
    )

    assert result == "ok"
    assert attempts["n"] == 2  # exactly one retry, never more than needed


def test_2_several_not_found_then_succeeds_within_the_warmup_window():
    """Requirement 2: the first several calls raise NotFoundError,
    then it succeeds, all within the bounded warmup window
    (max_retries=4 here easily covers 3 failures + 1 success)."""
    attempts = {"n": 0}

    def action():
        attempts["n"] += 1
        if attempts["n"] <= 3:
            raise _not_found_error()
        return "ok"

    result = _retry_on_not_found(
        action, endpoint="markets.book(slug-1)", max_retries=4, base_delay_seconds=0.5, max_delay_seconds=2.0,
        sleep=lambda s: None,
    )

    assert result == "ok"
    assert attempts["n"] == 4


def test_3_persistent_not_found_through_the_entire_warmup_raises(_no_real_sleep):
    """Requirement 3 (unit level): NotFoundError that never resolves
    exhausts the bounded warmup and RAISES -- never a fabricated
    "empty book" result. The end-to-end "safe NO TRADE" behavior this
    produces at the engine.run_cycle() level is proven separately
    below (test_3_persistent_...safe_no_trade)."""
    def always_not_found():
        raise _not_found_error("persistent")

    with pytest.raises(NotFoundError):
        _retry_on_not_found(
            always_not_found, endpoint="markets.book(slug-1)", max_retries=3, base_delay_seconds=0.5,
            max_delay_seconds=2.0, sleep=_no_real_sleep.append,
        )
    assert len(_no_real_sleep) == 3  # exactly max_retries backoffs, never more


def test_4_no_infinite_retry_bounded_attempt_count():
    """Requirement 4: never an infinite retry loop -- the TOTAL number
    of attempts is always exactly max_retries + 1 (the initial try),
    whatever max_retries is configured to."""
    attempts = {"n": 0}

    def always_not_found():
        attempts["n"] += 1
        raise _not_found_error("persistent")

    with pytest.raises(NotFoundError):
        _retry_on_not_found(
            always_not_found, endpoint="markets.book(slug-1)", max_retries=2, base_delay_seconds=0.1,
            max_delay_seconds=1.0, sleep=lambda s: None,
        )
    assert attempts["n"] == 3  # 1 initial + 2 retries, never more


def test_other_exceptions_are_never_retried_by_this_function():
    """Only NotFoundError is retried here -- any other exception type
    propagates on the very first attempt (the RateLimitError case is
    handled by the SEPARATE _retry_on_rate_limit/_retry layer -- see
    get_order_book()'s own composition of both)."""
    attempts = {"n": 0}

    def action():
        attempts["n"] += 1
        raise RuntimeError("some unrelated failure")

    with pytest.raises(RuntimeError):
        _retry_on_not_found(
            action, endpoint="markets.book(slug-1)", max_retries=4, base_delay_seconds=0.5, max_delay_seconds=2.0,
            sleep=lambda s: None,
        )
    assert attempts["n"] == 1


def test_retry_logs_the_exact_slug_attempt_number_and_recovery(caplog):
    """Requirement 12 (logging): the exact market slug (passed in via
    `endpoint`), the retry attempt number, and the eventual recovery
    are all visible in the log."""
    attempts = {"n": 0}

    def action():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _not_found_error()
        return "ok"

    with caplog.at_level("INFO", logger="src.polymarket.us_client"):
        _retry_on_not_found(
            action, endpoint="markets.book(cpc-btc-updown-15m-2026-10-10-1845z)", max_retries=4,
            base_delay_seconds=0.5, max_delay_seconds=2.0, sleep=lambda s: None,
        )

    messages = [r.getMessage() for r in caplog.records]
    assert any(
        "cpc-btc-updown-15m-2026-10-10-1845z" in m and "warmup" in m and "retry 1/4" in m for m in messages
    )
    assert any("cpc-btc-updown-15m-2026-10-10-1845z" in m and "became available" in m for m in messages)


# --- get_order_book(): the real call site -----------------------------------

def test_get_order_book_recovers_from_a_warmup_race(_no_real_sleep):
    response = _book_response([_book_level("0.44", "10")], [_book_level("0.46", "10")])
    markets = _FakeMarkets(book_side_effects=[_not_found_error(), response])
    sdk = _FakeSDKClient(markets=markets)
    client = PolymarketUSClient(_settings(), sdk_client=sdk)

    book = client.get_order_book("tok-1")

    assert book.best_bid == 0.44
    assert book.best_ask == 0.46
    assert len(markets.book_calls) == 2
    assert len(_no_real_sleep) == 1


# --- discovery-level: exact slug preserved, no fallback market -------------

def _warmup_event(event_slug: str, market_slug: str) -> dict:
    now = datetime.now(timezone.utc)
    return _event(slug=event_slug, start=now - timedelta(minutes=1), end=now + timedelta(minutes=14), market_slug=market_slug)


def test_6_exact_nested_slug_is_preserved_through_the_retry_loop(_no_real_sleep):
    """Requirement 6: the EXACT nested market slug returned by the
    event (never the event's own slug, never synthesized by string
    concatenation) is what every single warmup retry attempt targets."""
    event_slug = "btc-updown-15m-2026-10-10-1845z"
    market_slug = "cpc-btc-updown-15m-2026-10-10-1845z"
    event = _warmup_event(event_slug, market_slug)
    response = _book_response([_book_level("0.54", "100")], [_book_level("0.55", "100")])
    markets = _FakeMarkets(book_side_effects=[_not_found_error(), response], books={market_slug: response})
    sdk = _FakeSDKClient(events=_FakeEvents({event_slug: {"event": event}}), markets=markets)
    client = PolymarketUSClient(_settings(POLYMARKET_US_MARKET_SLUG=event_slug), sdk_client=sdk)

    market = client.find_active_btc_market()

    assert market.condition_id == event_slug
    assert market.token_id_yes == market.token_id_no == market_slug  # never synthesized, never the event slug
    assert all(slug == market_slug for slug in markets.book_calls)  # every attempt hit the SAME exact slug
    assert len(markets.book_calls) == 2  # 1 failed attempt + 1 recovery -- for the SAME market, never a second one


def test_5_no_fallback_market_is_ever_queried_even_after_warmup_exhausts(_no_real_sleep):
    """Requirement 5: a persistently-unavailable book must never cause
    a search or a fallback to a different market. find_active_btc_market()
    deterministically resolves ONE exact event/market and never
    substitutes anything else, regardless of whether that market's own
    book ever becomes available."""
    event_slug = "btc-updown-15m-2026-10-10-1845z"
    market_slug = "cpc-btc-updown-15m-2026-10-10-1845z"
    event = _warmup_event(event_slug, market_slug)
    markets = _FakeMarkets(book_exc=_not_found_error("persistent"))
    sdk = _FakeSDKClient(events=_FakeEvents({event_slug: {"event": event}}), markets=markets)
    client = PolymarketUSClient(_settings(POLYMARKET_US_MARKET_SLUG=event_slug), sdk_client=sdk)

    # _to_binary_market's own summary-price convenience fetch swallows
    # the exhausted warmup entirely -- discovery itself still succeeds
    # and still names the ONE correct market, never a different one.
    market = client.find_active_btc_market()

    assert market.condition_id == event_slug
    assert market.token_id_yes == market.token_id_no == market_slug
    assert market.yes_bid is None and market.yes_ask is None  # swallowed, never fabricated
    assert sdk.search.calls == []  # never searched for a fallback
    assert all(slug == market_slug for slug in markets.book_calls)  # never queried a different market's book


# --- engine.run_cycle(): persistent 404 -> safe NO TRADE, never a crash ----

def _market(**overrides) -> BinaryMarket:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="c1", question="Will BTC be up?", token_id_yes="y", token_id_no="n",
        close_time=now + timedelta(minutes=10), fetched_at=now, yes_bid=0.60, yes_ask=0.62,
    )
    defaults.update(overrides)
    return BinaryMarket(**defaults)


class _NotFoundOrderBookClient:
    """Mirrors the SHAPE engine.py needs from a client, standing in
    for what us_client.PolymarketUSClient.get_order_book() does once
    its OWN internal warmup retries are already exhausted: raises
    NotFoundError straight through. Tests at this level that
    engine.run_cycle() degrades safely regardless of what us_client.py's
    warmup retry layer decided."""

    def __init__(self, market: BinaryMarket):
        self._market = market
        self.get_order_book_calls: list[str] = []

    def find_active_btc_market(self, *, now=None) -> BinaryMarket:
        return self._market

    def get_order_book(self, token_id: str) -> OrderBookSnapshot:
        self.get_order_book_calls.append(token_id)
        raise _not_found_error("persistent -- warmup already exhausted upstream")

    def get_resolution(self, condition_id: str) -> str | None:
        return None


def test_3_persistent_not_found_through_the_entire_warmup_is_a_safe_no_trade(tmp_path):
    """Requirement 3 (end to end) + 11: once the book warmup exhausts
    for real, run_cycle() must never crash and must never place a
    false order -- it sits the cycle out cleanly."""
    now = datetime.now(timezone.utc)
    market = _market(yes_bid=0.78, yes_ask=0.80, close_time=now + timedelta(seconds=200))
    settings = _settings(POLYMARKET_LOG_DIR=str(tmp_path))
    client = _NotFoundOrderBookClient(market)
    strategy = BtcMomentumStrategy()
    risk = PolymarketRiskManager(settings)
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    gateway = PaperPolymarketGateway(settings, logger)
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    from src.polymarket.btc_market_data import BtcPriceHistoryStore
    history = MarketHistory()
    history.observe(market)
    btc_price_store = BtcPriceHistoryStore(tmp_path / "btc.json")

    report = run_cycle(
        settings=settings, client=client, strategy=strategy, risk_manager=risk, gateway=gateway,
        decision_logger=logger, state_store=state_store, position_store=position_store,
        pending_store=pending_store, history=history, btc_price_store=btc_price_store, now=now,
    )

    assert report.ran is True  # never crashed
    assert report.entered is False  # no false entry
    assert position_store.load() == []
    entries = [e for e in logger.read_all() if e.get("kind") == "no_trade"]
    assert any("NotFoundError" in e.get("reason", "") for e in entries)


# --- single real book fetch once after recovery; NO-perspective derivation -

def test_7_and_8_single_real_book_fetch_and_no_perspective_derivation(_no_real_sleep):
    """Requirements 7 + 8: once the warmup recovers, YES/NO perspective
    derivation (single_book.to_no_perspective()) still operates on
    THAT ONE real, recovered book -- never a second, independent
    fetch under a different name. Mirrors the exact production
    sequence: discover -> (warmup-aware) book fetch -> derive NO's
    perspective from that SAME book."""
    event_slug = "btc-updown-15m-2026-10-10-1845z"
    market_slug = "cpc-btc-updown-15m-2026-10-10-1845z"
    event = _warmup_event(event_slug, market_slug)
    response = _book_response([_book_level("0.27", "100")], [_book_level("0.30", "100")])
    markets = _FakeMarkets(book_side_effects=[_not_found_error(), response], books={market_slug: response})
    sdk = _FakeSDKClient(events=_FakeEvents({event_slug: {"event": event}}), markets=markets)
    client = PolymarketUSClient(_settings(POLYMARKET_US_MARKET_SLUG=event_slug), sdk_client=sdk)

    market = client.find_active_btc_market()
    assert is_single_book_market(market) is True
    calls_after_discovery = len(markets.book_calls)
    assert calls_after_discovery == 2  # discovery's own summary-price fetch already recovered via warmup

    # The SAME real fetch engine.py's entry path performs, moments later:
    yes_book = client.get_order_book(market.token_id_yes)
    assert len(markets.book_calls) == calls_after_discovery + 1  # exactly ONE more call, not a retry storm
    assert yes_book.best_bid == 0.27
    assert yes_book.best_ask == 0.30

    no_book = to_no_perspective(yes_book)  # derived, never a second independent fetch
    assert no_book.best_bid == pytest.approx(0.70)  # 1 - 0.30
    assert no_book.best_ask == pytest.approx(0.73)  # 1 - 0.27
    assert len(markets.book_calls) == calls_after_discovery + 1  # the derivation itself made NO further call
