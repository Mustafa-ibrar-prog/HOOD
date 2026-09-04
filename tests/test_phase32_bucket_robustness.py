"""Phase 32, Parts 9 & 10/21 — temporal robustness reuse + leave-one-
period-out + weighting comparison."""

from __future__ import annotations

import random
from datetime import date, datetime, timezone

from src.options.phase31_robustness import evaluate_robustness, evaluate_temporal_alignment
from src.options.phase32_bucket_robustness import (
    compare_equal_vs_observation_weighting,
    leave_one_period_out,
    split_into_periods,
)


def _row(underlying, d, feature, target, call_put="call", dte_bucket="8-30", moneyness_bucket="near_atm"):
    ts = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return {
        "underlying_symbol": underlying, "symbol": underlying, "timestamp": ts, "call_put": call_put,
        "expiration": dte_bucket, "moneyness_bucket": moneyness_bucket,
        "cs_group_key": (d,), "feature": feature, "target": target,
    }


def _dated(n, start_month=1, start_day=1, year=2026):
    out = []
    d = date(year, start_month, start_day)
    from datetime import timedelta
    for i in range(n):
        out.append(d + timedelta(days=i))
    return out


def test_phase31_robustness_reuse_works_unchanged_on_bucket_rows():
    rng = random.Random(1)
    rows = []
    for i, d in enumerate(_dated(40)):
        f = rng.uniform(-1, 1)
        rows.append(_row("AAPL", d, f, 0.5 * f + rng.gauss(0, 0.01)))
    report = evaluate_robustness(rows, feature_col="feature", target_col="target", min_universe_size=3)
    assert report.feature_col == "feature"
    assert isinstance(report.fragile, bool)


def test_phase31_temporal_alignment_reuse_works_on_bucket_rows():
    rng = random.Random(2)
    rows = []
    for d in _dated(30):
        f = rng.uniform(-1, 1)
        rows.append(_row("AAPL", d, f, 0.5 * f + rng.gauss(0, 0.01)))
    results = evaluate_temporal_alignment(rows, feature_col="feature", target_col="target", shifts=(1, 2), min_universe_size=3)
    assert len(results) == 2


def test_split_into_periods_covers_all_rows_chronologically():
    rows = [_row("AAPL", d, 0.1, 0.1) for d in _dated(40)]
    periods = split_into_periods(rows, n_periods=4)
    assert len(periods) == 4
    total = sum(len(chunk) for _label, chunk in periods)
    assert total == 40


def test_leave_one_period_out_excludes_the_right_chunk():
    rng = random.Random(3)
    rows = []
    for d in _dated(80):
        f = rng.uniform(-1, 1)
        rows.append(_row("AAPL", d, f, 0.6 * f + rng.gauss(0, 0.01)))
    results = leave_one_period_out(rows, feature_col="feature", target_col="target", n_periods=4, min_observations=10)
    assert len(results) == 4
    for r in results:
        assert r.n_observations == 60  # 80 - 20 (one quarter excluded)


def test_weighting_comparison_flags_disagreement():
    rng = random.Random(4)
    rows = []
    for i, d in enumerate(_dated(100)):
        f = rng.uniform(-1, 1)
        rows.append(_row("AAPL", d, f, 0.8 * f + rng.gauss(0, 0.01)))
    for i, d in enumerate(_dated(15)):
        f = rng.uniform(-1, 1)
        rows.append(_row("GOOG", d, f, -0.8 * f + rng.gauss(0, 0.01)))
    result = compare_equal_vs_observation_weighting(rows, feature_col="feature", target_col="target")
    # AAPL dominates row count -> observation-weighted pool should be strongly positive,
    # while equal-weighted (balances AAPL's + against GOOG's -) should be much closer to zero.
    assert result.observation_weighted_spearman > 0.5
    assert result.materially_disagree is True


def test_weighting_comparison_agrees_when_relationship_is_consistent():
    rng = random.Random(5)
    rows = []
    for sym in ("AAPL", "GOOG"):
        for d in _dated(50):
            f = rng.uniform(-1, 1)
            rows.append(_row(sym, d, f, 0.7 * f + rng.gauss(0, 0.01)))
    result = compare_equal_vs_observation_weighting(rows, feature_col="feature", target_col="target")
    assert result.materially_disagree is False
