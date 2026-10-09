"""Tests for the evidence-gated dynamic exit system (exit_manager.py).

Two layers are tested separately, on purpose:
  - The CASCADE (evaluate_dynamic_exit) is tested against directly-
    constructed BtcMarketAssessment objects (via `_assessment()` below)
    -- its job is "given a BTC state and profit level, what's the
    decision," independent of how that state was derived from real
    bars (that translation is btc_intelligence.py's job, already
    covered by tests/test_polymarket_btc_intelligence.py).
  - The FULL PIPELINE (check_and_execute_dynamic_exits, end to end,
    with a live order book / position store / paper or live gateway)
    is tested with real OrderBookSnapshots and a minimal fake client,
    mirroring test_polymarket_reconciliation.py's style.

Covers every scenario this system was redesigned around: the exact
user-specified decision table (target+strengthening->hold,
target+weakening->exit, target+reversing->exit, below-target+strong
reversal->exit, above-target+strengthening->hold,
insufficient-data->hold); liquidity/no-bid/already-pending guards;
idempotency; partial/full fills; unknown status; restart-safety;
emergency stop; fee-aware net P&L; and the dynamic_exit_enabled master
switch.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.execution.emergency_stop import EmergencyStopStore
from src.polymarket.btc_intelligence import BtcMarketAssessment
from src.polymarket.exit_manager import (
    DynamicExitConfig,
    check_and_execute_dynamic_exits,
    compute_target_price,
    evaluate_dynamic_exit,
    record_exit_fill,
    reconcile_exit_fill,
    submit_dynamic_exit,
)
from src.polymarket.gateway import LivePolymarketGateway, PaperPolymarketGateway
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import BookLevel, FillResult, OrderBookSnapshot, SubmissionOutcome
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.settings import PolymarketSettings
from src.polymarket.state import DailyPnlStateStore
from src.strategy.evidence import MomentumAssessment, MomentumState

_VALID_KEY = "0x" + "a" * 64


# --- Fakes --------------------------------------------------------------------

class _FakeClient:
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


class _DummyBtcPriceStore:
    """check_and_execute_dynamic_exits() only ever calls .get_bars() on
    this -- a trivial stand-in is enough since these full-pipeline
    tests construct the BtcMarketAssessment indirectly via a real
    order book but don't need real BTC bars (empty bars -> real
    build_btc_momentum_evidence() -> INSUFFICIENT_DATA, which these
    tests account for by injecting enough Polymarket-only signal via
    the monkeypatched assess_btc_market where needed, or by testing
    the INSUFFICIENT_DATA path directly, which IS the honest default)."""

    def get_bars(self, *, interval_seconds, now=None):
        return []


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


def _assessment(state: MomentumState, *, signal_count: int = 3) -> BtcMarketAssessment:
    """Directly constructs a BtcMarketAssessment with a given state and
    a given number of fired signals -- isolates the CASCADE's own
    logic from how that state is derived from real bars (see module
    docstring)."""
    fired = tuple(f"signal_{i}" for i in range(signal_count))
    momentum = MomentumAssessment(state=state, weakening_score=0, strengthening_score=0, signals=fired)
    return BtcMarketAssessment(state=state, evidence_score=0, btc_assessment=momentum, signals=())


def _harness(tmp_path: Path, *, settings: PolymarketSettings | None = None):
    client = _FakeClient()
    settings = settings or _settings(POLYMARKET_DYNAMIC_EXIT_ENABLED="true")
    decision_logger = _logger(tmp_path)
    gateway = PaperPolymarketGateway(settings, decision_logger) if settings.is_paper else None
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    return dict(
        client=client, settings=settings, gateway=gateway, position_store=position_store,
        pending_store=pending_store, state_store=state_store, decision_logger=decision_logger,
        btc_price_store=_DummyBtcPriceStore(),
    )


def _live_harness(tmp_path: Path, *, auto_exit_enabled: bool = True, dynamic_exit_enabled: bool = True):
    settings = _settings(
        POLYMARKET_TRADING_MODE="live", POLYMARKET_PRIVATE_KEY=_VALID_KEY,
        POLYMARKET_LIVE_TRADING_CONFIRMED="true",
        POLYMARKET_AUTO_EXIT_ENABLED="true" if auto_exit_enabled else "false",
        POLYMARKET_DYNAMIC_EXIT_ENABLED="true" if dynamic_exit_enabled else "false",
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


# --- compute_target_price (unchanged) -----------------------------------------

def test_compute_target_price_matches_the_real_2230z_position():
    assert compute_target_price(0.36, 0.20) == pytest.approx(0.432)


# --- evaluate_dynamic_exit: the exact user-specified decision table ----------

def test_insufficient_data_holds_regardless_of_profit():
    position = _position(avg_fill_price=0.36)
    book = _book(bids=(BookLevel(price=0.50, size=100.0),))  # would clearly hit target if evaluated
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.INSUFFICIENT_DATA), profit_target_pct=0.20,
    )
    assert decision.eligible is False
    assert "insufficient" in decision.reason.lower()


def test_target_reached_plus_strengthening_holds():
    """+20% profit + strong continuation evidence -> HOLD."""
    position = _position(avg_fill_price=0.36)  # target 0.432
    book = _book(bids=(BookLevel(price=0.44, size=100.0),))  # ~22% gain, past target
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.STRENGTHENING), profit_target_pct=0.20,
    )
    assert decision.eligible is False
    assert "strengthening" in decision.reason.lower()


def test_target_reached_plus_weakening_exits():
    """+20% profit + weakening momentum -> EXIT."""
    position = _position(avg_fill_price=0.36)
    book = _book(bids=(BookLevel(price=0.44, size=100.0),))
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.WEAKENING, signal_count=3), profit_target_pct=0.20,
    )
    assert decision.eligible is True


def test_target_reached_plus_reversing_exits():
    """+20% profit + reversal evidence -> EXIT."""
    position = _position(avg_fill_price=0.36)
    book = _book(bids=(BookLevel(price=0.44, size=100.0),))
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.REVERSING, signal_count=5), profit_target_pct=0.20,
    )
    assert decision.eligible is True


def test_below_target_plus_strong_reversal_exits():
    """+10% profit + strong reversal -> EXIT, even though the soft
    20% target was never reached."""
    position = _position(avg_fill_price=0.36)  # target 0.432; 10% gain = 0.396
    book = _book(bids=(BookLevel(price=0.396, size=100.0),))
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.REVERSING, signal_count=5), profit_target_pct=0.20,
    )
    assert decision.eligible is True
    assert decision.gross_pnl_pct == pytest.approx(0.10, abs=1e-6)


def test_above_target_plus_strengthening_holds():
    """+35% profit + strong continuation -> HOLD."""
    position = _position(avg_fill_price=0.36)  # 35% gain = 0.486
    book = _book(bids=(BookLevel(price=0.486, size=100.0),))
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.STRENGTHENING), profit_target_pct=0.20,
    )
    assert decision.eligible is False


def test_below_target_weakening_without_enough_signals_holds():
    """A barely-WEAKENING read (fewer than min_weakening_signals_for_exit)
    below target must NOT trigger an early exit -- a single soft
    signal is never enough (mirrors evaluate_momentum's own guarantee)."""
    position = _position(avg_fill_price=0.36)  # below target
    book = _book(bids=(BookLevel(price=0.37, size=100.0),))
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.WEAKENING, signal_count=1),
        profit_target_pct=0.20, config=DynamicExitConfig(min_weakening_signals_for_exit=2),
    )
    assert decision.eligible is False


