"""Tests for the exit retry/cooldown guard (exit_retry_guard.py) --
added after a live incident showed an automatic exit repeatedly
cycling for the same position:

    EXIT -> UNKNOWN -> EXPIRED -> EXIT -> UNKNOWN -> EXPIRED -> EXIT
    (repeats while the position keeps moving against the thesis)

Two layers, mirroring test_polymarket_entry_guard.py's own style:
  - UNIT tests directly against check_exit_retry_guard()'s pure logic
    (a constructed OpenPosition), isolated from the full
    evaluate_dynamic_exit()/submit_dynamic_exit()/record_exit_fill()
    pipeline.
  - FULL-PIPELINE tests reproducing the exact incident's state machine
    through the real exit_manager.py functions, confirming
    client.place_order is called at most once per blocked retry.

Never places a real order -- every client/placer here is a local fake.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.polymarket.exit_manager import evaluate_dynamic_exit, reconcile_exit_fill, submit_dynamic_exit
from src.polymarket.exit_retry_guard import check_exit_retry_guard
from src.polymarket.gateway import LivePolymarketGateway
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import BookLevel, FillResult, OrderBookSnapshot, Signal, SubmissionOutcome
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.settings import PolymarketSettings
from src.polymarket.state import DailyPnlStateStore
from src.strategy.evidence import MomentumAssessment, MomentumState

_VALID_KEY = "0x" + "a" * 64
_NOW = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)


def _position(**overrides) -> OpenPosition:
    defaults = dict(
        condition_id="c1", token_id="tok-1", outcome="YES", requested_size_usd=5.0, filled_shares=5.0,
        avg_fill_price=0.36, order_id="CZ510YB5PYWT", client_order_id="client-1", status="filled",
        opened_at=_NOW, close_time=_NOW + timedelta(minutes=10),
    )
    defaults.update(overrides)
    return OpenPosition(**defaults)


# --- Unit tests: check_exit_retry_guard()'s pure logic ----------------------

def test_no_prior_failed_attempt_is_never_blocked():
    decision = check_exit_retry_guard(
        _position(), candidate_btc_points=-6.0, cooldown_seconds=90, min_evidence_change=2.0, now=_NOW,
    )
    assert decision.blocked is False


def test_recently_failed_attempt_blocks_within_cooldown_at_unchanged_evidence():
    position = _position(last_exit_attempt_at=_NOW - timedelta(seconds=5), last_exit_attempt_edge_points=-6.0)
    decision = check_exit_retry_guard(
        position, candidate_btc_points=-6.0, cooldown_seconds=90, min_evidence_change=2.0, now=_NOW,
    )
    assert decision.blocked is True
    assert "not materially changed" in decision.reason.lower()


def test_recently_failed_attempt_allows_retry_once_cooldown_elapses():
    position = _position(last_exit_attempt_at=_NOW - timedelta(seconds=200), last_exit_attempt_edge_points=-6.0)
    decision = check_exit_retry_guard(
        position, candidate_btc_points=-6.0, cooldown_seconds=90, min_evidence_change=2.0, now=_NOW,  # evidence unchanged
    )
    assert decision.blocked is False
    assert "cooldown" in decision.reason.lower()


def test_recently_failed_attempt_allows_retry_within_cooldown_if_evidence_materially_changed():
    position = _position(last_exit_attempt_at=_NOW - timedelta(seconds=5), last_exit_attempt_edge_points=-6.0)
    decision = check_exit_retry_guard(
        position, candidate_btc_points=-12.0, cooldown_seconds=90, min_evidence_change=2.0, now=_NOW,  # moved 6 points
    )
    assert decision.blocked is False
    assert "materially changed" in decision.reason.lower()


def test_evidence_change_below_threshold_within_cooldown_still_blocks():
    position = _position(last_exit_attempt_at=_NOW - timedelta(seconds=5), last_exit_attempt_edge_points=-6.0)
    decision = check_exit_retry_guard(
        position, candidate_btc_points=-6.5, cooldown_seconds=90, min_evidence_change=2.0, now=_NOW,  # only 0.5 points
    )
    assert decision.blocked is True


# --- Full pipeline: the exact incident, reproduced and fixed ----------------
# EXIT -> UNKNOWN -> EXPIRED -> EXIT -> UNKNOWN -> EXPIRED -> EXIT, repeating
# with zero cooldown -- see exit_retry_guard.py/exit_manager.py's module
# docstrings.

class _FakeClient:
    def __init__(self):
        self._books: dict[str, OrderBookSnapshot] = {}
        self._fills: dict[str, FillResult] = {}
        self._place_outcome: SubmissionOutcome | None = None
        self.place_order_calls: list = []

    def set_order_book(self, token_id: str, book: OrderBookSnapshot) -> None:
        self._books[token_id] = book

    def set_fill_result(self, exchange_order_id: str, fill: FillResult) -> None:
        self._fills[exchange_order_id] = fill

    def get_order_book(self, token_id: str) -> OrderBookSnapshot:
        return self._books[token_id]

    def get_fill_status(self, exchange_order_id: str) -> FillResult:
        return self._fills[exchange_order_id]

    def set_place_outcome(self, outcome: SubmissionOutcome) -> None:
        self._place_outcome = outcome

    def place_order(self, order):
        self.place_order_calls.append(order)
        return self._place_outcome


def _book(**overrides) -> OrderBookSnapshot:
    defaults = dict(
        token_id="tok-1", bids=(BookLevel(price=0.40, size=100.0),), asks=(BookLevel(price=0.42, size=100.0),),
        fetched_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return OrderBookSnapshot(**defaults)


def _assessment(evidence_score: float, *, signal_count: int = 5):
    """A REVERSING BtcMarketAssessment with a specific btc_points
    (= -evidence_score) reading -- isolates the retry-guard mechanics
    from how that score is derived from real bars (covered elsewhere)."""
    from src.polymarket.btc_intelligence import BtcMarketAssessment

    fired = tuple(f"signal_{i}" for i in range(signal_count))
    momentum = MomentumAssessment(
        state=MomentumState.REVERSING, weakening_score=evidence_score, strengthening_score=0, signals=fired,
    )
    return BtcMarketAssessment(state=MomentumState.REVERSING, evidence_score=evidence_score, btc_assessment=momentum, signals=())


def _settings(**overrides) -> PolymarketSettings:
    env = dict(
        POLYMARKET_TRADING_MODE="live", POLYMARKET_PRIVATE_KEY=_VALID_KEY,
        POLYMARKET_LIVE_TRADING_CONFIRMED="true", POLYMARKET_AUTO_EXIT_ENABLED="true",
        POLYMARKET_DYNAMIC_EXIT_ENABLED="true",
    )
    env.update(overrides)
    return PolymarketSettings.from_env(env=env)


def _logger(tmp_path: Path) -> PolymarketDecisionLogger:
    return PolymarketDecisionLogger(tmp_path / "decisions.jsonl", also_console=False)


def _harness(tmp_path: Path, **settings_overrides):
    settings = _settings(**settings_overrides)
    client = _FakeClient()
    decision_logger = _logger(tmp_path)
    pending_store = PolymarketPendingOrderStore(tmp_path / "pending.json")
    position_store = PolymarketPositionStore(tmp_path / "positions.json")
    state_store = DailyPnlStateStore(tmp_path / "pnl.json")
    from src.execution.emergency_stop import EmergencyStopStore
    estop = EmergencyStopStore(tmp_path / "estop.json")
    estop.clear(authorized_by="test", reason="test")
    gateway = LivePolymarketGateway(settings, decision_logger, pending_store, order_placer=client, emergency_stop_store=estop)
    return dict(
        settings=settings, client=client, gateway=gateway, position_store=position_store,
        pending_store=pending_store, state_store=state_store, decision_logger=decision_logger,
    )


def test_unknown_then_expired_blocks_an_immediate_retry_on_unchanged_evidence(tmp_path):
    """Reproduces the live incident's exact state machine and proves
    the fix: UNKNOWN -> a retry attempt is already blocked by the
    pre-existing idempotency guard -> the exit resolves EXPIRED
    (authoritative, no fill) -> a FURTHER retry on the SAME, still
    exit-worthy evidence must now ALSO be blocked -- by the retry
    guard, not resubmitted unconditionally -- until the cooldown
    elapses or the evidence materially changes. Never more than ONE
    real order placed throughout."""
    harness = _harness(tmp_path)
    settings = harness["settings"]
    position = _position()
    harness["position_store"].add_if_absent(position)
    book = _book(bids=(BookLevel(price=0.40, size=100.0),))
    harness["client"].set_order_book("tok-1", book)
    assessment = _assessment(6.0)  # btc_points = -6.0, materially REVERSING

    decision = evaluate_dynamic_exit(
        position, book, assessment, profit_target_pct=0.20,
        exit_retry_cooldown_seconds=settings.exit_retry_cooldown_seconds,
        exit_retry_min_evidence_change=settings.exit_retry_min_evidence_change,
    )
    assert decision.eligible is True  # no prior failed attempt yet -- nothing to rate-limit

    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-1", raw_status="matched"))
    harness["client"].set_fill_result("exit-1", FillResult(
        order_id="exit-1", status="unknown", requested_shares=5.0, filled_shares=0.0, avg_fill_price=None,
    ))
    submit_dynamic_exit(
        decision, client=harness["client"], gateway=harness["gateway"], position_store=harness["position_store"],
        state_store=harness["state_store"], decision_logger=harness["decision_logger"], settings=settings,
        order_placer=harness["client"],
    )
    pending1 = harness["position_store"].get(position.client_order_id)
    assert pending1.exit_pending_order_id is not None  # UNKNOWN -- left pending, never assumed filled
    assert len(harness["client"].place_order_calls) == 1

    # A retry cycle while still UNKNOWN: the PRE-EXISTING idempotency
    # guard (exit_pending_order_id) already blocks this unconditionally.
    decision2 = evaluate_dynamic_exit(
        pending1, book, assessment, profit_target_pct=0.20,
        exit_retry_cooldown_seconds=settings.exit_retry_cooldown_seconds,
        exit_retry_min_evidence_change=settings.exit_retry_min_evidence_change,
    )
    assert decision2.eligible is False
    assert "pending" in decision2.reason.lower()

    # The exit now authoritatively resolves EXPIRED (no fill).
    harness["client"].set_fill_result("exit-1", FillResult(
        order_id="exit-1", status="expired", requested_shares=5.0, filled_shares=0.0, avg_fill_price=None,
    ))
    resolved = reconcile_exit_fill(
        pending1, client=harness["client"], pending_store=harness["pending_store"],
        position_store=harness["position_store"], state_store=harness["state_store"],
        decision_logger=harness["decision_logger"],
    )
    assert resolved.exit_pending_order_id is None  # free to retry...
    assert resolved.last_exit_attempt_at is not None  # ...but now rate-limited by the retry guard

    # THE FIX: an immediate retry on the SAME, still exit-worthy
    # evidence must be BLOCKED -- this is exactly where the old code
    # resubmitted unconditionally, producing the repeating incident.
    decision3 = evaluate_dynamic_exit(
        resolved, book, assessment, profit_target_pct=0.20,
        exit_retry_cooldown_seconds=settings.exit_retry_cooldown_seconds,
        exit_retry_min_evidence_change=settings.exit_retry_min_evidence_change,
    )
    assert decision3.eligible is False
    assert "not materially changed" in decision3.reason.lower()
    assert len(harness["client"].place_order_calls) == 1  # still only the ONE real submission ever


def test_retry_permitted_once_the_cooldown_elapses(tmp_path):
    harness = _harness(tmp_path, POLYMARKET_EXIT_RETRY_COOLDOWN_SECONDS="60")
    settings = harness["settings"]
    position = _position()
    harness["position_store"].add_if_absent(position)
    book = _book(bids=(BookLevel(price=0.40, size=100.0),))
    harness["client"].set_order_book("tok-1", book)
    assessment = _assessment(6.0)

    decision = evaluate_dynamic_exit(
        position, book, assessment, profit_target_pct=0.20,
        exit_retry_cooldown_seconds=settings.exit_retry_cooldown_seconds,
        exit_retry_min_evidence_change=settings.exit_retry_min_evidence_change,
    )
    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-1", raw_status="matched"))
    harness["client"].set_fill_result("exit-1", FillResult(
        order_id="exit-1", status="expired", requested_shares=5.0, filled_shares=0.0, avg_fill_price=None,
    ))
    submit_dynamic_exit(
        decision, client=harness["client"], gateway=harness["gateway"], position_store=harness["position_store"],
        state_store=harness["state_store"], decision_logger=harness["decision_logger"], settings=settings,
        order_placer=harness["client"],
    )
    resolved = harness["position_store"].get(position.client_order_id)
    assert resolved.exit_pending_order_id is None
    assert resolved.last_exit_attempt_at is not None

    # Still within the cooldown -- blocked.
    blocked = evaluate_dynamic_exit(
        resolved, book, assessment, profit_target_pct=0.20,
        exit_retry_cooldown_seconds=60.0, exit_retry_min_evidence_change=100.0,  # evidence threshold unreachable -- isolates the cooldown path
        now=resolved.last_exit_attempt_at + timedelta(seconds=10),
    )
    assert blocked.eligible is False

    # Cooldown elapsed -- retry permitted on the SAME unchanged evidence.
    permitted = evaluate_dynamic_exit(
        resolved, book, assessment, profit_target_pct=0.20,
        exit_retry_cooldown_seconds=60.0, exit_retry_min_evidence_change=100.0,
        now=resolved.last_exit_attempt_at + timedelta(seconds=75),
    )
    assert permitted.eligible is True


def test_retry_permitted_within_cooldown_when_evidence_materially_changes(tmp_path):
    harness = _harness(tmp_path, POLYMARKET_EXIT_RETRY_COOLDOWN_SECONDS="600", POLYMARKET_EXIT_RETRY_MIN_EVIDENCE_CHANGE="2.0")
    settings = harness["settings"]
    position = _position()
    harness["position_store"].add_if_absent(position)
    book = _book(bids=(BookLevel(price=0.40, size=100.0),))
    harness["client"].set_order_book("tok-1", book)
    assessment = _assessment(6.0)  # btc_points = -6.0

    decision = evaluate_dynamic_exit(
        position, book, assessment, profit_target_pct=0.20,
        exit_retry_cooldown_seconds=settings.exit_retry_cooldown_seconds,
        exit_retry_min_evidence_change=settings.exit_retry_min_evidence_change,
    )
    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-1", raw_status="matched"))
    harness["client"].set_fill_result("exit-1", FillResult(
        order_id="exit-1", status="expired", requested_shares=5.0, filled_shares=0.0, avg_fill_price=None,
    ))
    submit_dynamic_exit(
        decision, client=harness["client"], gateway=harness["gateway"], position_store=harness["position_store"],
        state_store=harness["state_store"], decision_logger=harness["decision_logger"], settings=settings,
        order_placer=harness["client"],
    )
    resolved = harness["position_store"].get(position.client_order_id)
    assert resolved.last_exit_attempt_edge_points == pytest.approx(-6.0)

    # Same evidence, well within the 600s cooldown -- blocked.
    unchanged = evaluate_dynamic_exit(
        resolved, book, assessment, profit_target_pct=0.20,
        exit_retry_cooldown_seconds=settings.exit_retry_cooldown_seconds,
        exit_retry_min_evidence_change=settings.exit_retry_min_evidence_change,
    )
    assert unchanged.eligible is False

    # Evidence moves materially (btc_points -6.0 -> -12.0, a 6-point
    # swing, well past the 2.0 threshold) -- retry permitted despite
    # being nowhere near the 600s cooldown.
    stronger = _assessment(12.0)
    permitted = evaluate_dynamic_exit(
        resolved, book, stronger, profit_target_pct=0.20,
        exit_retry_cooldown_seconds=settings.exit_retry_cooldown_seconds,
        exit_retry_min_evidence_change=settings.exit_retry_min_evidence_change,
    )
    assert permitted.eligible is True


def test_a_genuine_fill_clears_the_retry_guard_history(tmp_path):
    """A successful (even partial) fill means there's nothing left to
    rate-limit -- the next decision for the remaining shares must start
    with a clean slate, not inherit a stale failed-attempt record."""
    harness = _harness(tmp_path)
    settings = harness["settings"]
    position = _position(filled_shares=5.0)
    harness["position_store"].add_if_absent(position)
    book = _book(bids=(BookLevel(price=0.40, size=100.0),))
    harness["client"].set_order_book("tok-1", book)
    assessment = _assessment(6.0)

    decision = evaluate_dynamic_exit(
        position, book, assessment, profit_target_pct=0.20,
        exit_retry_cooldown_seconds=settings.exit_retry_cooldown_seconds,
        exit_retry_min_evidence_change=settings.exit_retry_min_evidence_change,
    )
    harness["client"].set_place_outcome(SubmissionOutcome(ok=True, exchange_order_id="exit-1", raw_status="matched"))
    harness["client"].set_fill_result("exit-1", FillResult(
        order_id="exit-1", status="partially_filled", requested_shares=5.0, filled_shares=3.0, avg_fill_price=0.40,
    ))
    submit_dynamic_exit(
        decision, client=harness["client"], gateway=harness["gateway"], position_store=harness["position_store"],
        state_store=harness["state_store"], decision_logger=harness["decision_logger"], settings=settings,
        order_placer=harness["client"],
    )
    updated = harness["position_store"].get(position.client_order_id)
    assert updated.filled_shares == pytest.approx(2.0)
    assert updated.exit_pending_order_id is None
    assert updated.last_exit_attempt_at is None  # cleared -- nothing to rate-limit after a real fill
    assert updated.last_exit_attempt_edge_points is None
