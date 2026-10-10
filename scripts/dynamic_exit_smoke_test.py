"""READ-ONLY dynamic-exit integration smoke test.

Exercises, end-to-end, with REAL data and the EXISTING implementation
(nothing redesigned, nothing new added to the data layer):

  1. The real Coinbase BTC feed (CoinbaseBtcQuoteSource) -- explicitly
     verifies this machine can reach Coinbase's candles endpoint, then
     records the fetched candles into the real BTC price history store.
  2. Real Polymarket US BTC Up/Down 15m market discovery
     (PolymarketUSClient.find_active_btc_market).
  3. The real, live order book for that market (PolymarketUSClient.
     get_order_book) -- READ ONLY.
  4. BTC momentum evidence + the combined assessment
     (btc_intelligence.assess_btc_market), which includes the real
     feed freshness/staleness gate (btc_market_data.compute_feed_status).
  5. The existing, pure dynamic-exit decision function
     (exit_manager.evaluate_dynamic_exit) -- against a REAL open
     position if one exists on disk, otherwise a clearly-labeled
     SYNTHETIC one used only to exercise the evaluator.

Hard guarantees:
  - Refuses to run at all unless settings.dynamic_exit_enabled and
    settings.live_auto_execute are both False in the real environment.
  - Never calls submit_dynamic_exit/check_and_execute_dynamic_exits
    (the only functions in exit_manager.py that touch the network or
    the position ledger) -- only the pure evaluate_dynamic_exit().
  - Never calls PolymarketUSClient.place_order (the only order-writing
    method this client has -- confirmed by inspection: no cancel/
    modify/amend method exists anywhere in src/polymarket/). This is
    enforced at RUNTIME, not just by omission: place_order is
    monkeypatched to raise if invoked, and the script reports whether
    that guard ever fired.

Usage:
    python scripts/dynamic_exit_smoke_test.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket.btc_coinbase_source import CoinbaseBtcQuoteSource, CoinbaseBtcQuoteSourceError  # noqa: E402
from src.polymarket.btc_intelligence import DEFAULT_MIN_BARS_FOR_INDICATORS, assess_btc_market  # noqa: E402
from src.polymarket.btc_market_data import BtcPriceHistoryStore  # noqa: E402
from src.polymarket.client import NoActiveMarketError, PolymarketClientError  # noqa: E402
from src.polymarket.exit_manager import evaluate_dynamic_exit  # noqa: E402
from src.polymarket.models import BinaryMarket, OrderBookSnapshot  # noqa: E402
from src.polymarket.positions import OpenPosition, PolymarketPositionStore  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.us_client import PolymarketUSClient  # noqa: E402


def _synthetic_position(market: BinaryMarket, order_book: OrderBookSnapshot) -> OpenPosition:
    """A clearly-labeled, made-up position -- used only so
    evaluate_dynamic_exit() has something to evaluate when there is no
    real open position on disk. Never written anywhere, never used for
    any real trade. avg_fill_price is pinned to the current best bid
    (or ask, or a neutral 0.5 if neither exists) so the evaluator sees
    a plausible ~0% pnl baseline rather than an arbitrary number."""
    now = datetime.now(timezone.utc)
    reference_price = order_book.best_bid or order_book.best_ask or 0.5
    return OpenPosition(
        condition_id=market.condition_id,
        token_id=market.token_id_yes,
        outcome="YES",
        requested_size_usd=reference_price,
        filled_shares=1.0,
        avg_fill_price=reference_price,
        order_id="SYNTHETIC-SMOKE-TEST",
        client_order_id="SYNTHETIC-SMOKE-TEST",
        status="filled",
        opened_at=now,
        close_time=market.close_time,
    )


def main() -> int:
    settings = PolymarketSettings.from_env()

    if settings.dynamic_exit_enabled:
        print("ABORTING: POLYMARKET_DYNAMIC_EXIT_ENABLED is true in this environment -- this "
              "read-only smoke test requires it to stay false. Not proceeding.")
        return 1
    if settings.live_auto_execute:
        print("ABORTING: POLYMARKET_LIVE_AUTO_EXECUTE is true in this environment -- this "
              "read-only smoke test requires it to stay false. Not proceeding.")
        return 1
    print("settings.dynamic_exit_enabled = False (confirmed)")
    print("settings.live_auto_execute    = False (confirmed)")

    # --- Runtime guard: prove no order-writing method is ever called -------
    guard_state = {"place_order_called": False}
    original_place_order = PolymarketUSClient.place_order

    def _guarded_place_order(self, order):  # noqa: ANN001 - mirrors the real method's signature
        guard_state["place_order_called"] = True
        raise AssertionError(
            "PolymarketUSClient.place_order was called during a READ-ONLY smoke test -- "
            "this must never happen."
        )

    PolymarketUSClient.place_order = _guarded_place_order
    client = PolymarketUSClient(settings)

    try:
        # --- 1. Real Polymarket US BTC Up/Down 15m market discovery --------
        try:
            market = client.find_active_btc_market()
        except NoActiveMarketError as exc:
            print(f"No active BTC Up/Down market right now: {exc}")
            return 1
        except PolymarketClientError as exc:
            print(f"Could not discover the active BTC market: {exc}")
            return 1
        print(f"market.condition_id = {market.condition_id}")
        print(f"market.question = {market.question}")
        print(f"market.close_time = {market.close_time.isoformat()}")

        # --- 2. Real, live order book (READ ONLY) ---------------------------
        try:
            order_book = client.get_order_book(market.token_id_yes)
        except Exception as exc:  # noqa: BLE001 - any transport/parse failure -> report and stop
            print(f"Could not fetch the live order book: {exc}")
            return 1
        print(f"order_book.best_bid = {order_book.best_bid}")
        print(f"order_book.best_ask = {order_book.best_ask}")
        print(f"order_book.mid = {order_book.mid}")

        # --- 3. Real Coinbase BTC feed ---------------------------------------
        source = CoinbaseBtcQuoteSource()
        print(f"Fetching recent BTC-USD 1-minute candles from Coinbase ({source.name})...")
        try:
            candles = source.get_recent_candles(limit=DEFAULT_MIN_BARS_FOR_INDICATORS + 5)
        except CoinbaseBtcQuoteSourceError as exc:
            print(f"Could not reach/parse Coinbase's candles endpoint: {exc}")
            return 1
        print(f"Coinbase reachable -- fetched {len(candles)} real candle(s).")

        store = BtcPriceHistoryStore(Path(settings.btc_price_history_file))
        store.record_bars(candles)
        bars = store.get_bars()
        print(f"btc feed: {len(bars)} usable (fully closed) bar(s) in history")

        # --- 4. Real open position, or a clearly-labeled synthetic one ------
        position_store = PolymarketPositionStore(Path(settings.positions_file))
        real_positions = position_store.load()
        if real_positions:
            position = real_positions[0]
            print(f"position: REAL, loaded from {settings.positions_file} (condition_id={position.condition_id})")
        else:
            position = _synthetic_position(market, order_book)
            print("position: SYNTHETIC (no real open position on disk) -- for exercising the evaluator only")

        # --- 5. BTC momentum evidence + combined assessment, including the --
        #        real feed freshness/staleness gate --------------------------
        recent_mids = [order_book.mid] if order_book.mid is not None else []
        assessment = assess_btc_market(
            bars, order_book, recent_mids, outcome=position.outcome,
            max_bar_age_seconds=settings.btc_max_bar_age_seconds, feed_source=source.name,
        )
        print(f"feed_status = {assessment.feed_status.status}")
        print(f"feed_status.bar_age_seconds = {assessment.feed_status.bar_age_seconds}")
        print(f"MomentumState = {assessment.state.value}")
        print(f"evidence_score = {assessment.evidence_score}")
        print(f"signals = {[s.source for s in assessment.signals]}")

        # --- 6. The existing, pure dynamic-exit decision function -----------
        decision = evaluate_dynamic_exit(
            position, order_book, assessment, profit_target_pct=settings.profit_target_pct,
        )
        print(f"dynamic_exit.eligible = {decision.eligible}")
        print(f"dynamic_exit.reason = {decision.reason}")
        print(f"dynamic_exit.target_price = {decision.target_price}")
        print(f"dynamic_exit.best_bid = {decision.best_bid}")
        print(f"dynamic_exit.gross_pnl_pct = {decision.gross_pnl_pct}")

        return 0
    finally:
        PolymarketUSClient.place_order = original_place_order
        client.close()
        print(
            f"order_api_called = {guard_state['place_order_called']} "
            "(PolymarketUSClient.place_order -- the only order-writing method on this "
            "client -- verified via a runtime guard, not just by inspection)"
        )


if __name__ == "__main__":
    raise SystemExit(main())
