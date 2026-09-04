"""Phase 31, Parts 2 & 7/18 — underlying-only control (Model A vs Model
B, ΔR², incremental IC) and the causal residual-return benchmark model.

Part 2's requirement ("An option signal is NOT automatically alpha just
because the option price is predictable... compare MODEL A: underlying-
only features, MODEL B: underlying + option feature") and Part 7's
requirement ("create a causal benchmark model: OPTION_RETURN ≈
UNDERLYING_RETURN + OPTION_FEATURES... test whether option features
explain residual behavior") are the SAME regression, used two ways: as a
ΔR²/incremental-IC comparison (Part 2) and as a residual-target
generator (Part 7). One shared OLS implementation serves both, rather
than two.

Reuses `src.options.mechanical_baseline.compare_option_vs_underlying_signal`
directly for the IC-gap side of the comparison (Phase 20's existing,
already-tested "does the option relationship exceed the underlying's own"
classifier) — this module adds ONLY the ΔR² regression piece that
function doesn't compute, plus economically-scoped cross-sectional
grouping (same underlying + expiration + real timestamp, Part 5's
explicit "avoid comparing contracts that are not economically
comparable... do not mix expirations blindly") via `economically_scoped_rows`,
used everywhere this campaign runs a cross-sectional test.

Pure stdlib (no numpy/scipy), matching this codebase's established
convention (`src.research.overfitting_metrics`'s own docstring: "pure
stdlib, no numpy/scipy").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.options.mechanical_baseline import compare_option_vs_underlying_signal
from src.research.analysis import mean


def economically_scoped_rows(panel_rows: Sequence[dict]) -> list[dict]:
    """Returns COPIES of `panel_rows` with `timestamp` replaced by each
    row's `cs_group_key` (same underlying + expiration + real timestamp)
    — so any function that groups cross-sectionally by `row["timestamp"]`
    (e.g. `src.research.ic.compute_ic_series`) automatically ranks
    contracts only against economically comparable peers, never mixing
    expirations or underlyings. The original `timestamp` value is
    preserved under `_real_timestamp` for any caller that still needs
    it."""
    out = []
    for r in panel_rows:
        copy = dict(r)
        copy["_real_timestamp"] = copy.get("timestamp")
        copy["timestamp"] = copy["cs_group_key"]
        out.append(copy)
    return out


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting for a small (<=3x3 in
    this module's usage) square system. Returns None if the system is
    singular (e.g. a constant/degenerate feature column)."""
    n = len(matrix)
    augmented = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(augmented[r][col]))
        if abs(augmented[pivot_row][col]) < 1e-12:
            return None
        augmented[col], augmented[pivot_row] = augmented[pivot_row], augmented[col]
        pivot = augmented[col][col]
        augmented[col] = [v / pivot for v in augmented[col]]
        for r in range(n):
            if r != col:
                factor = augmented[r][col]
                augmented[r] = [mrv - factor * mcv for mrv, mcv in zip(augmented[r], augmented[col])]
    return [augmented[i][n] for i in range(n)]


def ols_fit(feature_columns: list[list[float]], y: list[float]) -> tuple[list[float], float] | None:
    """Ordinary least squares, intercept + `len(feature_columns)` slopes.
    `feature_columns[j]` and `y` must already be the same length and
    contain no `None` (callers filter first). Returns
    `(coeffs, r_squared)` where `coeffs[0]` is the intercept; `None` if
    there are too few observations or the design matrix is singular."""
    n_obs = len(y)
    k = len(feature_columns)
    if n_obs < k + 2:
        return None
    design = [[1.0] + [feature_columns[j][i] for j in range(k)] for i in range(n_obs)]
    p = k + 1
    xtx = [[sum(design[i][a] * design[i][b] for i in range(n_obs)) for b in range(p)] for a in range(p)]
    xty = [sum(design[i][a] * y[i] for i in range(n_obs)) for a in range(p)]
    coeffs = _solve_linear_system(xtx, xty)
    if coeffs is None:
        return None
    y_mean = mean(y)
    sst = sum((v - y_mean) ** 2 for v in y)
    if sst == 0:
        return coeffs, 0.0
    preds = [sum(coeffs[a] * design[i][a] for a in range(p)) for i in range(n_obs)]
    ssr = sum((yi - pi) ** 2 for yi, pi in zip(y, preds))
    return coeffs, 1 - ssr / sst


