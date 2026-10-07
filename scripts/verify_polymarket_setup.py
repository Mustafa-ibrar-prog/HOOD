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
    python3 scripts/verify_polymarket_setup.py --debug-discovery
    python3 scripts/verify_polymarket_setup.py --debug-exact-slug

--debug-discovery (POLYMARKET_VENUE=us only) additionally dumps raw,
PUBLIC market/event/series metadata from the live search.query(),
events.list(), and series.list() gateway endpoints — before running
the normal checks — so a discovery failure can be debugged against the
actual live response shape instead of guessed at. These are all
unauthenticated public-gateway calls; nothing printed ever includes
POLYMARKET_US_KEY_ID/SECRET_KEY, any header, or any account-specific
data — only public market/event/series fields.

--debug-exact-slug (POLYMARKET_VENUE=us only) diagnoses the EXACT
deterministic-slug API request find_active_btc_market() makes (see
us_client.py), using that same production code's own
_current_window()/_expected_event_slug() so the slug tested is
guaranteed identical to what a real cycle would compute — never a
second, possibly-different implementation. For the previous, current,
and next 15-minute window, it tries the computed slug against BOTH
events.retrieve_by_slug() AND markets.retrieve_by_slug(), printing the
full raw response or the exact exception (type, message, and
status_code/request_id if the SDK's error carries them) for each —
so a wrong-resource guess (event vs. market) or an off-by-one window
is visible directly, instead of guessed at. Also public-gateway calls;
same no-credentials-printed guarantee as --debug-discovery.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket.client import NoActiveMarketError, PolymarketClientError  # noqa: E402
from src.polymarket.client import get_polymarket_client  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.us_client import PolymarketUSClient  # noqa: E402

_results: list[tuple[str, str]] = []  # (label, "PASS"/"FAIL"/"SKIPPED")


def _report(label: str, status: str, detail: str = "") -> None:
    _results.append((label, status))
    line = f"[{status}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)


def _event_summary(event: dict) -> dict:
    """Extracts exactly the PUBLIC fields useful for debugging discovery
    — nothing account-specific ever reaches this (events/series/search
    are unauthenticated gateway endpoints; there is no credential or
    account data in their responses to begin with)."""
    start = event.get("startTime")
    end = event.get("endTime")
    duration_seconds = None
    try:
        if start and end:
            s = datetime.fromisoformat(start)
            e = datetime.fromisoformat(end)
            if s.tzinfo is None:
                s = s.replace(tzinfo=timezone.utc)
            if e.tzinfo is None:
                e = e.replace(tzinfo=timezone.utc)
            duration_seconds = (e - s).total_seconds()
    except ValueError:
        pass
    series = event.get("series") or {}
    markets = event.get("markets") or []
    return {
        "event_slug": event.get("slug"),
        "event_title": event.get("title"),
        "event_startTime": start,
        "event_endTime": end,
        "event_duration_seconds": duration_seconds,
        "event_active": event.get("active"),
        "event_closed": event.get("closed"),
        "series_slug": series.get("slug"),
        "series_title": series.get("title"),
        "series_recurrence": series.get("recurrence"),
        "markets": [
            {"slug": m.get("slug"), "title": m.get("title"), "outcome": m.get("outcome"),
             "active": m.get("active"), "closed": m.get("closed")}
            for m in markets
        ],
    }


def _debug_discovery(settings: PolymarketSettings) -> None:
    print("=== DEBUG: raw discovery dump (public gateway data only — no credentials, no account data) ===")
    if not settings.is_us_venue:
        print("  (--debug-discovery currently only covers POLYMARKET_VENUE=us)")
        print()
        return

    us_client = PolymarketUSClient(settings)
    sdk_client = us_client._client()  # the real polymarket_us.PolymarketUS -- diagnostic use only

    for term in ("bitcoin", "btc", "up or down", "up down", "15m", "15 min"):
        print(f"\n--- search.query({{'query': {term!r}, 'status': 'active'}}) ---")
        try:
            response = sdk_client.search.query({"query": term, "status": "active"})
            events = response.get("events") or []
            print(f"  {len(events)} event(s) returned")
            for event in events:
                print(json.dumps(_event_summary(event), indent=2, default=str))
        except Exception as exc:  # noqa: BLE001 - this is a diagnostic dump; one failing call must not abort the rest
            print(f"  ERROR: {type(exc).__name__}: {exc}")

    print("\n--- events.list({'active': True, 'closed': False, 'limit': 100}) ---")
    try:
        response = sdk_client.events.list({"active": True, "closed": False, "limit": 100})
        events = response.get("events") or []
        print(f"  {len(events)} event(s) returned")
        btc_like = [
            e for e in events
            if "btc" in (e.get("title") or "").lower() or "bitcoin" in (e.get("title") or "").lower()
            or "btc" in (e.get("slug") or "").lower() or "bitcoin" in (e.get("slug") or "").lower()
        ]
        print(f"  {len(btc_like)} of those look BTC/Bitcoin-related by title or slug:")
        for event in btc_like:
            print(json.dumps(_event_summary(event), indent=2, default=str))
        if not btc_like:
            print("  (none matched by loose title/slug text -- all event titles/slugs below, for a manual look)")
            for event in events:
                print(f"    slug={event.get('slug')!r} title={event.get('title')!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ERROR: {type(exc).__name__}: {exc}")

    print("\n--- series.list({'active': True, 'limit': 100}) ---")
    try:
        response = sdk_client.series.list({"active": True, "limit": 100})
        series_list = response.get("series") or []
        print(f"  {len(series_list)} series returned")
        for series in series_list:
            print(json.dumps({
                "id": series.get("id"), "slug": series.get("slug"), "title": series.get("title"),
                "recurrence": series.get("recurrence"), "active": series.get("active"),
                "closed": series.get("closed"),
            }, indent=2, default=str))
    except Exception as exc:  # noqa: BLE001
        print(f"  ERROR: {type(exc).__name__}: {exc}")

    print("\n=== END DEBUG DUMP ===\n")


def _exception_detail(exc: Exception) -> str:
    detail = f"{type(exc).__name__}: {exc}"
    extras = []
    for attr in ("status_code", "message", "request_id"):
        val = getattr(exc, attr, None)
        if val is not None:
            extras.append(f"{attr}={val!r}")
    if extras:
        detail += " (" + ", ".join(extras) + ")"
    return detail


def _debug_exact_slug(settings: PolymarketSettings) -> None:
    print("=== DEBUG: exact-slug request diagnostic (public gateway data only — no credentials, no account data) ===")
    if not settings.is_us_venue:
        print("  (--debug-exact-slug currently only covers POLYMARKET_VENUE=us)")
        print()
        return

    us_client = PolymarketUSClient(settings)
    sdk_client = us_client._client()  # the real polymarket_us.PolymarketUS -- diagnostic use only

    now = datetime.now(timezone.utc)
    window_start, window_end = us_client._current_window(now)
    print(f"  now (UTC):       {now.isoformat()}")
    print(f"  current window:  {window_start.isoformat()} -> {window_end.isoformat()}")

    minutes = settings.market_duration_minutes
    windows = [
        ("previous window", window_start - timedelta(minutes=minutes)),
        ("current window", window_start),
        ("next window", window_start + timedelta(minutes=minutes)),
    ]

    for label, start in windows:
        try:
            slug = us_client._expected_event_slug(start)
        except Exception as exc:  # noqa: BLE001
            print(f"\n--- {label} ---\n  ERROR building slug: {_exception_detail(exc)}")
            continue

        print(f"\n--- {label}: {slug!r} ---")
        for resource_name, method in (
            ("events.retrieve_by_slug", sdk_client.events.retrieve_by_slug),
            ("markets.retrieve_by_slug", sdk_client.markets.retrieve_by_slug),
        ):
            try:
                response = method(slug)
                print(f"  {resource_name}({slug!r}) SUCCEEDED:")
                print(json.dumps(response, indent=2, default=str))
            except Exception as exc:  # noqa: BLE001 - this is a diagnostic dump; one failing call must not abort the rest
                print(f"  {resource_name}({slug!r}) FAILED: {_exception_detail(exc)}")

    print("\n=== END DEBUG DUMP ===\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--debug-discovery", action="store_true",
        help="Dump raw, public search/events/series metadata from the live API before running the normal checks.",
    )
    parser.add_argument(
        "--debug-exact-slug", action="store_true",
        help="Diagnose the exact events.retrieve_by_slug()/markets.retrieve_by_slug() request find_active_btc_market() makes.",
    )
    args = parser.parse_args()

    settings = PolymarketSettings.from_env()
    client = get_polymarket_client(settings)
    print(f"POLYMARKET_VENUE={settings.venue} ({type(client).__name__})")
    print()

    if args.debug_discovery:
        _debug_discovery(settings)
    if args.debug_exact_slug:
        _debug_exact_slug(settings)

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
