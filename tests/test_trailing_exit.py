"""Tests for the deterministic dynamic/trailing exit engine: the exact
worked example from the requirement — entry $0.95, target $1.15, price
reaches $1.05 (arming trailing), then gives back enough to trigger an EXIT
before the $1.15 target is ever reached."""

from __future__ import annotations

from src.position_manager.evaluator import EvaluatorConfig, PositionEvaluator, PositionSnapshot
from src.position_manager.peak_tracker import PeakPriceStore
from src.strategy.decision import Decision
from src.strategy.evidence import MomentumEvidence
from tests.conftest import make_position

NEUTRAL = MomentumEvidence(
    thesis_direction="bullish",
    rsi=55.0,
    rsi_prev=54.0,
    macd_histogram=0.02,
    macd_histogram_prev=0.02,
    ema_fast=101.0,
    ema_slow=100.0,
    higher_highs=False,
    lower_highs=False,
    breakout_continuation=False,
    failed_breakout=False,
    reversal_signal=False,
    volume_ratio=1.0,
)


def _snapshot(option_price: float, peak_price: float, **overrides) -> PositionSnapshot:
    position = overrides.pop("position", None) or make_position()  # entry=$0.95, target_usd=$20 -> target price $1.15
    defaults = dict(
        position=position,
        option_price=option_price,
        peak_price=peak_price,
        momentum=NEUTRAL,
        minutes_to_expiration=60 * 24 * 5,
    )
    defaults.update(overrides)
    return PositionSnapshot(**defaults)


def test_worked_example_exits_at_1_02_after_peaking_at_1_05():
    """Entry $0.95, target $1.15. Peak reaches $1.05 (arms trailing at 50%
    of the way to target). Price falls back to $1.02 (30% giveback of the
    $0.10 gained from entry to peak) -> EXIT, not TARGET_EXIT, and well
    before $1.15."""
    evaluator = PositionEvaluator()
    snapshot = _snapshot(option_price=1.02, peak_price=1.05)
    result = evaluator.evaluate(snapshot)
    assert result.decision is Decision.EXIT
    assert "Trailing exit" in result.reason
    assert "1.05" in result.reason


def test_not_armed_below_the_arm_threshold_never_exits_on_pullback():
    """Peak only reached $1.00 (below the $1.05 arm price) — trailing isn't
    armed yet, so a pullback to $0.98 must NOT trigger a trailing exit."""
    evaluator = PositionEvaluator()
    snapshot = _snapshot(option_price=0.98, peak_price=1.00)
    result = evaluator.evaluate(snapshot)
    assert result.decision is not Decision.EXIT or "Trailing exit" not in result.reason


def test_armed_but_no_giveback_yet_holds():
    """Peak at $1.05 (armed), but current price is still at the peak — no
    giveback has happened yet, so no trailing exit."""
    evaluator = PositionEvaluator()
    snapshot = _snapshot(option_price=1.05, peak_price=1.05)
    result = evaluator.evaluate(snapshot)
    assert "Trailing exit" not in result.reason


def test_armed_with_small_giveback_below_threshold_holds():
    """Peak at $1.05; price dips to $1.04 — only a $0.01 giveback (10% of
    the $0.10 gain), below the 30% trigger threshold. Must not exit."""
    evaluator = PositionEvaluator()
    snapshot = _snapshot(option_price=1.04, peak_price=1.05)
    result = evaluator.evaluate(snapshot)
    assert "Trailing exit" not in result.reason


def test_never_profitable_never_trails():
    """Peak never exceeded entry price — nothing to trail; must not exit
    on this basis even if price is now below entry."""
    evaluator = PositionEvaluator()
    snapshot = _snapshot(option_price=0.90, peak_price=0.95)
    result = evaluator.evaluate(snapshot)
    assert "Trailing exit" not in result.reason


def test_trailing_exit_fires_even_with_insufficient_momentum_data():
    """The trailing check is deterministic and price-only — it must fire
    even when there isn't enough momentum data to classify the move at
    all, which would otherwise force a HOLD (see evaluator.py step 5)."""
    sparse = MomentumEvidence(thesis_direction="bullish", rsi=50.0)
    evaluator = PositionEvaluator()
    snapshot = _snapshot(option_price=1.02, peak_price=1.05, momentum=sparse)
    result = evaluator.evaluate(snapshot)
    assert result.decision is Decision.EXIT
    assert "Trailing exit" in result.reason


def test_hard_stop_loss_still_takes_priority_over_trailing():
    """A hard stop-loss breach must win even if a (very unusual) trailing
    setup also happens to be triggered at the same time."""
    position = make_position(stop_loss_usd=1.0)  # tiny stop: any loss breaches it
    evaluator = PositionEvaluator()
    snapshot = _snapshot(option_price=0.80, peak_price=1.05, position=position)
    result = evaluator.evaluate(snapshot)
    assert result.decision is Decision.STOP_EXIT


def test_custom_fractions_change_arm_and_trigger_prices():
    config = EvaluatorConfig(trailing_arm_fraction=0.25, trailing_giveback_fraction=0.5)
    evaluator = PositionEvaluator(config)
    # arm price = 0.95 + 0.25*0.20 = $1.00; peak $1.02 is armed.
    # trigger = 1.02 - 0.5*(1.02-0.95) = 1.02 - 0.035 = $0.985
    snapshot = _snapshot(option_price=0.98, peak_price=1.02)
    result = evaluator.evaluate(snapshot)
    assert result.decision is Decision.EXIT
    assert "Trailing exit" in result.reason


# --- PeakPriceStore ---------------------------------------------------------------------------


def test_peak_price_store_tracks_the_running_max(tmp_path):
    store = PeakPriceStore(tmp_path / "peaks.json")
    assert store.update_peak("opt-1", 1.00, floor=0.95) == 1.00
    assert store.update_peak("opt-1", 0.98, floor=0.95) == 1.00  # doesn't drop on a lower price
    assert store.update_peak("opt-1", 1.05, floor=0.95) == 1.05  # new high updates it
    assert store.get("opt-1", default=0.0) == 1.05


def test_peak_price_store_remove(tmp_path):
    store = PeakPriceStore(tmp_path / "peaks.json")
    store.update_peak("opt-1", 1.05, floor=0.95)
    store.remove("opt-1")
    assert store.get("opt-1", default=0.0) == 0.0


def test_peak_price_store_corrupted_file_fails_closed(tmp_path):
    from src.position_manager.peak_tracker import PeakPriceStoreError
    import pytest

    path = tmp_path / "peaks.json"
    path.write_text("not json")
    store = PeakPriceStore(path)
    with pytest.raises(PeakPriceStoreError):
        store.load()
