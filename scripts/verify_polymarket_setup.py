#!/usr/bin/env python3
"""Read-only sanity check — run this FIRST, somewhere with real network
access to the configured venue, before trusting anything in
src/polymarket/ with real funds. Never places an order; only reads.

POLYMARKET_VENUE selects which venue this checks (see settings.py's
module docstring): "international" (polymarket.com, via client.py) or
"us" (Polymarket US, via us_client.py) — get_polymarket_client()
returns whichever client matches, and every check below is written
against that same common interface, so this script runs identically
against either venue.

Every check below prints an explicit PASS / FAIL / SKIPPED line and
this script's exit code is 1 if anything required FAILed. A SKIPPED
check (e.g. no credentials configured) is not a failure — it just
means that part was never exercised.

Usage:
    python3 scripts/verify_polymarket_setup.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket.client import NoActiveMarketError, PolymarketClientError  # noqa: E402
from src.polymarket.client import get_polymarket_client  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402

_results: list[tuple[str, str]] = []  # (label, "PASS"/"FAIL"/"SKIPPED")


def _report(label: str, status: str, detail: str = "") -> None:
    _results.append((label, status))
    line = f"[{status}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)


def main() -> int:
    settings = PolymarketSettings.from_env()
    client = get_polymarket_client(settings)
    print(f"POLYMARKET_VENUE={settings.venue} ({type(client).__name__})")
    print()

    # --- 1. SDK importable --------------------------------------------------
    try:
        if settings.is_us_venue:
            import polymarket_us  # noqa: F401
            sdk_label = "polymarket-us"
        else:
            import polymarket  # noqa: F401
            sdk_label = "polymarket-client"
        _report("SDK importable", "PASS", sdk_label)
    except ImportError as exc:
        _report("SDK importable", "FAIL", f"{exc} — run: pip install -e \".[polymarket]\"")
        return _finish()

    # --- 2. API connectivity + market discovery ------------------------------
    market = None
    try:
        market = client.find_active_btc_market()
        _report(
            "API connectivity", "PASS",
            f"reached the venue's public market-discovery endpoint",
        )
        _report(
            "BTC market discovery", "PASS",
            f"{market.question!r} (condition_id={market.condition_id}, closes in {market.seconds_to_close:.0f}s)",
        )
    except NoActiveMarketError as exc:
        _report("API connectivity", "PASS", "reached the venue; no exception — the venue responded")
        _report(
            "BTC market discovery", "FAIL",
            f"{exc} — either no matching market is live right now, or (for POLYMARKET_VENUE=us "
            "especially) this product may not exist on this venue; verify the catalog by hand "
            "with search.query()/events.list() before assuming the discovery filter is wrong.",
        )
    except PolymarketClientError as exc:
        _report("API connectivity", "FAIL", str(exc))
        _report("BTC market discovery", "SKIPPED", "API connectivity failed")
    except Exception as exc:  # noqa: BLE001 - this script's whole job is to surface exactly this kind of failure
        _report("API connectivity", "FAIL", f"{type(exc).__name__}: {exc}")
        _report("BTC market discovery", "SKIPPED", "API connectivity failed")

    # --- 3. Order book + executable liquidity, for EACH outcome's own book ---
    if market is not None:
        for outcome, token_id in (("YES", market.token_id_yes), ("NO", market.token_id_no)):
            try:
                book = client.get_order_book(token_id)
            except Exception as exc:  # noqa: BLE001
                _report(f"Order book ({outcome})", "FAIL", f"{type(exc).__name__}: {exc}")
                _report(f"Executable liquidity ({outcome})", "SKIPPED", "order book fetch failed")
                continue
            if book.best_bid is None and book.best_ask is None:
                _report(f"Order book ({outcome})", "FAIL", "book is completely empty (no bids or asks)")
                _report(f"Executable liquidity ({outcome})", "SKIPPED", "empty book")
                continue
            _report(f"Order book ({outcome})", "PASS", f"best_bid={book.best_bid} best_ask={book.best_ask}")
            if book.best_ask is None:
                _report(f"Executable liquidity ({outcome})", "FAIL", "no ask-side liquidity at all")
            else:
                max_price = round(min(book.best_ask * (1 + settings.max_price_slippage_pct), 0.99), 4)
                liquidity = book.executable_liquidity_usd(side="BUY", max_price=max_price)
                meets = liquidity >= settings.min_order_book_liquidity_usd
                _report(
                    f"Executable liquidity ({outcome})", "PASS" if meets else "FAIL",
                    f"${liquidity:.2f} at/below ${max_price:.4f} "
                    f"({'meets' if meets else 'BELOW'} the configured ${settings.min_order_book_liquidity_usd:.2f} minimum)",
                )
    else:
        _report("Order book", "SKIPPED", "no market discovered")
        _report("Executable liquidity", "SKIPPED", "no market discovered")

    # --- 4. Current market status / resolution metadata shape ---------------
    if market is not None:
        try:
            resolution = client.get_resolution(market.condition_id)
            _report(
                "Resolution metadata", "PASS",
                f"get_resolution() returned {resolution!r} for a still-open market (None expected) — "
                "the call itself succeeded and returned a validly-shaped response",
            )
        except Exception as exc:  # noqa: BLE001
            _report("Resolution metadata", "FAIL", f"{type(exc).__name__}: {exc}")
    else:
        _report("Resolution metadata", "SKIPPED", "no market discovered")

    # --- 5. Credential check (balance lookup, no order placed) ---------------
    if settings.is_us_venue:
        has_creds = bool(settings.us_key_id and settings.us_secret_key)
    else:
        has_creds = bool(settings.private_key or (settings.api_key and settings.api_secret and settings.api_passphrase))

    if not has_creds:
        _report("Authentication", "SKIPPED", "no credentials configured (fine for paper-mode-only use)")
        _report("Balance / account access", "SKIPPED", "no credentials configured")
    else:
        try:
            balance = client.get_balance_usdc()
            _report("Authentication", "PASS", "credentials accepted by the venue")
            _report("Balance / account access", "PASS", f"${balance:.2f}")
        except Exception as exc:  # noqa: BLE001 - this script's whole job is to surface exactly this kind of failure
            _report("Authentication", "FAIL", f"{type(exc).__name__}: {exc}")
            _report("Balance / account access", "SKIPPED", "authentication failed")

    return _finish()


def _finish() -> int:
    print()
    print("=== SUMMARY ===")
    for label, status in _results:
        print(f"  [{status}] {label}")
    failed = [r for r in _results if r[1] == "FAIL"]
    if failed:
        print(f"\n{len(failed)} check(s) FAILED. Do not trust this integration with real funds yet.")
        return 1
    print("\nNo FAILs. This does not guarantee the strategy is profitable, and SKIPPED checks were "
          "never exercised — it only confirms what actually ran worked against the real API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
