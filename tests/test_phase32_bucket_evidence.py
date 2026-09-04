"""Phase 32, Part 8/21 — pooled/cross-sectional/per-symbol/symbol-balanced evidence."""

from __future__ import annotations

import random
from datetime import date, datetime, timezone

from src.options.phase32_bucket_evidence import (
    cross_sectional_relationship,
    per_symbol_relationships,
    pooled_time_series_relationship,
    symbol_balanced_pooled_relationship,
)


def _row(underlying, d, feature, target, cs_group_key=None):
    ts = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return {
        "underlying_symbol": underlying, "symbol": underlying, "timestamp": ts,
        "cs_group_key": cs_group_key or (d,), "feature": feature, "target": target,
    }


def test_pooled_relationship_none_below_min_observations():
    rows = [_row("AAPL", date(2026, 1, 1 + i), 0.1 * i, 0.2 * i) for i in range(5)]
    result = pooled_time_series_relationship(rows, feature_col="feature", target_col="target", min_observations=30)
    assert result is None


def test_pooled_relationship_computed_when_enough_data():
    rng = random.Random(1)
    rows = []
    for i in range(50):
        f = rng.uniform(-1, 1)
        rows.append(_row("AAPL", date(2026, 1, 1) if i == 0 else date(2026, 1, 1), f, 0.5 * f + rng.gauss(0, 0.01)))
    result = pooled_time_series_relationship(rows, feature_col="feature", target_col="target", min_observations=30)
    assert result is not None
    assert result.sample_count == 50
    assert result.spearman_correlation > 0.5


def test_cross_sectional_relationship_reuses_phase31_evidence():
    rng = random.Random(2)
    rows = []
    for day in range(15):
        d = date(2026, 1, 1 + day)
        for i in range(5):
            f = rng.uniform(-1, 1)
            rows.append(_row("AAPL", d, f, 0.6 * f + rng.gauss(0, 0.01)))
    evidence = cross_sectional_relationship(rows, feature_col="feature", target_col="target", min_universe_size=3)
    assert evidence.applicable is True
    assert evidence.report.ic_summary.average_ic > 0.3


def test_per_symbol_relationships_one_per_underlying():
    rng = random.Random(3)
    rows = []
    for sym in ("AAPL", "GOOG"):
        for i in range(20):
            f = rng.uniform(-1, 1)
            rows.append(_row(sym, date(2026, 1, 1 + i), f, 0.5 * f + rng.gauss(0, 0.01)))
    results = per_symbol_relationships(rows, feature_col="feature", target_col="target", min_observations=15)
    assert {r.underlying for r in results} == {"AAPL", "GOOG"}
    assert all(r.result is not None for r in results)


def test_per_symbol_relationships_marks_insufficient_data():
    rows = [_row("AAPL", date(2026, 1, 1 + i), 0.1, 0.1) for i in range(3)]
    results = per_symbol_relationships(rows, feature_col="feature", target_col="target", min_observations=15)
    assert results[0].result is None
    assert "min_observations" in results[0].reason


def test_symbol_balanced_relationship_equal_weights_underlyings():
    rng = random.Random(4)
    rows = []
    # AAPL: 100 rows with a strong positive relationship. GOOG: 20 rows with a strong NEGATIVE relationship.
    for i in range(100):
        f = rng.uniform(-1, 1)
        rows.append(_row("AAPL", date(2026, 1, 1 + (i % 27)), f, 0.8 * f + rng.gauss(0, 0.01)))
    for i in range(20):
        f = rng.uniform(-1, 1)
        rows.append(_row("GOOG", date(2026, 1, 1 + (i % 27)), f, -0.8 * f + rng.gauss(0, 0.01)))
    per_symbol = per_symbol_relationships(rows, feature_col="feature", target_col="target", min_observations=15)
    balanced = symbol_balanced_pooled_relationship(per_symbol)
    assert balanced.n_symbols_eligible == 2
    # Equal-weighted average of a strong +correlation and a strong -correlation should be near zero,
    # NOT dominated by AAPL's 5x larger row count.
    assert abs(balanced.symbol_balanced_spearman) < 0.3


def test_symbol_dominance_flagged():
    rows = [_row("AAPL", date(2026, 1, 1 + (i % 27)), 0.1, 0.1) for i in range(90)]
    rows += [_row("GOOG", date(2026, 1, 1 + (i % 10)), 0.1, 0.1) for i in range(10)]
    per_symbol = per_symbol_relationships(rows, feature_col="feature", target_col="target", min_observations=1000)  # force both ineligible
    balanced = symbol_balanced_pooled_relationship(per_symbol, dominance_threshold=0.6)
    assert balanced.dominated_by_single_symbol is True
    assert balanced.dominant_symbol == "AAPL"
    assert balanced.dominant_symbol_share == 0.9
