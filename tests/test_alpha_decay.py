"""Phase 7, Part 8 & 19: alpha decay analysis tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.research.alpha_decay import STANDARD_DECAY_HORIZONS, measure_alpha_decay

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _panel(feature_fn, target_fn, n_timestamps=30, n_symbols=8):
    rows = []
    for t in range(n_timestamps):
        ts = T0 + timedelta(days=t)
        for s in range(n_symbols):
            rows.append({"timestamp": ts, "symbol": f"SYM{s}", "feature_x": feature_fn(s), f"target_future_return_5bar": target_fn(s)})
    return rows


def test_standard_decay_horizons_constant():
    assert STANDARD_DECAY_HORIZONS == (1, 2, 3, 5, 10, 20, 40)


def test_no_measurable_signal_when_ic_never_clears_threshold():
    import random

    rng = random.Random(1)
    panel_by_horizon = {}
    for h in (1, 5, 20):
        rows = []
        for t in range(30):
            ts = T0 + timedelta(days=t)
            for s in range(8):
                rows.append({"timestamp": ts, "symbol": f"SYM{s}", "feature_x": rng.gauss(0, 1), f"target_future_return_{h}bar": rng.gauss(0, 1)})
        panel_by_horizon[h] = rows
    report = measure_alpha_decay(panel_by_horizon, feature_col="feature_x", meaningful_ic_threshold=0.5)
    assert report.classification == "NO_MEASURABLE_DECAY_SIGNAL"


def test_short_lived_signal_classification():
    """Strong IC at horizon 1, nothing meaningful beyond horizon 5."""
    import random

    rng = random.Random(2)
    panel_by_horizon = {}
    for h in (1, 5, 20, 40):
        rows = []
        for t in range(30):
            ts = T0 + timedelta(days=t)
            for s in range(8):
                if h <= 3:
                    tgt = float(s) + rng.gauss(0, 0.1)  # strong relationship at short horizon
                else:
                    tgt = rng.gauss(0, 1)  # pure noise at longer horizons
                rows.append({"timestamp": ts, "symbol": f"SYM{s}", "feature_x": float(s), f"target_future_return_{h}bar": tgt})
        panel_by_horizon[h] = rows
    report = measure_alpha_decay(panel_by_horizon, feature_col="feature_x", meaningful_ic_threshold=0.3)
    assert report.classification == "SHORT_LIVED"
    assert report.sign_stable is True


def test_long_lived_signal_classification():
    import random

    rng = random.Random(3)
    panel_by_horizon = {}
    for h in (1, 5, 20, 40):
        rows = []
        for t in range(30):
            ts = T0 + timedelta(days=t)
            for s in range(8):
                tgt = float(s) + rng.gauss(0, 0.1)  # strong relationship persists at every horizon
                rows.append({"timestamp": ts, "symbol": f"SYM{s}", "feature_x": float(s), f"target_future_return_{h}bar": tgt})
        panel_by_horizon[h] = rows
    report = measure_alpha_decay(panel_by_horizon, feature_col="feature_x", meaningful_ic_threshold=0.3)
    assert report.classification == "LONG_LIVED"


def test_inconsistent_sign_classification():
    rows_pos = [{"timestamp": T0 + timedelta(days=t), "symbol": f"SYM{s}", "feature_x": float(s), "target_future_return_1bar": float(s)} for t in range(20) for s in range(8)]
    rows_neg = [{"timestamp": T0 + timedelta(days=t), "symbol": f"SYM{s}", "feature_x": float(s), "target_future_return_5bar": -float(s)} for t in range(20) for s in range(8)]
    report = measure_alpha_decay({1: rows_pos, 5: rows_neg}, feature_col="feature_x", meaningful_ic_threshold=0.5)
    assert report.classification == "INCONSISTENT_SIGN"
    assert report.sign_stable is False


def test_does_not_fit_a_curve_just_reports_raw_points():
    """The report exposes the raw per-horizon IC points, not a smoothed
    or fitted curve — Part 8's explicit 'do not fit arbitrary curves'
    instruction."""
    rows = [{"timestamp": T0 + timedelta(days=t), "symbol": f"SYM{s}", "feature_x": float(s), "target_future_return_5bar": float(s)} for t in range(10) for s in range(5)]
    report = measure_alpha_decay({5: rows}, feature_col="feature_x")
    assert len(report.points) == 1
    assert report.points[0].horizon_bars == 5
    assert report.points[0].effect_size == report.points[0].ic_summary.average_ic  # no transformation applied
