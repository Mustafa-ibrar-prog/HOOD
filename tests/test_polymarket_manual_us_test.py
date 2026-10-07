"""Tests for scripts/manual_polymarket_us_test.py's testable core
(run_manual_test) -- the ONE-TIME MANUAL LIVE TEST for Polymarket US
(see that script's module docstring for the full flow/safety-gate
list).

Reuses the fake-SDK boundary objects and fixture builders already
established in tests/test_polymarket_us_client.py (_FakeSDKClient,
_FakeEvents, _FakeMarkets, _FakeOrders, _event, _book_level,
_book_response, _order_response, _settings) rather than duplicating
them -- this file only adds what's specific to exercising
run_manual_test's own gate logic (amount cap, emergency stop, the
live-mode switches, preview success/failure, submission-vs-fill,
duplicate reconciliation).

IMPORTANT: run_manual_test's risk checks (DATA_FRESHNESS, ENTRY_CUTOFF)
read BinaryMarket.data_age_seconds / seconds_to_close, which are both
computed against the REAL wall clock (datetime.now(timezone.utc)), not
against any `now` passed in. So every fixture below anchors its
start/end times to the real wall clock at test-run time (`_real_now()`),
never to a fixed historical date.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from scripts.manual_polymarket_us_test import main, run_manual_test  # noqa: E402
from src.execution.emergency_stop import EmergencyStopStore  # noqa: E402
from src.polymarket import reconciliation  # noqa: E402
from src.polymarket.logger import PolymarketDecisionLogger  # noqa: E402
from src.polymarket.pending import PolymarketPendingOrderStore  # noqa: E402
from src.polymarket.positions import PolymarketPositionStore  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.state import DailyPnlStateStore  # noqa: E402
from src.polymarket.us_client import PolymarketUSClient  # noqa: E402
from tests.test_polymarket_us_client import (  # noqa: E402
    _FakeEvents,
    _FakeMarkets,
    _FakeOrders,
    _FakeSDKClient,
    _book_level,
    _book_response,
    _event,
    _order_response,
)


def _real_now() -> datetime:
    return datetime.now(timezone.utc)


_LIVE_CREDS = {"POLYMARKET_US_KEY_ID": "test-key-id", "POLYMARKET_US_SECRET_KEY": "dGVzdC1zZWNyZXQ="}


def _settings(slug: str, **overrides) -> PolymarketSettings:
    env = {"POLYMARKET_VENUE": "us", "POLYMARKET_US_MARKET_SLUG": slug}
    env.update(overrides)
    return PolymarketSettings.from_env(env=env)


def _good_book() -> dict:
    # bid/ask within POLYMARKET_MAX_SPREAD_PCT's 5% default, and enough
    # size at/below a 0.60 max_price to clear the $25 default
    # POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD.
    return _book_response([_book_level("0.54", 100)], [_book_level("0.55", 100)])


def _happy_event(slug: str) -> dict:
    now = _real_now()
    return _event(slug=slug, start=now - timedelta(minutes=1), end=now + timedelta(minutes=10), market_slug=slug)


def _happy_sdk(slug: str, *, orders: _FakeOrders | None = None) -> _FakeSDKClient:
    return _FakeSDKClient(
        events=_FakeEvents({slug: {"event": _happy_event(slug)}}),
        markets=_FakeMarkets(books={slug: _good_book()}),
        orders=orders or _FakeOrders(),
    )


def _stores(tmp_path) -> dict:
    return dict(
        decision_logger=PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False),
        state_store=DailyPnlStateStore(tmp_path / "pnl.json"),
        position_store=PolymarketPositionStore(tmp_path / "positions.json"),
        pending_store=PolymarketPendingOrderStore(tmp_path / "pending.json"),
        emergency_stop_store=EmergencyStopStore(tmp_path / "estop.json"),
    )


def _stores_with_emergency_stop_cleared(tmp_path) -> dict:
    """EmergencyStopStore fails closed: with no persisted record at
    all, is_stopped() defaults to True (STOPPED) -- see
    emergency_stop.py's _DEFAULT_STATE. Tests that need to reach past
    the emergency-stop gate (to exercise preview/submission/
    reconciliation behavior) must explicitly clear it first, exactly
    like a real human operator would have to."""
    stores = _stores(tmp_path)
    stores["emergency_stop_store"].clear(authorized_by="user:test-harness", reason="test setup")
    return stores


def _run(settings, client, stores, *, outcome="YES", amount=5.0, max_price=0.60, confirm_live=False):
    return run_manual_test(
        settings=settings, client=client, outcome=outcome, amount=amount, max_price=max_price,
        confirm_live=confirm_live, **stores,
    )


# --- Paper mode (the default) -----------------------------------------------

def test_paper_mode_default_opens_a_position_from_a_simulated_fill(tmp_path, capsys):
    slug = "manual-test-market-1"
    sdk = _happy_sdk(slug)
    client = PolymarketUSClient(_settings(slug), sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(_settings(slug), client, stores)

    assert rc == 0
    assert stores["position_store"].load()[0].condition_id == slug
    assert "PAPER FILL" in capsys.readouterr().out


def test_confirm_live_in_paper_mode_is_still_only_a_paper_dry_run(tmp_path, capsys):
    """--confirm-live alone, without POLYMARKET_TRADING_MODE=live, must
    never place a real order -- it silently falls through to the exact
    same paper pipeline, with a note explaining why."""
    slug = "manual-test-market-2"
    sdk = _happy_sdk(slug)
    client = PolymarketUSClient(_settings(slug), sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(_settings(slug), client, stores, confirm_live=True)

    assert rc == 0
    out = capsys.readouterr().out
    assert "PAPER-only dry run" in out
    assert sdk.orders.create_calls == []  # never actually submitted anywhere


# --- Gate 5: amount vs POLYMARKET_MAX_BET_USD --------------------------------

def test_amount_over_max_bet_is_refused_before_any_market_lookup(tmp_path, capsys):
    slug = "manual-test-market-3"
    sdk = _FakeSDKClient()  # deliberately empty -- must never be consulted
    client = PolymarketUSClient(_settings(slug, POLYMARKET_MAX_BET_USD="5.0"), sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(_settings(slug, POLYMARKET_MAX_BET_USD="5.0"), client, stores, amount=100.0)

    assert rc == 1
    assert "exceeds the configured" in capsys.readouterr().out
    assert stores["pending_store"].load() == []


# --- Manual-override market resolution failures (reject, don't crash) ------

def test_missing_market_is_refused_cleanly(tmp_path, capsys):
    slug = "does-not-exist-anywhere"
    sdk = _FakeSDKClient()  # no event, no market registered under this slug
    client = PolymarketUSClient(_settings(slug), sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(_settings(slug), client, stores)

    assert rc == 1
    assert "could not retrieve the exact market" in capsys.readouterr().out


def test_mismatched_slug_is_refused_cleanly(tmp_path, capsys):
    slug = "manual-test-market-mismatch"
    now = _real_now()
    wrong = _event(slug="something-else-entirely", start=now - timedelta(minutes=1), end=now + timedelta(minutes=10))
    sdk = _FakeSDKClient(events=_FakeEvents({slug: {"event": wrong}}))
    client = PolymarketUSClient(_settings(slug), sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(_settings(slug), client, stores)

    assert rc == 1
    assert "could not retrieve the exact market" in capsys.readouterr().out


def test_inactive_market_is_refused_cleanly(tmp_path, capsys):
    slug = "manual-test-market-inactive"
    now = _real_now()
    inactive = _event(slug=slug, start=now - timedelta(minutes=1), end=now + timedelta(minutes=10),
                       market_slug=slug, active=False, closed=True)
    sdk = _FakeSDKClient(events=_FakeEvents({slug: {"event": inactive}}))
    client = PolymarketUSClient(_settings(slug), sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(_settings(slug), client, stores)

    assert rc == 1
    assert "could not retrieve the exact market" in capsys.readouterr().out


# --- Risk checks still apply in the manual-override path --------------------

def test_insufficient_liquidity_is_refused_by_risk_checks(tmp_path, capsys):
    slug = "manual-test-market-illiquid"
    now = _real_now()
    event = _event(slug=slug, start=now - timedelta(minutes=1), end=now + timedelta(minutes=10), market_slug=slug)
    thin_book = _book_response([_book_level("0.54", 1)], [_book_level("0.55", 1)])  # $0.55 total, well under $25
    sdk = _FakeSDKClient(events=_FakeEvents({slug: {"event": event}}), markets=_FakeMarkets(books={slug: thin_book}))
    client = PolymarketUSClient(_settings(slug), sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(_settings(slug), client, stores)

    assert rc == 1
    out = capsys.readouterr().out
    assert "ORDER_BOOK_LIQUIDITY" in out
    assert "risk checks did not pass" in out
    assert stores["position_store"].load() == []


# --- No manual override set => existing BTC 15m discovery path untouched ---

def test_no_slug_set_falls_through_to_btc_15m_discovery(tmp_path, capsys):
    """Deliberately does NOT assert rc==0 / a position being opened --
    the real current 15-minute window's remaining time (and thus
    ENTRY_CUTOFF) is a function of the wall clock at the moment this
    test happens to run, which this test must not be sensitive to. The
    one property under test is that, with POLYMARKET_US_MARKET_SLUG
    unset, run_manual_test resolves the market via the real BTC 15m
    deterministic-slug discovery path (client._current_window/
    _expected_event_slug) rather than the manual-override path or a
    "could not retrieve the exact market" failure."""
    now = _real_now()
    settings_no_slug = PolymarketSettings.from_env(env={"POLYMARKET_VENUE": "us"})
    client = PolymarketUSClient(settings_no_slug)
    window_start, window_end = client._current_window(now)
    btc_slug = client._expected_event_slug(window_start)
    event = _event(slug=btc_slug, start=window_start, end=window_end, market_slug=btc_slug, title="BTC Up or Down 15m")
    sdk = _FakeSDKClient(events=_FakeEvents({btc_slug: {"event": event}}), markets=_FakeMarkets(books={btc_slug: _good_book()}))
    client = PolymarketUSClient(settings_no_slug, sdk_client=sdk)
    stores = _stores(tmp_path)

    _run(settings_no_slug, client, stores)

    assert f"slug:      {btc_slug}" in capsys.readouterr().out


# --- Live mode: every gate is independently required ------------------------

def test_live_without_confirm_live_flag_stops_at_awaiting_approval(tmp_path, capsys):
    """Gate 3 missing: POLYMARKET_TRADING_MODE=live and
    LIVE_TRADING_CONFIRMED=true are set, but --confirm-live was not
    passed -- must stop cleanly with no submission, return 0 (this is
    an expected, clean stop, not a failure)."""
    slug = "manual-test-live-1"
    sdk = _happy_sdk(slug)
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(settings, client, stores, confirm_live=False)

    assert rc == 0
    assert "No real order placed" in capsys.readouterr().out
    assert sdk.orders.create_calls == []
    assert stores["position_store"].load() == []


def test_live_trading_not_confirmed_is_refused_even_with_confirm_live(tmp_path, capsys):
    """Gate 1/2 missing: POLYMARKET_TRADING_MODE=live but
    POLYMARKET_LIVE_TRADING_CONFIRMED is NOT true -- LivePolymarketGateway
    itself refuses to construct; must surface as a clean REFUSING
    message, never an unhandled traceback."""
    slug = "manual-test-live-2"
    sdk = _happy_sdk(slug)
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="false",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores(tmp_path)

    rc = _run(settings, client, stores, confirm_live=True)

    assert rc == 1
    assert "REFUSING" in capsys.readouterr().out
    assert sdk.orders.create_calls == []


def test_emergency_stop_active_refuses_a_live_attempt(tmp_path, capsys):
    slug = "manual-test-live-3"
    sdk = _happy_sdk(slug)
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores(tmp_path)
    stores["emergency_stop_store"].activate(reason="test", set_by="system:test")

    rc = _run(settings, client, stores, confirm_live=True)

    assert rc == 1
    assert "emergency stop is ACTIVE" in capsys.readouterr().out
    assert sdk.orders.create_calls == []


def test_preview_failure_refuses_a_live_attempt(tmp_path, capsys):
    """Gate 6: orders.preview() failing must block a live submission,
    even though every other gate is satisfied."""
    slug = "manual-test-live-4"
    sdk = _happy_sdk(slug, orders=_FakeOrders(preview_exc=RuntimeError("preview endpoint is down")))
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)

    rc = _run(settings, client, stores, confirm_live=True)

    assert rc == 1
    assert "orders.preview() did not succeed" in capsys.readouterr().out
    assert sdk.orders.create_calls == []


# --- Live happy path: submission reaches the exchange, then reconciles -----

def test_live_submission_that_fills_opens_a_position(tmp_path, capsys):
    """Order submission != fill determination: place_order()'s own
    response is ignored for fill purposes; only the separate
    reconcile_order() -> get_fill_status() lookup decides whether a
    position opens."""
    slug = "manual-test-live-5"
    orders = _FakeOrders(
        preview_response={"order": {"id": "preview-ok"}},
        create_response={"id": "ord-live-5", "executions": []},
        retrieve_responses={"ord-live-5": _order_response("ORDER_STATE_FILLED", quantity=8, cum=8, avg_px="0.55")},
    )
    sdk = _happy_sdk(slug, orders=orders)
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)

    rc = _run(settings, client, stores, confirm_live=True)

    assert rc == 0
    out = capsys.readouterr().out
    assert "Submission result: submitted" in out
    assert "POSITION OPENED" in out
    positions = stores["position_store"].load()
    assert len(positions) == 1
    assert positions[0].condition_id == slug


def test_live_submission_that_does_not_fill_opens_no_position(tmp_path, capsys):
    slug = "manual-test-live-6"
    orders = _FakeOrders(
        preview_response={"order": {"id": "preview-ok"}},
        create_response={"id": "ord-live-6", "executions": []},
        retrieve_responses={"ord-live-6": _order_response("ORDER_STATE_REJECTED", quantity=8, cum=0)},
    )
    sdk = _happy_sdk(slug, orders=orders)
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)

    rc = _run(settings, client, stores, confirm_live=True)

    assert rc == 0
    assert "No position opened" in capsys.readouterr().out
    assert stores["position_store"].load() == []


def test_duplicate_reconciliation_does_not_double_create_a_position(tmp_path):
    """Calling reconcile_order() a second time for the same pending
    order (e.g. a restart-safety sweep picking up the same order this
    script already reconciled) must be a no-op, per
    reconciliation.py's own idempotency guard."""
    slug = "manual-test-live-7"
    orders = _FakeOrders(
        preview_response={"order": {"id": "preview-ok"}},
        create_response={"id": "ord-live-7", "executions": []},
        retrieve_responses={"ord-live-7": _order_response("ORDER_STATE_FILLED", quantity=8, cum=8, avg_px="0.55")},
    )
    sdk = _happy_sdk(slug, orders=orders)
    settings = _settings(
        slug, **_LIVE_CREDS, POLYMARKET_TRADING_MODE="live", POLYMARKET_LIVE_TRADING_CONFIRMED="true",
    )
    client = PolymarketUSClient(settings, sdk_client=sdk)
    stores = _stores_with_emergency_stop_cleared(tmp_path)

    rc = _run(settings, client, stores, confirm_live=True)
    assert rc == 0
    assert len(stores["position_store"].load()) == 1

    pending = stores["pending_store"].load()[0]
    second = reconciliation.reconcile_order(
        pending, client=client, pending_store=stores["pending_store"], position_store=stores["position_store"],
        state_store=stores["state_store"], decision_logger=stores["decision_logger"],
    )

    assert second is None  # already reconciled -- no-op
    assert len(stores["position_store"].load()) == 1


