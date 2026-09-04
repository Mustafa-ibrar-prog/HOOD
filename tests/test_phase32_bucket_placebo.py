"""Phase 32, Part 10/21 — placebo battery, including the new top-
outlier-removal test and confirmation of reused placebo functions."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from src.options.phase32_bucket_placebo import outlier_removal_test, trim_target_outliers
from src.options.placebo_extensions import symbol_identity_shuffle_placebo
from src.research.cross_sectional_placebo import shifted_signal_placebo, shuffled_signal_placebo, time_shuffled_target_placebo


def _row(underlying, d, feature, target):
    ts = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return {
        "underlying_symbol": underlying, "symbol": underlying, "timestamp": ts,
        "cs_group_key": (d,), "feature": feature, "target": target,
    }


def _panel(n_days=15, n_per_day=5, seed=1):
    rng = random.Random(seed)
    rows = []
    for day in range(n_days):
        d = date(2026, 1, 1 + day)
        for i in range(n_per_day):
            f = rng.uniform(-1, 1)
            rows.append(_row("AAPL", d, f, 0.6 * f + rng.gauss(0, 0.01)))
    return rows


def test_reused_placebos_run_without_modification_on_bucket_rows():
    rows = _panel()
    r1 = shuffled_signal_placebo(rows, feature_col="feature", target_col="target", n_trials=10, min_universe_size=3)
    r2 = shifted_signal_placebo(rows, feature_col="feature", target_col="target", shift_bars=1, min_universe_size=3)
    r3 = time_shuffled_target_placebo(rows, feature_col="feature", target_col="target", n_trials=10, min_universe_size=3)
    r4 = symbol_identity_shuffle_placebo(rows, feature_col="feature", target_col="target", n_trials=10, min_universe_size=3)
    for r in (r1, r2, r3, r4):
        assert r.method


def test_trim_target_outliers_removes_extremes():
    rows = [_row("AAPL", date(2026, 1, 1) + timedelta(days=i), 0.1, float(i)) for i in range(100)]
    trimmed = trim_target_outliers(rows, target_col="target", fraction_each_tail=0.05)
    assert len(trimmed) < len(rows)
    remaining_targets = sorted(r["target"] for r in trimmed)
    assert remaining_targets[0] >= 5
    assert remaining_targets[-1] <= 94


def test_trim_target_outliers_noop_on_small_samples():
    rows = [_row("AAPL", date(2026, 1, 1 + i), 0.1, float(i)) for i in range(5)]
    trimmed = trim_target_outliers(rows, target_col="target")
    assert len(trimmed) == 5


def test_outlier_removal_test_detects_dependence():
    """Construct a relationship driven entirely by one extreme point --
    trimming it should collapse the IC."""
    rng = random.Random(9)
    rows = []
    for day in range(30):
        d = date(2026, 1, 1 + day)
        for i in range(4):
            f = rng.uniform(-0.01, 0.01)  # near-zero, near-random feature
            target = rng.gauss(0, 0.01)
            rows.append(_row("AAPL", d, f, target))
    # inject one massive outlier pair that single-handedly creates a "relationship"
    rows.append(_row("AAPL", date(2026, 3, 1), 100.0, 100.0))
    rows.append(_row("AAPL", date(2026, 3, 1), -100.0, -100.0))
    rows.append(_row("AAPL", date(2026, 3, 1), 50.0, 50.0))
    result = outlier_removal_test(rows, feature_col="feature", target_col="target", fraction_each_tail=0.02)
    assert result.n_before == len(rows)
    assert result.n_after <= result.n_before


def test_outlier_removal_test_stable_relationship_not_flagged_dependent():
    rows = _panel(n_days=30, n_per_day=6, seed=7)
    result = outlier_removal_test(rows, feature_col="feature", target_col="target", fraction_each_tail=0.02)
    assert result.ic_before is not None
    assert result.outlier_dependent is False
