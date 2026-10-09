"""Tests for the evidence-gated dynamic exit system (exit_manager.py).

Two layers are tested separately, on purpose:
  - The CASCADE (evaluate_dynamic_exit / compute_edge_assessment) is
    tested against directly-constructed BtcMarketAssessment objects
    (via `_assessment()` below) -- its job is "given a bundle of
    signals and a profit level, what's the decision," independent of
    how those signals were derived from real bars (that translation is
    btc_intelligence.py's job, covered by
    tests/test_polymarket_btc_intelligence.py; the full, realistic
    bars-to-decision replay scenarios the v2 redesign was built around
    live in tests/test_polymarket_dynamic_exit_evidence_model.py).
  - The FULL PIPELINE (check_and_execute_dynamic_exits, end to end,
    with a live order book / position store / paper or live gateway)
    is tested with real OrderBookSnapshots and a minimal fake client,
    mirroring test_polymarket_reconciliation.py's style.

v2 (continuous evidence/expected-value model, see exit_manager.py's
module docstring): P&L never independently triggers an exit here --
_assessment()'s default signal synthesis (below) still lets every
pre-existing non-cascade-specific test (fill reconciliation,
idempotency, emergency stop, live_auto_execute) construct an
"obviously eligible" or "obviously not eligible" decision without
hand-building Signal tuples itself. The cascade-specific tests in this
file cover the mechanics (hard safety, liquidity/no-bid/already-
pending guards, the supporting/opposing majority rule); the 8
user-specified P&L-vs-evidence replay scenarios live in the dedicated
file named above.
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
    compute_edge_assessment,
    compute_target_price,
    evaluate_dynamic_exit,
    record_exit_fill,
    reconcile_exit_fill,
    submit_dynamic_exit,
)
from src.polymarket.gateway import LivePolymarketGateway, PaperPolymarketGateway
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import BookLevel, FillResult, OrderBookSnapshot, Signal, SubmissionOutcome
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


def _assessment(
    state: MomentumState, *, signal_count: int = 3, evidence_score: int | None = None,
    microstructure_signals: tuple[Signal, ...] = (),
) -> BtcMarketAssessment:
    """Directly constructs a BtcMarketAssessment -- isolates the
    CASCADE's own logic from how that state is derived from real bars
    (see module docstring).

    `signal_count` sets the number of NAMED fired conditions on the
    nested MomentumAssessment (btc_assessment.btc_assessment.signals)
    -- the exact quantity compute_edge_assessment()'s
    btc_fired_signal_count reads, and what
    config.min_weakening_signals_for_exit gates on (see
    exit_manager.py -- this is the SAME quantity/threshold the pre-v2
    cascade used).

    `evidence_score` sets the top-level weakening-minus-strengthening
    score (btc_points = -evidence_score). When omitted, a value
    consistent with `state` is used: positive (weakening-dominant, so
    btc_points is negative/opposing) for WEAKENING/REVERSING, negative
    (so btc_points is positive/supporting) for STRENGTHENING, 0 for
    STABLE/INSUFFICIENT_DATA -- so tests that only care about the
    state don't have to compute a raw score by hand.

    `microstructure_signals` are Polymarket-sourced Signal objects
    (source prefixed "polymarket_") for testing the corroboration/
    veto mechanism specifically -- compute_edge_assessment() ignores
    any signal whose source isn't "polymarket_"-prefixed (see its own
    docstring on why raw per-indicator BTC signals are never read this
    way)."""
    fired = tuple(f"signal_{i}" for i in range(signal_count))
    if evidence_score is None:
        evidence_score = _default_evidence_score_for_state(state)
    momentum = MomentumAssessment(
        state=state, weakening_score=max(evidence_score, 0), strengthening_score=max(-evidence_score, 0), signals=fired,
    )
    return BtcMarketAssessment(state=state, evidence_score=evidence_score, btc_assessment=momentum, signals=microstructure_signals)


def _default_evidence_score_for_state(state: MomentumState) -> int:
    if state is MomentumState.REVERSING:
        return 6
    if state is MomentumState.WEAKENING:
        return 3
    if state is MomentumState.STRENGTHENING:
        return -3
    return 0  # STABLE / INSUFFICIENT_DATA


def _microstructure_signal(source: str, *, direction: str, confidence: float) -> Signal:
    return Signal(source=source, timestamp=datetime.now(timezone.utc), value=1.0, direction=direction, confidence=confidence)


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


def _live_harness(
    tmp_path: Path, *, auto_exit_enabled: bool = True, dynamic_exit_enabled: bool = True, live_auto_execute: bool = False,
):
    settings = _settings(
        POLYMARKET_TRADING_MODE="live", POLYMARKET_PRIVATE_KEY=_VALID_KEY,
        POLYMARKET_LIVE_TRADING_CONFIRMED="true",
        POLYMARKET_AUTO_EXIT_ENABLED="true" if auto_exit_enabled else "false",
        POLYMARKET_DYNAMIC_EXIT_ENABLED="true" if dynamic_exit_enabled else "false",
        POLYMARKET_LIVE_AUTO_EXECUTE="true" if live_auto_execute else "false",
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


# --- evaluate_dynamic_exit: v2 continuous evidence/expected-value model -----
# The pre-v2 decision table (target+strengthening->hold, target+weakening->
# exit, unprofitable-never-exits-on-reversal-alone, etc.) tested P&L-gated
# behavior this redesign deliberately removed -- see exit_manager.py's
# module docstring. These tests cover the SAME mechanics (hard safety,
# corroboration-count/majority rule) under the new model; the user's 8
# explicit P&L-vs-evidence replay scenarios, built from realistic BTC bars
# through the real assess_btc_market() pipeline, live in
# tests/test_polymarket_dynamic_exit_evidence_model.py.

def test_insufficient_data_holds_regardless_of_profit():
    position = _position(avg_fill_price=0.36)
    book = _book(bids=(BookLevel(price=0.50, size=100.0),))  # would clearly hit target if evaluated
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.INSUFFICIENT_DATA), profit_target_pct=0.20,
    )
    assert decision.eligible is False
    assert "insufficient" in decision.reason.lower()


def test_strongly_opposing_evidence_exits_even_when_profitable():
    """+20% profit + strongly deteriorating evidence -> EXIT. Profit
    alone never protects a position whose edge has gone negative."""
    position = _position(avg_fill_price=0.36)
    book = _book(bids=(BookLevel(price=0.44, size=100.0),))
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.REVERSING, signal_count=5), profit_target_pct=0.20,
    )
    assert decision.eligible is True


def test_strongly_supporting_evidence_holds_even_well_past_target():
    """+35% profit + strongly supporting evidence -> HOLD. A soft
    profit target reached is never, by itself, a reason to exit."""
    position = _position(avg_fill_price=0.36)  # 35% gain = 0.486
    book = _book(bids=(BookLevel(price=0.486, size=100.0),))
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.STRENGTHENING), profit_target_pct=0.20,
    )
    assert decision.eligible is False
    assert "p&l is context" in decision.reason.lower()


def test_unprofitable_position_exits_on_strong_opposing_evidence():
    """A position currently at a loss, with strongly deteriorating
    evidence, must still EXIT -- cutting further loss on real evidence
    is exactly the expected-value behavior this redesign adds. (Mirrors
    the user's replay scenario 2 with synthetic signals; see the
    dedicated replay-scenario file for the realistic-bars version.)"""
    position = _position(avg_fill_price=0.50)  # currently a loss at the book below
    book = _book(bids=(BookLevel(price=0.40, size=100.0),))
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.REVERSING, signal_count=5), profit_target_pct=0.20,
    )
    assert decision.eligible is True


def test_unprofitable_position_holds_on_strong_supporting_evidence():
    """A position deeply underwater, with strongly supporting evidence,
    must HOLD -- the loss is context, not a trigger (replay scenario 1
    with synthetic signals)."""
    position = _position(avg_fill_price=0.50)
    book = _book(bids=(BookLevel(price=0.25, size=100.0),))  # -50%
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.STRENGTHENING, signal_count=5), profit_target_pct=0.20,
    )
    assert decision.eligible is False


def test_weakening_without_enough_opposing_signals_holds():
    """Fewer opposing signals than min_weakening_signals_for_exit must
    NOT trigger an early exit -- a single soft signal is never enough
    (mirrors evaluate_momentum's own guarantee)."""
    position = _position(avg_fill_price=0.36)
    book = _book(bids=(BookLevel(price=0.37, size=100.0),))
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.WEAKENING, signal_count=1),
        profit_target_pct=0.20, config=DynamicExitConfig(min_weakening_signals_for_exit=2),
    )
    assert decision.eligible is False


