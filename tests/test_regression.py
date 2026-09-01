"""Phase 9, Part 14 & 21: OLS regression tests (incremental-information
test machinery) — closed-form recovery, R^2 correctness, NOT_APPLICABLE
handling, reproducibility."""

from __future__ import annotations

import random

from src.research.regression import ols_regression


def test_perfect_linear_relationship_recovers_exact_coefficients():
    xs = list(range(30))
    ys = [2.0 + 3.0 * x for x in xs]
    r = ols_regression(ys, {"x": xs}, min_observations=5)
    assert r.applicable
    assert abs(r.coefficients["intercept"] - 2.0) < 1e-6
    assert abs(r.coefficients["x"] - 3.0) < 1e-6
    assert abs(r.r_squared - 1.0) < 1e-6


def test_noisy_relationship_recovers_approximate_coefficients():
    random.seed(1)
    xs = list(range(100))
    ys = [2.0 + 3.0 * x + random.gauss(0, 2) for x in xs]
    r = ols_regression(ys, {"x": xs}, min_observations=5)
    assert r.applicable
    assert abs(r.coefficients["x"] - 3.0) < 0.2
    assert 0.9 < r.r_squared < 1.0


def test_multi_predictor_recovers_all_true_coefficients():
    random.seed(2)
    x1 = [random.gauss(0, 1) for _ in range(80)]
    x2 = [random.gauss(0, 1) for _ in range(80)]
    ys = [1.0 + 2.0 * a - 1.0 * b + random.gauss(0, 0.1) for a, b in zip(x1, x2)]
    r = ols_regression(ys, {"x1": x1, "x2": x2}, min_observations=10)
    assert r.applicable
    assert abs(r.coefficients["intercept"] - 1.0) < 0.1
    assert abs(r.coefficients["x1"] - 2.0) < 0.1
    assert abs(r.coefficients["x2"] - (-1.0)) < 0.1


def test_irrelevant_predictor_has_a_small_insignificant_coefficient():
    random.seed(3)
    x_real = [random.gauss(0, 1) for _ in range(200)]
    x_noise = [random.gauss(0, 1) for _ in range(200)]  # unrelated to y
    ys = [5.0 * v + random.gauss(0, 0.5) for v in x_real]
    r = ols_regression(ys, {"x_real": x_real, "x_noise": x_noise}, min_observations=10)
    assert r.applicable
    assert r.coefficient_p_values["x_real"] < 0.001
    assert r.coefficient_p_values["x_noise"] > 0.05  # should NOT look significant


def test_below_min_observations_not_applicable():
    r = ols_regression([1.0, 2.0, 3.0], {"x": [1.0, 2.0, 3.0]}, min_observations=15)
    assert not r.applicable
    assert "observations" in r.reason


def test_rows_with_none_are_dropped_not_imputed():
    ys = [1.0, None, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0]
    xs = [1.0, 2.0, None, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0]
    r = ols_regression(ys, {"x": xs}, min_observations=10)
    assert r.applicable
    assert r.n_observations == 15  # 17 rows minus 2 with a None


def test_zero_variance_target_not_applicable():
    r = ols_regression([5.0] * 20, {"x": list(range(20))}, min_observations=5)
    assert not r.applicable
    assert "variance" in r.reason


def test_collinear_predictors_reported_not_applicable_not_crashed():
    xs = list(range(20))
    xs_dup = list(range(20))  # perfectly collinear with xs
    r = ols_regression([float(x) for x in xs], {"x": xs, "x_dup": xs_dup}, min_observations=5)
    assert not r.applicable
    assert "singular" in r.reason


def test_reproducibility_same_inputs_same_output():
    random.seed(4)
    xs = [random.gauss(0, 1) for _ in range(50)]
    ys = [3.0 * x + random.gauss(0, 1) for x in xs]
    r1 = ols_regression(ys, {"x": xs}, min_observations=5)
    r2 = ols_regression(ys, {"x": xs}, min_observations=5)
    assert r1.coefficients == r2.coefficients
    assert r1.r_squared == r2.r_squared
