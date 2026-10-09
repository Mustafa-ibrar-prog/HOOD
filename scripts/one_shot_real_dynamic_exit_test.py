#!/usr/bin/env python3
"""ONE-SHOT, CONTROLLED REAL-MONEY entry+exit smoke test for Polymarket US.

*** THIS SCRIPT CAN SPEND REAL MONEY (capped at $5.00). READ THIS FULLY. ***

Purpose: a single, explicit, human-confirmed real round trip through the
REAL dynamic-exit path -- not a backtest, not paper mode, not shadow mode
(all already covered by scripts/dynamic_exit_smoke_test.py,
scripts/dynamic_exit_shadow.py, and tests/test_polymarket_exit_manager.py's
paper-mode coverage). This is the first and only script in this codebase
that can submit a REAL exit order.

Flow (every step logged to the existing Polymarket decision log,
settings.decision_log_file):
  1. Discover the current active Polymarket US BTC Up/Down 15m market
     (PolymarketUSClient.find_active_btc_market -- unmodified).
  2. Place ONE real entry, capped at $5, by calling
     scripts/manual_polymarket_us_test.py's own run_manual_test()
     UNCHANGED -- the exact same discovery/risk/preview/submit/reconcile
     pipeline already reviewed and tested there. This script adds
     NOTHING to, and removes NOTHING from, that entry path.
  3. Reconcile the real exchange order authoritatively (run_manual_test's
     own retry-on-"unknown" logic, never a second submission). If this
     doesn't resolve cleanly, THIS SCRIPT STOPS HERE -- no exit is ever
     attempted without a confirmed, filled, real position.
  4. Once filled: fetch the real Coinbase BTC feed and the real live
     order book for the exact position just opened, and run the
     existing, UNMODIFIED evaluate_dynamic_exit() (exit_manager.py)
     against them -- the identical function scripts/dynamic_exit_shadow.py
     already exercises read-only. A stale/unavailable BTC feed is never
     special-cased here: assess_btc_market()'s own existing staleness
     gate already forces INSUFFICIENT_DATA -> HOLD in that case, exactly
     as it does everywhere else in this system.
  5. If (and only if) the evaluator approves an exit, submit it via the
     existing, UNMODIFIED submit_dynamic_exit() -- respecting
     settings.auto_exit_enabled and settings.live_auto_execute EXACTLY as
     every other real caller of that function does. If auto_exit_enabled
     is false (ships disabled by default), the exit correctly stops at
     awaiting_approval and this script says so and stops -- it does NOT
     self-confirm an exit on your behalf. That is not a bug: it is the
     exact, already-reviewed Mode B/C distinction from the
     auto_exit_enabled/live_auto_execute interaction trace. Run
     scripts/confirm_pending_order.py yourself to complete it.
  6. If the evaluator says HOLD, this script does NOT force an exit. The
     real position stays open, exactly as it would under normal
     operation, to be resolved by the running bot, by settlement at the
     market's close, or by you.

Safety (every one of these is enforced in code, not just documented):
  - Hard-capped at $5.00 regardless of POLYMARKET_MAX_BET_USD -- this
    script's own ceiling, independent of and in addition to the normal
    risk check.
  - Refuses to run at all outside POLYMARKET_TRADING_MODE=live, outside
    POLYMARKET_VENUE=us, or if POLYMARKET_LIVE_AUTO_EXECUTE is true (this
    script's entry confirmation must be its own single explicit
    approval, not an automatic one).
  - Refuses to run if an open position or an awaiting-approval pending
    order already exists -- never averages down, never risks a
    duplicate/conflicting submission.
  - Never attempts the exit phase unless the entry was authoritatively
    reconciled to a definite outcome (never on an "unknown" fill status).
  - A real exit reconciliation retry (mirroring the entry side's own
    pattern) only ever RE-QUERIES the same order's status -- it never
    resubmits.
  - A runtime guard counts every real PolymarketUSClient.place_order
    call by side and ACTIVELY REFUSES (raises, before the network call)
    a second BUY or a second SELL in the same run -- this is enforced,
    not just asserted afterward.
  - Never touches risk.py/strategy.py/BTC intelligence/settlement --
    this script only calls their existing, public functions.

Usage:
    # Preview only -- discovers the market, runs the full entry preflight,
    # submits NOTHING. Safe to run any number of times.
    python3 scripts/one_shot_real_dynamic_exit_test.py --outcome YES --max-price 0.60

    # The real attempt -- places the one real $5 entry, and if/when the
    # evaluator approves, the one real exit.
    python3 scripts/one_shot_real_dynamic_exit_test.py --outcome YES --max-price 0.60 --confirm-live

Required real environment, verified before anything else runs:
    POLYMARKET_VENUE=us
    POLYMARKET_TRADING_MODE=live
    POLYMARKET_LIVE_TRADING_CONFIRMED=true
    POLYMARKET_LIVE_AUTO_EXECUTE=false
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.manual_polymarket_us_test import run_manual_test  # noqa: E402 - reused unmodified
from src.execution.emergency_stop import EmergencyStopStore  # noqa: E402
from src.polymarket.btc_coinbase_source import CoinbaseBtcQuoteSource, CoinbaseBtcQuoteSourceError  # noqa: E402
from src.polymarket.btc_intelligence import DEFAULT_MIN_BARS_FOR_INDICATORS, assess_btc_market  # noqa: E402
from src.polymarket.btc_market_data import BtcPriceHistoryStore  # noqa: E402
from src.polymarket.client import get_polymarket_client  # noqa: E402
from src.polymarket.exit_manager import evaluate_dynamic_exit, reconcile_exit_fill, submit_dynamic_exit  # noqa: E402
from src.polymarket.gateway import get_execution_gateway  # noqa: E402
from src.polymarket.logger import PolymarketDecisionLogger  # noqa: E402
from src.polymarket.pending import PolymarketPendingOrderStore  # noqa: E402
from src.polymarket.positions import PolymarketPositionStore  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.state import DailyPnlStateStore  # noqa: E402
from src.polymarket.us_client import PolymarketUSClient  # noqa: E402

MAX_TEST_AMOUNT_USD = 5.0


class OrderGuardViolation(RuntimeError):
    pass


def install_order_guard(client_cls=PolymarketUSClient):
    """Wraps place_order to COUNT every real call by side and ACTIVELY
    REFUSE (before the network call) a second BUY or a second SELL in
    the same run. Returns (call_log, restore) -- call restore() in a
    finally block regardless of outcome."""
    call_log: list[str] = []
    original = client_cls.place_order

    def _guarded(self, order):
        if call_log.count(order.side) >= 1:
            raise OrderGuardViolation(
                f"GUARD: refusing a second {order.side} order this run (already submitted "
                f"{call_log.count(order.side)})."
            )
        call_log.append(order.side)
        return original(self, order)

    client_cls.place_order = _guarded

    def restore():
        client_cls.place_order = original

    return call_log, restore


def run_one_shot_test(
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
    """The testable core (argparse-free). Returns a process exit code: 0
    for any clean terminal state (including "preflight only, nothing
    submitted" and "HOLD, position left open"), 1 for anything that
    needs a human to look at it."""
    now = now or datetime.now(timezone.utc)

    decision_logger.log_decision(
        kind="one_shot_real_test_started",
        reason=f"outcome={outcome} amount=${amount:.2f} max_price=${max_price:.4f} confirm_live={confirm_live}",
    )

    if position_store.load():
        print("REFUSING: an open position already exists -- this is a one-position test, not an averaging tool.")
        return 1
    # Actionable only -- status == "awaiting_approval" AND not yet
    # expired; an expired-but-unswept historical record is never a live
    # conflict (see PolymarketPendingOrderStore.list_awaiting_approval,
    # which also normalizes it to a terminal "expired" status here, via
    # the existing expire_stale() reconciliation transition).
    if pending_store.list_awaiting_approval(now):
        print("REFUSING: a pending order is already awaiting approval -- resolve it first.")
        return 1

    # --- Entry: the existing, unmodified manual-test pipeline -----------------
    print("\n=== ENTRY ===")
    entry_rc = run_manual_test(
        settings=settings, client=client, outcome=outcome, amount=amount, max_price=max_price,
        confirm_live=confirm_live, decision_logger=decision_logger, state_store=state_store,
        position_store=position_store, pending_store=pending_store, emergency_stop_store=emergency_stop_store,
        now=now, unknown_status_retries=unknown_status_retries,
        unknown_status_retry_delay_seconds=unknown_status_retry_delay_seconds,
    )
    if entry_rc != 0:
        print(
            "\nABORTING: the entry did not complete cleanly (see ENTRY output above for the exact reason -- "
            "preflight not ready, or a fill status that could not be authoritatively reconciled). No exit "
            "will be attempted. If a real order WAS submitted but its fill is unknown, do NOT re-run this "
            "script -- investigate with scripts/check_order_status.py first."
        )
        decision_logger.log_decision(kind="one_shot_real_test_aborted", reason="entry did not complete cleanly")
        return 1

    if not confirm_live:
        print("\nPreflight-only run (no --confirm-live). Nothing was submitted. Re-run with --confirm-live "
              "to actually place the real entry.")
        return 0

    positions = position_store.load()
    if not positions:
        print("\nNo open position after the entry step (the order did not fill) -- nothing to exit. Done.")
        return 0
    position = positions[0]
    print(f"\nENTRY CONFIRMED FILLED: {position.filled_shares} shares @ ${position.avg_fill_price} "
          f"(condition_id={position.condition_id})")

    # --- Exit evaluation: real BTC feed + real order book + the existing, ----
    # unmodified evaluator. A stale/unavailable feed is never special-cased
    # here -- assess_btc_market()'s own staleness gate already forces
    # INSUFFICIENT_DATA -> HOLD, exactly as everywhere else in this system.
    print("\n=== EXIT EVALUATION ===")
    source = CoinbaseBtcQuoteSource()
    btc_store = BtcPriceHistoryStore(Path(settings.btc_price_history_file))
    try:
        candles = source.get_recent_candles(limit=DEFAULT_MIN_BARS_FOR_INDICATORS + 5)
        btc_store.record_bars(candles)
        print(f"Coinbase reachable -- recorded {len(candles)} real candle(s).")
    except CoinbaseBtcQuoteSourceError as exc:
        print(f"Coinbase unreachable ({exc}) -- proceeding with whatever BTC history is already persisted; "
              "the feed-staleness gate below will correctly force INSUFFICIENT_DATA/HOLD if that's not enough.")
    bars = btc_store.get_bars(interval_seconds=settings.btc_bar_interval_seconds, now=now)

    try:
        order_book = client.get_order_book(position.token_id)
    except Exception as exc:  # noqa: BLE001 - a book-fetch failure must never be treated as "no signal"
        print(f"\nABORTING: could not fetch the live order book for the open position: {exc}. The real "
              f"${position.filled_shares * position.avg_fill_price:.2f} position remains OPEN and "
              "unaffected -- it will be handled by the normal bot/settlement path.")
        decision_logger.log_decision(
            kind="one_shot_real_test_aborted", reason=f"order book fetch failed: {exc}",
            evidence={"position": position.to_dict()},
        )
        return 1

    recent_mids = [order_book.mid] if order_book.mid is not None else []
    assessment = assess_btc_market(
        bars, order_book, recent_mids, outcome=position.outcome, now=now,
        max_bar_age_seconds=settings.btc_max_bar_age_seconds, feed_source=source.name,
    )
    feed_status = assessment.feed_status
    decision_logger.log_decision(
        kind="btc_feed_status",
        reason=(f"BTC_FEED_SOURCE={feed_status.source} BTC_LAST_BAR_TIME={feed_status.last_bar_time} "
                f"BTC_BAR_AGE_SECONDS={feed_status.bar_age_seconds} BTC_FEED_STATUS={feed_status.status} "
                f"BTC_EVIDENCE_STATE={assessment.state.value}"),
        evidence={
            "condition_id": position.condition_id, "BTC_FEED_SOURCE": feed_status.source,
            "BTC_BAR_AGE_SECONDS": feed_status.bar_age_seconds, "BTC_FEED_STATUS": feed_status.status,
            "BTC_EVIDENCE_STATE": assessment.state.value,
        },
    )
    print(f"BTC feed status: {feed_status.status} (bar_age_seconds={feed_status.bar_age_seconds})")
    print(f"BTC evidence state: {assessment.state.value}")

    decision = evaluate_dynamic_exit(position, order_book, assessment, profit_target_pct=settings.profit_target_pct)
    decision_logger.log_decision(
        kind="one_shot_real_exit_evaluation",
        reason=decision.reason,
        evidence={
            "condition_id": position.condition_id, "eligible": decision.eligible, "target_price": decision.target_price,
            "best_bid": decision.best_bid, "gross_pnl_pct": decision.gross_pnl_pct,
        },
    )
    print(f"Dynamic-exit decision: {'EXIT' if decision.eligible else 'HOLD'} -- {decision.reason}")

    if not decision.eligible:
        print("\nHOLD: the evaluator did not approve an exit this run. The real position REMAINS OPEN -- "
              "it will be resolved by the normal bot cycle (if running), by settlement at the market's "
              "close, or by you. This one-shot script never forces an exit.")
        return 0

    # --- Exit submission: the existing, unmodified submit_dynamic_exit(), ----
    # respecting auto_exit_enabled/live_auto_execute exactly as every other
    # real caller does -- never bypassed, never self-confirmed here.
    print("\n=== EXIT SUBMISSION ===")
    gateway = get_execution_gateway(
        settings, decision_logger, pending_store=pending_store, order_placer=client,
        emergency_stop_store=emergency_stop_store,
    )
    result = submit_dynamic_exit(
        decision, client=client, gateway=gateway, position_store=position_store, state_store=state_store,
        decision_logger=decision_logger, settings=settings, order_placer=client, now=now,
    )
    print(f"Exit submission result: {result.status}")

    if result.status == "awaiting_approval":
        pending_id = (result.extra or {}).get("pending_order_id")
        print(f"\nEXIT PENDING HUMAN CONFIRMATION (POLYMARKET_AUTO_EXIT_ENABLED is false): "
              f"pending_order_id={pending_id}. The real position remains open until you run "
              f"'python3 scripts/confirm_pending_order.py {pending_id}' (or let it expire and it will be "
              "re-evaluated next cycle). This is expected, correct behavior -- not a failure.")
        return 0
    if result.status in ("rejected", "failed"):
        print(f"\nEXIT NOT SUBMITTED ({result.status}): {result.error}. The real position remains open; "
              "the exit guard was cleared so a later cycle can retry.")
        return 0

    # result.status == "submitted": submit_dynamic_exit() already reconciled
    # once, synchronously, via client.get_fill_status() inside itself. If
    # that came back "unknown", retry the SAME reconciliation (never a
    # resubmission) a bounded number of times before giving up.
    current = position_store.get(position.client_order_id)
    attempt = 1
    while current is not None and current.exit_pending_order_id is not None and attempt < unknown_status_retries:
        print(f"Exit fill status unknown (attempt {attempt}/{unknown_status_retries}) -- "
              f"retrying reconciliation in {unknown_status_retry_delay_seconds:.0f}s...")
        time.sleep(unknown_status_retry_delay_seconds)
        current = reconcile_exit_fill(
            current, client=client, pending_store=pending_store, position_store=position_store,
            state_store=state_store, decision_logger=decision_logger, now=now,
        )
        attempt += 1

    if current is None:
        print("\nPOSITION CLOSED: the real exit filled and the position ledger shows it fully closed.")
        return 0
    if current.exit_pending_order_id is not None:
        print(f"\nEXIT STATUS STILL UNKNOWN after {attempt}/{unknown_status_retries} attempts "
              f"(exit_pending_order_id={current.exit_pending_order_id}). Do NOT submit a second exit -- "
              "investigate with scripts/check_order_status.py, or let the next cycle's reconciliation "
              "sweep pick it up.")
        return 1
    print(f"\nPOSITION PARTIALLY CLOSED: {current.filled_shares} shares remain open.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--outcome", required=True, choices=["YES", "NO"])
    parser.add_argument("--max-price", required=True, type=float, dest="max_price")
    parser.add_argument(
        "--amount", type=float, default=MAX_TEST_AMOUNT_USD,
        help=f"USD size, hard-capped at ${MAX_TEST_AMOUNT_USD:.2f} regardless of POLYMARKET_MAX_BET_USD "
             f"(default: ${MAX_TEST_AMOUNT_USD:.2f})",
    )
    parser.add_argument(
        "--confirm-live", action="store_true",
        help="Required to actually place the real entry (and, if approved, the real exit). Without it, "
             "this only runs the entry preflight and stops -- nothing is submitted.",
    )
    args = parser.parse_args()

    if args.amount > MAX_TEST_AMOUNT_USD:
        print(f"REFUSING: --amount ${args.amount:.2f} exceeds this script's own ${MAX_TEST_AMOUNT_USD:.2f} hard cap.")
        return 1
    if args.amount <= 0:
        print("REFUSING: --amount must be > 0.")
        return 1

    settings = PolymarketSettings.from_env()
    if not settings.is_us_venue:
        print("REFUSING: this script is Polymarket US only -- set POLYMARKET_VENUE=us.")
        return 1
    if not settings.is_live:
        print(f"REFUSING: this is a REAL-MONEY one-shot test -- POLYMARKET_TRADING_MODE must be 'live' "
              f"(currently {settings.trading_mode!r}). Use scripts/manual_polymarket_us_test.py for a paper "
              "dry run, or scripts/dynamic_exit_shadow.py for a read-only real-data rehearsal.")
        return 1
    if settings.live_auto_execute:
        print("REFUSING: POLYMARKET_LIVE_AUTO_EXECUTE is true -- this script requires it to stay false, so "
              "--confirm-live is this script's own single explicit approval, not an automatic one.")
        return 1

    client = get_polymarket_client(settings)
    call_log, restore_order_guard = install_order_guard()

    decision_logger = PolymarketDecisionLogger(Path(settings.decision_log_file))
    state_store = DailyPnlStateStore(Path(settings.daily_pnl_file))
    position_store = PolymarketPositionStore(Path(settings.positions_file))
    pending_store = PolymarketPendingOrderStore(Path(settings.pending_orders_file))
    emergency_stop_store = EmergencyStopStore(Path(settings.emergency_stop_file))

    print("=" * 78)
    print("ONE-SHOT REAL-MONEY ENTRY+EXIT SMOKE TEST -- POLYMARKET_TRADING_MODE=live (REAL MONEY)")
    print(f"amount=${min(args.amount, MAX_TEST_AMOUNT_USD):.2f}  outcome={args.outcome}  max_price=${args.max_price:.4f}")
    print(f"confirm_live={args.confirm_live}")
    print("=" * 78)

    try:
        return run_one_shot_test(
            settings=settings, client=client, outcome=args.outcome, amount=args.amount, max_price=args.max_price,
            confirm_live=args.confirm_live, decision_logger=decision_logger, state_store=state_store,
            position_store=position_store, pending_store=pending_store, emergency_stop_store=emergency_stop_store,
        )
    except OrderGuardViolation as exc:
        print(f"\nGUARD VIOLATION -- STOPPED BEFORE A SECOND REAL ORDER REACHED THE EXCHANGE: {exc}")
        decision_logger.log_decision(kind="one_shot_real_test_guard_violation", reason=str(exc))
        return 1
    finally:
        restore_order_guard()
        client.close()
        buys = call_log.count("BUY")
        sells = call_log.count("SELL")
        print(f"\nRUNTIME GUARD: {buys} entry (BUY) order(s), {sells} exit (SELL) order(s) submitted this run.")
        decision_logger.log_decision(
            kind="one_shot_real_test_order_guard_summary",
            reason=f"{buys} BUY order(s), {sells} SELL order(s) submitted",
            evidence={"buy_count": buys, "sell_count": sells},
        )


if __name__ == "__main__":
    raise SystemExit(main())
