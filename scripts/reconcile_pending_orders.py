#!/usr/bin/env python3
"""Read-safe reconciliation ONLY — sweeps every pending order that has
an exchange_order_id but isn't yet fill_reconciled, re-checking each
one's authoritative status via reconciliation.reconcile_pending_orders().

Unlike scripts/run_polymarket_bot.py, this does NOT run a trading
cycle: no market discovery, no strategy evaluation, no risk check for a
NEW trade, and no order is ever submitted here — gateway.submit_order()
is never called. The only side effects are: updating pending_orders.json
(marking a now-resolved order's fill_reconciled flag) and
open_positions.json (opening a position if, and only if, the
authoritative lookup shows a real fill that hasn't been recorded yet).

This exists for exactly the situation where an order's fill status came
back "unknown" (a transient 404 right after submission, now confirmed
resolved on the exchange) and you want your LOCAL ledger to catch up
with reality WITHOUT running anything that could place a new order.

Usage:
    python3 scripts/reconcile_pending_orders.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket import reconciliation  # noqa: E402
from src.polymarket.client import get_polymarket_client  # noqa: E402
from src.polymarket.logger import PolymarketDecisionLogger  # noqa: E402
from src.polymarket.pending import PolymarketPendingOrderStore  # noqa: E402
from src.polymarket.positions import PolymarketPositionStore  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.state import DailyPnlStateStore  # noqa: E402


def main() -> int:
    settings = PolymarketSettings.from_env()
    client = get_polymarket_client(settings)
    decision_logger = PolymarketDecisionLogger(Path(settings.decision_log_file))
    state_store = DailyPnlStateStore(Path(settings.daily_pnl_file))
    position_store = PolymarketPositionStore(Path(settings.positions_file))
    pending_store = PolymarketPendingOrderStore(Path(settings.pending_orders_file))

    unreconciled_before = [p for p in pending_store.load() if not p.fill_reconciled and p.exchange_order_id is not None]
    print(f"POLYMARKET_VENUE={settings.venue} ({type(client).__name__})")
    print(f"Unreconciled pending orders found: {len(unreconciled_before)}")
    for pending in unreconciled_before:
        print(f"  pending_order_id={pending.id} exchange_order_id={pending.exchange_order_id} "
              f"market={pending.order.condition_id} outcome={pending.order.outcome}")

    if not unreconciled_before:
        print("Nothing to reconcile.")
        return 0

    count = reconciliation.reconcile_pending_orders(
        client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    print(f"\nAttempted {count} reconciliation(s).")

    for pending in unreconciled_before:
        updated = pending_store.get(pending.id)
        status = "RECONCILED" if updated.fill_reconciled else "STILL UNKNOWN -- will be retried on a later sweep"
        print(f"  pending_order_id={pending.id}: {status}")

    positions = position_store.load()
    print(f"\nOpen positions now: {len(positions)}")
    for position in positions:
        print(f"  {position.outcome} on {position.condition_id}: {position.filled_shares} shares "
              f"@ ${position.avg_fill_price} (status={position.status})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
