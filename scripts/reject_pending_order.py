#!/usr/bin/env python3
"""Reject ONE already-proposed pending live order without ever calling
place_option_order. See src/execution/gateway.py's LiveExecutionGateway.
reject_pending().

Usage:
    python3 scripts/reject_pending_order.py \\
        --pending-order-id <id> \\
        --rejected-by "user:jane" \\
        --reason "spread too wide now"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.settings import Settings  # noqa: E402
from src.execution.gateway import LiveExecutionGateway  # noqa: E402
from src.execution.pending import PendingOrderStore  # noqa: E402
from src.logging.decision_logger import DecisionLogger  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pending-order-id", required=True)
    parser.add_argument("--rejected-by", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()

    settings = Settings.from_env()
    decision_logger = DecisionLogger(path=settings.decision_log_file, app_log_file=settings.app_log_file)
    pending_store = PendingOrderStore(Path(settings.pending_orders_file))
    gateway = LiveExecutionGateway(settings, decision_logger, pending_store)

    rejected = gateway.reject_pending(args.pending_order_id, reason=args.reason, rejected_by=args.rejected_by)
    print(f"status={rejected.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
