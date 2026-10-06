#!/usr/bin/env python3
"""Read-only sanity check — run this FIRST, somewhere with real network
access to polymarket.com, before trusting anything in src/polymarket/
with real funds. Never places an order; only reads.

Checks, in order, stopping at the first failure:
  1. polymarket-client (import name `polymarket`) is installed.
  2. find_active_btc_market() actually finds a real, currently-open
     market near the configured duration — this is the single
     least-verified assumption in client.py (written without ever
     seeing a live response from this sandboxed environment — see
     client.py's module docstring).
  3. The market's own YES order book has a real, two-sided quote.
  4. The SPECIFIC outcome token this system would actually buy right
     now (whichever side momentum currently favors) has real,
     executable liquidity on its own book — the same
     OrderBookSnapshot.executable_liquidity_usd() check risk.py's
     check_order_book_liquidity() runs before every real trade (Task
     6). This is read-only: it reports the number, it never trades on it.
  5. If credentials are configured: the SDK can authenticate and fetch
     a balance (does NOT place an order).

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

    print("[1/5] polymarket-client importable ...")
    try:
        import polymarket  # noqa: F401
    except ImportError as exc:
        print(f"      FAILED: {exc}\n      Run: pip install polymarket-client")
        return 1
    print("      OK")

    print(f"[2/5] Finding an open {settings.asset!r} market near {settings.market_duration_minutes} minutes ...")
    try:
        market = client.find_active_btc_market()
    except NoActiveMarketError as exc:
        print(f"      Reached the API, but found no matching market: {exc}")
        print("      This means either no matching market is currently live, or the "
              "list_markets() filtering in client.py's find_active_btc_market() needs "
              "adjusting to match the real response shape. Inspect a raw list_markets() "
              "call by hand next.")
        return 1
    except PolymarketClientError as exc:
        print(f"      FAILED: {exc}")
        return 1
    print(f"      OK — found: {market.question!r} (condition_id={market.condition_id}, closes in {market.seconds_to_close:.0f}s)")

    print("[3/5] YES order book has a real, two-sided quote ...")
    if market.yes_bid is None or market.yes_ask is None:
        print(f"      FAILED: yes_bid={market.yes_bid} yes_ask={market.yes_ask} — book may be empty or get_order_book() needs adjusting")
        return 1
    print(f"      OK — yes_bid={market.yes_bid} yes_ask={market.yes_ask} yes_mid={market.yes_mid} spread={market.yes_spread_pct}")

    print("[4/5] Executable liquidity on each outcome's OWN book (read-only; this does not trade) ...")
    for outcome, token_id in (("YES", market.token_id_yes), ("NO", market.token_id_no)):
        book = client.get_order_book(token_id)
        if book.best_ask is None:
            print(f"      {outcome}: no ask-side liquidity at all (best_bid={book.best_bid})")
            continue
        max_price = round(book.best_ask * (1 + settings.max_price_slippage_pct), 4)
        liquidity = book.executable_liquidity_usd(side="BUY", max_price=max_price)
        meets = liquidity >= settings.min_order_book_liquidity_usd
        print(
            f"      {outcome}: best_ask={book.best_ask} executable_liquidity=${liquidity:.2f} at/below ${max_price:.4f} "
            f"({'meets' if meets else 'BELOW'} the configured ${settings.min_order_book_liquidity_usd:.2f} minimum)"
        )

    print("[5/5] Credential check (balance lookup, no order placed) ...")
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
          "it only confirms the plumbing (market discovery, order book, liquidity, "
          "credentials) works against the real API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
