"""Phase 20, Part 11-12/24 — mechanical-baseline (option vs underlying
signal) comparison tests."""

from __future__ import annotations

from datetime import date

from src.options.mechanical_baseline import BaselineClassification, compare_option_vs_underlying_signal


def _panel(n_timestamps: int, *, option_signal_strength: float, underlying_signal_strength: float) -> list[dict]:
    """Builds a synthetic panel where `feature` deterministically ranks
    with `option_target` at strength `option_signal_strength` and with
    `underlying_target` at strength `underlying_signal_strength` (both
    in [-1, 1], via a monotone-preserving construction) -- enough
    symbols per timestamp for compute_ic_series to produce a real IC."""
    rows = []
    for t in range(n_timestamps):
        base = date(2022, 1, 1 + t)
        for i in range(5):
            feature = float(i)
            # A small non-monotonic perturbation (independent of feature's rank order) keeps the
            # target from ever being a degenerate constant column when *_signal_strength is 0 --
            # compute_ic_series/spearman_correlation return None for a zero-variance target, which
            # would otherwise make "no underlying signal" indistinguishable from "no data".
            noise = 0.5 if i in (1, 3) else 0.0
            rows.append({
                "timestamp": base, "symbol": f"c{i}",
                "feature": feature,
                "option_target": feature * option_signal_strength + noise,
                "underlying_target": feature * underlying_signal_strength + noise,
            })
    return rows


def test_option_adds_information_when_option_ic_much_larger():
    panel = _panel(10, option_signal_strength=1.0, underlying_signal_strength=0.0)
    result = compare_option_vs_underlying_signal(panel, feature_col="feature", option_target_col="option_target", underlying_target_col="underlying_target")
    assert result.classification == BaselineClassification.OPTION_ADDS_INFORMATION
    assert result.gap is not None and result.gap > 0


def test_inherited_from_underlying_when_ics_are_similar():
    panel = _panel(10, option_signal_strength=1.0, underlying_signal_strength=1.0)
    result = compare_option_vs_underlying_signal(panel, feature_col="feature", option_target_col="option_target", underlying_target_col="underlying_target")
    assert result.classification == BaselineClassification.INHERITED_FROM_UNDERLYING


def test_both_weak_or_undefined_when_ic_is_none():
    panel = [{"timestamp": date(2022, 1, 1), "symbol": "c1", "feature": 1.0, "option_target": None, "underlying_target": None}]
    result = compare_option_vs_underlying_signal(panel, feature_col="feature", option_target_col="option_target", underlying_target_col="underlying_target")
    assert result.classification == BaselineClassification.BOTH_WEAK_OR_UNDEFINED
    assert result.gap is None


def test_render_includes_classification():
    panel = _panel(10, option_signal_strength=1.0, underlying_signal_strength=0.0)
    result = compare_option_vs_underlying_signal(panel, feature_col="feature", option_target_col="option_target", underlying_target_col="underlying_target")
    assert result.classification in result.render()
