#!/usr/bin/env python3
"""Run the Polymarket BTC 15-minute bot — an UNATTENDED loop, unlike
scripts/run_paper_scheduler.py: client.py/us_client.py call the real
Polymarket API directly, so no agent needs to relay data each cycle.
POLYMARKET_VENUE selects which venue/client (see settings.py's module
docstring) — get_polymarket_client() below returns whichever one
matches, and nothing else in this script needs to know which. See
src/polymarket/__init__.py before running this against real funds —
none of the live-API code paths have been verified against the real
API from the environment this was written in.

TRADING_MODE defaults to paper (POLYMARKET_TRADING_MODE, see
.env.polymarket.example) — this script never places a real order
unless you've explicitly set POLYMARKET_TRADING_MODE=live AND
POLYMARKET_LIVE_TRADING_CONFIRMED=true, and even then, every order
stops at pending-approval unless POLYMARKET_LIVE_AUTO_EXECUTE=true too
(see src/polymarket/gateway.py's module docstring for the full guard
list — emergency stop, max bet size, daily loss cap, cooldown, spread,
staleness, entry cutoff).

Usage:
    python3 scripts/run_polymarket_bot.py [--once] [--max-cycles N]

--once runs a single cycle and exits (useful for manually verifying
behavior before leaving it running unattended). Ctrl-C / SIGTERM stops
the loop at any time; no partial order state is left behind (every
order either reached pending_approval, placed, or failed — never silently lost).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.execution.emergency_stop import EmergencyStopStore  # noqa: E402
from src.polymarket.btc_market_data import BtcPriceHistoryStore  # noqa: E402
from src.polymarket.client import get_polymarket_client  # noqa: E402
from src.polymarket.engine import MarketHistory, run_cycle  # noqa: E402
from src.polymarket.gateway import get_execution_gateway  # noqa: E402
from src.polymarket.logger import PolymarketDecisionLogger  # noqa: E402
from src.polymarket.pending import PolymarketPendingOrderStore  # noqa: E402
from src.polymarket.positions import PolymarketPositionStore  # noqa: E402
from src.polymarket.risk import PolymarketRiskManager  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.state import DailyPnlStateStore  # noqa: E402
from src.polymarket.strategy import BtcMomentumStrategy  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument("--max-cycles", type=int, default=None, help="Stop after N cycles (default: run forever)")
    args = parser.parse_args()

    settings = PolymarketSettings.from_env()
    client = get_polymarket_client(settings)
    strategy = BtcMomentumStrategy()
    risk_manager = PolymarketRiskManager(settings)
    decision_logger = PolymarketDecisionLogger(Path(settings.decision_log_file))
    state_store = DailyPnlStateStore(Path(settings.daily_pnl_file))
    position_store = PolymarketPositionStore(Path(settings.positions_file))
    # Always constructed, even in paper mode: run_cycle()'s restart-safety
    # sweep (reconcile_pending_orders) needs a store to sweep, even though
    # paper mode itself never creates a pending order in it (see
    # gateway.py's PaperPolymarketGateway — it never calls place_order).
    pending_store = PolymarketPendingOrderStore(Path(settings.pending_orders_file))
    history = MarketHistory()
    # Dynamic-exit BTC evidence (see exit_manager.py/btc_market_data.py):
    # stays empty (INSUFFICIENT_DATA -> HOLD) unless something -- an
    # agent calling scripts/feed_btc_quote.py after reading
    # get_crypto_quotes -- actually feeds it. A no-op dependency to
    # construct either way: check_and_execute_dynamic_exits() itself is
    # a complete no-op while settings.dynamic_exit_enabled is False.
    btc_price_store = BtcPriceHistoryStore(Path(settings.btc_price_history_file))

    order_placer = client if settings.is_live else None
    emergency_stop_store = EmergencyStopStore(Path(settings.emergency_stop_file))
    gateway = get_execution_gateway(
        settings, decision_logger, pending_store=pending_store if settings.is_live else None,
        order_placer=order_placer, emergency_stop_store=emergency_stop_store,
    )

    print(f"POLYMARKET_VENUE={settings.venue} ({type(client).__name__})")
    print(f"POLYMARKET_TRADING_MODE={settings.trading_mode}" + (" (REAL MONEY)" if settings.is_live else " (paper — no real funds at risk)"))
    print(f"asset={settings.asset} market_duration_minutes={settings.market_duration_minutes}")
    print(f"max_bet_usd={settings.max_bet_usd} max_daily_loss_usd={settings.max_daily_loss_usd}")
    if settings.is_live:
        print(f"live_auto_execute={settings.live_auto_execute} emergency_stop_active={emergency_stop_store.is_stopped()}")
        if emergency_stop_store.is_stopped():
            print("NOTE: emergency stop is currently ACTIVE (default). No live order will place until "
                  "someone clears it — see src/execution/emergency_stop.py's EmergencyStopStore.clear().")

    cycles = 0
    try:
        while True:
            report = run_cycle(
                settings=settings, client=client, strategy=strategy, risk_manager=risk_manager,
                gateway=gateway, decision_logger=decision_logger, state_store=state_store,
                position_store=position_store, pending_store=pending_store, history=history,
                btc_price_store=btc_price_store,
            )
            cycles += 1
            print(
                f"cycle {cycles}: ran={report.ran} market={report.market_question!r} entered={report.entered} "
                f"settled={report.settled_count} reconciled={report.reconciled_count} exits_submitted={report.exits_submitted}"
            )
            if args.once or (args.max_cycles is not None and cycles >= args.max_cycles):
                break
            time.sleep(settings.poll_interval_seconds)
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
