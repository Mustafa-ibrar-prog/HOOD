#!/usr/bin/env python3
"""Reject ONE already-proposed Polymarket pending order without ever
calling place_market_order. See src/polymarket/gateway.py's
LivePolymarketGateway.reject_pending().

Usage:
    python3 scripts/reject_polymarket_order.py \\
        --pending-order-id <id> \\
        --rejected-by "user:jane" \\
        --reason "spread too wide now"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket.gateway import LivePolymarketGateway  # noqa: E402
from src.polymarket.logger import PolymarketDecisionLogger  # noqa: E402
from src.polymarket.pending import PolymarketPendingOrderStore  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pending-order-id", required=True)
    parser.add_argument("--rejected-by", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()

    settings = PolymarketSettings.from_env()
    decision_logger = PolymarketDecisionLogger(Path(settings.decision_log_file))
    pending_store = PolymarketPendingOrderStore(Path(settings.pending_orders_file))
    gateway = LivePolymarketGateway(settings, decision_logger, pending_store)

    rejected = gateway.reject_pending(args.pending_order_id, reason=args.reason, rejected_by=args.rejected_by)
    print(f"status={rejected.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
