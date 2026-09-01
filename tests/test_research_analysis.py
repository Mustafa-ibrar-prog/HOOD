"""Tests for the predictive feature analyzer, against synthetic data with
a KNOWN engineered relationship (so we can assert the analyzer actually
finds it) and a pure-noise case (so we can assert it doesn't hallucinate
one)."""

from __future__ import annotations

import random

from src.research.analysis import analyze_feature


def test_strong_known_relationship_is_detected():
    # target = 2 * feature, exactly — the strongest possible signal.
    rows = [{"feature_x": float(i), "target_y": 2.0 * i} for i in range(100)]
    result = analyze_feature(rows, "feature_x", "target_y", n_quantiles=5)
    assert result.pearson_correlation is not None
    assert result.pearson_correlation > 0.99
    assert result.spearman_correlation > 0.99
    # Quantile means should be monotonically increasing with feature quantile.
    means = [q.mean_future_return for q in result.quantiles]
    assert means == sorted(means)
    assert result.quantiles[0].mean_future_return < result.quantiles[-1].mean_future_return


def test_pure_noise_shows_weak_correlation():
    rng = random.Random(42)
    rows = [{"feature_x": rng.uniform(-1, 1), "target_y": rng.uniform(-1, 1)} for _ in range(500)]
    result = analyze_feature(rows, "feature_x", "target_y", n_quantiles=5)
    assert result.pearson_correlation is not None
    assert abs(result.pearson_correlation) < 0.2  # should not find a spurious strong relationship


def test_none_values_are_dropped_not_imputed():
    rows = [{"feature_x": None, "target_y": 0.5}, {"feature_x": 1.0, "target_y": None}] + [
        {"feature_x": float(i), "target_y": float(i)} for i in range(20)
    ]
    result = analyze_feature(rows, "feature_x", "target_y", n_quantiles=5)
    assert result.sample_count == 20


def test_insufficient_samples_returns_none_correlations_not_a_crash():
    rows = [{"feature_x": 1.0, "target_y": 0.1}]
    result = analyze_feature(rows, "feature_x", "target_y", n_quantiles=5)
    assert result.pearson_correlation is None
    assert result.quantiles == ()
    assert "Insufficient" in result.significance_note


def test_render_produces_readable_report():
    rows = [{"feature_x": float(i), "target_y": 2.0 * i} for i in range(50)]
    result = analyze_feature(rows, "feature_x", "target_y")
    text = result.render()
    assert "Feature: feature_x" in text
    assert "Target: target_y" in text
    assert "Q1:" in text
    assert "CAUTION" in text


def test_significance_note_always_present_and_warns_about_autocorrelation():
    rows = [{"feature_x": float(i), "target_y": float(i) * 0.5} for i in range(30)]
    result = analyze_feature(rows, "feature_x", "target_y")
    assert "autocorrelated" in result.significance_note.lower()
