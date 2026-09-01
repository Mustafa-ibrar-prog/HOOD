"""Phase 7, Part 5: data-snooping / overfitting diagnostics.

Every function here either (a) computes a real number under documented
assumptions, or (b) returns NOT_APPLICABLE with the specific reason those
assumptions were not met. Nothing here fabricates confidence to satisfy
the prompt's request for these metrics — a metric that cannot be computed
honestly from the available evidence is reported as such.

Implements, from scratch (pure stdlib, no numpy/scipy):
  - Probability of Backtest Overfitting (PBO) via Combinatorially
    Symmetric Cross-Validation (Bailey, Borwein, Zhu & Lopez de Prado 2014)
  - Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014)
  - an effective-number-of-trials estimate from average pairwise
    correlation among candidate variants' return series
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Sequence

from src.research.analysis import mean, pearson_correlation, stdev
from src.research.stats_utils import normal_cdf


# ==============================================================================
# Probability of Backtest Overfitting (PBO)
# ==============================================================================


@dataclass(frozen=True)
class PBOResult:
    applicable: bool
    reason: str
    n_variants: int | None = None
    n_periods: int | None = None
    n_combinations: int | None = None
    pbo: float | None = None  # fraction of combinations where the best IS variant underperforms OOS (rank <= median)

    def render(self) -> str:
        if not self.applicable:
            return f"PBO: NOT_APPLICABLE ({self.reason})"
        return f"PBO: {self.pbo:.3f}  ({self.n_combinations} combinations, {self.n_variants} variants x {self.n_periods} periods)"


def probability_of_backtest_overfitting(returns_by_variant: Sequence[Sequence[float]], *, min_periods: int = 4) -> PBOResult:
    """`returns_by_variant[i][s]` = variant i's return in sub-period s —
    ALL variants must share the same S contiguous sub-periods (e.g. a
    parameter sweep's per-window returns). Implements Combinatorially
    Symmetric Cross-Validation: splits the S periods into all size-S/2
    train/test combinations, and for each combination checks whether the
    variant that looked best IN-SAMPLE (by mean return over the training
    half) ranks in the bottom half of variants OUT-OF-SAMPLE (over the
    testing half). PBO is the fraction of combinations where this happens
    — a high PBO means "the best in-sample choice is no better than
    chance out-of-sample," the signature of overfitting a parameter sweep.

    Requires >= 2 variants and an EVEN number of periods >= min_periods
    (CSCV splits periods exactly in half); returns NOT_APPLICABLE
    otherwise rather than forcing an uneven split."""
    n_variants = len(returns_by_variant)
    if n_variants < 2:
        return PBOResult(applicable=False, reason=f"PBO requires >= 2 candidate variants to compare, got {n_variants}")
    n_periods = len(returns_by_variant[0])
    if any(len(r) != n_periods for r in returns_by_variant):
        return PBOResult(applicable=False, reason="all variants must share the same number of sub-periods")
    if n_periods < min_periods:
        return PBOResult(applicable=False, reason=f"need >= {min_periods} sub-periods for a meaningful CSCV split, got {n_periods}")
    if n_periods % 2 != 0:
        return PBOResult(applicable=False, reason=f"CSCV requires an EVEN number of sub-periods to split in half, got {n_periods}")

    half = n_periods // 2
    period_indices = list(range(n_periods))
    combos = list(itertools.combinations(period_indices, half))
    # Each unordered half-selection defines ONE train/test split by itself
    # (train = selected half, test = the complement) — using all C(n,half)
    # selections already covers every symmetric train/test partition once,
    # the standard CSCV construction.
    overfit_count = 0
    n_combinations = 0
    for train_idx in combos:
        test_idx = tuple(i for i in period_indices if i not in train_idx)
        train_means = [mean([returns_by_variant[v][i] for i in train_idx]) for v in range(n_variants)]
        best_variant = max(range(n_variants), key=lambda v: train_means[v])
        test_means = [mean([returns_by_variant[v][i] for i in test_idx]) for v in range(n_variants)]
        # rank of the IS-best variant OOS, 1 = best OOS too
        oos_rank = sorted(range(n_variants), key=lambda v: test_means[v], reverse=True).index(best_variant) + 1
        median_rank = (n_variants + 1) / 2
        if oos_rank > median_rank:  # the IS winner fell into the BOTTOM half OOS
            overfit_count += 1
        n_combinations += 1

    return PBOResult(applicable=True, reason="", n_variants=n_variants, n_periods=n_periods, n_combinations=n_combinations, pbo=overfit_count / n_combinations)


# ==============================================================================
# Deflated Sharpe Ratio (DSR)
# ==============================================================================


_EULER_MASCHERONI = 0.5772156649015329


def _inverse_normal_cdf(p: float) -> float:
    """Peter Acklam's rational approximation to the inverse standard
    normal CDF — accurate to ~1.15e-9, pure stdlib, no external
    dependency. Standard, widely used approximation (not novel to this
    codebase)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def _skewness(xs: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    m = mean(xs)
    sd = stdev(xs)
    if sd == 0:
        return None
    return (sum((x - m) ** 3 for x in xs) / n) / (sd ** 3)


def _kurtosis(xs: Sequence[float]) -> float | None:
    """Sample excess-free (i.e. NOT subtracting 3) kurtosis — matches the
    gamma_4 convention used directly in the DSR formula below."""
    n = len(xs)
    if n < 4:
        return None
    m = mean(xs)
    sd = stdev(xs)
    if sd == 0:
        return None
    return (sum((x - m) ** 4 for x in xs) / n) / (sd ** 4)


@dataclass(frozen=True)
class DeflatedSharpeResult:
    applicable: bool
    reason: str
    observed_sharpe: float | None = None
    expected_max_sharpe_under_n_trials: float | None = None
    n_trials: int | None = None
    n_observations: int | None = None
    skewness: float | None = None
    kurtosis: float | None = None
    deflated_sharpe_ratio: float | None = None  # a probability in [0, 1]: P(true SR > 0 | observed SR, N trials)

    def render(self) -> str:
        if not self.applicable:
            return f"Deflated Sharpe Ratio: NOT_APPLICABLE ({self.reason})"
        return (
            f"Deflated Sharpe Ratio: {self.deflated_sharpe_ratio:.4f}  "
            f"(observed SR={self.observed_sharpe:.4f}, expected max SR under {self.n_trials} trials={self.expected_max_sharpe_under_n_trials:.4f}, "
            f"n_obs={self.n_observations}, skew={self.skewness:.3f}, kurtosis={self.kurtosis:.3f})"
        )


def deflated_sharpe_ratio(
    returns: Sequence[float], *, n_trials: int, sharpe_variance_across_trials: float | None = None, periods_per_year: float = 252.0, min_observations: int = 30,
) -> DeflatedSharpeResult:
    """`returns` is the OBSERVED (winning) variant's return series;
    `n_trials` is how many variants/parameter combinations were actually
    searched to find it (this MUST come from an honest count — e.g.
    src.research.search_space.compute_search_space_summary — never a
    guess).

    Follows Bailey & Lopez de Prado (2014) exactly: the entire test
    statistic is computed in PER-PERIOD (non-annualized) Sharpe units —
    the asymptotic variance formula for a Sharpe-ratio ESTIMATOR
    (Var[SR_hat] ~= (1 - gamma3*SR_hat + (gamma4-1)/4*SR_hat^2) / (n-1),
    Mertens 2002) is only valid at that native sampling frequency, so
    annualizing SR_hat before plugging it in would silently invalidate
    the formula. `observed_sharpe` in the result IS annualized (for
    readability); `deflated_sharpe_ratio` itself is computed from the
    per-period figure and is unaffected by the annualization choice.

    `sharpe_variance_across_trials`, if supplied, must ALSO be in
    per-period units (Var[SR_hat] at the same frequency as `returns`).
    When omitted, this function uses the same Mertens-formula estimate
    for every trial as it computed for the observed one — a documented
    simplifying assumption (every trial assumed to share this trial's
    sampling variance), not a hidden one.

    Requires >= min_observations returns (default 30 — below that, sample
    skewness/kurtosis estimates are too noisy to trust) and n_trials >= 2
    (deflation is meaningless for a single trial)."""
    n = len(returns)
    if n < min_observations:
        return DeflatedSharpeResult(applicable=False, reason=f"need >= {min_observations} return observations for stable skew/kurtosis estimates, got {n}")
    if n_trials < 2:
        return DeflatedSharpeResult(applicable=False, reason=f"deflation requires >= 2 trials searched, got {n_trials}")
    sd = stdev(returns)
    if sd == 0:
        return DeflatedSharpeResult(applicable=False, reason="return series has zero variance")

    sr_hat_period = mean(returns) / sd  # NON-annualized — the units the DSR formula is derived in
    skew = _skewness(returns)
    kurt = _kurtosis(returns)
    if skew is None or kurt is None:
        return DeflatedSharpeResult(applicable=False, reason="insufficient observations to estimate skewness/kurtosis")

    denom = 1 - skew * sr_hat_period + ((kurt - 1) / 4) * sr_hat_period ** 2
    if denom <= 0:
        return DeflatedSharpeResult(applicable=False, reason=f"DSR denominator is non-positive ({denom:.4f}) given this sample's skew/kurtosis — the formula's assumptions are not satisfied for this sample")
    var_sr_hat_period = sharpe_variance_across_trials if sharpe_variance_across_trials is not None else denom / (n - 1)
    if var_sr_hat_period <= 0:
        return DeflatedSharpeResult(applicable=False, reason="non-positive cross-trial Sharpe-estimator variance — cannot estimate expected max Sharpe under the null")

    # Expected maximum per-period Sharpe ratio across n_trials i.i.d.
    # trials with a TRUE Sharpe of 0 (Bailey & Lopez de Prado 2014, eq. 7).
    sr0_expected_max_period = math.sqrt(var_sr_hat_period) * (
        (1 - _EULER_MASCHERONI) * _inverse_normal_cdf(1 - 1 / n_trials) + _EULER_MASCHERONI * _inverse_normal_cdf(1 - 1 / (n_trials * math.e))
    )

    z = (sr_hat_period - sr0_expected_max_period) / math.sqrt(var_sr_hat_period)
    dsr = normal_cdf(z)
    return DeflatedSharpeResult(
        applicable=True, reason="",
        observed_sharpe=sr_hat_period * math.sqrt(periods_per_year),  # annualized, for readability only
        expected_max_sharpe_under_n_trials=sr0_expected_max_period * math.sqrt(periods_per_year),
        n_trials=n_trials, n_observations=n, skewness=skew, kurtosis=kurt, deflated_sharpe_ratio=dsr,
    )


# ==============================================================================
# Effective number of (correlated) trials
# ==============================================================================


@dataclass(frozen=True)
class EffectiveTrialsResult:
    applicable: bool
    reason: str
    nominal_trials: int | None = None
    average_pairwise_correlation: float | None = None
    effective_trials: float | None = None

    def render(self) -> str:
        if not self.applicable:
            return f"Effective number of trials: NOT_APPLICABLE ({self.reason})"
        return f"Effective trials: {self.effective_trials:.2f}  (nominal={self.nominal_trials}, avg pairwise correlation={self.average_pairwise_correlation:.3f})"


def effective_number_of_trials(returns_by_variant: Sequence[Sequence[float]]) -> EffectiveTrialsResult:
    """Highly correlated variants (e.g. 20-day vs 22-day momentum) are not
    genuinely independent trials — this approximates how many INDEPENDENT
    trials the searched set is actually worth, via
    N_eff = N / (1 + (N-1) * avg_pairwise_correlation), a standard
    correction for the effective sample size of correlated tests. avg
    pairwise correlation near 1 (near-duplicate variants) collapses N_eff
    toward 1; near 0 (genuinely distinct variants) leaves N_eff near N."""
    n = len(returns_by_variant)
    if n < 2:
        return EffectiveTrialsResult(applicable=False, reason=f"need >= 2 variants to estimate pairwise correlation, got {n}")
    correlations = []
    for i, j in itertools.combinations(range(n), 2):
        c = pearson_correlation(list(returns_by_variant[i]), list(returns_by_variant[j]))
        if c is not None:
            correlations.append(c)
    if not correlations:
        return EffectiveTrialsResult(applicable=False, reason="no valid pairwise correlations could be computed (constant or too-short series)")
    avg_corr = mean(correlations)
    denom = 1 + (n - 1) * avg_corr
    if denom <= 0:
        return EffectiveTrialsResult(applicable=False, reason=f"average pairwise correlation ({avg_corr:.3f}) makes the effective-trials formula undefined (non-positive denominator)")
    return EffectiveTrialsResult(applicable=True, reason="", nominal_trials=n, average_pairwise_correlation=avg_corr, effective_trials=n / denom)