def test_unprofitable_position_never_exits_on_reversal_alone():
    """Scope: this redesign only ever exits a PROFITABLE position
    early on evidence. A position currently at a loss must HOLD
    (deferring to settlement) even with strong reversal evidence --
    no new stop-loss concept was requested or added."""
    position = _position(avg_fill_price=0.50)  # currently a loss at the book below
    book = _book(bids=(BookLevel(price=0.40, size=100.0),))
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.REVERSING, signal_count=5), profit_target_pct=0.20,
    )
    assert decision.eligible is False


def test_no_live_bid_is_not_eligible():
    position = _position()
    book = _book(bids=())
    decision = evaluate_dynamic_exit(position, book, _assessment(MomentumState.REVERSING), profit_target_pct=0.20)
    assert decision.eligible is False
    assert "no live bid" in decision.reason.lower()


def test_already_pending_exit_is_not_eligible():
    position = _position(exit_pending_order_id="already-in-flight")
    book = _book(bids=(BookLevel(price=0.50, size=100.0),))
    decision = evaluate_dynamic_exit(position, book, _assessment(MomentumState.REVERSING), profit_target_pct=0.20)
    assert decision.eligible is False
    assert "pending" in decision.reason.lower()


def test_insufficient_liquidity_at_best_bid_is_not_eligible():
    position = _position(filled_shares=5.0)
    book = _book(bids=(BookLevel(price=0.44, size=1.0),))  # only 1 of 5 needed shares at the bid
    decision = evaluate_dynamic_exit(position, book, _assessment(MomentumState.REVERSING), profit_target_pct=0.20)
    assert decision.eligible is False
    assert "liquidity" in decision.reason.lower()


