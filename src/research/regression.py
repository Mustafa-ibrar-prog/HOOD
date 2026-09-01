"""Phase 9, Part 14: a small, from-scratch Ordinary Least Squares
implementation — pure stdlib (no numpy/scipy), same
zero-third-party-dependency convention as every other stats module in
this package. Exists specifically for the INCREMENTAL_PREDICTIVE_INFORMATION
test: does a volume-clustering feature explain forward volatility beyond
what LAGGED VOLATILITY ALONE already explains?

Solved via the normal equations (X'X)b = X'y using Gauss-Jordan
elimination — adequate and exact for the tiny (1-3 predictor) regressions
this module is used for; not a general-purpose numerically-robust solver
for ill-conditioned or large problems.

Standard errors / t-stats use the normal approximation documented in
src.research.stats_utils — approximate for small samples, same caveat
repeated here rather than silently assumed away.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from src.research.analysis import mean
from src.research.stats_utils import two_tailed_p_value_from_z


def _gauss_jordan_inverse(matrix: list[list[float]]) -> list[list[float]] | None:
    """Returns the inverse of a square matrix, or None if singular."""
    n = len(matrix)
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot_row][col]) < 1e-12:
            return None
        aug[col], aug[pivot_row] = aug[pivot_row], aug[col]
        pivot = aug[col][col]
        aug[col] = [x / pivot for x in aug[col]]
        for r in range(n):
            if r != col:
                factor = aug[r][col]
                aug[r] = [aug[r][k] - factor * aug[col][k] for k in range(2 * n)]
    return [row[n:] for row in aug]


def _matvec(matrix: list[list[float]], vec: list[float]) -> list[float]:
    return [sum(row[j] * vec[j] for j in range(len(vec))) for row in matrix]


@dataclass(frozen=True)
class OLSResult:
    applicable: bool
    reason: str
    n_observations: int | None = None
    predictor_names: tuple[str, ...] = ()
    coefficients: Mapping[str, float] | None = None  # includes "intercept"
    r_squared: float | None = None
    adjusted_r_squared: float | None = None
    coefficient_t_stats: Mapping[str, float] | None = None
    coefficient_p_values: Mapping[str, float] | None = None

    def render(self) -> str:
        if not self.applicable:
            return f"OLS: NOT_APPLICABLE ({self.reason})"
        coef_lines = "; ".join(f"{k}={v:.6f} (t={self.coefficient_t_stats[k]:.2f}, p={self.coefficient_p_values[k]:.4f})" for k, v in self.coefficients.items())
        return f"OLS (n={self.n_observations}, R2={self.r_squared:.4f}, adj_R2={self.adjusted_r_squared:.4f}): {coef_lines}"


def ols_regression(y: Sequence[float], predictors: Mapping[str, Sequence[float]], *, min_observations: int = 15) -> OLSResult:
    """`predictors` maps NAME -> a series the same length as `y`. Rows with
    ANY None (in y or any predictor) are dropped before fitting — never
    imputed. Requires `min_observations` valid rows (default 15 — below
    that, coefficient standard errors are too noisy to trust) and at
    least 2 more observations than parameters (for residual degrees of
    freedom)."""
    names = list(predictors.keys())
    n_total = len(y)
    valid_rows = []
    for i in range(n_total):
        row_y = y[i]
        row_x = [predictors[name][i] for name in names]
        if row_y is None or any(x is None for x in row_x):
            continue
        valid_rows.append((row_y, row_x))

    n = len(valid_rows)
    k = len(names) + 1  # + intercept
    if n < min_observations:
        return OLSResult(applicable=False, reason=f"need >= {min_observations} valid (non-None) observations, got {n}")
    if n - k < 2:
        return OLSResult(applicable=False, reason=f"too few observations ({n}) relative to parameters ({k}) for meaningful residual degrees of freedom")

    ys = [r[0] for r in valid_rows]
    X = [[1.0] + r[1] for r in valid_rows]

    XtX = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(k)] for a in range(k)]
    Xty = [sum(X[i][a] * ys[i] for i in range(n)) for a in range(k)]

    inv = _gauss_jordan_inverse(XtX)
    if inv is None:
        return OLSResult(applicable=False, reason="design matrix is singular (perfectly collinear predictors) — cannot solve")
    coeffs = _matvec(inv, Xty)

    y_pred = [sum(coeffs[a] * X[i][a] for a in range(k)) for i in range(n)]
    y_mean = mean(ys)
    ss_res = sum((ys[i] - y_pred[i]) ** 2 for i in range(n))
    ss_tot = sum((ys[i] - y_mean) ** 2 for i in range(n))
    if ss_tot == 0:
        return OLSResult(applicable=False, reason="target has zero variance in this sample")
    r_squared = 1 - ss_res / ss_tot
    adj_r_squared = 1 - (1 - r_squared) * (n - 1) / (n - k)

    dof = n - k
    sigma_squared = ss_res / dof if dof > 0 else None
    coef_names = ["intercept"] + names
    coefficients = {name: coeffs[i] for i, name in enumerate(coef_names)}
    t_stats: dict[str, float] = {}
    p_values: dict[str, float] = {}
    for i, name in enumerate(coef_names):
        se = (sigma_squared * inv[i][i]) ** 0.5 if sigma_squared is not None and inv[i][i] > 0 else None
        if se is None or se == 0:
            t_stats[name] = 0.0
            p_values[name] = 1.0
        else:
            t = coefficients[name] / se
            t_stats[name] = t
            p_values[name] = two_tailed_p_value_from_z(t)

    return OLSResult(
        applicable=True, reason="", n_observations=n, predictor_names=tuple(names), coefficients=coefficients,
        r_squared=r_squared, adjusted_r_squared=adj_r_squared, coefficient_t_stats=t_stats, coefficient_p_values=p_values,
    )
