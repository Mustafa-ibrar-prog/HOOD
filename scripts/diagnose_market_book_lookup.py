#!/usr/bin/env python3
"""READ-ONLY diagnostic for the Polymarket US discovery -> order-book
lookup path: exactly reproduces, and prints at each step, the real
request chain find_active_btc_market() + get_order_book() make, so a
NotFoundError on the book call can be diagnosed against the ACTUAL
live response shape instead of guessed at.

Never places an order. Never submits anything. Imports nothing from
gateway.py/exit_manager.py/reconciliation.py -- it has no way to place
an order even by mistake.

Background: a real run hit
    NotFoundError: market with slug "cpc-btc-updown-15m-2026-10-09-0645z" not found
immediately after discovery printed that exact slug as the TRADEABLE
MARKET SLUG, for a market with ~806s left in its 15-minute window
(i.e. ~94s after the window opened). This script isolates and prints,
side by side:

  1. the EVENT slug (production find_active_btc_market()'s own
     _expected_event_slug(), or your manual-override slug)
  2. the ACTUAL nested market slug, read directly from a RAW
     events.retrieve_by_slug() response (event["markets"][0]["slug"]),
     bypassing _to_binary_market() so there is no intermediate parsing
     between the raw API response and what gets printed
  3. the EXACT slug that would be passed to the book call -- the
     production BinaryMarket.token_id_yes, from the real
     find_active_btc_market() call -- compared byte-for-byte against
     #2, so a mapping bug (if there were one) would show up directly
     as a MISMATCH line
  4. the EXACT SDK method about to be used (named explicitly, plus
     its real HTTP route, read directly from the installed SDK's own
     resources/markets.py: `markets.book(slug)` -> GET
     /v1/markets/{slug}/book)
  5. the raw SDK/API error (type, message, and status_code/request_id
     when the SDK's exception carries them), from calling that exact
     method with that exact slug

Also cross-checks markets.retrieve_by_slug() (GET /v1/market/slug/
{slug} -- note: singular "market", unlike book()'s plural "markets" in
its own route) against the SAME nested slug: if that succeeds while
book() 404s, the nested market's metadata exists but its order book
specifically does not (yet) -- pointing at a backend propagation delay
for a brand-new market rather than a wrong identifier. If BOTH 404,
the slug itself is not recognized by the API at all.

Also prints the installed polymarket-us SDK version, since
us_client.py's own module docstring says its request shapes were
verified against polymarket-us==2.3.0 specifically -- a newer
installed version changing an endpoint would reproduce exactly this
symptom.

Usage:
    python3 scripts/diagnose_market_book_lookup.py
    python3 scripts/diagnose_market_book_lookup.py --market-slug <EVENT_SLUG>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket.client import NoActiveMarketError, PolymarketClientError  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.us_client import PolymarketUSClient  # noqa: E402


def _exception_detail(exc: Exception) -> str:
    """Same convention as verify_polymarket_setup.py's own helper --
    duplicated here (not imported) so this stays a fully standalone,
    single-purpose diagnostic."""
    detail = f"{type(exc).__name__}: {exc}"
    extras = []
    for attr in ("status_code", "message", "request_id"):
        val = getattr(exc, attr, None)
        if val is not None:
            extras.append(f"{attr}={val!r}")
    if extras:
        detail += " (" + ", ".join(extras) + ")"
    return detail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--market-slug", default=None, metavar="EVENT_SLUG",
        help="Diagnose one specific event slug instead of the current automatic BTC 15m window "
             "(equivalent to POLYMARKET_US_MARKET_SLUG for this run only).",
    )
    args = parser.parse_args()

    settings = PolymarketSettings.from_env()
    if not settings.is_us_venue:
        print("REFUSING: this diagnostic is Polymarket US only -- set POLYMARKET_VENUE=us.")
        return 1

    try:
        import polymarket_us
        installed_version = getattr(polymarket_us, "__version__", "unknown")
    except ImportError as exc:
        print(f"REFUSING: polymarket-us is not installed: {exc}")
        return 1
    print(f"installed polymarket-us version: {installed_version}")
    print("us_client.py's request shapes were verified live against polymarket-us==2.3.0 -- "
          "a different installed version is worth noting, though not by itself proof of anything.\n")

    client = PolymarketUSClient(settings)
    sdk_client = client._client()  # the real polymarket_us.PolymarketUS -- diagnostic use only, read-only calls below

    event_slug = args.market_slug or settings.us_market_slug
    now = datetime.now(timezone.utc)
    if not event_slug:
        window_start, _window_end = client._current_window(now)
        event_slug = client._expected_event_slug(window_start)
        print(f"No --market-slug given -- using the current automatic BTC 15m window: {event_slug!r}")
    print(f"\n1. EVENT SLUG: {event_slug!r}")

    # --- Raw event fetch -- bypasses _to_binary_market() entirely, so what's --
    # printed below is read directly off the live response, with nothing in between.
    try:
        raw_event_response = sdk_client.events.retrieve_by_slug(event_slug)
    except Exception as exc:  # noqa: BLE001 - this diagnostic's whole job is to surface exactly this
        print(f"\n   events.retrieve_by_slug({event_slug!r}) FAILED: {_exception_detail(exc)}")
        return 1
    raw_event = raw_event_response.get("event") or {}
    raw_markets = raw_event.get("markets") or []
    print(f"   events.retrieve_by_slug({event_slug!r}) OK -- active={raw_event.get('active')} "
          f"closed={raw_event.get('closed')} -- {len(raw_markets)} nested market(s)")
    if not raw_markets:
        print("   REFUSING: the raw event response has no nested markets at all -- nothing to look up.")
        return 1

    raw_nested_slug = raw_markets[0].get("slug")
    print(f"\n2. ACTUAL NESTED MARKET SLUG (raw event['markets'][0]['slug']): {raw_nested_slug!r}")
    print(f"   raw nested market object: {json.dumps(raw_markets[0], indent=2, default=str)}")

    # --- The real production discovery call, for comparison -------------------
    try:
        if args.market_slug:
            import os
            os.environ["POLYMARKET_US_MARKET_SLUG"] = args.market_slug
            production_settings = PolymarketSettings.from_env()
            production_client = PolymarketUSClient(production_settings)
            market = production_client.find_active_btc_market(now=now)
        else:
            market = client.find_active_btc_market(now=now)
    except (NoActiveMarketError, PolymarketClientError) as exc:
        print(f"\n   find_active_btc_market() FAILED: {exc}")
        return 1
    print(f"\n   production find_active_btc_market() -> BinaryMarket.token_id_yes = {market.token_id_yes!r}")
    if market.token_id_yes == raw_nested_slug:
        print("   MATCH: production token_id_yes is byte-for-byte identical to the raw nested market slug.")
    else:
        print("   *** MISMATCH: production token_id_yes DIFFERS from the raw nested market slug above -- "
              "this alone would explain a NotFoundError and is a real code bug if it ever prints. ***")

    token_id = market.token_id_yes
    print(f"\n3. EXACT SLUG PASSED TO THE BOOK CALL: {token_id!r}")
    print("\n4. EXACT SDK METHOD: sdk_client.markets.book(slug) -> GET /v1/markets/{slug}/book "
          "(read directly from the installed SDK's resources/markets.py)")

    print(f"\n5. Calling markets.book({token_id!r}) now...")
    try:
        raw_book = sdk_client.markets.book(token_id)
        print(f"   markets.book({token_id!r}) SUCCEEDED:")
        print(f"   {json.dumps(raw_book, indent=2, default=str)}")
        book_failed = False
    except Exception as exc:  # noqa: BLE001 - this diagnostic's whole job is to surface exactly this
        print(f"   markets.book({token_id!r}) FAILED: {_exception_detail(exc)}")
        book_failed = True

    # --- Cross-check: does the SAME slug resolve via a DIFFERENT endpoint? ----
    print(f"\n--- Cross-check: markets.retrieve_by_slug({token_id!r}) -> GET /v1/market/slug/{{slug}} "
          "(singular 'market', a different route than book()'s) ---")
    try:
        raw_market = sdk_client.markets.retrieve_by_slug(token_id)
        print(f"   markets.retrieve_by_slug({token_id!r}) SUCCEEDED:")
        print(f"   {json.dumps(raw_market, indent=2, default=str)}")
        if book_failed:
            print("\n   *** The nested market's metadata EXISTS (retrieve_by_slug succeeded) but its order "
                  "book does NOT (book() failed) -- this points at a backend propagation delay between "
                  "market creation and order-book availability for a brand-new market, not a wrong "
                  "identifier. Try this diagnostic again in a few seconds against the SAME event slug. ***")
    except Exception as exc:  # noqa: BLE001
        print(f"   markets.retrieve_by_slug({token_id!r}) FAILED: {_exception_detail(exc)}")
        if book_failed:
            print("\n   *** BOTH endpoints 404 for this exact slug -- the slug itself is not recognized "
                  "by the API at all right now. ***")

    print("\nNothing above includes POLYMARKET_US_KEY_ID/SECRET_KEY, any auth header, balance, or "
          "account data -- every call made here is an unauthenticated, public-gateway read. No order "
          "was placed or attempted.")
    return 1 if book_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
