#!/usr/bin/env python3
"""Place a real live order for ONE already-proposed Polymarket pending
order, then immediately reconcile it.

Unlike scripts/confirm_pending_order.py (Robinhood's equivalent), there
is no agent-mediated MCP call to bridge: PolymarketClient makes the real
HTTP call itself, so this script passes `client` directly as the
order_placer. The two-step nature of Task 5's fix is still visible
here on purpose — confirm_and_place() only SUBMITS (see gateway.py's
docstring); this script then calls reconciliation.reconcile_order() in
the same process, right after, so a human running this script sees the
real outcome (filled / partially filled / rejected / cancelled/
expired — never an assumed fill) instead of just "submitted." If this
script is interrupted before the reconcile call, or you lose the
process entirely, the next scripts/run_polymarket_bot.py cycle's own
reconcile_pending_orders() sweep will still pick it up — reconciliation
is restart-safe and idempotent by construction (see reconciliation.py).

Requires POLYMARKET_TRADING_MODE=live and
POLYMARKET_LIVE_TRADING_CONFIRMED=true in the environment/.env —
refuses otherwise, the same as LivePolymarketGateway itself.

Usage:
    python3 scripts/confirm_polymarket_order.py \\
        --pending-order-id <id> \\
        --approved-by "user:jane"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.execution.emergency_stop import EmergencyStopStore  # noqa: E402
from src.polymarket import reconciliation  # noqa: E402
from src.polymarket.client import get_polymarket_client  # noqa: E402
from src.polymarket.gateway import LivePolymarketGateway  # noqa: E402
from src.polymarket.logger import PolymarketDecisionLogger  # noqa: E402
from src.polymarket.pending import PolymarketPendingOrderStore  # noqa: E402
from src.polymarket.positions import PolymarketPositionStore  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.state import DailyPnlStateStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pending-order-id", required=True)
    parser.add_argument("--approved-by", required=True, help='e.g. "user:jane" — never a generic placeholder')
    args = parser.parse_args()

    settings = PolymarketSettings.from_env()
    client = get_polymarket_client(settings)
    decision_logger = PolymarketDecisionLogger(Path(settings.decision_log_file))
    pending_store = PolymarketPendingOrderStore(Path(settings.pending_orders_file))
    position_store = PolymarketPositionStore(Path(settings.positions_file))
    state_store = DailyPnlStateStore(Path(settings.daily_pnl_file))
    emergency_stop_store = EmergencyStopStore(Path(settings.emergency_stop_file))
    gateway = LivePolymarketGateway(
        settings, decision_logger, pending_store, order_placer=client, emergency_stop_store=emergency_stop_store,
    )

    result = gateway.confirm_and_place(args.pending_order_id, client, approved_by=args.approved_by)
    print(f"submission status={result.status}")
    if result.submission is not None:
        print(f"exchange_order_id={result.submission.exchange_order_id} raw_status={result.submission.raw_status}")
    if result.status != "submitted":
        return 0  # rejected/failed — gateway.py already marked it fill_reconciled=True; nothing more to do

    pending = pending_store.get(args.pending_order_id)
    assert pending is not None  # confirm_and_place() above would have raised if this id never existed
    fill = reconciliation.reconcile_order(
        pending, client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger,
    )
    if fill is None:
        print("reconciliation: nothing to reconcile (already reconciled, or no exchange_order_id)")
    else:
        print(f"fill status={fill.status} filled_shares={fill.filled_shares} avg_fill_price={fill.avg_fill_price}")
        print("POSITION OPENED" if fill.is_fill else "no position opened")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
