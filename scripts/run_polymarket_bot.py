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
from src.polymarket.btc_coinbase_source import CoinbaseBtcQuoteSource  # noqa: E402
from src.polymarket.btc_intelligence import DEFAULT_MIN_BARS_FOR_INDICATORS  # noqa: E402
from src.polymarket.btc_market_data import BtcFeedRefresher, BtcPriceHistoryStore, bootstrap_btc_price_history  # noqa: E402
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
    # NOTE: as of this round, the production strategy is fully
    # autonomous and deliberately simple: entry is evaluated across
    # the full 15-minute market, at any point while it's open, with NO
    # probability threshold -- direction is whichever side the market
    # currently favors (simple_entry_signal.py). Every open position is
    # then actively managed by a configurable +5% take-profit AND a
    # configurable -20% stop-loss (take_profit.py; both settings, see
    # settings.py's simple_take_profit_pct/simple_stop_loss_pct) --
    # engine.run_cycle() no longer calls btc_entry_signal.py or
    # exit_manager.check_and_execute_dynamic_exits() at all (see
    # engine.py's own module docstring). The BTC bootstrap/
    # feed-refresh plumbing below is kept running harmlessly (feeding
    # btc_price_store, never read by the live decision) so Coinbase
    # BTC intelligence stays warm and ready to re-enable later without
    # any further setup. CoinbaseBtcQuoteSource is a DIRECT, unattended
    # HTTPS source (no agent/MCP) -- construction alone makes no
    # network call; bootstrap/refresh below are what actually call it,
    # and both fail safe (never raise, never crash this bot) on any
    # provider outage -- see btc_market_data.py's module docstring.
    btc_price_store = BtcPriceHistoryStore(Path(settings.btc_price_history_file))
    btc_source = CoinbaseBtcQuoteSource()
    btc_bootstrapped = bootstrap_btc_price_history(
        btc_price_store, btc_source, min_bars=DEFAULT_MIN_BARS_FOR_INDICATORS,
    )
    print(f"BTC price history bootstrap: {btc_bootstrapped} candle(s) recorded from {btc_source.name}")
    btc_refresher = BtcFeedRefresher(btc_price_store, btc_source)

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
            # Isolated from the Polymarket cycle below on purpose (see
            # requirement that a BTC-provider outage never affects
            # normal Polymarket functionality): maybe_refresh() never
            # raises on its own (every failure mode is captured on the
            # returned BtcFeedRefreshResult instead -- see
            # btc_market_data.py), but this belt-and-suspenders guard
            # also protects against something unexpected escaping it.
            # Called unconditionally, every loop iteration, BEFORE
            # run_cycle() -- this is what makes maybe_refresh()'s own
            # once-a-new-minute cadence check actually see every
            # iteration, not just some of them.
            try:
                refresh_result = btc_refresher.maybe_refresh()
            except Exception as exc:  # noqa: BLE001 - a BTC feed problem must never stop Polymarket trading
                print(f"BTC feed refresh failed (ignored, Polymarket trading continues): {exc}")
            else:
                # Logged persistently (not just printed) ONLY for an
                # actual attempt -- the routine same-minute skip is not
                # logged, so this never spams the decision log on a
                # fast poll_interval_seconds. Every field the operator
                # needs to diagnose a stuck feed live: request time,
                # newest candle timestamp, candle age, a fresh/stale
                # label (computed here for display only, from
                # settings.btc_max_bar_age_seconds -- the SAME
                # threshold compute_feed_status/assess_btc_market
                # already enforce; never a second, independent gate),
                # and the raw provider error when there was one.
                if refresh_result.attempted:
                    is_fresh = (
                        refresh_result.candle_age_seconds is not None
                        and refresh_result.candle_age_seconds <= settings.btc_max_bar_age_seconds
                    )
                    feed_label = "FRESH" if is_fresh else ("STALE" if refresh_result.candle_age_seconds is not None else "UNAVAILABLE")
                    newest_before = (
                        refresh_result.newest_persisted_before.isoformat() if refresh_result.newest_persisted_before else None
                    )
                    newest_after = (
                        refresh_result.newest_persisted_after.isoformat() if refresh_result.newest_persisted_after else None
                    )
                    reason = (
                        f"BTC feed refresh at {refresh_result.now.isoformat()}: "
                        + (f"ERROR: {refresh_result.error}" if refresh_result.error else
                           f"recorded={refresh_result.candles_recorded} candle(s), newest="
                           f"{refresh_result.newest_candle_time.isoformat() if refresh_result.newest_candle_time else None}, "
                           f"age={refresh_result.candle_age_seconds}s, {feed_label}, "
                           f"newest_persisted_before={newest_before}, newest_persisted_after={newest_after}")
                    )
                    # log_decision() already prints this to the console
                    # itself (decision_logger defaults to
                    # also_console=True) -- no separate print needed here.
                    decision_logger.log_decision(
                        kind="btc_feed_refresh",
                        reason=reason,
                        evidence={
                            "request_time": refresh_result.now.isoformat(),
                            "newest_candle_time": (
                                refresh_result.newest_candle_time.isoformat() if refresh_result.newest_candle_time else None
                            ),
                            "candle_age_seconds": refresh_result.candle_age_seconds,
                            "feed_label": feed_label,
                            "candles_recorded": refresh_result.candles_recorded,
                            "newest_persisted_before": newest_before,
                            "newest_persisted_after": newest_after,
                            "provider_error": refresh_result.error,
                            "provider": btc_source.name,
                        },
                    )

            report = run_cycle(
                settings=settings, client=client, strategy=strategy, risk_manager=risk_manager,
                gateway=gateway, decision_logger=decision_logger, state_store=state_store,
                position_store=position_store, pending_store=pending_store, history=history,
                btc_price_store=btc_price_store, btc_feed_source=btc_source.name,
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
