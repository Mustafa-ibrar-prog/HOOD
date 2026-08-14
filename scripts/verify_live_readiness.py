#!/usr/bin/env python3
"""Run the account preflight check (src/execution/preflight.py) against
REAL, already-fetched get_accounts / get_portfolio responses.

Must be run — and pass — before the first live order is ever proposed, per
the project's own safety requirements. Never fetches anything itself; the
agent must call get_accounts and get_portfolio(account_number) for real
first and save each response as JSON.

Usage:
    python3 scripts/verify_live_readiness.py \\
        --accounts-file <path to a REAL get_accounts response> \\
        --portfolio-file <path to a REAL get_portfolio response>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.settings import Settings  # noqa: E402
from src.execution.preflight import verify_account_preflight  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--accounts-file", required=True, type=Path)
    parser.add_argument("--portfolio-file", required=True, type=Path)
    args = parser.parse_args()

    settings = Settings.from_env()
    if not settings.account_number:
        print("ROBINHOOD_ACCOUNT_NUMBER is not configured", file=sys.stderr)
        return 2

    result = verify_account_preflight(
        accounts_response=json.loads(args.accounts_file.read_text()),
        portfolio_response=json.loads(args.portfolio_file.read_text()),
        account_number=settings.account_number,
        max_position_size_usd=settings.max_position_size_usd,
    )

    print(f"account={result.account_number} ok={result.ok}")
    for check in result.checks:
        print(f"  PASS: {check}")
    for failure in result.failures:
        print(f"  FAIL: {failure}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
