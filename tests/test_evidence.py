from __future__ import annotations

from src.strategy.evidence import MomentumEvidence, MomentumState, evaluate_momentum


def test_insufficient_data_when_almost_everything_is_none():
    evidence = MomentumEvidence(thesis_direction="bullish", rsi=60.0)
    result = evaluate_momentum(evidence)
    assert result.state is MomentumState.INSUFFICIENT_DATA


def test_strong_continuation_is_strengthening():
    evidence = MomentumEvidence(
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
    result = evaluate_momentum(evidence)
    assert result.state is MomentumState.STRENGTHENING


def test_mere_pause_does_not_count_as_weakening():
    """A single soft signal (RSI ticking down one point, volume roughly
    flat) must not be enough to call a move weakening — this is the crux of
    'do not exit simply because price pauses.'"""
    evidence = MomentumEvidence(
        thesis_direction="bullish",
        rsi=58.0,
        rsi_prev=59.0,  # trivial dip, not overbought/exhausted
        macd_histogram=0.04,
        macd_histogram_prev=0.05,  # barely fading
        ema_fast=105.0,
        ema_slow=100.0,  # trend still fully intact
        higher_highs=False,
        lower_highs=False,  # no structure break either way
        breakout_continuation=False,
        failed_breakout=False,
        reversal_signal=False,
        volume_ratio=1.0,  # flat, not drying up
    )
    result = evaluate_momentum(evidence)
    assert result.state in (MomentumState.STABLE, MomentumState.STRENGTHENING)
    assert result.state is not MomentumState.WEAKENING
    assert result.state is not MomentumState.REVERSING


def test_multiple_corroborating_signals_produce_weakening():
    evidence = MomentumEvidence(
        thesis_direction="bullish",
        rsi=74.0,
        rsi_prev=78.0,  # overbought AND rolling over
        macd_histogram=0.02,
        macd_histogram_prev=0.08,  # fading fast
        ema_fast=100.5,
        ema_slow=100.0,
        higher_highs=False,
        lower_highs=True,  # structure turning
        breakout_continuation=False,
        failed_breakout=True,
        reversal_signal=False,
        volume_ratio=0.5,  # volume drying up
    )
    result = evaluate_momentum(evidence)
    assert result.state in (MomentumState.WEAKENING, MomentumState.REVERSING)
    assert len(result.signals) >= 3


def test_reversal_signal_alone_plus_structure_break_reaches_reversing():
    evidence = MomentumEvidence(
        thesis_direction="bullish",
        rsi=72.0,
        rsi_prev=80.0,
        macd_histogram=-0.02,
        macd_histogram_prev=0.05,
        ema_fast=99.0,
        ema_slow=100.0,  # trend flipped against the thesis
        higher_highs=False,
        lower_highs=True,
        breakout_continuation=False,
        failed_breakout=True,
        reversal_signal=True,
        volume_ratio=0.4,
    )
    result = evaluate_momentum(evidence)
    assert result.state is MomentumState.REVERSING


def test_bearish_thesis_flips_favorable_direction():
    # For a bearish (long put) thesis, lower highs + downtrend are the
    # *favorable* structure, not a warning sign.
    evidence = MomentumEvidence(
        thesis_direction="bearish",
        rsi=25.0,
        rsi_prev=30.0,
        macd_histogram=-0.10,
        macd_histogram_prev=-0.05,
        ema_fast=95.0,
        ema_slow=100.0,
        higher_highs=False,
        lower_highs=True,
        breakout_continuation=True,
        failed_breakout=False,
        reversal_signal=False,
        volume_ratio=1.5,
    )
    result = evaluate_momentum(evidence)
    assert result.state is MomentumState.STRENGTHENING
