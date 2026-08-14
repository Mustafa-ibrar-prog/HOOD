"""Tests for the core "should we HOLD / EXIT / TARGET_EXIT / STOP_EXIT this
open position?" decision logic — including the exact scenario from the
requirements: entry $0.95, price moves to $1.05, and the call is decided by
the strength of the evidence, not by whether the $20 target was hit.
"""

from __future__ import annotations

from src.position_manager.evaluator import EvaluatorConfig, PositionEvaluator, PositionSnapshot
from src.strategy.decision import Decision
from src.strategy.evidence import MomentumEvidence
from tests.conftest import make_position

STRONG_CONTINUATION = MomentumEvidence(
    thesis_direction="bullish",
    rsi=62.0,
    rsi_prev=58.0,
    macd_histogram=0.10,
    macd_histogram_prev=0.05,
    ema_fast=105.0,
    ema_slow=100.0,
    higher_highs=True,
    lower_highs=False,
    breakout_continuation=True,
    failed_breakout=False,
    reversal_signal=False,
    volume_ratio=1.4,
)

WEAKENED_PEAKED = MomentumEvidence(
    thesis_direction="bullish",
    rsi=74.0,
    rsi_prev=79.0,
    macd_histogram=0.01,
    macd_histogram_prev=0.08,
    ema_fast=100.2,
    ema_slow=100.0,
    higher_highs=False,
    lower_highs=True,
    breakout_continuation=False,
    failed_breakout=True,
    reversal_signal=False,
    volume_ratio=0.5,
)

NEUTRAL_PAUSE = MomentumEvidence(
    thesis_direction="bullish",
    rsi=45.0,
    rsi_prev=None,
    macd_histogram=0.05,
    macd_histogram_prev=None,
    ema_fast=None,
    ema_slow=None,
    higher_highs=False,
    lower_highs=False,
    breakout_continuation=False,
    failed_breakout=False,
    reversal_signal=False,
    volume_ratio=1.0,
)

SPARSE_DATA = MomentumEvidence(thesis_direction="bullish", rsi=55.0)


def _snapshot(**overrides) -> PositionSnapshot:
    position = overrides.pop("position", None) or make_position()
    defaults = dict(
        position=position,
        option_price=1.05,
        momentum=STRONG_CONTINUATION,
        minutes_to_expiration=60 * 24 * 5,  # 5 days out, not an expiration concern
    )
    defaults.update(overrides)
    return PositionSnapshot(**defaults)


def test_example_scenario_hold_on_strong_continued_momentum():
    """Entry $0.95 -> $1.05, profit target $20 not reached ($10 pnl at
    qty=1), but momentum evidence shows strong continuation: HOLD."""
    evaluator = PositionEvaluator()
    snapshot = _snapshot(option_price=1.05, momentum=STRONG_CONTINUATION)
    result = evaluator.evaluate(snapshot)
    assert result.decision is Decision.HOLD
    assert result.evidence["pnl_usd"] == 10.0


def test_example_scenario_exit_when_momentum_has_peaked():
    """Same price move, but the evidence shows the move has weakened/peaked:
    EXIT early, well before the $20 target."""
    evaluator = PositionEvaluator()
    snapshot = _snapshot(option_price=1.05, momentum=WEAKENED_PEAKED)
    result = evaluator.evaluate(snapshot)
    assert result.decision is Decision.EXIT
    assert result.evidence["pnl_usd"] == 10.0
    assert result.evidence["pnl_usd"] < make_position().profit_target_usd


def test_does_not_exit_on_a_mere_pause():
    """Flat/neutral evidence with no corroborating weakening signals must
    result in HOLD, never EXIT — a pause alone is not evidence."""
    evaluator = PositionEvaluator()
    snapshot = _snapshot(option_price=1.02, momentum=NEUTRAL_PAUSE)  # small, positive, unremarkable move
    result = evaluator.evaluate(snapshot)
    assert result.decision is Decision.HOLD


