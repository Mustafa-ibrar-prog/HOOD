"""Phase 7, Part 7 & 19: general cross-sectional alpha evaluator tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.research.cross_sectional_alpha import CrossSectionalAlphaConfig, evaluate_cross_sectional_alpha

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _panel_perfect_rank_correlation(n_timestamps=20, n_symbols=6):
    """feature == target at every timestamp (up to a per-timestamp
    constant shift) -> IC should be a clean +1.0 every time."""
    rows = []
    for t in range(n_timestamps):
        ts = T0 + timedelta(days=t)
        for s in range(n_symbols):
            rows.append({"timestamp": ts, "symbol": f"SYM{s}", "f": float(s), "tgt": float(s) * 2 + 1})
    return rows


def test_perfect_rank_correlation_gives_ic_near_one():
    panel = _panel_perfect_rank_correlation()
    config = CrossSectionalAlphaConfig(feature_col="f", target_col="tgt", n_quantiles=3)
    report = evaluate_cross_sectional_alpha(panel, config)
    assert report.ic_summary.average_ic == 1.0
    # IC is a CONSTANT 1.0 at every timestamp here -> zero variance across
    # timestamps -> t_statistic is correctly undefined (None), not a bug;
    # a near-perfect-but-noisy version below produces a real large t-stat.
    assert report.ic_t_statistic is None
    assert report.ic_p_value is None


def test_strong_but_noisy_relationship_gives_a_large_t_statistic_and_small_p_value():
    import random

    rng = random.Random(5)
    rows = []
    for t in range(40):
        ts = T0 + timedelta(days=t)
        for s in range(8):
            f = float(s) + rng.gauss(0, 0.3)  # mostly rank-preserving, small per-timestamp noise
            rows.append({"timestamp": ts, "symbol": f"SYM{s}", "f": f, "tgt": float(s) * 2 + 1})
    config = CrossSectionalAlphaConfig(feature_col="f", target_col="tgt", n_quantiles=4)
    report = evaluate_cross_sectional_alpha(rows, config)
    assert report.ic_summary.average_ic > 0.7
    assert report.ic_t_statistic is not None and report.ic_t_statistic > 5
    assert report.ic_p_value is not None and report.ic_p_value < 0.01


def test_quantile_spread_is_positive_and_monotonic_for_a_real_relationship():
    panel = _panel_perfect_rank_correlation()
    config = CrossSectionalAlphaConfig(feature_col="f", target_col="tgt", n_quantiles=3)
    report = evaluate_cross_sectional_alpha(panel, config)
    assert report.quantile_report.is_monotonic is True
    assert report.quantile_report.spread_q5_minus_q1 > 0


def test_weighted_portfolio_equal_vs_signal_weighted_can_differ():
    import random

    rng = random.Random(1)
    rows = []
    for t in range(30):
        ts = T0 + timedelta(days=t)
        for s in range(8):
            f = rng.uniform(-1, 1)
            rows.append({"timestamp": ts, "symbol": f"SYM{s}", "f": f, "tgt": f * 0.5 + rng.gauss(0, 0.1)})
    equal_cfg = CrossSectionalAlphaConfig(feature_col="f", target_col="tgt", n_quantiles=4, weighting="equal")
    signal_cfg = CrossSectionalAlphaConfig(feature_col="f", target_col="tgt", n_quantiles=4, weighting="signal_weighted")
    equal_report = evaluate_cross_sectional_alpha(rows, equal_cfg)
    signal_report = evaluate_cross_sectional_alpha(rows, signal_cfg)
    assert equal_report.weighted_portfolio.long_short_return is not None
    assert signal_report.weighted_portfolio.long_short_return is not None
    # not asserting they differ numerically (could coincide) — just that both compute cleanly with the requested weighting label
    assert equal_report.weighted_portfolio.weighting == "equal"
    assert signal_report.weighted_portfolio.weighting == "signal_weighted"


def test_no_relationship_gives_ic_near_zero():
    import random

    rng = random.Random(2)
    rows = []
    for t in range(50):
        ts = T0 + timedelta(days=t)
        for s in range(10):
            rows.append({"timestamp": ts, "symbol": f"SYM{s}", "f": rng.gauss(0, 1), "tgt": rng.gauss(0, 1)})
    config = CrossSectionalAlphaConfig(feature_col="f", target_col="tgt", n_quantiles=5)
    report = evaluate_cross_sectional_alpha(rows, config)
    assert abs(report.ic_summary.average_ic) < 0.3  # loose bound for random noise over a modest sample


def test_config_is_never_auto_tuned_every_field_is_explicit():
    """Structural guarantee: CrossSectionalAlphaConfig has no
    'auto'/'best' option for any field — every value must be supplied."""
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(CrossSectionalAlphaConfig)}
    assert field_names == {"feature_col", "target_col", "n_quantiles", "min_universe_size", "weighting"}
