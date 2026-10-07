#!/usr/bin/env python3
"""ONE-TIME MANUAL LIVE TEST for Polymarket US — an explicit, exact-market
integration test of the complete trading pipeline (discovery → order
book → risk → preview → submission → authoritative fill → reconciliation
→ position ledger), NOT an autonomous "trade anything you find" mode.

You give this script a market slug you picked yourself from the
Polymarket US app (the SAME mechanism as
scripts/verify_polymarket_setup.py --market-slug — see
settings.py's/us_client.py's module docstrings on
POLYMARKET_US_MARKET_SLUG: no search, no "closest available," the
exact slug only), an outcome, a USD amount, and a max price. This
script NEVER bypasses the gateway: it calls the exact same
gateway.py/reconciliation.py code paths scripts/confirm_polymarket_order.py
already uses, and the exact same risk.py PolymarketRiskManager
engine.py uses — nothing here is a shortcut around risk or reconciliation.

Flow, every single time, regardless of paper or live:
    exact market (manual override)
    -> current order book
    -> current price
    -> executable liquidity
    -> risk checks (max bet, daily loss, open positions, cooldown,
       stale data, spread, liquidity, entry cutoff — PolymarketRiskManager,
       the SAME class engine.py uses)
    -> order preview (orders.preview() — never places anything)
    -> emergency-stop check
    -> explicit live confirmation gates
    -> FOK/appropriate bounded order via gateway.submit_order()/confirm_and_place()
    -> submission
    -> authoritative fill lookup (reconciliation.reconcile_order())
    -> position ledger

SAFETY — multiple independent, all-required gates before a REAL order
can ever be placed (any one missing falls through to a PAPER dry run
of the exact same pipeline instead):
  1. POLYMARKET_TRADING_MODE=live
  2. POLYMARKET_LIVE_TRADING_CONFIRMED=true
  3. --confirm-live (this script's own explicit flag)
  4. Emergency stop not active (src/execution/emergency_stop.py)
  5. --amount <= POLYMARKET_MAX_BET_USD
  6. orders.preview() succeeded
  7. PolymarketRiskManager.evaluate_new_trade().allowed

Usage (read-only verification FIRST):
    python3 scripts/verify_polymarket_setup.py --market-slug <SLUG>

Then, a safe PAPER dry run of the full pipeline (no env changes needed
— POLYMARKET_TRADING_MODE stays "paper", the default):
    python3 scripts/manual_polymarket_us_test.py \\
        --market-slug <SLUG> --outcome YES --amount 5 --max-price 0.60

Only once that looks right, and POLYMARKET_TRADING_MODE=live /
POLYMARKET_LIVE_TRADING_CONFIRMED=true are set and the emergency stop
is cleared, add --confirm-live to actually attempt a real order:
    python3 scripts/manual_polymarket_us_test.py \\
        --market-slug <SLUG> --outcome YES --amount 5 --max-price 0.60 --confirm-live

--outcome accepts YES/NO (this codebase's own vocabulary) or LONG/SHORT
(the US venue's own CreateOrderParams.intent vocabulary) — LONG/SHORT
are normalized to YES/NO respectively; see us_client.py's
_INTENT_FOR_OUTCOME for the reverse mapping at order-construction time.
"""

from __future__ import annotations

import argparse
import os
import sys
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
from src.polymarket.risk import PolymarketRiskManager  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.state import DailyPnlStateStore  # noqa: E402
from src.polymarket.us_client import PolymarketUSClient  # noqa: E402

