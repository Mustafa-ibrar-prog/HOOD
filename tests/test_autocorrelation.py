"""Phase 8, Part 27: autocorrelation helper tests."""

from __future__ import annotations

import random

from src.research.autocorrelation import autocorrelation_profile, lag_autocorrelation


def test_lag_autocorrelation_none_for_lag_zero_or_negative():
    assert lag_autocorrelation([1.0, 2.0, 3.0], 0) is None
    assert lag_autocorrelation([1.0, 2.0, 3.0], -1) is None


def test_lag_autocorrelation_none_when_lag_exceeds_series_length():
    assert lag_autocorrelation([1.0, 2.0, 3.0], 5) is None


def test_lag_autocorrelation_perfect_for_a_linear_ramp():
    values = [float(i) for i in range(50)]
    r = lag_autocorrelation(values, 1)
    assert r is not None and r > 0.99  # a monotonic ramp is nearly perfectly self-correlated at lag 1


def test_lag_autocorrelation_near_zero_for_iid_noise():
    rng = random.Random(1)
    values = [rng.gauss(0, 1) for _ in range(500)]
    r = lag_autocorrelation(values, 1)
    assert r is not None and abs(r) < 0.15


def test_lag_autocorrelation_drops_none_pairs():
    values = [1.0, None, 3.0, 4.0, None, 6.0, 7.0, 8.0, 9.0, 10.0]
    r = lag_autocorrelation(values, 1)
    assert r is not None  # still computable from the remaining valid pairs


def test_lag_autocorrelation_none_with_too_few_valid_pairs():
    values = [1.0, None, None, None, None]
    assert lag_autocorrelation(values, 1) is None


def test_autocorrelation_profile_covers_all_requested_lags():
    values = [float(i % 7) for i in range(100)]
    profile = autocorrelation_profile(values, (1, 2, 5, 10))
    assert set(profile.keys()) == {1, 2, 5, 10}
    assert all(v is not None for v in profile.values())


def test_autocorrelation_profile_reproducible():
    values = [float((i * 3) % 11) for i in range(80)]
    p1 = autocorrelation_profile(values, (1, 3, 7))
    p2 = autocorrelation_profile(values, (1, 3, 7))
    assert p1 == p2