def test_stable_btc_evidence_holds():
    """STABLE (weakening roughly balances strengthening, i.e.
    genuinely conflicting/ambiguous BTC evidence) must HOLD -- the
    materiality gate requires WEAKENING/REVERSING specifically, so
    ambiguous evidence never guesses a direction (replay scenario 6;
    see tests/test_polymarket_dynamic_exit_evidence_model.py for the
    realistic-bars version of this exact scenario)."""
    position = _position(avg_fill_price=0.36)
    book = _book(bids=(BookLevel(price=0.40, size=100.0),))
    decision = evaluate_dynamic_exit(position, book, _assessment(MomentumState.STABLE), profit_target_pct=0.20)
    assert decision.eligible is False


def test_polymarket_microstructure_vetoes_an_otherwise_material_btc_exit():
    """The v2 redesign's whole point for microstructure: a materially
    WEAKENING/REVERSING BTC read (which alone WOULD exit) must be
    HELD when Polymarket's own order-book flow clearly contradicts it
    -- real continued buying pressure despite softening technicals is
    exactly the kind of corroborating-evidence check this was built
    for. See EdgeAssessment's docstring for why this is a veto on an
    already-material BTC read, not an independent trigger."""
    position = _position(avg_fill_price=0.36)
    book = _book(bids=(BookLevel(price=0.40, size=100.0),))

    without_microstructure = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.REVERSING, signal_count=5), profit_target_pct=0.20,
    )
    assert without_microstructure.eligible is True

    contradicting_microstructure = (
        _microstructure_signal("polymarket_order_book_imbalance", direction="bullish", confidence=0.6),
        _microstructure_signal("polymarket_price_momentum", direction="bullish", confidence=0.5),
    )
    vetoed = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.REVERSING, signal_count=5, microstructure_signals=contradicting_microstructure),
        profit_target_pct=0.20,
    )
    assert vetoed.eligible is False
    assert "order-book flow contradicts" in vetoed.reason.lower()


