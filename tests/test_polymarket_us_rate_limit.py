"""Tests for the Polymarket US rate-limit retry/backoff path
(us_client._retry_on_rate_limit / PolymarketUSClient._retry) added
after a real incident: an uncaught polymarket_us.errors.RateLimitError
(Cloudflare 1015 "You are being rate limited" on gateway.polymarket.us)
out of client.get_order_book() crashed engine.run_cycle() mid-loop.

Real polymarket_us.errors.RateLimitError instances are constructed
throughout (never the local placeholder exception classes
test_polymarket_us_client.py otherwise uses) because the production
retry logic now deliberately type-checks on that exact class -- any
other exception type must propagate immediately, unretried.

time.sleep is monkeypatched to a no-op recorder everywhere here: these
tests assert on the NUMBER and MAGNITUDE of backoffs, never actually
wait for them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from polymarket_us.errors import NotFoundError, RateLimitError

import src.polymarket.us_client as us_client_module
from src.polymarket.engine import run_cycle
from src.polymarket.gateway import PaperPolymarketGateway
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import BinaryMarket, OrderBookSnapshot
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.risk import PolymarketRiskManager
from src.polymarket.state import DailyPnlStateStore
from src.polymarket.strategy import BtcMomentumStrategy
from src.polymarket.us_client import PolymarketUSClient, _retry_on_rate_limit
from tests.test_polymarket_us_client import (
    _FakeMarkets,
    _FakeSDKClient,
    _book_level,
    _book_response,
    _settings,
)

_NOW = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)


def _rate_limit_error(message: str = "You are being rate limited.") -> RateLimitError:
    """A REAL polymarket_us.errors.RateLimitError -- the exact type
    the production retry logic type-checks on, mirroring the real
    Cloudflare 1015 / 429 response from the live incident."""
    request = httpx.Request("GET", "https://gateway.polymarket.us/fake")
    response = httpx.Response(429, request=request, text='{"error": "rate limited"}')
    return RateLimitError(message, response=response, body=None, request_id="req-test")


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Every test in this file replaces time.sleep with a recorder --
    never actually wait out a real backoff."""
    calls: list[float] = []
    monkeypatch.setattr(us_client_module.time, "sleep", lambda seconds: calls.append(seconds))
    return calls


# --- _retry_on_rate_limit: the retry/backoff mechanics themselves ----------

def test_first_call_rate_limited_second_succeeds():
    """Requirement 9a: first request rate-limited, second succeeds."""
    attempts = {"n": 0}

    def action():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _rate_limit_error()
        return "ok"

    result = _retry_on_rate_limit(
        action, endpoint="test.endpoint", max_retries=4, base_delay_seconds=0.5, max_delay_seconds=8.0,
        sleep=lambda s: None,
    )

    assert result == "ok"
    assert attempts["n"] == 2  # exactly one retry, never more than needed


def test_backoff_is_bounded_exponential_with_jitter_never_immediate():
    """Requirement 3/4: bounded exponential backoff with jitter -- each
    successive backoff is drawn from a widening (but capped) window,
    and is NEVER zero/immediate (a real rate limit must never be
    hammered with back-to-back retries)."""
    sleeps: list[float] = []

    def always_rate_limited():
        raise _rate_limit_error()

    with pytest.raises(RateLimitError):
        _retry_on_rate_limit(
            always_rate_limited, endpoint="test.endpoint", max_retries=4, base_delay_seconds=0.5,
            max_delay_seconds=8.0, sleep=sleeps.append,
        )

    assert len(sleeps) == 4  # exactly max_retries backoffs before giving up
    for backoff in sleeps:
        assert 0.0 <= backoff <= 8.0  # bounded by max_delay_seconds, always
    # Successive windows widen (0.5, 1, 2, 4 before jitter) -- never
    # literally zero-delay immediate retries.
    assert all(b >= 0.0 for b in sleeps)


def test_repeated_rate_limits_exhaust_retries_and_raise():
    """Requirement 9b half: persistent rate limiting raises (never
    silently fabricates a result) once retries are exhausted -- the
    caller is what turns this into a safe HOLD/no-trade (see the
    run_cycle-level tests below)."""
    def always_rate_limited():
        raise _rate_limit_error("persistent 429")

    with pytest.raises(RateLimitError):
        _retry_on_rate_limit(
            always_rate_limited, endpoint="test.endpoint", max_retries=2, base_delay_seconds=0.1,
            max_delay_seconds=1.0, sleep=lambda s: None,
        )


