"""SHADOW dynamic-exit evaluation.

Logs what evaluate_dynamic_exit() WOULD decide for every REAL open
Polymarket US BTC position, using real market data (real order book,
real Coinbase BTC feed) -- without ever submitting, modifying, or
cancelling anything. Meant to be run repeatedly (by hand, via a
scheduled task, or alongside the live bot) to build an observable
track record BEFORE POLYMARKET_DYNAMIC_EXIT_ENABLED is ever flipped to
true in production.

Does NOT:
  - place, modify, or cancel any order. No cancel/modify method exists
    anywhere in src/polymarket/ (confirmed by inspection); place_order
    is the only order-writing method on PolymarketUSClient, and is
    monkeypatched here to raise if ever called -- verified at runtime,
    not just by omission.
  - call submit_dynamic_exit / check_and_execute_dynamic_exits /
    reconcile_exit_fill -- the only functions in exit_manager.py that
    mutate the position/pending-order store or touch the network to
    submit. Only the pure, side-effect-free evaluate_dynamic_exit() is
    called.
  - fabricate a position. If there is no real open position, this
    reports that and exits -- it never substitutes a synthetic one
    (unlike scripts/dynamic_exit_smoke_test.py, whose synthetic
    fallback exists only to exercise the evaluator with zero real
    positions available).
  - touch risk.py's entry checks, engine.settle_resolved_positions, or
    any other existing gate -- this script only reads positions/order
    books/BTC bars and logs; it is additive, not a replacement for
    anything.

Refuses to run at all unless settings.dynamic_exit_enabled and
settings.live_auto_execute both read False from the real environment.

Logs every decision to the SAME decision log the live bot already uses
(settings.decision_log_file), via the SAME PolymarketDecisionLogger:
  - kind="btc_feed_status" -- the exact same shape
    check_and_execute_dynamic_exits() itself logs every cycle for
    every open position (BTC_FEED_SOURCE/BTC_LAST_BAR_TIME/
    BTC_BAR_AGE_SECONDS/BTC_FEED_STATUS/BTC_EVIDENCE_STATE), reused
    verbatim so a shadow run's log entries are directly comparable to
    what production logging will look like once enabled.
  - kind="dynamic_exit_shadow" -- the would-be HOLD/EXIT verdict,
    reason, target price, best bid, gross pnl, and fired signals.
    Unambiguously tagged "shadow" so these entries can never be
    mistaken for a real decision.

Usage:
    python scripts/dynamic_exit_shadow.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket.btc_coinbase_source import CoinbaseBtcQuoteSource, CoinbaseBtcQuoteSourceError  # noqa: E402
from src.polymarket.btc_intelligence import DEFAULT_MIN_BARS_FOR_INDICATORS, assess_btc_market  # noqa: E402
from src.polymarket.btc_market_data import BtcPriceHistoryStore  # noqa: E402
from src.polymarket.exit_manager import evaluate_dynamic_exit  # noqa: E402
from src.polymarket.logger import PolymarketDecisionLogger  # noqa: E402
from src.polymarket.positions import PolymarketPositionStore  # noqa: E402
from src.polymarket.settings import PolymarketSettings  # noqa: E402
from src.polymarket.us_client import PolymarketUSClient  # noqa: E402


def main() -> int:
    settings = PolymarketSettings.from_env()

    if settings.dynamic_exit_enabled:
        print("ABORTING: POLYMARKET_DYNAMIC_EXIT_ENABLED is true in this environment -- shadow "
              "mode requires it to stay false (that flag gates REAL submission). Not proceeding.")
        return 1
    if settings.live_auto_execute:
        print("ABORTING: POLYMARKET_LIVE_AUTO_EXECUTE is true in this environment -- shadow "
              "mode requires it to stay false. Not proceeding.")
        return 1
    print("settings.dynamic_exit_enabled = False (confirmed)")
    print("settings.live_auto_execute    = False (confirmed)")

    # --- Runtime guard: prove no order-writing method is ever called -------
    guard_state = {"place_order_called": False}
    original_place_order = PolymarketUSClient.place_order

    def _guarded_place_order(self, order):  # noqa: ANN001 - mirrors the real method's signature
        guard_state["place_order_called"] = True
        raise AssertionError(
            "PolymarketUSClient.place_order was called during a SHADOW (read-only) "
            "evaluation -- this must never happen."
        )

    PolymarketUSClient.place_order = _guarded_place_order
    client = PolymarketUSClient(settings)
    decision_logger = PolymarketDecisionLogger(Path(settings.decision_log_file))

    try:
        position_store = PolymarketPositionStore(Path(settings.positions_file))
        positions = position_store.load()
        if not positions:
            print(f"No real open position in {settings.positions_file} -- nothing to shadow-evaluate.")
            return 0
        print(f"{len(positions)} real open position(s) found -- shadow-evaluating each one.")

        # --- Real Coinbase BTC feed (shared across all positions this run) --
        source = CoinbaseBtcQuoteSource()
        print(f"Fetching recent BTC-USD 1-minute candles from Coinbase ({source.name})...")
        try:
            candles = source.get_recent_candles(limit=DEFAULT_MIN_BARS_FOR_INDICATORS + 5)
        except CoinbaseBtcQuoteSourceError as exc:
            print(f"Could not reach/parse Coinbase's candles endpoint: {exc}")
            return 1
        print(f"Coinbase reachable -- fetched {len(candles)} real candle(s).")

        btc_store = BtcPriceHistoryStore(Path(settings.btc_price_history_file))
        btc_store.record_bars(candles)
        bars = btc_store.get_bars(interval_seconds=settings.btc_bar_interval_seconds)
        print(f"btc feed: {len(bars)} usable (fully closed) bar(s) in history")

        exit_code = 0
        for position in positions:
            print(f"\n--- position condition_id={position.condition_id} outcome={position.outcome} ---")

            try:
                order_book = client.get_order_book(position.token_id)
            except Exception as exc:  # noqa: BLE001 - a book-fetch failure must never be treated as "no signal"
                decision_logger.log_decision(
                    kind="exit_check_failed",
                    reason=f"Could not fetch order book for {position.condition_id}: {exc}",
                    evidence={"position": position.to_dict()},
                )
                print(f"Could not fetch the live order book: {exc}")
                exit_code = 1
                continue

            recent_mids = [order_book.mid] if order_book.mid is not None else []
            assessment = assess_btc_market(
                bars, order_book, recent_mids, outcome=position.outcome,
                max_bar_age_seconds=settings.btc_max_bar_age_seconds, feed_source=source.name,
            )
            feed_status = assessment.feed_status

            # Same shape exit_manager.check_and_execute_dynamic_exits() itself
            # logs every cycle for every open position -- reused verbatim.
            decision_logger.log_decision(
                kind="btc_feed_status",
                reason=(
                    f"BTC_FEED_SOURCE={feed_status.source} BTC_LAST_BAR_TIME={feed_status.last_bar_time} "
                    f"BTC_BAR_AGE_SECONDS={feed_status.bar_age_seconds} BTC_FEED_STATUS={feed_status.status} "
                    f"BTC_EVIDENCE_STATE={assessment.state.value}"
                ),
                evidence={
                    "condition_id": position.condition_id,
                    "BTC_FEED_SOURCE": feed_status.source,
                    "BTC_LAST_BAR_TIME": feed_status.last_bar_time.isoformat() if feed_status.last_bar_time else None,
                    "BTC_BAR_AGE_SECONDS": feed_status.bar_age_seconds,
                    "BTC_FEED_STATUS": feed_status.status,
                    "BTC_EVIDENCE_STATE": assessment.state.value,
                },
            )

            decision = evaluate_dynamic_exit(
                position, order_book, assessment, profit_target_pct=settings.profit_target_pct,
            )
            would_decide = "EXIT" if decision.eligible else "HOLD"
            fired_signals = [s.source for s in assessment.signals]

            decision_logger.log_decision(
                kind="dynamic_exit_shadow",
                reason=decision.reason,
                evidence={
                    "condition_id": position.condition_id,
                    "would_decide": would_decide,
                    "reason": decision.reason,
                    "BTC_EVIDENCE_STATE": assessment.state.value,
                    "BTC_FEED_STATUS": feed_status.status,
                    "BTC_BAR_AGE_SECONDS": feed_status.bar_age_seconds,
                    "signals": fired_signals,
                    "target_price": decision.target_price,
                    "best_bid": decision.best_bid,
                    "gross_pnl_pct": decision.gross_pnl_pct,
                },
            )

            print(f"MomentumState = {assessment.state.value}")
            print(f"feed_status = {feed_status.status}  (bar_age_seconds={feed_status.bar_age_seconds})")
            print(f"signals = {fired_signals}")
            print(f"SHADOW decision = {would_decide}")
            print(f"reason = {decision.reason}")

        return exit_code
    finally:
        PolymarketUSClient.place_order = original_place_order
        client.close()
        print(
            f"\norder_api_called = {guard_state['place_order_called']} "
            "(PolymarketUSClient.place_order -- the only order-writing method on this "
            "client -- verified via a runtime guard, not just by inspection)"
        )


if __name__ == "__main__":
    raise SystemExit(main())