def test_polymarket_microstructure_never_triggers_an_exit_on_its_own():
    """Strongly bearish microstructure signals alone, with BTC
    evidence STRENGTHENING, must never exit -- microstructure is
    corroboration/veto on an already-material BTC read, never an
    independent trigger (see EdgeAssessment's docstring)."""
    position = _position(avg_fill_price=0.36)
    book = _book(bids=(BookLevel(price=0.40, size=100.0),))
    opposing_microstructure = (
        _microstructure_signal("polymarket_order_book_imbalance", direction="bearish", confidence=0.6),
        _microstructure_signal("polymarket_price_momentum", direction="bearish", confidence=0.5),
        _microstructure_signal("polymarket_trade_flow", direction="bearish", confidence=0.3),
    )
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.STRENGTHENING, microstructure_signals=opposing_microstructure),
        profit_target_pct=0.20,
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


# --- live_auto_execute / auto_exit_enabled interaction -------------------------
# Traced directly from gateway.py/exit_manager.py's source (not just the
# docstrings): LivePolymarketGateway.submit_order() checks settings.
# live_auto_execute FIRST, for EVERY order it submits, entry or exit alike.
# auto_exit_enabled is a SEPARATE flag submit_dynamic_exit() itself checks,
# but only AFTER gateway.submit_order() has already returned --  and only
# if that result was "awaiting_approval". Consequence: if live_auto_execute
# is True, every order (including an exit) submits immediately and
# auto_exit_enabled is never even consulted. The reverse is representable
# (entries manual, exits automatic, via auto_exit_enabled=True with
# live_auto_execute=False -- already exercised by every _live_harness-based
# fill test above, whose default is exactly that combination), but there is
# NO configuration that makes entries automatic while keeping exits manual.

