"""Tests for the automatic 20%-profit-target exit system
(exit_manager.py). Mirrors test_polymarket_reconciliation.py's style —
a fake object shaped like the real client's surface (get_order_book,
get_fill_status, place_order), never the real polymarket-us SDK.

Covers every scenario the feature was built against: target not
reached -> no sell; target reached -> one sell; insufficient bid
liquidity -> no sell; price falls after trigger (fill comes back not
filled) -> no sell; partial exit fill; full exit fill; unknown exit
status; restart with a pending exit; duplicate-cycle idempotency;
settlement without reaching target (see test_polymarket_engine.py for
the full run_cycle() integration version); fee-aware NET profit-target
accounting.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.execution.emergency_stop import EmergencyStopStore
from src.polymarket.exit_manager import (
    check_and_execute_profit_target_exits,
    compute_target_price,
    evaluate_profit_target_exit,
    record_exit_fill,
    reconcile_exit_fill,
    submit_profit_target_exit,
)
from src.polymarket.gateway import LivePolymarketGateway, PaperPolymarketGateway
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import BookLevel, FillResult, OrderBookSnapshot, SubmissionOutcome
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.settings import PolymarketSettings
from src.polymarket.state import DailyPnlStateStore

_VALID_KEY = "0x" + "a" * 64


# --- Fakes: only the network boundary ----------------------------------------

class _FakeClient:
    """Doubles as both `client` and (in live scenarios) `order_placer`
    -- exactly like the real PolymarketClient/PolymarketUSClient, which
    implement both get_order_book/get_fill_status AND place_order on
    the same object (see engine.py/run_polymarket_bot.py)."""

    def __init__(self):
        self._books: dict[str, OrderBookSnapshot] = {}
        self._fills: dict[str, FillResult] = {}
        self._place_outcome: SubmissionOutcome | None = None
        self.get_order_book_calls: list[str] = []
        self.get_fill_status_calls: list[str] = []
        self.place_order_calls: list = []

    def set_order_book(self, token_id: str, book: OrderBookSnapshot) -> None:
        self._books[token_id] = book

    def set_fill_result(self, exchange_order_id: str, fill: FillResult) -> None:
        self._fills[exchange_order_id] = fill

    def set_place_outcome(self, outcome: SubmissionOutcome) -> None:
        self._place_outcome = outcome

    def get_order_book(self, token_id: str) -> OrderBookSnapshot:
        self.get_order_book_calls.append(token_id)
        return self._books[token_id]

    def get_fill_status(self, exchange_order_id: str) -> FillResult:
        self.get_fill_status_calls.append(exchange_order_id)
        return self._fills[exchange_order_id]

    def place_order(self, order):
        self.place_order_calls.append(order)
        return self._place_outcome


def _book(**overrides) -> OrderBookSnapshot:
    defaults = dict(
        token_id="tok-1", bids=(BookLevel(price=0.44, size=100.0),), asks=(BookLevel(price=0.46, size=100.0),),
        fetched_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return OrderBookSnapshot(**defaults)


def _position(**overrides) -> OpenPosition:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="cpc-btc-updown-15m-2026-10-07-2230z", token_id="tok-1", outcome="YES",
        requested_size_usd=5.0, filled_shares=5.0, avg_fill_price=0.36, order_id="CZ510YB5PYWT",
        client_order_id="client-2230z", status="filled", opened_at=now, close_time=now + timedelta(minutes=10),
    )
    defaults.update(overrides)
    return OpenPosition(**defaults)


def _settings(**overrides) -> PolymarketSettings:
    return PolymarketSettings.from_env(env=dict(overrides))


def _logger(tmp_path: Path) -> PolymarketDecisionLogger:
    return PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)


def _harness(tmp_path: Path, *, settings: PolymarketSettings | None = None):
    client = _FakeClient()
    settings = settings or _settings()
    decision_logger = _logger(tmp_path)
    gateway = PaperPolymarketGateway(settings, decision_logger) if settings.is_paper else None
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    return dict(
        client=client, settings=settings, gateway=gateway, position_store=position_store,
        pending_store=pending_store, state_store=state_store, decision_logger=decision_logger,
    )


# --- compute_target_price -----------------------------------------------------

def test_compute_target_price_matches_the_real_2230z_position():
    """The real, already-filled live position this feature was built
    for: 5 YES shares at avg_fill_price=$0.36. Target should be
    approximately $0.432, BEFORE accounting for exit fees."""
    assert compute_target_price(0.36, 0.20) == pytest.approx(0.432)


def test_compute_target_price_rounds_away_float_noise():
    # 0.36 * 1.2 == 0.43200000000000005 in raw IEEE 754 arithmetic.
    assert compute_target_price(0.36, 0.20) == 0.432


# --- evaluate_profit_target_exit: pure decision logic -------------------------

def test_target_not_reached_is_not_eligible():
    position = _position(avg_fill_price=0.36)  # target 0.432
    book = _book(bids=(BookLevel(price=0.40, size=100.0),))  # below target
    decision = evaluate_profit_target_exit(position, book, profit_target_pct=0.20)
    assert decision.eligible is False
    assert decision.target_price == pytest.approx(0.432)


def test_never_triggers_from_the_ask_or_midpoint():
    """Requirement: do NOT trigger from the ask price or midpoint --
    only a real, executable BID counts. Here the ask (and therefore the
    midpoint) are above target, but the bid is not."""
    position = _position(avg_fill_price=0.36)  # target 0.432
    book = _book(bids=(BookLevel(price=0.40, size=100.0),), asks=(BookLevel(price=0.50, size=100.0),))
    assert book.mid == pytest.approx(0.45)  # midpoint alone WOULD have triggered
    assert book.best_ask == 0.50  # ask alone WOULD have triggered too
    decision = evaluate_profit_target_exit(position, book, profit_target_pct=0.20)
    assert decision.eligible is False
    assert "0.4" in decision.reason or "target" in decision.reason.lower()


def test_target_reached_with_sufficient_liquidity_is_eligible():
    position = _position(avg_fill_price=0.36, filled_shares=5.0)  # target 0.432
    book = _book(bids=(BookLevel(price=0.44, size=100.0),))
    decision = evaluate_profit_target_exit(position, book, profit_target_pct=0.20)
    assert decision.eligible is True
    assert decision.target_price == pytest.approx(0.432)
    assert decision.best_bid == pytest.approx(0.44)


def test_insufficient_bid_liquidity_is_not_eligible():
    position = _position(avg_fill_price=0.36, filled_shares=5.0)  # target 0.432
    book = _book(bids=(BookLevel(price=0.44, size=2.0),))  # only 2 of the 5 needed shares
    decision = evaluate_profit_target_exit(position, book, profit_target_pct=0.20)
    assert decision.eligible is False
    assert decision.executable_shares_at_target == pytest.approx(2.0)


def test_liquidity_below_target_price_does_not_count_even_if_total_book_is_deep():
    position = _position(avg_fill_price=0.36, filled_shares=5.0)  # target 0.432
    book = _book(bids=(BookLevel(price=0.432, size=3.0), BookLevel(price=0.40, size=1000.0)))
    decision = evaluate_profit_target_exit(position, book, profit_target_pct=0.20)
    assert decision.eligible is False  # only the 3 shares at/above target count, not the deep 0.40 level
    assert decision.executable_shares_at_target == pytest.approx(3.0)


def test_already_pending_exit_is_not_eligible_for_another_one():
    position = _position(avg_fill_price=0.36, exit_pending_order_id="already-in-flight")
    book = _book(bids=(BookLevel(price=0.50, size=100.0),))  # would otherwise clearly trigger
    decision = evaluate_profit_target_exit(position, book, profit_target_pct=0.20)
    assert decision.eligible is False
    assert "pending" in decision.reason.lower()


# --- check_and_execute_profit_target_exits: paper-mode end-to-end ------------

def test_paper_mode_target_not_reached_submits_no_sell(tmp_path):
    harness = _harness(tmp_path)
    position = _position(avg_fill_price=0.36)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(bids=(BookLevel(price=0.40, size=100.0),)))

    submitted = check_and_execute_profit_target_exits(**harness)

    assert submitted == 0
    positions = harness["position_store"].load()
    assert len(positions) == 1
    assert positions[0].filled_shares == 5.0  # untouched
    assert positions[0].exit_pending_order_id is None


def test_paper_mode_target_reached_submits_exactly_one_sell_and_closes_the_position(tmp_path):
    harness = _harness(tmp_path)
    position = _position(avg_fill_price=0.36, filled_shares=5.0)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(bids=(BookLevel(price=0.44, size=100.0),)))
    state = harness["state_store"].load()
    state.open_position_count = 1
    harness["state_store"].save(state)

    submitted = check_and_execute_profit_target_exits(**harness)

    assert submitted == 1
    assert harness["position_store"].load() == []  # fully closed -- paper fills are always complete
    state = harness["state_store"].load()
    assert state.open_position_count == 0
    assert state.realized_pnl_usd == pytest.approx(5.0 * (0.432 - 0.36))  # (target_price - avg_fill_price) * shares
    assert state.last_exit_time is not None


def test_paper_mode_insufficient_liquidity_submits_no_sell(tmp_path):
    harness = _harness(tmp_path)
    position = _position(avg_fill_price=0.36, filled_shares=5.0)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(bids=(BookLevel(price=0.44, size=1.0),)))

    submitted = check_and_execute_profit_target_exits(**harness)

    assert submitted == 0
    positions = harness["position_store"].load()
    assert len(positions) == 1
    assert positions[0].filled_shares == 5.0


def test_a_position_with_a_pending_exit_is_never_offered_a_second_one_in_the_same_pass(tmp_path):
    """Duplicate-cycle idempotency: a position already marked with an
    exit in flight must never have its order book re-evaluated for a
    FRESH exit decision within the same check_and_execute_profit_target_exits()
    call -- it is only ever swept via reconcile_exit_fill()."""
    harness = _harness(tmp_path)
    position = _position(avg_fill_price=0.36, exit_pending_order_id="paper:already-done")
    harness["position_store"].add_if_absent(position)
    # Deliberately no order book registered for "tok-1" -- if
    # check_and_execute_profit_target_exits() tried to fetch one for
    # this position, the fake client would raise KeyError.

    submitted = check_and_execute_profit_target_exits(**harness)

    assert submitted == 0
    assert harness["client"].get_order_book_calls == []  # never even looked at the book


def test_two_consecutive_cycles_submit_only_one_sell_for_the_same_position(tmp_path):
    """The literal duplicate-cycle scenario: call
    check_and_execute_profit_target_exits() twice back-to-back (as
    run_cycle() would across two polling iterations) against a position
    whose exit is still pending between calls -- must submit at most
    one exit total, never two."""
    settings = _settings(POLYMARKET_TRADING_MODE="live", POLYMARKET_PRIVATE_KEY=_VALID_KEY, POLYMARKET_LIVE_TRADING_CONFIRMED="true")
    harness = _harness(tmp_path, settings=settings)
    emergency_stop_store = EmergencyStopStore(tmp_path / "estop.json")
    emergency_stop_store.clear(authorized_by="test", reason="test")
    gateway = LivePolymarketGateway(
        settings, harness["decision_logger"], harness["pending_store"],
        order_placer=harness["client"], emergency_stop_store=emergency_stop_store,
    )
    harness["gateway"] = gateway
    position = _position(avg_fill_price=0.36, filled_shares=5.0)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(bids=(BookLevel(price=0.44, size=100.0),)))

    first = check_and_execute_profit_target_exits(**harness)
    assert first == 1
    assert len(harness["pending_store"].load()) == 1  # exactly one exit order created
    # live_auto_execute/auto_exit_enabled are both false by default -- it
    # stays at awaiting_approval, never reaching the fake order placer.
    assert harness["client"].place_order_calls == []

    second = check_and_execute_profit_target_exits(**harness)
    assert second == 0  # the pending exit blocks a second submission
    assert len(harness["pending_store"].load()) == 1  # still just the one


# --- Live-path fill reconciliation: full/partial/unknown/not-filled ----------

def _live_harness(tmp_path: Path, *, auto_exit_enabled: bool = True):
    settings = _settings(
        POLYMARKET_TRADING_MODE="live", POLYMARKET_PRIVATE_KEY=_VALID_KEY,
        POLYMARKET_LIVE_TRADING_CONFIRMED="true",
        POLYMARKET_AUTO_EXIT_ENABLED="true" if auto_exit_enabled else "false",
    )
    harness = _harness(tmp_path, settings=settings)
    emergency_stop_store = EmergencyStopStore(tmp_path / "estop.json")
    emergency_stop_store.clear(authorized_by="test", reason="test")
    gateway = LivePolymarketGateway(
        settings, harness["decision_logger"], harness["pending_store"],
        order_placer=harness["client"], emergency_stop_store=emergency_stop_store,
    )
    harness["gateway"] = gateway
    return harness


def test_full_exit_fill_closes_the_position_and_records_net_pnl(tmp_path):
    harness = _live_harness(tmp_path)
    position = _position(avg_fill_price=0.36, filled_shares=5.0, entry_fee_usd=0.05)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(bids=(BookLevel(price=0.44, size=100.0),)))
    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-ex-1", raw_status="matched"))
    harness["client"].set_fill_result("exit-ex-1", FillResult(
        order_id="exit-ex-1", status="filled", requested_shares=5.0, filled_shares=5.0,
        avg_fill_price=0.432, fee_usd=0.03,
    ))
    state = harness["state_store"].load()
    state.open_position_count = 1
    harness["state_store"].save(state)

    submitted = check_and_execute_profit_target_exits(**harness)

    assert submitted == 1
    assert harness["position_store"].load() == []
    state = harness["state_store"].load()
    # proceeds(5*0.432) - entry_cost(5*0.36) - entry_fee(0.05) - exit_fee(0.03)
    expected = (5 * 0.432) - (5 * 0.36) - 0.05 - 0.03
    assert state.realized_pnl_usd == pytest.approx(expected)
    assert state.open_position_count == 0


def test_partial_exit_fill_leaves_the_remaining_quantity_open(tmp_path):
    harness = _live_harness(tmp_path)
    position = _position(avg_fill_price=0.36, filled_shares=5.0, entry_fee_usd=0.05)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(bids=(BookLevel(price=0.44, size=100.0),)))
    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-ex-2", raw_status="matched"))
    harness["client"].set_fill_result("exit-ex-2", FillResult(
        order_id="exit-ex-2", status="partially_filled", requested_shares=5.0, filled_shares=3.0,
        avg_fill_price=0.432, fee_usd=0.018,
    ))

    submitted = check_and_execute_profit_target_exits(**harness)

    assert submitted == 1
    positions = harness["position_store"].load()
    assert len(positions) == 1
    remaining = positions[0]
    assert remaining.filled_shares == pytest.approx(2.0)  # 5 - 3 left open
    assert remaining.exit_pending_order_id is None  # free to retry on a later cycle
    assert remaining.avg_fill_price == 0.36  # entry cost basis for the remaining shares is unchanged
    assert remaining.entry_fee_usd == pytest.approx(0.05 * (2.0 / 5.0))  # only the unclosed slice's fee remains
    state = harness["state_store"].load()
    expected_pnl = (3 * 0.432) - (3 * 0.36) - (0.05 * 3 / 5) - 0.018
    assert state.realized_pnl_usd == pytest.approx(expected_pnl)


def test_unknown_exit_status_leaves_position_unchanged_and_pending(tmp_path):
    """Requirement: if exit status is unknown, STOP and retry
    reconciliation later; never assume an exit filled."""
    harness = _live_harness(tmp_path)
    position = _position(avg_fill_price=0.36, filled_shares=5.0)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(bids=(BookLevel(price=0.44, size=100.0),)))
    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-ex-3", raw_status="matched"))
    harness["client"].set_fill_result("exit-ex-3", FillResult(
        order_id="exit-ex-3", status="unknown", requested_shares=5.0, filled_shares=0.0, avg_fill_price=None,
        raw={"lookup_error": "timed out"},
    ))

    submitted = check_and_execute_profit_target_exits(**harness)

    assert submitted == 1  # an exit WAS submitted -- its outcome just isn't known yet
    positions = harness["position_store"].load()
    assert len(positions) == 1
    assert positions[0].filled_shares == 5.0  # unchanged -- never assumed filled
    assert positions[0].exit_pending_order_id is not None  # left SET -- not cleared, not assumed filled
    state = harness["state_store"].load()
    assert state.realized_pnl_usd == 0.0  # nothing recorded for an unknown outcome

    # A later sweep (e.g. the next cycle, or after a restart) must
    # genuinely re-query, not silently no-op.
    harness["client"].set_fill_result("exit-ex-3", FillResult(
        order_id="exit-ex-3", status="filled", requested_shares=5.0, filled_shares=5.0, avg_fill_price=0.432,
    ))
    second = check_and_execute_profit_target_exits(**harness)
    assert second == 0  # no NEW exit submitted -- this is a reconciliation of the existing one
    assert harness["position_store"].load() == []  # now genuinely closed
    assert harness["client"].get_fill_status_calls.count("exit-ex-3") == 2  # re-queried, not cached


def test_price_falls_after_trigger_results_in_no_sell(tmp_path):
    """The exit order reached the exchange as an IOC/FOK order, but by
    matching time the bid had fallen back below the target price, so
    it simply did not fill (never left resting) -- the position must
    be completely unchanged and free to try again."""
    harness = _live_harness(tmp_path)
    position = _position(avg_fill_price=0.36, filled_shares=5.0)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(bids=(BookLevel(price=0.44, size=100.0),)))
    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-ex-4", raw_status="matched"))
    harness["client"].set_fill_result("exit-ex-4", FillResult(
        order_id="exit-ex-4", status="cancelled", requested_shares=5.0, filled_shares=0.0, avg_fill_price=None,
    ))

    submitted = check_and_execute_profit_target_exits(**harness)

    assert submitted == 1  # an exit attempt was made
    positions = harness["position_store"].load()
    assert len(positions) == 1
    assert positions[0].filled_shares == 5.0  # nothing sold
    assert positions[0].exit_pending_order_id is None  # free to retry next cycle
    state = harness["state_store"].load()
    assert state.realized_pnl_usd == 0.0


def test_restart_with_a_pending_exit_is_reconciled_by_a_fresh_process(tmp_path):
    """Restart-safety: an exit order that reached the exchange in one
    process (exit_pending_order_id persisted) must be correctly
    reconciled by a brand-new set of store instances pointed at the
    same files -- simulating a bot restart -- never re-submitted."""
    harness = _live_harness(tmp_path)
    position = _position(avg_fill_price=0.36, filled_shares=5.0)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(bids=(BookLevel(price=0.44, size=100.0),)))
    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-ex-5", raw_status="matched"))
    harness["client"].set_fill_result("exit-ex-5", FillResult(
        order_id="exit-ex-5", status="unknown", requested_shares=5.0, filled_shares=0.0, avg_fill_price=None,
    ))
    check_and_execute_profit_target_exits(**harness)
    pending_before = harness["position_store"].get("client-2230z")
    assert pending_before.exit_pending_order_id is not None

    # Fresh store instances, same files, same fake client (standing in
    # for a real reconnect) -- simulates a restarted process that lost
    # all in-memory state.
    fresh_position_store = PolymarketPositionStore(tmp_path / "positions.json")
    fresh_pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    fresh_state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    harness["client"].set_fill_result("exit-ex-5", FillResult(
        order_id="exit-ex-5", status="filled", requested_shares=5.0, filled_shares=5.0, avg_fill_price=0.432,
    ))

    restarted_position = fresh_position_store.get("client-2230z")
    result = reconcile_exit_fill(
        restarted_position, client=harness["client"], pending_store=fresh_pending_store,
        position_store=fresh_position_store, state_store=fresh_state_store, decision_logger=harness["decision_logger"],
    )
    assert result is None  # fully closed
    assert fresh_position_store.load() == []
    assert harness["client"].place_order_calls == [] or len(harness["client"].place_order_calls) == 1  # never re-submitted


# --- Emergency stop: must block automatic exits, exactly like entries -------

def test_emergency_stop_blocks_an_automatic_exit_from_reaching_the_exchange(tmp_path):
    """Requirement: emergency stop must block NEW entries AND automatic
    exits. This reuses LivePolymarketGateway.confirm_and_place()'s own
    pre-existing emergency-stop check (the same one entries already go
    through) -- there is no separate check in exit_manager.py, by
    design, so the two paths can never drift apart."""
    settings = _settings(
        POLYMARKET_TRADING_MODE="live", POLYMARKET_PRIVATE_KEY=_VALID_KEY,
        POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_AUTO_EXIT_ENABLED="true",
    )
    harness = _harness(tmp_path, settings=settings)
    emergency_stop_store = EmergencyStopStore(tmp_path / "estop.json")
    assert emergency_stop_store.is_stopped() is True  # defaults to STOPPED -- never cleared in this test
    gateway = LivePolymarketGateway(
        settings, harness["decision_logger"], harness["pending_store"],
        order_placer=harness["client"], emergency_stop_store=emergency_stop_store,
    )
    harness["gateway"] = gateway
    position = _position(avg_fill_price=0.36, filled_shares=5.0)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(bids=(BookLevel(price=0.44, size=100.0),)))

    submitted = check_and_execute_profit_target_exits(**harness)

    assert submitted == 1  # an exit attempt was made (and recorded as blocked)
    assert harness["client"].place_order_calls == []  # NEVER reached the exchange
    positions = harness["position_store"].load()
    assert len(positions) == 1
    assert positions[0].filled_shares == 5.0  # unchanged
    assert positions[0].exit_pending_order_id is None  # cleared -- free to retry once the stop lifts, not stuck forever
    state = harness["state_store"].load()
    assert state.realized_pnl_usd == 0.0


def test_emergency_stop_does_not_block_a_paper_mode_simulated_exit(tmp_path):
    """Paper mode never touches real money or the real order placer --
    exactly like an entry, it is unaffected by emergency stop, which
    only ever guards LivePolymarketGateway._submit_pending()."""
    harness = _harness(tmp_path)  # paper mode by default, no emergency-stop store involved at all
    position = _position(avg_fill_price=0.36, filled_shares=5.0)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(bids=(BookLevel(price=0.44, size=100.0),)))

    submitted = check_and_execute_profit_target_exits(**harness)

    assert submitted == 1
    assert harness["position_store"].load() == []  # closed normally, exactly as if nothing were stopped


# --- Fee-aware NET realized P&L (record_exit_fill, unit-level) ---------------

def test_fee_aware_net_pnl_is_less_than_the_gross_twenty_percent_move(tmp_path):
    """Requirement: do not call a trade profitable merely because the
    gross price increased 20% -- the RECORDED P&L must net out both
    entry and exit fees whenever the exchange actually reports them."""
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    decision_logger = _logger(tmp_path)
    position = _position(avg_fill_price=0.36, filled_shares=5.0, entry_fee_usd=0.05)
    position_store.add_if_absent(position)

    gross_pnl = 5 * (0.432 - 0.36)
    fill = FillResult(order_id="exit-fee-1", status="filled", requested_shares=5.0, filled_shares=5.0, avg_fill_price=0.432, fee_usd=0.03)
    record_exit_fill(fill, position, position_store=position_store, state_store=state_store, decision_logger=decision_logger, now=datetime.now(timezone.utc))

    state = state_store.load()
    assert state.realized_pnl_usd < gross_pnl
    assert state.realized_pnl_usd == pytest.approx(gross_pnl - 0.05 - 0.03)


def test_net_pnl_with_no_reported_fee_equals_the_gross_move():
    """fee_usd=None (not reported) must not be treated as a fabricated
    fee of some made-up size -- it contributes exactly 0 -- but it must
    also not be CONFUSED with a confirmed $0.00 fee elsewhere in the
    system (see FillResult.fee_usd's docstring)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        position_store = PolymarketPositionStore(tmp_path / "positions.json")
        state_store = DailyPnlStateStore(tmp_path / "pnl.json")
        decision_logger = _logger(tmp_path)
        position = _position(avg_fill_price=0.36, filled_shares=5.0, entry_fee_usd=0.0)
        position_store.add_if_absent(position)

        fill = FillResult(order_id="exit-fee-2", status="filled", requested_shares=5.0, filled_shares=5.0, avg_fill_price=0.432, fee_usd=None)
        record_exit_fill(fill, position, position_store=position_store, state_store=state_store, decision_logger=decision_logger, now=datetime.now(timezone.utc))

        state = state_store.load()
        assert state.realized_pnl_usd == pytest.approx(5 * (0.432 - 0.36))
