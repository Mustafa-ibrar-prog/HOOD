"""Phase 31, Parts 5 & 6/18 — CROSS_SECTIONAL and TIME_SERIES evidence,
reported separately (Part 6's explicit instruction), never blended into
one number.

CROSS_SECTIONAL (Part 5): reuses `src.research.cross_sectional_alpha.
evaluate_cross_sectional_alpha` directly — it already computes
everything Part 5 asks for (per-timestamp ranking, quantile buckets,
Q5-Q1 spread, IC, monotonicity, via `src.research.quantile.
QuantilePortfolioReport`'s `spread_q5_minus_q1`/`is_monotonic` fields).
The one thing added here is ECONOMIC SCOPING: every cross-sectional call
in this campaign runs through `phase31_underlying_control.
economically_scoped_rows` first (same underlying + expiration + real
timestamp peer groups, never raw cross-underlying/cross-expiration
ranking — Part 5's explicit "avoid comparing contracts that are not
economically comparable... do not mix expirations blindly"), and
`src.options.expiration_diversity.has_cross_sectional_variance` is
checked first so a structurally-undefined case (e.g. a feature constant
within every peer group) is reported as `CROSS_SECTIONAL_IC_UNDEFINED`,
never a misleading `None`.

TIME_SERIES (Part 6): genuinely new — no existing module runs a
PER-CONTRACT (not pooled, not cross-sectional) correlation with an
explicit minimum-observation-count / minimum-independent-period /
overlap-dependence gate. `independent_periods_estimate` divides a
contract's row count by its horizon (Part 6: "no excessive overlap
dependence") as a documented, conservative approximation for how many
NON-OVERLAPPING forward-return windows that contract's real history
actually contains — not a rigorous Newey-West-style correction, but an
honest, disclosed guard against treating N overlapping rows as N
independent observations.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

from src.options.expiration_diversity import CROSS_SECTIONAL_IC_UNDEFINED, has_cross_sectional_variance
from src.options.phase31_underlying_control import economically_scoped_rows
from src.research.analysis import mean, pearson_correlation, spearman_correlation
from src.research.cross_sectional_alpha import CrossSectionalAlphaConfig, CrossSectionalAlphaReport, evaluate_cross_sectional_alpha


@dataclass(frozen=True)
class CrossSectionalEvidence:
    feature_col: str
    target_col: str
    applicable: bool
    reason: str
    report: CrossSectionalAlphaReport | None


def evaluate_cross_sectional_evidence(
    panel_rows: Sequence[dict], *, feature_col: str, target_col: str,
    n_quantiles: int = 5, min_universe_size: int = 3, weighting: str = "equal",
) -> CrossSectionalEvidence:
    scoped = economically_scoped_rows(panel_rows)
    if not has_cross_sectional_variance(scoped, feature_col):
        return CrossSectionalEvidence(feature_col, target_col, False, CROSS_SECTIONAL_IC_UNDEFINED, None)
    config = CrossSectionalAlphaConfig(
        feature_col=feature_col, target_col=target_col, n_quantiles=n_quantiles,
        min_universe_size=min_universe_size, weighting=weighting,
    )
    report = evaluate_cross_sectional_alpha(scoped, config)
    if report.ic_summary.average_ic is None:
        return CrossSectionalEvidence(feature_col, target_col, False, "no economically-scoped peer group ever reached min_universe_size", report)
    return CrossSectionalEvidence(feature_col, target_col, True, "", report)


@dataclass(frozen=True)
class TimeSeriesContractResult:
    option_id: str
    n_obs: int
    independent_periods_estimate: int
    pearson: float | None
    spearman: float | None
    eligible: bool
    reason: str


@dataclass(frozen=True)
class TimeSeriesEvidence:
    feature_col: str
    target_col: str
    horizon_bars: int
    min_obs: int
    min_independent_periods: int
    n_contracts_evaluated: int
    n_contracts_eligible: int
    per_contract: tuple[TimeSeriesContractResult, ...]
    pooled_spearman_mean: float | None
    sign_stable_fraction: float | None
    applicable: bool
    reason: str


def evaluate_time_series_evidence(
    panel_rows: Sequence[dict], *, feature_col: str, target_col: str, horizon_bars: int,
    min_obs: int = 15, min_independent_periods: int = 5,
) -> TimeSeriesEvidence:
    by_contract: dict[str, list[dict]] = defaultdict(list)
    for r in panel_rows:
        if r.get(feature_col) is not None and r.get(target_col) is not None:
            by_contract[r["option_id"]].append(r)

    per_contract: list[TimeSeriesContractResult] = []
    eligible_spearmans: list[float] = []
    for option_id, rows in by_contract.items():
        n = len(rows)
        independent_periods = max(1, n // max(horizon_bars, 1))
        if n < min_obs or independent_periods < min_independent_periods:
            per_contract.append(TimeSeriesContractResult(
                option_id, n, independent_periods, None, None, False,
                f"insufficient data (n={n} < min_obs={min_obs}, or independent_periods~{independent_periods} < {min_independent_periods})",
            ))
            continue
        xs = [r[feature_col] for r in rows]
        ys = [r[target_col] for r in rows]
        pear = pearson_correlation(xs, ys)
        spear = spearman_correlation(xs, ys)
        if spear is None:
            per_contract.append(TimeSeriesContractResult(option_id, n, independent_periods, pear, spear, False, "correlation undefined (constant series)"))
            continue
        per_contract.append(TimeSeriesContractResult(option_id, n, independent_periods, pear, spear, True, ""))
        eligible_spearmans.append(spear)

    n_eligible = len(eligible_spearmans)
    if n_eligible == 0:
        return TimeSeriesEvidence(
            feature_col=feature_col, target_col=target_col, horizon_bars=horizon_bars, min_obs=min_obs,
            min_independent_periods=min_independent_periods, n_contracts_evaluated=len(by_contract),
            n_contracts_eligible=0, per_contract=tuple(per_contract), pooled_spearman_mean=None,
            sign_stable_fraction=None, applicable=False,
            reason="no contract met the minimum observation/independent-period thresholds",
        )
    pooled_mean = mean(eligible_spearmans)
    sign_stable = sum(1 for s in eligible_spearmans if (s > 0) == (pooled_mean > 0)) / n_eligible
    return TimeSeriesEvidence(
        feature_col=feature_col, target_col=target_col, horizon_bars=horizon_bars, min_obs=min_obs,
        min_independent_periods=min_independent_periods, n_contracts_evaluated=len(by_contract),
        n_contracts_eligible=n_eligible, per_contract=tuple(per_contract), pooled_spearman_mean=pooled_mean,
        sign_stable_fraction=sign_stable, applicable=True, reason="",
    )
