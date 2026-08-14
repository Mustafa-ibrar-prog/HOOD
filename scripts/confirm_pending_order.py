#!/usr/bin/env python3
"""Place a real live order for ONE already-proposed pending order.

This is the executable half of the "LIVE-ORDER CONFIRMATION BRIDGE"
documented in src/live_bridge.py's module docstring. It is the only script
in this codebase that can result in a real place_option_order call, and
even this script never calls that tool itself — it consumes a response the
agent already obtained from a REAL call it made, and does the bookkeeping
(mark the pending order "placed", update LiveBotPositionsStore, write the
audit log) against what actually happened.

Usage (see src/live_bridge.py's docstring for the full step-by-step flow):
    python3 scripts/confirm_pending_order.py \\
        --pending-order-id <id> \\
        --approved-by "user:jane" \\
        --place-response-file <path to the REAL place_option_order response>

Requires TRADING_MODE=live and LIVE_TRADING_CONFIRMED=true in the
environment/.env — refuses otherwise, the same as LiveExecutionGateway
itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.settings import Settings  # noqa: E402
from src.execution.gateway import LiveExecutionGateway  # noqa: E402
from src.execution.live_positions import LiveBotPositionsStore  # noqa: E402
from src.execution.pending import PendingOrderStore  # noqa: E402
from src.live_bridge import StaticLiveOrderPlacer  # noqa: E402
from src.logging.decision_logger import DecisionLogger  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pending-order-id", required=True)
    parser.add_argument("--approved-by", required=True, help='e.g. "user:jane" — never a generic placeholder')
    parser.add_argument(
        "--place-response-file",
        required=True,
        type=Path,
        help="JSON file holding the REAL response from a REAL place_option_order call the agent already made",
    )
    args = parser.parse_args()

    settings = Settings.from_env()
    decision_logger = DecisionLogger(path=settings.decision_log_file, app_log_file=settings.app_log_file)
    pending_store = PendingOrderStore(Path(settings.pending_orders_file))
    bot_positions_store = LiveBotPositionsStore(Path(settings.live_bot_positions_file))
    gateway = LiveExecutionGateway(settings, decision_logger, pending_store, bot_positions_store)

    placer = StaticLiveOrderPlacer()
    placer.record_place_option_order(json.loads(args.place_response_file.read_text()))

    result = gateway.confirm_and_place(args.pending_order_id, placer, approved_by=args.approved_by)
    print(f"status={result.status}")
    if result.live_fill is not None:
        print(f"order_id={result.live_fill.order_id} state={result.live_fill.state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
