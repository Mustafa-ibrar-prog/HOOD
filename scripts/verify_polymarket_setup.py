#!/usr/bin/env python3
"""Read-only sanity check — run this FIRST, somewhere with real network
access to polymarket.com, before trusting anything in src/polymarket/
with real funds. Never places an order; only reads.

Checks, in order, stopping at the first failure:
  1. Can reach the Gamma API at all.
  2. find_active_btc_market() actually finds a real, currently-open
     market near the configured duration — this is the single
     least-verified assumption in client.py (the tag/slug query was
     written without ever seeing a live response).
  3. The market's order book has a real, two-sided quote.
  4. If credentials are configured: py-clob-client can authenticate and
     fetch a balance (does NOT place an order).

Usage:
    python3 scripts/verify_polymarket_setup.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket.client import NoActiveMarketError, PolymarketClient, PolymarketClientError  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402


def main() -> int:
    settings = PolymarketSettings.from_env()
    client = PolymarketClient(settings)

    print(f"[1/4] Gamma API reachable at {settings.gamma_api_url} ...")
    try:
        market = client.find_active_btc_market()
    except NoActiveMarketError as exc:
        print(f"      Reached the API, but found no matching market: {exc}")
        print("      This means either no bitcoin market near "
              f"{settings.market_duration_minutes} minutes is currently live, or the "
              "Gamma API query in client.py's find_active_btc_market() needs adjusting "
              "to match the real response shape. Inspect the raw /events response by hand next.")
        return 1
    except PolymarketClientError as exc:
        print(f"      FAILED: {exc}")
        return 1
    print(f"      OK — found: {market.question!r} (condition_id={market.condition_id}, closes in {market.seconds_to_close:.0f}s)")

    print("[2/4] Order book has a real, two-sided quote ...")
    if market.yes_bid is None or market.yes_ask is None:
        print(f"      FAILED: yes_bid={market.yes_bid} yes_ask={market.yes_ask} — book may be empty or get_order_book() needs adjusting")
        return 1
    print(f"      OK — yes_bid={market.yes_bid} yes_ask={market.yes_ask} yes_mid={market.yes_mid} spread={market.yes_spread_pct}")

    print("[3/4] Re-fetching the same market (refresh path) ...")
    refreshed = client.refresh(market)
    print(f"      OK — fetched_at updated, data_age_seconds={refreshed.data_age_seconds:.1f}")

    print("[4/4] Credential check (balance lookup, no order placed) ...")
    if not (settings.private_key or (settings.api_key and settings.api_secret and settings.api_passphrase)):
        print("      SKIPPED — no credentials configured (fine if you only plan to run in paper mode for now).")
    else:
        try:
            balance = client.get_balance_usdc()
            print(f"      OK — authenticated, USDC balance: ${balance:.2f}")
        except Exception as exc:  # noqa: BLE001 - this script's whole job is to surface exactly this kind of failure
            print(f"      FAILED: {exc}")
            return 1

    print("\nAll checks passed. This does not guarantee the strategy is profitable — "
          "it only confirms the plumbing (market discovery, order book, credentials) works "
          "against the real API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
