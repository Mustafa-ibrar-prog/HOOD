#!/usr/bin/env python3
"""Read-only investigation of ONE exact, already-submitted order — for
exactly the situation where orders.retrieve() comes back NotFoundError
and the post-submit status is "unknown". Never places, cancels, or
modifies anything; never submits a second order.

Queries FOUR separate, authoritative, read-only endpoints (verified by
inspecting the installed polymarket-us==2.3.0 package's own resources/
orders.py, resources/portfolio.py, and types/orders.py, types/portfolio.py
directly — not guessed):
  1. orders.retrieve(order_id)  -- GET /v1/order/{order_id} (one exact order)
  2. orders.list()              -- GET /v1/orders/open (currently open orders)
  3. portfolio.activities()     -- GET /v1/portfolio/activities (trade/
     resolution/balance history — the authoritative record of whether a
     TRADE actually happened for this order's market)
  4. portfolio.positions()      -- GET /v1/portfolio/positions (current
     positions, keyed by market slug)

A 404 from orders.retrieve() alone is NEVER treated as FILLED, CANCELED,
REJECTED, or EXPIRED — it only means that ONE lookup failed. This script
deliberately gathers evidence from all four sources and prints it side
by side; it draws no conclusion for you, since "the order isn't in
orders.retrieve() or orders.list(), and there's no matching trade in
activities() or a position for this market" is suggestive but still not
a positive confirmation from this venue's documented API surface.

Usage:
    python3 scripts/check_order_status.py <ORDER_ID> --market-slug <SLUG>

--market-slug is STRONGLY recommended (it is the NESTED tradeable
market slug printed as "EXCHANGE ORDER ID"/"NESTED MARKET" by
manual_polymarket_us_test.py at submission time, e.g.
cpc-btc-updown-15m-...) — activities()/positions() are organized by
market, not by order id, so without it this can only show your
account's most recent activity/positions overall, which may not
include this specific market if much has happened since.

Nothing printed includes POLYMARKET_US_KEY_ID/SECRET_KEY or any auth
header — every response body here is the account's own order/trade/
position data, not a credential.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.us_client import PolymarketUSClient  # noqa: E402


def _dump(label: str, fn) -> None:
    print(f"{label}:")
    try:
        response = fn()
        print(json.dumps(response, indent=2, default=str))
    except Exception as exc:  # noqa: BLE001 - surfacing exactly this is the point of the tool
        print(f"  FAILED: {type(exc).__name__}: {exc}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("order_id", metavar="ORDER_ID")
    parser.add_argument(
        "--market-slug", default=None, metavar="SLUG",
        help="The nested tradeable market slug this order was placed against (recommended -- "
             "filters activities()/positions() to this exact market).",
    )
    args = parser.parse_args()

    settings = PolymarketSettings.from_env()
    if not settings.is_us_venue:
        print("REFUSING: this script is Polymarket US only — set POLYMARKET_VENUE=us.")
        return 1

    client = PolymarketUSClient(settings)
    sdk_client = client._client()  # same private accessor verify_polymarket_setup.py's debug tools already use

    print(f"Investigating order {args.order_id!r}" + (f" on market {args.market_slug!r}" if args.market_slug else "") + " ...\n")

    # --- 1. orders.retrieve(order_id) -- the one exact order ------------------
    _dump("1. RAW ORDER RESPONSE (orders.retrieve)", lambda: sdk_client.orders.retrieve(args.order_id))

    print("   PARSED (via client.get_fill_status — the SAME authoritative call reconciliation.py uses):")
    fill = client.get_fill_status(args.order_id)
    print(f"     STATUS: {fill.status}")
    print(f"     FILLED SHARES: {fill.filled_shares}")
    print(f"     AVG FILL PRICE: {fill.avg_fill_price}")
    print(f"     IS_FILL: {fill.is_fill}")
    print(f"     RAW DETAIL: {fill.raw}")
    print()

    # --- 2. orders.list() -- currently open orders -----------------------------
    list_params = {"slugs": [args.market_slug]} if args.market_slug else None
    _dump("2. OPEN ORDERS (orders.list)", lambda: sdk_client.orders.list(list_params))

    # --- 3. portfolio.activities() -- trade/resolution/balance history --------
    activities_params = {"marketSlug": args.market_slug} if args.market_slug else None
    _dump("3. ACCOUNT ACTIVITY (portfolio.activities)", lambda: sdk_client.portfolio.activities(activities_params))

    # --- 4. portfolio.positions() -- current positions, keyed by market -------
    positions_params = {"market": args.market_slug} if args.market_slug else None
    _dump("4. CURRENT POSITIONS (portfolio.positions)", lambda: sdk_client.portfolio.positions(positions_params))

    if fill.status == "unknown":
        print("STATUS REMAINS UNKNOWN. This script draws NO conclusion from a 404 alone -- review")
        print("sections 2-4 above yourself:")
        print("  - Does this order id appear in OPEN ORDERS (section 2)? If so, it's still live/resting.")
        print("  - Does ACCOUNT ACTIVITY (section 3) show a trade for this market around the time you")
        print("    submitted? If so, it filled (check the trade's own price/qty there).")
        print("  - Does CURRENT POSITIONS (section 4) show a nonzero position for this market? If so,")
        print("    a fill happened regardless of what orders.retrieve() says.")
        print("  - If NONE of the above show any trace of this order, that is still not a positive")
        print("    confirmation of CANCELED/REJECTED/EXPIRED from this venue's documented API --")
        print("    it only means this script found no evidence it ever filled. No position has been")
        print("    opened in this codebase's own ledger either way.")
        if not args.market_slug:
            print("\nRe-run with --market-slug <the nested tradeable market slug> to filter sections 3-4")
            print("to exactly this market instead of your account's general recent activity.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