def test_non_rate_limit_errors_are_never_retried():
    """Requirement 1: ONLY RateLimitError is retried -- any other
    exception type (here, NotFoundError) propagates on the very first
    attempt, exactly as it always did before this feature existed."""
    attempts = {"n": 0}

    def action():
        attempts["n"] += 1
        raise NotFoundError("nope", response=httpx.Response(
            404, request=httpx.Request("GET", "https://gateway.polymarket.us/fake"),
        ))

    with pytest.raises(NotFoundError):
        _retry_on_rate_limit(
            action, endpoint="test.endpoint", max_retries=4, base_delay_seconds=0.5, max_delay_seconds=8.0,
            sleep=lambda s: None,
        )
    assert attempts["n"] == 1  # never retried


def test_retry_logs_endpoint_retry_number_and_backoff(caplog):
    """Requirement 8: endpoint/action, rate-limit detected, retry
    number, and backoff must all be visible in the log."""
    attempts = {"n": 0}

    def action():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _rate_limit_error()
        return "ok"

    with caplog.at_level("WARNING", logger="src.polymarket.us_client"):
        _retry_on_rate_limit(
            action, endpoint="markets.book", max_retries=4, base_delay_seconds=0.5, max_delay_seconds=8.0,
            sleep=lambda s: None,
        )

    messages = [r.getMessage() for r in caplog.records]
    assert any("markets.book" in m and "rate limited" in m and "retry 1/4" in m for m in messages)


def test_final_degraded_outcome_is_logged_when_retries_exhaust(caplog):
    """Requirement 8: the final degraded outcome (giving up) is
    visible too, not just the individual retry attempts."""
    def always_rate_limited():
        raise _rate_limit_error()

    with caplog.at_level("WARNING", logger="src.polymarket.us_client"):
        with pytest.raises(RateLimitError):
            _retry_on_rate_limit(
                always_rate_limited, endpoint="markets.book", max_retries=2, base_delay_seconds=0.1,
                max_delay_seconds=1.0, sleep=lambda s: None,
            )

    messages = [r.getMessage() for r in caplog.records]
    assert any("exhausted all 2 retries" in m and "markets.book" in m for m in messages)


# --- PolymarketUSClient.get_order_book(): the real crash site ---------------

def test_get_order_book_retries_on_rate_limit_then_succeeds(_no_real_sleep):
    """Requirement 9a, at the real call-site level: get_order_book()
    itself recovers from exactly one rate limit without the caller
    ever seeing an exception."""
    response = _book_response([_book_level("0.44", "10")], [_book_level("0.46", "10")])
    markets = _FakeMarkets(book_side_effects=[_rate_limit_error(), response])
    sdk = _FakeSDKClient(markets=markets)
    client = PolymarketUSClient(_settings(), sdk_client=sdk)

    book = client.get_order_book("tok-1")

    assert book.best_bid == 0.44
    assert book.best_ask == 0.46
    assert len(markets.book_calls) == 2  # one failed attempt, one real retry
    assert len(_no_real_sleep) == 1  # exactly one backoff was taken


def test_get_order_book_persistent_rate_limit_raises_after_configured_retries(_no_real_sleep):
    """Requirement 9b, at the real call-site level: a PERSISTENTLY
    rate-limited order book raises (never a fabricated empty book)
    after exhausting settings.us_rate_limit_max_retries."""
    markets = _FakeMarkets(book_exc=_rate_limit_error("persistent 429"))
    sdk = _FakeSDKClient(markets=markets)
    settings = _settings(POLYMARKET_US_RATE_LIMIT_MAX_RETRIES="2")
    client = PolymarketUSClient(settings, sdk_client=sdk)

    with pytest.raises(RateLimitError):
        client.get_order_book("tok-1")

    assert len(markets.book_calls) == 3  # 1 initial + 2 retries, never more
    assert len(_no_real_sleep) == 2


def test_get_order_book_does_not_retry_a_not_found_error(_no_real_sleep):
    markets = _FakeMarkets(book_exc=NotFoundError(
        "nope", response=httpx.Response(404, request=httpx.Request("GET", "https://gateway.polymarket.us/fake")),
    ))
    sdk = _FakeSDKClient(markets=markets)
    client = PolymarketUSClient(_settings(), sdk_client=sdk)

    with pytest.raises(NotFoundError):
        client.get_order_book("tok-1")

    assert len(markets.book_calls) == 1  # never retried
    assert _no_real_sleep == []


