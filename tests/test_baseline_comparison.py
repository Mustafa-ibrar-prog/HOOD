"""Phase 7, Part 15 & 19: baseline-control comparison tests."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from src.research.baseline_comparison import compare_against_baselines

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _panel(feature_col="f", n_timestamps=25, n_symbols=8, strong=True, seed=1):
    rng = random.Random(seed)
    rows = []
    for t in range(n_timestamps):
        ts = T0 + timedelta(days=t)
        for s in range(n_symbols):
            f = float(s) if strong else rng.gauss(0, 1)
            tgt = float(s) + rng.gauss(0, 0.1) if strong else rng.gauss(0, 1)
            rows.append({"timestamp": ts, "symbol": f"SYM{s}", feature_col: f, "tgt": tgt})
    return rows


def test_strong_candidate_beats_random_signal_baseline():
    panel = _panel(strong=True)
    report = compare_against_baselines(panel, candidate_feature_col="f", target_col="tgt", n_placebo_trials=100, seed=1)
    assert report.candidate_ic is not None and report.candidate_ic > 0.8
    assert report.adds_information_beyond_random is True


def test_pure_noise_candidate_does_not_beat_random_signal_baseline():
    panel = _panel(strong=False, seed=2)
    report = compare_against_baselines(panel, candidate_feature_col="f", target_col="tgt", n_placebo_trials=100, seed=2)
    assert report.adds_information_beyond_random is False or report.adds_information_beyond_random is None


def test_momentum_and_mean_reversion_baselines_are_computed_when_supplied():
    panel = _panel(feature_col="candidate_feature", strong=True)
    momentum_panel = _panel(feature_col="feature_roc_20", strong=True, seed=3)
    mr_panel = _panel(feature_col="feature_zscore_20", strong=False, seed=4)
    report = compare_against_baselines(
        panel, candidate_feature_col="candidate_feature", target_col="tgt",
        momentum_panel_rows=momentum_panel, mean_reversion_panel_rows=mr_panel,
    )
    assert report.momentum_baseline_ic is not None
    assert report.mean_reversion_baseline_ic is not None


def test_self_comparison_returns_none_not_a_trivial_1_0():
    """If the candidate feature IS the momentum baseline feature, no
    self-comparison should be reported (it would be meaningless)."""
    panel = _panel(feature_col="feature_roc_20", strong=True)
    report = compare_against_baselines(panel, candidate_feature_col="feature_roc_20", target_col="tgt", momentum_panel_rows=panel, momentum_feature_col="feature_roc_20")
    assert report.momentum_baseline_ic is None


def test_shuffled_signal_p_value_is_reported():
    panel = _panel(strong=True)
    report = compare_against_baselines(panel, candidate_feature_col="f", target_col="tgt", n_placebo_trials=50, seed=1)
    assert report.shuffled_signal_empirical_p_value is not None
    assert 0.0 <= report.shuffled_signal_empirical_p_value <= 1.0
