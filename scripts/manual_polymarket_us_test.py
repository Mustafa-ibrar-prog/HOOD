#!/usr/bin/env python3
"""ONE-TIME MANUAL LIVE TEST for Polymarket US — an explicit, exact-market
integration test of the complete trading pipeline (discovery → order
book → risk → preview → submission → authoritative fill → reconciliation
→ position ledger), NOT an autonomous "trade anything you find" mode.

--market-slug is OPTIONAL. Give it a slug you picked yourself from the
Polymarket US app (the SAME mechanism as
scripts/verify_polymarket_setup.py --market-slug — see
settings.py's/us_client.py's module docstrings on
POLYMARKET_US_MARKET_SLUG: no search, no "closest available," the
exact slug only) to test one specific market. OMIT it to use the
normal, automatic BTC 15m discovery (find_active_btc_market() with no
override) — this is the mode for a real production live test, since
the current BTC 15m market changes every 15 minutes and nothing here
should require pasting a fresh slug each cycle.

This script NEVER bypasses the gateway: it calls the exact same
gateway.py/reconciliation.py code paths scripts/confirm_polymarket_order.py
already uses, and the exact same risk.py PolymarketRiskManager
engine.py uses — nothing here is a shortcut around risk or reconciliation.

Two distinct modes, selected ENTIRELY by POLYMARKET_TRADING_MODE (never
by a flag on this script):

PAPER (POLYMARKET_TRADING_MODE=paper, the default) — a dry run of the
full pipeline, ending in a simulated fill. Safe to run any time, any
number of times:
    python3 scripts/manual_polymarket_us_test.py --outcome YES --amount 5 --max-price 0.60

LIVE (POLYMARKET_TRADING_MODE=live) — prints a consolidated LIVE
PREFLIGHT block covering every gate below, then READY FOR FIRST $<amount>
LIVE TEST: YES/NO, and STOPS there — no order, paper or real, is placed
by a preflight-only run. Only a SECOND, explicit invocation with
--confirm-live goes on to actually submit, and only if the preflight
was READY:
    python3 scripts/manual_polymarket_us_test.py --outcome YES --amount 5 --max-price 0.60                 (preflight only)
    python3 scripts/manual_polymarket_us_test.py --outcome YES --amount 5 --max-price 0.60 --confirm-live   (the real attempt)

SAFETY — multiple independent, all-required gates before a REAL order
can ever be placed (any one missing keeps this at the preflight stage):
  1. POLYMARKET_TRADING_MODE=live
  2. POLYMARKET_LIVE_TRADING_CONFIRMED=true
  3. --confirm-live (this script's own explicit flag, on its own
     separate invocation from the preflight-only check)
  4. Emergency stop not active (src/execution/emergency_stop.py —
     cleared ONLY by a human, via scripts/emergency_stop_control.py;
     this script never clears it)
  5. --amount <= POLYMARKET_MAX_BET_USD
  6. orders.preview() succeeded
  7. PolymarketRiskManager.evaluate_new_trade().allowed (max bet,
     daily loss, open positions, cooldown, stale data, spread,
     liquidity, entry cutoff)
  8. No existing open position (positions.py) — this is a ONE-position
     integration test, not an averaging-down tool.
  9. No existing pending order awaiting approval — refuses to risk a
     duplicate/conflicting submission.

--outcome accepts YES/NO (this codebase's own vocabulary) or LONG/SHORT
(the US venue's own CreateOrderParams.intent vocabulary) — LONG/SHORT
are normalized to YES/NO respectively; see us_client.py's
_INTENT_FOR_OUTCOME for the reverse mapping at order-construction time.
The outcome is ALWAYS explicit on the command line — this script never
lets a strategy choose it.

If a fill's status comes back "unknown" (get_fill_status() couldn't
confidently interpret the exchange's response — this includes
orders.retrieve() 404ing on an order that was JUST submitted, a real,
observed, transient delay before the exchange makes a new order
visible), this retries the SAME reconciliation check a few times with a
short delay (never a second submission — only re-querying the status of
the one order already placed) before giving up and reporting "unknown"
to stop and let a human investigate with scripts/check_order_status.py.
See run_manual_test()'s reconciliation step.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.execution.emergency_stop import EmergencyStopStore  # noqa: E402
from src.polymarket import reconciliation  # noqa: E402
from src.polymarket.client import NoActiveMarketError, PolymarketClientError, get_polymarket_client  # noqa: E402
from src.polymarket.gateway import (  # noqa: E402
    LiveTradingDisabledError,
    PendingOrderNotActionableError,
    get_execution_gateway,
)
from src.polymarket.logger import PolymarketDecisionLogger  # noqa: E402
from src.polymarket.models import OrderRequest  # noqa: E402
from src.polymarket.pending import PolymarketPendingOrderStore  # noqa: E402
from src.polymarket.positions import PolymarketPositionStore  # noqa: E402
from src.polymarket.risk import PolymarketRiskManager, RiskDecision  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.state import DailyPnlStateStore  # noqa: E402
from src.polymarket.us_client import PolymarketUSClient  # noqa: E402

_OUTCOME_ALIASES = {"YES": "YES", "LONG": "YES", "NO": "NO", "SHORT": "NO"}


def _risk_result(decision: RiskDecision, name: str):
    return next(r for r in decision.results if r.name == name)


def run_manual_test(
    *,
    settings: PolymarketSettings,
    client,
    outcome: str,
    amount: float,
    max_price: float,
    confirm_live: bool,
    decision_logger: PolymarketDecisionLogger,
    state_store: DailyPnlStateStore,
    position_store: PolymarketPositionStore,
    pending_store: PolymarketPendingOrderStore,
    emergency_stop_store: EmergencyStopStore,
    now: datetime | None = None,
    unknown_status_retries: int = 3,
    unknown_status_retry_delay_seconds: float = 2.0,
) -> int:
    """The testable core (argparse-free) — see module docstring for the
    full flow and safety-gate list. Returns a process exit code (0 on
    a clean paper/live outcome including a preflight-not-ready or
    live-gate refusal that was handled cleanly; 1 on anything that
    should be treated as a hard failure by a calling script)."""
    now = now or datetime.now(timezone.utc)

    # --- Gate 5: amount <= POLYMARKET_MAX_BET_USD -----------------------------
    if amount > settings.max_bet_usd:
        print(f"REFUSING: --amount ${amount:.2f} exceeds the configured POLYMARKET_MAX_BET_USD=${settings.max_bet_usd:.2f}.")
        return 1

    # --- exact market (automatic BTC 15m discovery, or the manual override) ---
    try:
        market = client.find_active_btc_market(now=now)
    except (NoActiveMarketError, PolymarketClientError) as exc:
        print(f"REFUSING: could not retrieve the exact market: {exc}")
        return 1
    print(f"Market: {market.question!r}")
    print(f"  slug:      {market.condition_id}")
    print(f"  closes in: {market.seconds_to_close:.0f}s ({market.close_time.isoformat()})")

    # --- current order book / current price / executable liquidity ----------
    # EVENT SLUG and TRADEABLE MARKET SLUG are printed separately and
    # explicitly here on purpose: market.condition_id is the EVENT's own
    # slug (btc-updown-15m-...), while token_id is the NESTED market's own
    # slug exactly as returned by event["markets"][0]["slug"] in
    # _to_binary_market() -- NEVER synthesized by string concatenation
    # anywhere in this codebase (see us_client.py's _to_binary_market/
    # _get_manual_override_market). These two are genuinely different
    # strings on the live API (confirmed: a "cpc-"-prefixed value has been
    # observed as the real, API-returned nested market slug for at least
    # one event) -- this print exists so that distinction, and the exact
    # value about to be used for markets.book()/orders.create(), is never
    # guessed at.
    token_id = market.token_id_for(outcome)
    print(f"EVENT SLUG: {market.condition_id}")
    print(f"TRADEABLE MARKET SLUG: {token_id}")
    try:
        order_book = client.get_order_book(token_id)
    except Exception as exc:  # noqa: BLE001 - this script's whole job is to surface exactly this kind of failure
        print(f"REFUSING: could not retrieve the order book: {type(exc).__name__}: {exc}")
        return 1
    print(f"Order book ({outcome}): best_bid={order_book.best_bid} best_ask={order_book.best_ask}")
    liquidity = order_book.executable_liquidity_usd(side="BUY", max_price=max_price)
    print(f"Executable liquidity at/below ${max_price:.4f}: ${liquidity:.2f}")

    # --- risk checks: PolymarketRiskManager, the SAME class engine.py uses ---
    risk_manager = PolymarketRiskManager(settings)
    state = state_store.load(today=now.date())
    decision = risk_manager.evaluate_new_trade(
        size_usd=amount, market=market, state=state, order_book=order_book, side="BUY", max_price=max_price, now=now,
    )
    print("Risk checks:")
    for result in decision.results:
        print(f"  [{'PASS' if result.passed else 'FAIL'}] {result.name}: {result.detail}")
    if not decision.allowed and not settings.is_live:
        # Paper mode: fail fast with the simple message, exactly as
        # before. LIVE mode deliberately does NOT return here -- a
        # failed risk check (e.g. MAX_SPREAD/ORDER_BOOK_LIQUIDITY on a
        # real, currently-too-wide/too-thin market) must still flow all
        # the way into the consolidated LIVE PREFLIGHT block below, so
        # "which gate prevented entry" is always shown there, never only
        # in this early, paper-only message.
        print("REFUSING: risk checks did not pass. No order (paper or live) will be attempted.")
        return 1

    order = OrderRequest(
        condition_id=market.condition_id, token_id=token_id, outcome=outcome, side="BUY",
        size_usd=amount, max_price=max_price, close_time=market.close_time, reason="manual test",
        order_type=settings.default_order_type,
    )
    print(f"Order: outcome={outcome} size_usd=${amount:.2f} max_price=${max_price:.4f} order_type={order.order_type}")

    # --- order preview (never places anything) --------------------------------
    preview_ok = False
    if isinstance(client, PolymarketUSClient):
        try:
            preview = client.preview_order(order)
            preview_ok = True
            print(f"Preview OK: {preview}")
        except Exception as exc:  # noqa: BLE001 - preview failing is a real, reportable outcome, not a crash
            print(f"Preview FAILED: {type(exc).__name__}: {exc}")
    else:
        print("Preview: not available for this venue's client — treated as not confirmed for the live-gate check below.")

    # --- PAPER MODE: unchanged dry run of the full pipeline -------------------
    if not settings.is_live:
        try:
            gateway = get_execution_gateway(settings, decision_logger, order_placer=None, emergency_stop_store=emergency_stop_store)
            result = gateway.submit_order(order)
        except LiveTradingDisabledError as exc:
            print(f"REFUSING: {exc}")
            return 1
        assert result.status == "simulated_fill"
        assert result.fill_result is not None
        position = reconciliation.record_fill(
            result.fill_result, order, result.fill_result.order_id,
            position_store=position_store, state_store=state_store, decision_logger=decision_logger, now=now,
        )
        print(f"PAPER FILL: {result.fill_result.filled_shares:.4f} shares @ ${result.fill_result.avg_fill_price}")
        print("Position created." if position is not None else "No new position (already reconciled — idempotent).")
        return 0

    # --- LIVE MODE: consolidated preflight, then an explicit second step ------
    stopped = emergency_stop_store.is_stopped()
    open_positions = position_store.load()
    conflicting_pending = [p for p in pending_store.load() if p.status == "awaiting_approval"]
    live_confirmed = settings.live_trading_confirmed  # settings.is_live is already true here

    entry_cutoff_ok = _risk_result(decision, "ENTRY_CUTOFF").passed
    ready = (
        decision.allowed and preview_ok and not stopped and live_confirmed
        and not open_positions and not conflicting_pending
    )

    auth_ok = True
    auth_error = ""
    print("")
    print("LIVE PREFLIGHT")
    print(f"API: reached (market + order book retrieved from the live venue)")
    try:
        balance = client.get_balance_usdc()
        print(f"AUTH: OK")
        print(f"BALANCE: ${balance:.2f}")
    except Exception as exc:  # noqa: BLE001 - authentication/balance failing is a real, reportable gate, not a crash
        auth_ok = False
        auth_error = f"{type(exc).__name__}: {exc}"
        print(f"AUTH: FAILED ({auth_error})")
        print(f"BALANCE: unknown")
    ready = ready and auth_ok
    print(f"CURRENT BTC 15M: {market.question!r} (condition_id={market.condition_id})")
    print(f"NESTED MARKET: {token_id}")
    print(f"BEST BID: {order_book.best_bid}")
    print(f"BEST ASK: {order_book.best_ask}")
    print(f"SPREAD: {order_book.spread_pct}")
    print(f"LIQUIDITY: ${liquidity:.2f}")
    print(f"ENTRY CUTOFF: {'PASS' if entry_cutoff_ok else 'FAIL'} ({market.seconds_to_close:.0f}s remaining)")
    print(f"RISK: {'PASS' if decision.allowed else 'FAIL'}")
    print(f"PREVIEW: {'PASS' if preview_ok else 'FAIL'}")
    print(f"EMERGENCY STOP: {'ACTIVE' if stopped else 'CLEARED'}")
    print(f"OPEN POSITIONS: {len(open_positions)}")
    print(f"PENDING ORDERS: {len(conflicting_pending)}")
    print("")
    print(f"READY FOR FIRST ${amount:.0f} LIVE TEST: {'YES' if ready else 'NO'}")

    if not ready:
        print("")
        print("STOP. The following gate(s) are not satisfied:")
        if not auth_ok:
            print(f"  - AUTH: {auth_error}")
        if not decision.allowed:
            for result in decision.results:
                if not result.passed:
                    print(f"  - RISK:{result.name}: {result.detail}")
        if not preview_ok:
            print("  - PREVIEW: orders.preview() did not succeed.")
        if stopped:
            print("  - EMERGENCY STOP: active. Clear it yourself (a human, not this script) via "
                  "scripts/emergency_stop_control.py clear --authorized-by <you> --reason <...> "
                  "only once every other gate above is already satisfied.")
        if not live_confirmed:
            print("  - POLYMARKET_LIVE_TRADING_CONFIRMED is not true.")
        if open_positions:
            print(f"  - OPEN POSITIONS: {len(open_positions)} existing open position(s) — this is a "
                  "one-position integration test, not an averaging-down tool.")
        if conflicting_pending:
            print(f"  - PENDING ORDERS: {len(conflicting_pending)} pending order(s) already awaiting "
                  "approval — resolve or let those expire before attempting a new one.")
        print("No order (paper or live) was attempted.")
        return 1

    if not confirm_live:
        print("")
        print("Preflight PASSED. Nothing has been submitted. Re-run this EXACT command with "
              "--confirm-live to actually attempt the live order.")
        return 0

    # --- Only now: READY=YES and --confirm-live both hold. Submit for real. --
    try:
        gateway = get_execution_gateway(
            settings, decision_logger, pending_store=pending_store, order_placer=None,
            emergency_stop_store=emergency_stop_store,
        )
        result = gateway.submit_order(order)
    except LiveTradingDisabledError as exc:
        print(f"REFUSING: {exc}")
        return 1
    assert result.status == "awaiting_approval"
    pending_id = result.extra["pending_order_id"]

    try:
        confirmed = gateway.confirm_and_place(pending_id, client, approved_by="user:manual-test")
    except (LiveTradingDisabledError, PendingOrderNotActionableError) as exc:
        print("")
        print("LIVE ORDER:")
        print(f"ORDER ID: {pending_id}")
        print(f"SUBMISSION: refused")
        print(f"ERROR: {exc}")
        return 1

    print("")
    print("LIVE ORDER:")
    print(f"ORDER ID: {pending_id}")
    print(f"SUBMISSION: {confirmed.status}")
    if confirmed.status != "submitted":
        print(f"FILL STATUS: n/a (never reached the exchange)")
        print(f"ERROR: {confirmed.error}")
        return 1

    # The COMPLETE raw orders.create() response, printed now and only now --
    # this process is the ONLY place that will ever see it. If a later
    # status lookup for this exact order ever comes back inconclusive (see
    # scripts/check_order_status.py), this is the one piece of evidence
    # that cannot be recovered after the fact.
    assert confirmed.submission is not None
    print(f"EXCHANGE ORDER ID: {confirmed.submission.exchange_order_id}")
    print(f"RAW SUBMISSION RESPONSE: {confirmed.submission.raw}")

    # A 404 from orders.retrieve() immediately after submission can be a
    # real, transient visibility delay (confirmed live: an order that
    # 404'd moments after submission was definitively FILLED on a later
    # check) -- retry the SAME status check a bounded number of times
    # before giving up. This NEVER resubmits the order: reconcile_order()
    # only re-queries get_fill_status() for the SAME exchange_order_id;
    # reconciliation.py's own fill_reconciled=False-on-"unknown" guard
    # (see its module docstring) is what makes each retry here safe and
    # idempotent -- a later FILLED result still opens exactly one
    # position, never a duplicate.
    attempt = 1
    while True:
        pending = pending_store.get(pending_id)
        fill = reconciliation.reconcile_order(
            pending, client=client, pending_store=pending_store, position_store=position_store,
            state_store=state_store, decision_logger=decision_logger, now=now,
        )
        if fill is None or fill.status != "unknown" or attempt >= unknown_status_retries:
            break
        print(f"FILL STATUS: unknown (attempt {attempt}/{unknown_status_retries}; {fill.raw}) -- "
              f"retrying in {unknown_status_retry_delay_seconds:.0f}s...")
        time.sleep(unknown_status_retry_delay_seconds)
        attempt += 1

    if fill is None:
        print("FILL STATUS: n/a (nothing to reconcile -- unexpected for a freshly-submitted order)")
        print("ERROR: reconciliation returned nothing to reconcile")
        return 1
    if fill.status == "unknown":
        print(f"FILL STATUS: unknown (after {attempt}/{unknown_status_retries} attempts)")
        print(f"FILLED SHARES: {fill.filled_shares}")
        print(f"AVG FILL PRICE: {fill.avg_fill_price}")
        print(f"POSITION CREATED: NO")
        # NOT a terminal determination -- reconciliation.py deliberately does
        # NOT mark this pending order fill_reconciled, so it can be re-checked
        # later (a communication failure may be transient; an unrecognized
        # state may become interpretable once the code is updated). RAW
        # DETAIL below is whatever get_fill_status() preserved -- either
        # {"lookup_error": ...} (the status call itself failed) or
        # {"state": ...} (the exchange returned a state this system doesn't
        # recognize) -- never discarded.
        print(f"RAW DETAIL: {fill.raw}")
        print(f"RECONCILIATION: NOT done -- this pending order remains re-checkable "
              f"(pending_order_id={pending_id}, exchange_order_id={fill.order_id})")
        print(f"ERROR: fill status is unknown -- do not assume a fill. Run "
              f"'python3 scripts/check_order_status.py {fill.order_id}' to re-query the exchange "
              "directly (prints the raw response). No second order was submitted.")
        return 1

    print(f"FILL STATUS: {fill.status}")
    print(f"FILLED SHARES: {fill.filled_shares}")
    print(f"AVG FILL PRICE: {fill.avg_fill_price}")
    print(f"POSITION CREATED: {'YES' if fill.is_fill else 'NO'}")
    print(f"RECONCILIATION: done")
    print(f"OPEN POSITIONS NOW: {len(position_store.load())}")
    print(f"ERROR: none")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--market-slug", default=None, metavar="SLUG",
        help="OPTIONAL. A specific market/event slug to test instead of automatic BTC 15m discovery. "
             "Omit this for a real production live test -- the current BTC market is found automatically.",
    )
    parser.add_argument("--outcome", required=True, choices=sorted(_OUTCOME_ALIASES))
    parser.add_argument("--amount", required=True, type=float, help="USD size — capped at POLYMARKET_MAX_BET_USD")
    parser.add_argument("--max-price", required=True, type=float, dest="max_price")
    parser.add_argument(
        "--confirm-live", action="store_true",
        help="Required (along with POLYMARKET_TRADING_MODE=live, POLYMARKET_LIVE_TRADING_CONFIRMED=true, "
             "a cleared emergency stop, and a READY preflight) to attempt a REAL order. Without it, in live "
             "mode this only prints the preflight and stops; in paper mode it is ignored.",
    )
    args = parser.parse_args()

    if args.market_slug:
        os.environ["POLYMARKET_US_MARKET_SLUG"] = args.market_slug
    settings = PolymarketSettings.from_env()
    if not settings.is_us_venue:
        print("REFUSING: this script is Polymarket US only — set POLYMARKET_VENUE=us.")
        return 1

    client = get_polymarket_client(settings)
    decision_logger = PolymarketDecisionLogger(Path(settings.decision_log_file))
    state_store = DailyPnlStateStore(Path(settings.daily_pnl_file))
    position_store = PolymarketPositionStore(Path(settings.positions_file))
    pending_store = PolymarketPendingOrderStore(Path(settings.pending_orders_file))
    emergency_stop_store = EmergencyStopStore(Path(settings.emergency_stop_file))

    print(f"POLYMARKET_TRADING_MODE={settings.trading_mode}" + (" (REAL MONEY)" if settings.is_live else " (paper)"))
    return run_manual_test(
        settings=settings, client=client, outcome=_OUTCOME_ALIASES[args.outcome], amount=args.amount,
        max_price=args.max_price, confirm_live=args.confirm_live, decision_logger=decision_logger,
        state_store=state_store, position_store=position_store, pending_store=pending_store,
        emergency_stop_store=emergency_stop_store,
    )


if __name__ == "__main__":
    raise SystemExit(main())