def test_eligible_decision_prices_at_the_real_best_bid_not_a_fixed_target():
    position = _position(avg_fill_price=0.36, filled_shares=5.0)
    book = _book(bids=(BookLevel(price=0.50, size=100.0),))  # well past target
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.WEAKENING, signal_count=3), profit_target_pct=0.20,
    )
    assert decision.eligible is True
    assert decision.best_bid == 0.50  # prices at the live bid, not the 0.432 soft target


# --- Full pipeline: dynamic_exit_enabled master switch ------------------------

def test_master_switch_off_never_evaluates_any_position(tmp_path):
    harness = _harness(tmp_path, settings=_settings())  # dynamic_exit_enabled defaults False
    harness["position_store"].add_if_absent(_position())
    submitted = check_and_execute_dynamic_exits(**harness)
    assert submitted == 0
    assert harness["client"].get_order_book_calls == []  # never even looked


def test_master_switch_on_with_no_btc_data_holds(tmp_path):
    """With dynamic_exit_enabled=true but no fed BTC quotes at all
    (_DummyBtcPriceStore always returns []), BTC evidence is honestly
    INSUFFICIENT_DATA -- the position must be left completely alone."""
    harness = _harness(tmp_path)
    position = _position(avg_fill_price=0.36)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(bids=(BookLevel(price=0.50, size=100.0),)))

    submitted = check_and_execute_dynamic_exits(**harness)

    assert submitted == 0
    positions = harness["position_store"].load()
    assert len(positions) == 1
    assert positions[0].filled_shares == 5.0


# --- Full pipeline: idempotency / duplicate-cycle guard -----------------------

def test_a_position_with_a_pending_exit_is_never_offered_a_second_one(tmp_path):
    harness = _harness(tmp_path)
    position = _position(exit_pending_order_id="paper:already-done")
    harness["position_store"].add_if_absent(position)

    submitted = check_and_execute_dynamic_exits(**harness)

    assert submitted == 0
    assert harness["client"].get_order_book_calls == []  # never re-evaluated -- only reconciled


def test_two_consecutive_cycles_submit_only_one_exit_for_the_same_position(tmp_path):
    harness = _live_harness(tmp_path, auto_exit_enabled=False)
    position = _position(avg_fill_price=0.36, filled_shares=5.0)
    harness["position_store"].add_if_absent(position)
    harness["client"].set_order_book("tok-1", _book(bids=(BookLevel(price=0.50, size=100.0),)))

    # Build and submit an eligible decision directly (bypassing the
    # INSUFFICIENT_DATA default, since this test's fake client has no
    # real BTC bars) to get the position into "exit pending" state.
    decision = evaluate_dynamic_exit(
        position, harness["client"]._books["tok-1"], _assessment(MomentumState.REVERSING, signal_count=5),
        profit_target_pct=0.20,
    )
    assert decision.eligible is True
    submit_dynamic_exit(
        decision, client=harness["client"], gateway=harness["gateway"], position_store=harness["position_store"],
        state_store=harness["state_store"], decision_logger=harness["decision_logger"], settings=harness["settings"],
    )
    assert len(harness["pending_store"].load()) == 1

    # A full pipeline pass must now only RECONCILE the pending exit,
    # never propose (or submit) a second one.
    submitted = check_and_execute_dynamic_exits(**harness)
    assert submitted == 0
    assert len(harness["pending_store"].load()) == 1
    assert harness["client"].place_order_calls == []  # never reached the exchange (auto_exit_enabled=False)


# --- Full pipeline: fill reconciliation (record_exit_fill is UNCHANGED) ------

def _live_harness_with_decision(tmp_path, *, bid=0.50, filled_shares=5.0, entry_fee_usd=0.0, auto_exit_enabled=True):
    harness = _live_harness(tmp_path, auto_exit_enabled=auto_exit_enabled)
    position = _position(avg_fill_price=0.36, filled_shares=filled_shares, entry_fee_usd=entry_fee_usd)
    harness["position_store"].add_if_absent(position)
    book = _book(bids=(BookLevel(price=bid, size=100.0),))
    harness["client"].set_order_book("tok-1", book)
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.REVERSING, signal_count=5), profit_target_pct=0.20,
    )
    assert decision.eligible is True
    return harness, decision