@dataclass(frozen=True)
class UnderlyingControlReport:
    option_feature: str
    target: str
    n: int
    model_a_r_squared: float | None  # target ~ underlying_return alone
    model_b_r_squared: float | None  # target ~ underlying_return + option_feature
    delta_r_squared: float | None
    option_ic: float | None  # IC(option_feature, target) -- from mechanical_baseline
    underlying_ic: float | None  # IC(option_feature, underlying's own target) -- from mechanical_baseline
    ic_gap: float | None
    classification: str  # src.options.mechanical_baseline.BaselineClassification value

    def adds_information_beyond_underlying(self) -> bool:
        from src.options.mechanical_baseline import BaselineClassification
        return self.classification == BaselineClassification.OPTION_ADDS_INFORMATION


def underlying_control_comparison(
    panel_rows: Sequence[dict], *, option_feature_col: str, target_col: str, underlying_return_col: str,
    underlying_target_col: str, min_universe_size: int = 3, material_gap: float = 0.01,
) -> UnderlyingControlReport:
    """`underlying_return_col` is the underlying's own SAME-horizon
    forward return used as the regression control (e.g.
    `forward_underlying_return_5`); `underlying_target_col` is what
    `compare_option_vs_underlying_signal` cross-sectionally ranks the
    feature against as the "underlying's own target" (often the SAME
    column, but callers must state it explicitly -- no silent
    string-parsing guess of which horizon a target name implies)."""
    common = [
        r for r in panel_rows
        if r.get(option_feature_col) is not None and r.get(target_col) is not None and r.get(underlying_return_col) is not None
    ]
    xs = [r[underlying_return_col] for r in common]
    fs = [r[option_feature_col] for r in common]
    ys = [r[target_col] for r in common]

    model_a = ols_fit([xs], ys)
    model_b = ols_fit([xs, fs], ys)
    model_a_r2 = model_a[1] if model_a else None
    model_b_r2 = model_b[1] if model_b else None
    delta = (model_b_r2 - model_a_r2) if (model_a_r2 is not None and model_b_r2 is not None) else None

    scoped = economically_scoped_rows(panel_rows)
    baseline = compare_option_vs_underlying_signal(
        scoped, feature_col=option_feature_col, option_target_col=target_col,
        underlying_target_col=underlying_target_col, min_universe_size=min_universe_size, material_gap=material_gap,
    )

    return UnderlyingControlReport(
        option_feature=option_feature_col, target=target_col, n=len(common),
        model_a_r_squared=model_a_r2, model_b_r_squared=model_b_r2, delta_r_squared=delta,
        option_ic=baseline.option_ic, underlying_ic=baseline.underlying_ic, ic_gap=baseline.gap,
        classification=baseline.classification,
    )


def residualize_against_underlying(
    panel_rows: Sequence[dict], *, option_target_col: str, underlying_target_col: str, out_col: str | None = None,
) -> list[dict]:
    """Part 7's causal benchmark model: fits ONE global OLS
    `option_target ~ underlying_target` across the whole real panel, then
    attaches each row's residual under `out_col` (default
    `f"{option_target_col}_residualized"`). Returns NEW row dicts (never
    mutates the input) with `None` for any row missing either input --
    never a fabricated residual. If Greeks/delta are unavailable (this
    dataset has none natively -- see `free_dataset_limitations.py`), no
    delta-adjustment is attempted; this is an EMPIRICAL regression
    residual only, clearly distinct from a delta-hedged residual, and is
    labeled as such by its column name."""
    out_col = out_col or f"{option_target_col}_residualized"
    eligible = [
        i for i, r in enumerate(panel_rows)
        if r.get(option_target_col) is not None and r.get(underlying_target_col) is not None
    ]
    xs = [panel_rows[i][underlying_target_col] for i in eligible]
    ys = [panel_rows[i][option_target_col] for i in eligible]
    fit = ols_fit([xs], ys)

    new_rows = [dict(r) for r in panel_rows]
    if fit is None:
        for r in new_rows:
            r[out_col] = None
        return new_rows

    coeffs, _r2 = fit
    intercept, slope = coeffs[0], coeffs[1]
    eligible_set = set(eligible)
    for i, r in enumerate(new_rows):
        if i in eligible_set:
            predicted = intercept + slope * r[underlying_target_col]
            r[out_col] = r[option_target_col] - predicted
        else:
            r[out_col] = None
    return new_rows