# --- main()'s argparse-level gates ------------------------------------------

def test_bad_outcome_is_rejected_by_argparse(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "manual_polymarket_us_test.py", "--market-slug", "whatever", "--outcome", "MAYBE",
        "--amount", "5", "--max-price", "0.6",
    ])
    with pytest.raises(SystemExit):
        main()


def test_non_us_venue_is_refused(monkeypatch, tmp_path, capsys):
    """main() itself (not run_manual_test) must refuse to proceed when
    POLYMARKET_VENUE isn't "us" -- this script only ever makes sense
    against the US venue's manual-override mechanism."""
    monkeypatch.setattr(sys, "argv", [
        "manual_polymarket_us_test.py", "--market-slug", "whatever", "--outcome", "YES",
        "--amount", "5", "--max-price", "0.6",
    ])
    monkeypatch.setenv("POLYMARKET_VENUE", "international")
    # main() itself writes os.environ["POLYMARKET_US_MARKET_SLUG"] directly
    # (the same mechanism verify_polymarket_setup.py --market-slug uses) --
    # pre-registering it with monkeypatch here ensures that mutation is
    # still cleaned up after this test, even though monkeypatch didn't
    # perform it directly.
    monkeypatch.setenv("POLYMARKET_US_MARKET_SLUG", "placeholder")
    monkeypatch.chdir(tmp_path)  # no .env file here to accidentally override POLYMARKET_VENUE
    rc = main()
    assert rc == 1
    assert "Polymarket US only" in capsys.readouterr().out
