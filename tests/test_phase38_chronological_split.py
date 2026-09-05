"""Phase 38, Part 7 — chronological DEVELOPMENT/VALIDATION/FINAL_HOLDOUT
split."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.options.phase38_chronological_split import MIN_TOTAL_FOR_CHRONOLOGICAL_SPLIT, split_chronologically
from src.options.phase38_targets import ForwardOutcome


def _outcome(i):
    t = datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(hours=i)
    return ForwardOutcome(
        option_id="opt-1", underlying_symbol="AAPL", horizon_label="5min", entry_cycle_id=f"c{i}",
        entry_timestamp=t, exit_cycle_id=f"c{i}x", exit_timestamp=t + timedelta(minutes=5),
        entry_ask=1.0, entry_bid=0.95, exit_bid=1.0, exit_ask=1.05, mid_return_pct=0.0, executable_return_pct=0.0,
        mfe_pct=0.0, mae_pct=0.0, directional_outcome="FLAT", risk_adjusted_outcome=None, entry_underlying=100.0,
        exit_underlying=100.0, underlying_return_pct=0.0, option_minus_underlying_return_pct=0.0, data_limited_reason=None,
    )


def test_insufficient_sample_reported_not_relaxed():
    result = split_chronologically([_outcome(i) for i in range(10)])
    assert not result.sufficient
    assert result.development == () and result.validation == () and result.final_holdout == ()


def test_sufficient_sample_splits_into_three_nonempty_chronological_groups():
    outcomes = [_outcome(i) for i in range(MIN_TOTAL_FOR_CHRONOLOGICAL_SPLIT)]
    result = split_chronologically(outcomes)
    assert result.sufficient
    assert len(result.development) > 0 and len(result.validation) > 0 and len(result.final_holdout) > 0
    assert len(result.development) + len(result.validation) + len(result.final_holdout) == MIN_TOTAL_FOR_CHRONOLOGICAL_SPLIT


def test_split_is_chronological_never_shuffled():
    outcomes = [_outcome(i) for i in reversed(range(MIN_TOTAL_FOR_CHRONOLOGICAL_SPLIT))]  # fed in reverse order
    result = split_chronologically(outcomes)
    assert result.development[0].entry_timestamp < result.development[-1].entry_timestamp
    assert result.development[-1].entry_timestamp <= result.validation[0].entry_timestamp
    assert result.validation[-1].entry_timestamp <= result.final_holdout[0].entry_timestamp


def test_final_holdout_is_strictly_the_latest_chronological_segment():
    outcomes = [_outcome(i) for i in range(MIN_TOTAL_FOR_CHRONOLOGICAL_SPLIT)]
    result = split_chronologically(outcomes)
    max_dev_time = max(o.entry_timestamp for o in result.development)
    min_holdout_time = min(o.entry_timestamp for o in result.final_holdout)
    assert max_dev_time < min_holdout_time