_OUTCOME_ALIASES = {"YES": "YES", "LONG": "YES", "NO": "NO", "SHORT": "NO"}


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
) -> int:
    """The testable core (argparse-free) — see module docstring for the
    full flow and safety-gate list. Returns a process exit code (0 on
    a clean paper/live outcome including a risk/preview/live-gate
    refusal that was handled cleanly; 1 on anything that should be
    treated as a hard failure by a calling script)."""
    now = now or datetime.now(timezone.utc)

    # --- Gate 5: amount <= POLYMARKET_MAX_BET_USD -----------------------------
    if amount > settings.max_bet_usd:
        print(f"REFUSING: --amount ${amount:.2f} exceeds the configured POLYMARKET_MAX_BET_USD=${settings.max_bet_usd:.2f}.")
        return 1

    print(f"Emergency stop active: {emergency_stop_store.is_stopped()}")

    # --- exact market (manual override) ---------------------------------------
    try:
        market = client.find_active_btc_market(now=now)
    except (NoActiveMarketError, PolymarketClientError) as exc:
        print(f"REFUSING: could not retrieve the exact market: {exc}")
        return 1
    print(f"Market: {market.question!r}")
    print(f"  slug:      {market.condition_id}")
    print(f"  closes in: {market.seconds_to_close:.0f}s ({market.close_time.isoformat()})")

    # --- current order book / current price / executable liquidity ----------
    token_id = market.token_id_for(outcome)
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
    if not decision.allowed:
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

    # --- submission, via the gateway (never bypassed) -------------------------
    # IMPORTANT: order_placer is deliberately omitted here (always None), even
    # in live mode. If POLYMARKET_LIVE_AUTO_EXECUTE=true happens to be set in
    # the environment (a legitimate setting for the automated bot's own
    # loop — see run_polymarket_bot.py), passing a real order_placer here
    # would let gateway.submit_order() auto-submit the live order on the
    # spot, bypassing this script's own --confirm-live / preview-success
    # gates below entirely. This script supplies the order_placer only to
    # the explicit confirm_and_place() call further down, once every gate
    # has independently passed.
    try:
        gateway = get_execution_gateway(
            settings, decision_logger, pending_store=pending_store if settings.is_live else None,
            order_placer=None, emergency_stop_store=emergency_stop_store,
        )
        result = gateway.submit_order(order)
    except LiveTradingDisabledError as exc:
        # e.g. POLYMARKET_TRADING_MODE=live but POLYMARKET_LIVE_TRADING_CONFIRMED
        # is not true -- LivePolymarketGateway.__init__ itself refuses to
        # construct in that state. Fail closed with a clear message instead
        # of an unhandled traceback.
        print(f"REFUSING: {exc}")
        return 1

    if result.status == "simulated_fill":
        if confirm_live:
            print("NOTE: --confirm-live was passed, but POLYMARKET_TRADING_MODE is not \"live\" — "
                  "this was a PAPER-only dry run of the full pipeline; no real order was ever possible.")
        assert result.fill_result is not None
        position = reconciliation.record_fill(
            result.fill_result, order, result.fill_result.order_id,
            position_store=position_store, state_store=state_store, decision_logger=decision_logger, now=now,
        )
        print(f"PAPER FILL: {result.fill_result.filled_shares:.4f} shares @ ${result.fill_result.avg_fill_price}")
        print("Position created." if position is not None else "No new position (already reconciled — idempotent).")
        return 0

    if result.status == "awaiting_approval":
        pending_id = result.extra["pending_order_id"]
        print(f"Order is PENDING APPROVAL (pending_order_id={pending_id}) — nothing has reached the exchange yet.")

        # --- Gates 1-4, 6: ALL required before a real order is attempted -----
        if not confirm_live:
            print("--confirm-live was not passed — stopping here. No real order placed.")
            return 0
        if not (settings.is_live and settings.live_trading_confirmed):
            print("REFUSING: --confirm-live was passed, but POLYMARKET_TRADING_MODE=live and "
                  "POLYMARKET_LIVE_TRADING_CONFIRMED=true are not BOTH set. No order placed.")
            return 1
        if emergency_stop_store.is_stopped():
            print("REFUSING: the emergency stop is ACTIVE. No order placed.")
            return 1
        if not preview_ok:
            print("REFUSING: orders.preview() did not succeed. An order is never placed live without "
                  "a successful preview first.")
            return 1

        try:
            confirmed = gateway.confirm_and_place(pending_id, client, approved_by="user:manual-test")
        except (LiveTradingDisabledError, PendingOrderNotActionableError) as exc:
            print(f"REFUSING: {exc}")
            return 1
        print(f"Submission result: {confirmed.status}")
        if confirmed.status != "submitted":
            print(f"  error: {confirmed.error}")
            return 1

        pending = pending_store.get(pending_id)
        fill = reconciliation.reconcile_order(
            pending, client=client, pending_store=pending_store, position_store=position_store,
            state_store=state_store, decision_logger=decision_logger, now=now,
        )
        if fill is None:
            print("Reconciliation: nothing to reconcile (unexpected for a freshly-submitted order).")
            return 1
        print(f"Fill status: {fill.status} filled_shares={fill.filled_shares} avg_fill_price={fill.avg_fill_price}")
        print("POSITION OPENED" if fill.is_fill else "No position opened (order did not fill).")
        return 0

    print(f"Submission result: {result.status} (error={result.error})")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--market-slug", required=True, metavar="SLUG")
    parser.add_argument("--outcome", required=True, choices=sorted(_OUTCOME_ALIASES))
    parser.add_argument("--amount", required=True, type=float, help="USD size — capped at POLYMARKET_MAX_BET_USD")
    parser.add_argument("--max-price", required=True, type=float, dest="max_price")
    parser.add_argument(
        "--confirm-live", action="store_true",
        help="Required (along with POLYMARKET_TRADING_MODE=live and POLYMARKET_LIVE_TRADING_CONFIRMED=true "
             "and a cleared emergency stop) to attempt a REAL order. Without it, this is always a paper dry run.",
    )
    args = parser.parse_args()

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