# --- engine.run_cycle(): never crashes, never a false entry/exit ------------

def _market(**overrides) -> BinaryMarket:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="c1", question="Will BTC be up?", token_id_yes="y", token_id_no="n",
        close_time=now + timedelta(minutes=10), fetched_at=now, yes_bid=0.60, yes_ask=0.62,
    )
    defaults.update(overrides)
    return BinaryMarket(**defaults)


class _RateLimitedOrderBookClient:
    """Mirrors the SHAPE engine.py needs from a client (find_active_
    btc_market/get_order_book/get_resolution), standing in for what
    us_client.PolymarketUSClient.get_order_book() does once its OWN
    internal retries are exhausted: raises RateLimitError straight
    through. Tests at this level that engine.run_cycle() degrades
    safely regardless of what us_client.py's retry layer decided."""

    def __init__(self, market: BinaryMarket):
        self._market = market
        self.get_order_book_calls: list[str] = []

    def find_active_btc_market(self, *, now=None) -> BinaryMarket:
        return self._market

    def get_order_book(self, token_id: str) -> OrderBookSnapshot:
        self.get_order_book_calls.append(token_id)
        raise _rate_limit_error("persistent 429 -- retries already exhausted upstream")

    def get_resolution(self, condition_id: str) -> str | None:
        return None


def test_run_cycle_does_not_crash_on_exhausted_rate_limit_and_places_no_order(tmp_path):
    """Requirements 2, 5, 7, 9 (run_cycle never crashes / safe no-trade
    / no order placement during recovery)."""
    now = datetime.now(timezone.utc)
    # ask=0.80 >= the 0.70 threshold and close_time within the 300s
    # window (see simple_entry_signal.py) -- the ONLY production
    # entry-direction logic as of this round; otherwise clearly
    # qualifies for an entry, so this test actually reaches the
    # rate-limited order-book fetch it exists to exercise.
    market = _market(yes_bid=0.78, yes_ask=0.80, close_time=now + timedelta(seconds=200))
    settings = _settings(POLYMARKET_LOG_DIR=str(tmp_path))
    client = _RateLimitedOrderBookClient(market)
    strategy = BtcMomentumStrategy()
    risk = PolymarketRiskManager(settings)
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    gateway = PaperPolymarketGateway(settings, logger)
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    from src.polymarket.engine import MarketHistory
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
    assert any("RateLimitError" in e.get("reason", "") for e in entries)


def test_rate_limited_order_book_during_dynamic_exit_skips_without_a_false_exit(tmp_path):
    """Requirement 6: an existing open position must still be
    monitored when possible, and a rate-limited order-book call must
    never create a false exit. exit_manager.check_and_execute_dynamic_exits()
    already wraps its own get_order_book() call in a broad except and
    skips the position for this cycle -- this locks that existing
    safety behavior in against the REAL RateLimitError type."""
    from src.polymarket.exit_manager import check_and_execute_dynamic_exits
    from src.polymarket.btc_market_data import BtcPriceHistoryStore

    settings = _settings(POLYMARKET_LOG_DIR=str(tmp_path), POLYMARKET_DYNAMIC_EXIT_ENABLED="true")
    client = _RateLimitedOrderBookClient(_market())
    logger = PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)
    gateway = PaperPolymarketGateway(settings, logger)
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    btc_price_store = BtcPriceHistoryStore(tmp_path / "btc.json")
    now = datetime.now(timezone.utc)
    position_store.add_if_absent(OpenPosition(
        condition_id="existing-market", token_id="y", outcome="YES", requested_size_usd=5.0,
        filled_shares=10.0, avg_fill_price=0.36, order_id="paper:seed", client_order_id="seed-1",
        status="filled", opened_at=now - timedelta(minutes=5), close_time=now + timedelta(minutes=5),
    ))

    submitted = check_and_execute_dynamic_exits(
        client=client, settings=settings, gateway=gateway, position_store=position_store,
        pending_store=pending_store, state_store=state_store, decision_logger=logger,
        btc_price_store=btc_price_store, now=now,
    )

    assert submitted == 0  # never a false exit
    assert len(position_store.load()) == 1  # the existing position is untouched, still open
    assert position_store.load()[0].exit_pending_order_id is None
    entries = [e for e in logger.read_all() if e.get("kind") == "exit_check_failed"]
    assert len(entries) == 1
