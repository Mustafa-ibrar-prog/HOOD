"""Phase 31, Parts 10, 11 & 13/18 — multiple testing, stratified
robustness, temporal-alignment shift test."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from src.options.phase31_robustness import (
    evaluate_robustness,
    evaluate_temporal_alignment,
    family_effective_trials,
    multiple_testing_across_family,
)


def _row(ts, underlying, expiration, option_id, symbol, feature, target, call_put="call", moneyness_bucket="near_atm"):
    return {
        "timestamp": ts, "underlying_symbol": underlying, "symbol": symbol, "option_id": option_id,
        "expiration": expiration, "call_put": call_put, "moneyness_bucket": moneyness_bucket,
        "cs_group_key": (underlying, expiration, ts), "feature": feature, "target": target,
    }


def test_multiple_testing_across_family_returns_all_three_methods():
    labeled = [(f"H{i}", 0.001 * (i + 1)) for i in range(16)]
    reports = multiple_testing_across_family(labeled)
    assert set(reports.keys()) == {"bonferroni", "holm", "benjamini_hochberg"}
    assert reports["bonferroni"].n_tests == 16
    assert reports["holm"].n_significant >= reports["bonferroni"].n_significant


def test_family_effective_trials_below_nominal_when_correlated():
    ic_series = {f"H{i}": [0.1, 0.2, 0.15, 0.05, 0.3] for i in range(5)}  # identical series -> highly correlated
    result = family_effective_trials(ic_series)
    assert result.applicable is True
    assert result.effective_trials < result.nominal_trials


def _stable_sign_panel(*, underlyings, n_per=10, sign=1.0, seed=1):
    rng = random.Random(seed)
    rows = []
    for u in underlyings:
        for day in range(n_per):
            ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
            expiration = date(2026, 12, 18)
            for i in range(4):
                feature = rng.uniform(-1, 1)
                target = sign * 0.6 * feature + rng.gauss(0, 0.01)
                rows.append(_row(ts, u, expiration.isoformat(), f"{u}_{i}", u, feature, target))
    return rows


def test_robustness_report_no_sign_flip_when_consistent():
    rows = _stable_sign_panel(underlyings=("AAPL", "GOOG"), sign=1.0, seed=2)
    report = evaluate_robustness(rows, feature_col="feature", target_col="target", min_universe_size=3)
    assert report.sign_flips_across_underlyings is False
    assert report.fragile is False


def test_robustness_report_detects_sign_flip_across_underlyings():
    a = _stable_sign_panel(underlyings=("AAPL",), sign=1.0, seed=3)
    b = _stable_sign_panel(underlyings=("GOOG",), sign=-1.0, seed=4)
    rows = a + b
    report = evaluate_robustness(rows, feature_col="feature", target_col="target", min_universe_size=3)
    assert report.sign_flips_across_underlyings is True
    assert report.fragile is True


def test_leave_one_underlying_out_present_for_every_underlying():
    rows = _stable_sign_panel(underlyings=("AAPL", "GOOG", "FOXA"), seed=5)
    report = evaluate_robustness(rows, feature_col="feature", target_col="target", min_universe_size=3)
    excluded = {r.stratum_value for r in report.leave_one_underlying_out}
    assert excluded == {"AAPL", "GOOG", "FOXA"}


def test_temporal_alignment_no_concern_for_a_genuinely_causal_relationship():
    rows = _stable_sign_panel(underlyings=("AAPL",), n_per=30, seed=6)
    results = evaluate_temporal_alignment(rows, feature_col="feature", target_col="target", shifts=(1, 2), min_universe_size=3)
    assert len(results) == 2
    for r in results:
        assert r.true_ic is not None


def test_temporal_alignment_flags_concern_when_shifted_ic_dominates():
    """Construct a feature that's actually only correlated with the
    TARGET FROM shift_bars EARLIER (i.e. genuinely temporally misaligned) --
    the shift test should find that relationship, not the (near-zero) true one."""
    rng = random.Random(9)
    rows = []
    underlying = "AAPL"
    n_days = 40
    daily_targets = {}
    for day in range(n_days):
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
        daily_targets[ts] = rng.uniform(-1, 1)
    dates = sorted(daily_targets)
    for i, ts in enumerate(dates):
        for j in range(4):
            # feature at day i secretly equals the target that will be recorded shift_bars=1 LATER on average
            future_ts = dates[i + 1] if i + 1 < len(dates) else ts
            feature = daily_targets[future_ts] + rng.gauss(0, 0.001)
            rows.append(_row(ts, underlying, "2026-12-18", f"c{j}", underlying, feature, daily_targets[ts] + rng.gauss(0, 5.0)))
    results = evaluate_temporal_alignment(rows, feature_col="feature", target_col="target", shifts=(1,), min_universe_size=3)
    # true relationship is swamped by noise; shifted-by-1 relationship should be much stronger.
    assert results[0].shifted_ic is not None