def test_target_exit_when_target_reached_and_momentum_not_strengthening():
    evaluator = PositionEvaluator()
    # entry 0.95, price 1.15 -> pnl = 0.20 * 100 = $20, meets target exactly
    snapshot = _snapshot(option_price=1.15, momentum=NEUTRAL_PAUSE)
    result = evaluator.evaluate(snapshot)
    assert result.decision is Decision.TARGET_EXIT
    assert result.evidence["pnl_usd"] >= 20.0


def test_holds_past_target_when_momentum_still_strengthening():
    """Do NOT require the system to wait for the $20 target — and
    symmetrically, don't force an exit there either if the evidence still
    supports the move."""
    evaluator = PositionEvaluator()
    snapshot = _snapshot(option_price=1.25, momentum=STRONG_CONTINUATION)  # pnl = $30, well past target
    result = evaluator.evaluate(snapshot)
    assert result.decision is Decision.HOLD


def test_stop_exit_on_hard_stop_loss_regardless_of_momentum():
    evaluator = PositionEvaluator()
    position = make_position(entry_price=0.95, stop_loss_usd=15.0)
    # price 0.80 -> pnl = (0.80-0.95)*100 = -$15.00, at the stop
    snapshot = _snapshot(position=position, option_price=0.80, momentum=STRONG_CONTINUATION)
    result = evaluator.evaluate(snapshot)
    assert result.decision is Decision.STOP_EXIT


def test_stop_exit_when_thesis_invalidated_even_if_profitable():
    evaluator = PositionEvaluator()
    snapshot = _snapshot(
        option_price=1.05,
        momentum=STRONG_CONTINUATION,
        thesis_invalidated=True,
        thesis_invalidation_reason="underlying closed back below the breakout level",
    )
    result = evaluator.evaluate(snapshot)
    assert result.decision is Decision.STOP_EXIT
    assert "invalidated" in result.reason.lower()


def test_target_exit_near_expiration_when_profitable():
    evaluator = PositionEvaluator(EvaluatorConfig(expiration_buffer_minutes=30))
    snapshot = _snapshot(option_price=1.05, momentum=STRONG_CONTINUATION, minutes_to_expiration=15)
    result = evaluator.evaluate(snapshot)
    assert result.decision is Decision.TARGET_EXIT
    assert "expiration" in result.reason.lower()


def test_stop_exit_near_expiration_when_unprofitable():
    evaluator = PositionEvaluator(EvaluatorConfig(expiration_buffer_minutes=30))
    snapshot = _snapshot(option_price=0.90, momentum=STRONG_CONTINUATION, minutes_to_expiration=15)
    result = evaluator.evaluate(snapshot)
    assert result.decision is Decision.STOP_EXIT
    assert "expiration" in result.reason.lower()


def test_hold_on_insufficient_data_never_guesses_an_exit():
    evaluator = PositionEvaluator()
    snapshot = _snapshot(option_price=1.05, momentum=SPARSE_DATA)
    result = evaluator.evaluate(snapshot)
    assert result.decision is Decision.HOLD
    assert result.confidence < 0.5


def test_min_weakening_signal_count_is_configurable():
    """Raising the required corroborating-signal count should be able to
    turn a would-be EXIT back into a HOLD."""
    strict_evaluator = PositionEvaluator(EvaluatorConfig(min_weakening_signals_for_exit=10))
    snapshot = _snapshot(option_price=1.05, momentum=WEAKENED_PEAKED)
    result = strict_evaluator.evaluate(snapshot)
    assert result.decision is Decision.HOLD


def test_every_decision_carries_a_nonempty_reason_and_evidence():
    evaluator = PositionEvaluator()
    for momentum in (STRONG_CONTINUATION, WEAKENED_PEAKED, NEUTRAL_PAUSE, SPARSE_DATA):
        snapshot = _snapshot(option_price=1.05, momentum=momentum)
        result = evaluator.evaluate(snapshot)
        assert result.reason
        assert "pnl_usd" in result.evidence
