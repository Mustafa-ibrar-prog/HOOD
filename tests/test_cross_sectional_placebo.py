"""Phase 7, Part 10 & 19: panel-level placebo/negative-control tests."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from src.research.cross_sectional_placebo import (
    irrelevant_feature_control,
    random_feature_control,
    shifted_signal_placebo,
    shuffled_signal_placebo,
    time_shuffled_target_placebo,
)

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _strong_signal_panel(n_timestamps=25, n_symbols=8):
    rng = random.Random(1)
    rows = []
    for t in range(n_timestamps):
        ts = T0 + timedelta(days=t)
        for s in range(n_symbols):
            rows.append({"timestamp": ts, "symbol": f"SYM{s}", "f": float(s), "tgt": float(s) + rng.gauss(0, 0.05)})
    return rows


def test_shuffled_signal_placebo_is_deterministic_given_a_seed():
    panel = _strong_signal_panel()
    r1 = shuffled_signal_placebo(panel, feature_col="f", target_col="tgt", n_trials=20, seed=7)
    r2 = shuffled_signal_placebo(panel, feature_col="f", target_col="tgt", n_trials=20, seed=7)
    assert r1.placebo_distribution == r2.placebo_distribution


def test_shuffled_signal_placebo_gives_low_p_value_for_a_real_relationship():
    panel = _strong_signal_panel()
    r = shuffled_signal_placebo(panel, feature_col="f", target_col="tgt", n_trials=100, seed=1)
    assert r.observed_statistic is not None and r.observed_statistic > 0.9
    assert r.empirical_p_value is not None and r.empirical_p_value < 0.1


def test_shuffled_signal_placebo_documents_what_it_touches():
    panel = _strong_signal_panel()
    r = shuffled_signal_placebo(panel, feature_col="f", target_col="tgt", n_trials=5, seed=1)
    assert r.what_was_randomized and r.what_was_preserved and r.what_was_destroyed


def test_shifted_signal_placebo_destroys_a_purely_contemporaneous_relationship():
    """If feature and target are related ONLY at the true (unshifted)
    alignment, shifting should knock the IC toward zero."""
    rows = []
    for s in range(8):
        for t in range(60):
            ts = T0 + timedelta(days=t)
            value = float((s + t) % 8)  # varies BOTH cross-sectionally (by s) and over time (by t)
            rows.append({"timestamp": ts, "symbol": f"SYM{s}", "f": value, "tgt": value})  # tgt matches f at the SAME (s, t) — a purely contemporaneous relationship
    r = shifted_signal_placebo(rows, feature_col="f", target_col="tgt", shift_bars=5)
    assert r.observed_statistic is not None
    shifted_ic = r.placebo_distribution[0] if r.placebo_distribution else None
    assert shifted_ic is not None
    assert abs(shifted_ic) < abs(r.observed_statistic)


def test_random_feature_control_produces_a_null_distribution_centered_near_zero():
    panel = _strong_signal_panel()
    r = random_feature_control(panel, target_col="tgt", n_trials=200, seed=44)
    from src.research.analysis import mean

    assert len(r.placebo_distribution) > 50
    assert abs(mean(r.placebo_distribution)) < 0.2  # random noise feature -> should center near zero


def test_random_feature_control_is_deterministic():
    panel = _strong_signal_panel()
    r1 = random_feature_control(panel, target_col="tgt", n_trials=20, seed=5)
    r2 = random_feature_control(panel, target_col="tgt", n_trials=20, seed=5)
    assert r1.placebo_distribution == r2.placebo_distribution


def test_irrelevant_feature_control_just_reports_the_ic_no_trials():
    panel = _strong_signal_panel()
    r = irrelevant_feature_control(panel, irrelevant_feature_col="f", target_col="tgt")
    assert r.n_trials == 1
    assert r.observed_statistic is not None


def test_time_shuffled_target_placebo_is_the_most_destructive_null():
    panel = _strong_signal_panel()
    r = time_shuffled_target_placebo(panel, feature_col="f", target_col="tgt", n_trials=100, seed=45)
    assert r.observed_statistic is not None and r.observed_statistic > 0.9
    assert r.empirical_p_value is not None and r.empirical_p_value < 0.1
    assert "temporal" in r.what_was_destroyed.lower() or "cross-sectional" in r.what_was_destroyed.lower()


def test_no_relationship_gives_a_high_empirical_p_value_under_shuffled_placebo():
    rng = random.Random(9)
    panel = []
    for t in range(30):
        ts = T0 + timedelta(days=t)
        for s in range(8):
            panel.append({"timestamp": ts, "symbol": f"SYM{s}", "f": rng.gauss(0, 1), "tgt": rng.gauss(0, 1)})
    r = shuffled_signal_placebo(panel, feature_col="f", target_col="tgt", n_trials=100, seed=1)
    assert r.empirical_p_value is not None and r.empirical_p_value > 0.1  # a null feature shouldn't look "extreme"