def test_full_exit_fill_closes_the_position_and_records_net_pnl(tmp_path):
    harness, decision = _live_harness_with_decision(tmp_path, bid=0.50, entry_fee_usd=0.05)
    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-ex-1", raw_status="matched"))
    harness["client"].set_fill_result("exit-ex-1", FillResult(
        order_id="exit-ex-1", status="filled", requested_shares=5.0, filled_shares=5.0, avg_fill_price=0.50, fee_usd=0.03,
    ))

    submit_dynamic_exit(
        decision, client=harness["client"], gateway=harness["gateway"], position_store=harness["position_store"],
        state_store=harness["state_store"], decision_logger=harness["decision_logger"], settings=harness["settings"],
        order_placer=harness["client"],
    )

    assert harness["position_store"].load() == []
    state = harness["state_store"].load()
    expected = (5 * 0.50) - (5 * 0.36) - 0.05 - 0.03
    assert state.realized_pnl_usd == pytest.approx(expected)


def test_partial_exit_fill_leaves_the_remaining_quantity_open(tmp_path):
    harness, decision = _live_harness_with_decision(tmp_path, bid=0.50, entry_fee_usd=0.05)
    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-ex-2", raw_status="matched"))
    harness["client"].set_fill_result("exit-ex-2", FillResult(
        order_id="exit-ex-2", status="partially_filled", requested_shares=5.0, filled_shares=3.0, avg_fill_price=0.50, fee_usd=0.018,
    ))

    submit_dynamic_exit(
        decision, client=harness["client"], gateway=harness["gateway"], position_store=harness["position_store"],
        state_store=harness["state_store"], decision_logger=harness["decision_logger"], settings=harness["settings"],
        order_placer=harness["client"],
    )

    positions = harness["position_store"].load()
    assert len(positions) == 1
    assert positions[0].filled_shares == pytest.approx(2.0)
    assert positions[0].exit_pending_order_id is None


def test_unknown_exit_status_leaves_position_unchanged_and_pending(tmp_path):
    harness, decision = _live_harness_with_decision(tmp_path, bid=0.50)
    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-ex-3", raw_status="matched"))
    harness["client"].set_fill_result("exit-ex-3", FillResult(
        order_id="exit-ex-3", status="unknown", requested_shares=5.0, filled_shares=0.0, avg_fill_price=None,
    ))

    submit_dynamic_exit(
        decision, client=harness["client"], gateway=harness["gateway"], position_store=harness["position_store"],
        state_store=harness["state_store"], decision_logger=harness["decision_logger"], settings=harness["settings"],
        order_placer=harness["client"],
    )

    positions = harness["position_store"].load()
    assert len(positions) == 1
    assert positions[0].filled_shares == 5.0
    assert positions[0].exit_pending_order_id is not None  # left SET, never assumed filled


def test_price_falls_after_trigger_results_in_no_sell(tmp_path):
    harness, decision = _live_harness_with_decision(tmp_path, bid=0.50)
    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-ex-4", raw_status="matched"))
    harness["client"].set_fill_result("exit-ex-4", FillResult(
        order_id="exit-ex-4", status="cancelled", requested_shares=5.0, filled_shares=0.0, avg_fill_price=None,
    ))

    submit_dynamic_exit(
        decision, client=harness["client"], gateway=harness["gateway"], position_store=harness["position_store"],
        state_store=harness["state_store"], decision_logger=harness["decision_logger"], settings=harness["settings"],
        order_placer=harness["client"],
    )

    positions = harness["position_store"].load()
    assert positions[0].filled_shares == 5.0
    assert positions[0].exit_pending_order_id is None  # free to retry next cycle


def test_restart_with_a_pending_exit_is_reconciled_by_a_fresh_process(tmp_path):
    harness, decision = _live_harness_with_decision(tmp_path, bid=0.50)
    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-ex-5", raw_status="matched"))
    harness["client"].set_fill_result("exit-ex-5", FillResult(
        order_id="exit-ex-5", status="unknown", requested_shares=5.0, filled_shares=0.0, avg_fill_price=None,
    ))
    submit_dynamic_exit(
        decision, client=harness["client"], gateway=harness["gateway"], position_store=harness["position_store"],
        state_store=harness["state_store"], decision_logger=harness["decision_logger"], settings=harness["settings"],
        order_placer=harness["client"],
    )
    pending_before = harness["position_store"].get("client-2230z")
    assert pending_before.exit_pending_order_id is not None

    fresh_position_store = PolymarketPositionStore(tmp_path / "positions.json")
    fresh_pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    fresh_state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    harness["client"].set_fill_result("exit-ex-5", FillResult(
        order_id="exit-ex-5", status="filled", requested_shares=5.0, filled_shares=5.0, avg_fill_price=0.50,
    ))

    restarted_position = fresh_position_store.get("client-2230z")
    result = reconcile_exit_fill(
        restarted_position, client=harness["client"], pending_store=fresh_pending_store,
        position_store=fresh_position_store, state_store=fresh_state_store, decision_logger=harness["decision_logger"],
    )
    assert result is None  # fully closed
    assert fresh_position_store.load() == []


