#!/usr/bin/env python3
"""Human-operated control for the Polymarket emergency stop
(src/execution/emergency_stop.py) — status / activate / clear.

This is the ONLY way to clear an active stop. EmergencyStopStore.clear()
itself requires a real human identity in --authorized-by (it rejects an
empty string or one starting with "system:" — see emergency_stop.py's
module docstring) — there is no code path anywhere in this codebase that
clears a stop automatically, and this script does not add one: it is a
thin, interactive wrapper a human runs themselves. Activating a stop
requires no authorization by design (a kill switch must be trivially
easy to trip); clearing one always does.

Usage:
    python3 scripts/emergency_stop_control.py status
    python3 scripts/emergency_stop_control.py activate --reason "pausing for the night"
    python3 scripts/emergency_stop_control.py clear --authorized-by "Mustafa" --reason "cleared for the first $5 live test"

Uses POLYMARKET_EMERGENCY_STOP_FILE from the current environment/.env
(PolymarketSettings.from_env()) — the SAME file run_polymarket_bot.py /
manual_polymarket_us_test.py / confirm_polymarket_order.py check, so
clearing it here is immediately visible to all of them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.execution.emergency_stop import EmergencyStopStore  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status", help="Print the current emergency-stop state. Read-only.")
    p_activate = sub.add_parser("activate", help="Trip the stop. No authorization required, by design.")
    p_activate.add_argument("--reason", required=True)
    p_clear = sub.add_parser("clear", help="Clear the stop. Requires a real human identity.")
    p_clear.add_argument("--authorized-by", required=True, metavar="NAME")
    p_clear.add_argument("--reason", required=True)
    args = parser.parse_args()

    settings = PolymarketSettings.from_env()
    store = EmergencyStopStore(Path(settings.emergency_stop_file))

    if args.action == "status":
        state = store.current()
        print(f"EMERGENCY STOP: {'ACTIVE' if state.active else 'CLEARED'}")
        print(f"  reason:  {state.reason}")
        print(f"  set_at:  {state.set_at.isoformat()}")
        print(f"  set_by:  {state.set_by}")
        return 0

    if args.action == "activate":
        state = store.activate(reason=args.reason, set_by="user:manual")
        print(f"EMERGENCY STOP ACTIVATED: {state.reason}")
        return 0

    try:
        state = store.clear(authorized_by=args.authorized_by, reason=args.reason)
    except ValueError as exc:
        print(f"REFUSING: {exc}")
        return 1
    print(f"EMERGENCY STOP CLEARED by {state.set_by!r}: {state.reason}")
    print("Remember to re-activate it when you're done testing:")
    print('  python3 scripts/emergency_stop_control.py activate --reason "done testing"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