def test_live_auto_execute_true_submits_the_exit_immediately_even_with_auto_exit_enabled_false(tmp_path):
    """The one genuinely surprising case: auto_exit_enabled=False does NOT
    force manual confirmation on an exit when live_auto_execute=True --
    that flag is checked first and wins, for every order."""
    harness = _live_harness(tmp_path, auto_exit_enabled=False, live_auto_execute=True)
    assert harness["settings"].live_auto_execute is True
    assert harness["settings"].auto_exit_enabled is False
    position = _position(avg_fill_price=0.36, filled_shares=5.0)
    harness["position_store"].add_if_absent(position)
    book = _book(bids=(BookLevel(price=0.50, size=100.0),))
    harness["client"].set_order_book("tok-1", book)
    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-auto-1", raw_status="matched"))
    harness["client"].set_fill_result("exit-auto-1", FillResult(
        order_id="exit-auto-1", status="filled", requested_shares=5.0, filled_shares=5.0, avg_fill_price=0.50,
    ))
    decision = evaluate_dynamic_exit(
        position, book, _assessment(MomentumState.REVERSING, signal_count=5), profit_target_pct=0.20,
    )
    assert decision.eligible is True

    result = submit_dynamic_exit(
        decision, client=harness["client"], gateway=harness["gateway"], position_store=harness["position_store"],
        state_store=harness["state_store"], decision_logger=harness["decision_logger"], settings=harness["settings"],
        order_placer=harness["client"],
    )

    assert result.status == "submitted"  # never stopped at awaiting_approval, despite auto_exit_enabled=False
    assert len(harness["client"].place_order_calls) == 1  # reached the exchange immediately
    assert harness["position_store"].load() == []  # reconciled synchronously


def test_awaiting_approval_exit_is_pushed_through_only_by_an_explicit_confirm_and_place_call(tmp_path):
    """The "B: manual confirmation" lifecycle (live_auto_execute=False,
    auto_exit_enabled=False): submit_dynamic_exit() stops the exit at
    awaiting_approval -- nothing reaches the exchange yet -- and only a
    SEPARATE, explicit gateway.confirm_and_place() call (what
    scripts/confirm_pending_order.py and scripts/confirm_polymarket_order.py
    do, generically, for either side -- see gateway.py's module docstring)
    pushes it through, after which the normal reconcile_exit_fill() sweep
    closes the position exactly as it would for an entry."""
    harness = _live_harness(tmp_path, auto_exit_enabled=False, live_auto_execute=False)
    assert harness["settings"].live_auto_execute is False
    assert harness["settings"].auto_exit_enabled is False
    position = _position(avg_fill_price=0.36, filled_shares=5.0)
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
        order_placer=harness["client"],
    )
    assert result.status == "awaiting_approval"
    assert harness["client"].place_order_calls == []  # nothing reached the exchange yet
    pending_order_id = result.extra["pending_order_id"]
    pending_position = harness["position_store"].get(position.client_order_id)
    assert pending_position.exit_pending_order_id == pending_order_id

    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-manual-1", raw_status="matched"))
    harness["client"].set_fill_result("exit-manual-1", FillResult(
        order_id="exit-manual-1", status="filled", requested_shares=5.0, filled_shares=5.0, avg_fill_price=0.50,
    ))

    # The human confirmation step.
    confirmed = harness["gateway"].confirm_and_place(
        pending_order_id, harness["client"], approved_by="human:test-operator",
    )
    assert confirmed.status == "submitted"
    assert len(harness["client"].place_order_calls) == 1  # reached the exchange only now, on explicit approval

    reconciled = reconcile_exit_fill(
        pending_position, client=harness["client"], pending_store=harness["pending_store"],
        position_store=harness["position_store"], state_store=harness["state_store"],
        decision_logger=harness["decision_logger"],
    )
    assert reconciled is None  # fully closed
    assert harness["position_store"].load() == []


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