# --- Full pipeline, PAPER mode specifically ------------------------------------
# Every fill-handling test above (full/partial/unknown/cancelled fill, restart
# reconciliation) uses _live_harness -- LIVE mode's gateway -- because
# submission and fill determination are genuinely two separate steps there
# (see gateway.py's module docstring). PaperPolymarketGateway has no such
# gap: submit_order() returns an immediate, synchronous, ALWAYS-full
# FillResult, so submit_dynamic_exit() resolves it in the very same call via
# record_exit_fill() -- nothing to reconcile, nothing to retry. These tests
# cover that PAPER-specific end-to-end path, which none of the tests above
# exercise.

def test_paper_mode_full_exit_closes_the_position_and_updates_pnl_via_submit_dynamic_exit(tmp_path):
    """The missing PAPER-mode case: evaluate_dynamic_exit() -> an eligible
    decision -> submit_dynamic_exit() -> PaperPolymarketGateway's own
    synchronous simulated fill -> record_exit_fill() closes the position
    and records net realized P&L, all inside ONE submit_dynamic_exit()
    call. Never reaches client.place_order (paper mode never submits to a
    real exchange) and never calls client.get_fill_status (there is
    nothing to look up -- the fill was never in question)."""
    harness = _harness(tmp_path)  # _settings() defaults to paper (POLYMARKET_TRADING_MODE unset)
    assert harness["settings"].is_paper
    position = _position(avg_fill_price=0.36, filled_shares=5.0, entry_fee_usd=0.05)
    harness["position_store"].add_if_absent(position)
    book = _book(bids=(BookLevel(price=0.50, size=100.0),))
    harness["client"].set_order_book("tok-1", book)
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.REVERSING, signal_count=5), profit_target_pct=0.20,
    )
    assert decision.eligible is True

    result = submit_dynamic_exit(
        decision, client=harness["client"], gateway=harness["gateway"], position_store=harness["position_store"],
        state_store=harness["state_store"], decision_logger=harness["decision_logger"], settings=harness["settings"],
    )

    assert result.status == "simulated_fill"
    assert harness["client"].place_order_calls == []  # paper mode never reaches the exchange
    assert harness["client"].get_fill_status_calls == []  # nothing to reconcile for a synchronous simulation
    assert harness["position_store"].load() == []  # fully closed
    state = harness["state_store"].load()
    expected = (5 * 0.50) - (5 * 0.36) - 0.05  # entry fee only -- the simulated FillResult reports no exit fee
    assert state.realized_pnl_usd == pytest.approx(expected)


def test_paper_mode_partial_fill_is_reconciled_correctly(tmp_path):
    """PaperPolymarketGateway itself always simulates a FULL fill (see its
    own docstring) -- it structurally cannot produce a partial fill.
    record_exit_fill() is mode-agnostic reconciliation logic shared by
    both the paper and live paths, so this proves it handles a partial
    fill correctly under a PAPER settings/store environment too, exactly
    the way test_partial_exit_fill_leaves_the_remaining_quantity_open
    already proves it for LIVE."""
    settings = _settings()  # paper, isolated -- never touches the real .env
    assert settings.is_paper
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    decision_logger = _logger(tmp_path)
    position = _position(
        avg_fill_price=0.36, filled_shares=5.0, entry_fee_usd=0.05, exit_pending_order_id="paper:pending-1",
    )
    position_store.add_if_absent(position)

    fill = FillResult(
        order_id="paper:pending-1", status="partially_filled", requested_shares=5.0, filled_shares=3.0,
        avg_fill_price=0.50, fee_usd=0.018,
    )
    updated = record_exit_fill(
        fill, position, position_store=position_store, state_store=state_store, decision_logger=decision_logger,
        now=datetime.now(timezone.utc),
    )

    assert updated is not None
    assert updated.filled_shares == pytest.approx(2.0)
    assert updated.exit_pending_order_id is None  # cleared -- free for a fresh exit decision on the remainder
    positions = position_store.load()
    assert len(positions) == 1
    assert positions[0].filled_shares == pytest.approx(2.0)


