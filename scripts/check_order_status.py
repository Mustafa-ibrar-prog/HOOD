#!/usr/bin/env python3
"""Read-only lookup of ONE exact order's authoritative status, by its
exchange order id — for exactly the situation where an order was
submitted and the post-submit status came back "unknown." Never places
an order, never cancels one, never touches pending_orders.json or
open_positions.json — it only calls the same authoritative
orders.retrieve()/get_fill_status() code path reconciliation.py uses,
and prints BOTH the raw exchange response and the parsed result, so
the real state is visible directly instead of guessed at.

The order id is whatever was printed as "ORDER ID:" by
scripts/manual_polymarket_us_test.py (or the pending order's own
exchange_order_id, once confirmed) — not a pending-order id.

Usage:
    python3 scripts/check_order_status.py <ORDER_ID>

Nothing printed includes POLYMARKET_US_KEY_ID/SECRET_KEY or any auth
header — orders.retrieve()'s response body is the order's own public
fields (price, quantity, state, timestamps), not account credentials.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.us_client import PolymarketUSClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("order_id", metavar="ORDER_ID")
    args = parser.parse_args()

    settings = PolymarketSettings.from_env()
    if not settings.is_us_venue:
        print("REFUSING: this script is Polymarket US only — set POLYMARKET_VENUE=us.")
        return 1

    client = PolymarketUSClient(settings)
    sdk_client = client._client()  # same private accessor verify_polymarket_setup.py's debug tools already use

    print(f"Looking up order {args.order_id!r} ...\n")

    print("RAW ORDER RESPONSE (orders.retrieve):")
    try:
        raw = sdk_client.orders.retrieve(args.order_id)
        print(json.dumps(raw, indent=2, default=str))
    except Exception as exc:  # noqa: BLE001 - surfacing exactly this is the point of the tool
        print(f"  FAILED: {type(exc).__name__}: {exc}")

    print("\nPARSED (via client.get_fill_status — the SAME authoritative call reconciliation.py uses):")
    fill = client.get_fill_status(args.order_id)
    print(f"  STATUS: {fill.status}")
    print(f"  REQUESTED SHARES: {fill.requested_shares}")
    print(f"  FILLED SHARES: {fill.filled_shares}")
    print(f"  AVG FILL PRICE: {fill.avg_fill_price}")
    print(f"  IS_FILL: {fill.is_fill}")
    print(f"  RAW DETAIL: {fill.raw}")

    if fill.status == "unknown":
        print("\nSTATUS IS UNKNOWN. Per fill.raw above, this is either:")
        print('  - a lookup/communication failure ("lookup_error" key) -- re-run this script; if it')
        print("    keeps failing, check credentials/connectivity, not the order itself.")
        print('  - an exchange-reported state this system does not yet recognize ("state" key) --')
        print("    note the exact state string above; it needs a new case in")
        print("    us_client.py's _TERMINAL_NON_FILL_STATE/_RESTING_STATES (never guessed at).")
        print("This script has NOT modified any pending-order or position record. If this order's")
        print("pending record was already marked fill_reconciled=True by an earlier run (before this")
        print("fix), re-running the normal bot's reconcile_pending_orders() sweep will NOT retry it on")
        print("its own -- that requires a deliberate, separate decision, not an automatic one.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