def test_paper_mode_unknown_status_stays_pending_then_retry_resolves_it(tmp_path):
    """Same mode-agnostic point as the partial-fill test above, for the
    "unknown status -> retry" requirement: the first call must leave the
    position and its exit_pending_order_id completely untouched (never
    assume filled), and a SECOND call (the retry) with an authoritative
    result must then resolve it -- under a PAPER settings/store
    environment, mirroring test_unknown_exit_status_leaves_position_
    unchanged_and_pending's LIVE coverage."""
    settings = _settings()
    assert settings.is_paper
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    decision_logger = _logger(tmp_path)
    position = _position(avg_fill_price=0.36, filled_shares=5.0, exit_pending_order_id="paper:pending-2")
    position_store.add_if_absent(position)
    now = datetime.now(timezone.utc)

    unknown_fill = FillResult(
        order_id="paper:pending-2", status="unknown", requested_shares=5.0, filled_shares=0.0, avg_fill_price=None,
    )
    first = record_exit_fill(
        unknown_fill, position, position_store=position_store, state_store=state_store,
        decision_logger=decision_logger, now=now,
    )
    assert first is not None
    assert first.filled_shares == 5.0
    assert first.exit_pending_order_id == "paper:pending-2"  # left SET -- never assumed filled
    assert position_store.load()[0].exit_pending_order_id == "paper:pending-2"

    retry_fill = FillResult(
        order_id="paper:pending-2", status="filled", requested_shares=5.0, filled_shares=5.0, avg_fill_price=0.44,
    )
    second = record_exit_fill(
        retry_fill, position, position_store=position_store, state_store=state_store,
        decision_logger=decision_logger, now=now,
    )
    assert second is None  # fully closed on the retry
    assert position_store.load() == []


# --- Emergency stop ------------------------------------------------------------

def test_emergency_stop_blocks_an_automatic_exit_from_reaching_the_exchange(tmp_path):
    settings = _settings(
        POLYMARKET_TRADING_MODE="live", POLYMARKET_PRIVATE_KEY=_VALID_KEY,
        POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_AUTO_EXIT_ENABLED="true",
        POLYMARKET_DYNAMIC_EXIT_ENABLED="true",
    )
    harness = _harness(tmp_path, settings=settings)
    emergency_stop_store = EmergencyStopStore(tmp_path / "estop.json")
    assert emergency_stop_store.is_stopped() is True  # never cleared in this test
    gateway = LivePolymarketGateway(
        settings, harness["decision_logger"], harness["pending_store"],
        order_placer=harness["client"], emergency_stop_store=emergency_stop_store,
    )
    harness["gateway"] = gateway
    position = _position(avg_fill_price=0.36, filled_shares=5.0)
    harness["position_store"].add_if_absent(position)
    book = _book(bids=(BookLevel(price=0.50, size=100.0),))
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.REVERSING, signal_count=5), profit_target_pct=0.20,
    )

    submit_dynamic_exit(
        decision, client=harness["client"], gateway=gateway, position_store=harness["position_store"],
        state_store=harness["state_store"], decision_logger=harness["decision_logger"], settings=settings,
        order_placer=harness["client"],
    )

    assert harness["client"].place_order_calls == []
    positions = harness["position_store"].load()
    assert positions[0].exit_pending_order_id is None  # cleared -- retryable once the stop lifts


# --- Fee-aware NET realized P&L (record_exit_fill, unit-level, unchanged) ----

def test_fee_aware_net_pnl_is_less_than_the_gross_move(tmp_path):
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    decision_logger = _logger(tmp_path)
    position = _position(avg_fill_price=0.36, filled_shares=5.0, entry_fee_usd=0.05)
    position_store.add_if_absent(position)

    gross_pnl = 5 * (0.50 - 0.36)
    fill = FillResult(order_id="exit-fee-1", status="filled", requested_shares=5.0, filled_shares=5.0, avg_fill_price=0.50, fee_usd=0.03)
    record_exit_fill(fill, position, position_store=position_store, state_store=state_store, decision_logger=decision_logger, now=datetime.now(timezone.utc))

    state = state_store.load()
    assert state.realized_pnl_usd < gross_pnl
    assert state.realized_pnl_usd == pytest.approx(gross_pnl - 0.05 - 0.03)
