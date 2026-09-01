"""Phase 7, Part 7: a general, configurable cross-sectional alpha
evaluator. Wraps Phase 4's compute_ic_series/cross_sectional_quantile_returns
(src.research.ic, src.research.quantile) rather than reimplementing
cross-sectional ranking — this module adds exactly what those two didn't
already have: an IC t-statistic/p-value, and configurable PORTFOLIO
WEIGHTING (equal / signal-weighted / rank-weighted) for the quantile
spread, none of which existed before Phase 7.

Nothing here auto-selects n_quantiles, horizon, or weighting — Part 7 is
explicit that these choices are NOT optimized automatically; every
CrossSectionalAlphaConfig field must be supplied by the caller.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Sequence

from src.research.analysis import mean
from src.research.ic import ICSummary, compute_ic_series, summarize_ic
from src.research.quantile import QuantilePortfolioReport, cross_sectional_quantile_returns
from src.research.stats_utils import t_statistic, two_tailed_p_value_from_z

WeightingMethod = Literal["equal", "signal_weighted", "rank_weighted"]


@dataclass(frozen=True)
class CrossSectionalAlphaConfig:
    feature_col: str
    target_col: str
    n_quantiles: int = 5
    min_universe_size: int = 3
    weighting: WeightingMethod = "equal"


@dataclass(frozen=True)
class WeightedPortfolioReturn:
    weighting: WeightingMethod
    long_short_return: float | None  # long the top quantile, short the bottom quantile, per the chosen weighting
    timestamps_used: int


@dataclass(frozen=True)
class CrossSectionalAlphaReport:
    ic_summary: ICSummary
    ic_t_statistic: float | None
    ic_p_value: float | None
    quantile_report: QuantilePortfolioReport
    weighted_portfolio: WeightedPortfolioReturn

    def render(self) -> str:
        lines = [self.ic_summary.render(), f"IC t-statistic: {self.ic_t_statistic}  (normal-approximation p-value: {self.ic_p_value})", "", self.quantile_report.render(), ""]
        lines.append(f"Weighted long-short return ({self.weighted_portfolio.weighting}): {self.weighted_portfolio.long_short_return}  (timestamps_used={self.weighted_portfolio.timestamps_used})")
        return "\n".join(lines)


def _weighted_long_short_return(panel_rows: Sequence[dict], config: CrossSectionalAlphaConfig) -> WeightedPortfolioReturn:
    """At each timestamp: rank the eligible universe by feature_col,
    take the top and bottom n_quantiles-th bucket, and compute a
    long-short return under the requested weighting:
      equal          -> simple average within each leg
      signal_weighted-> weight by |feature value| within each leg (a
                         stronger signal gets more weight)
      rank_weighted   -> weight by cross-sectional rank distance from the
                         median within each leg (more extreme rank = more weight)
    Averaged across all timestamps with an eligible top+bottom bucket.
    """
    by_timestamp: dict[datetime, list[tuple[str, float, float]]] = defaultdict(list)
    for row in panel_rows:
        f, t = row.get(config.feature_col), row.get(config.target_col)
        if f is not None and t is not None:
            by_timestamp[row["timestamp"]].append((row.get("symbol", ""), f, t))

    period_returns: list[float] = []
    for ts, triples in by_timestamp.items():
        if len(triples) < config.min_universe_size:
            continue
        ranked = sorted(triples, key=lambda triple: triple[1])
        n = len(ranked)
        bucket_of = [min(config.n_quantiles - 1, (i * config.n_quantiles) // n) for i in range(n)]
        bottom = [ranked[i] for i in range(n) if bucket_of[i] == 0]
        top = [ranked[i] for i in range(n) if bucket_of[i] == config.n_quantiles - 1]
        if not bottom or not top:
            continue

        def leg_return(leg: list[tuple[str, float, float]]) -> float:
            if config.weighting == "equal":
                return mean([r for _s, _f, r in leg])
            if config.weighting == "signal_weighted":
                weights = [abs(f) for _s, f, _r in leg]
                total_w = sum(weights)
                if total_w == 0:
                    return mean([r for _s, _f, r in leg])
                return sum(w * r for w, (_s, _f, r) in zip(weights, leg)) / total_w
            if config.weighting == "rank_weighted":
                median_rank = (n - 1) / 2
                weights = []
                for s, f, r in leg:
                    idx = ranked.index((s, f, r))
                    weights.append(abs(idx - median_rank))
                total_w = sum(weights)
                if total_w == 0:
                    return mean([r for _s, _f, r in leg])
                return sum(w * r for w, (_s, _f, r) in zip(weights, leg)) / total_w
            raise ValueError(f"unknown weighting method: {config.weighting}")

        period_returns.append(leg_return(top) - leg_return(bottom))

    long_short = mean(period_returns) if period_returns else None
    return WeightedPortfolioReturn(weighting=config.weighting, long_short_return=long_short, timestamps_used=len(period_returns))


def evaluate_cross_sectional_alpha(panel_rows: Sequence[dict], config: CrossSectionalAlphaConfig) -> CrossSectionalAlphaReport:
    ic_points = compute_ic_series(panel_rows, config.feature_col, config.target_col, min_universe_size=config.min_universe_size)
    ic_summary = summarize_ic(ic_points, feature_name=config.feature_col, target_name=config.target_col)
    ic_values = [p.ic for p in ic_points if p.ic is not None]
    t_stat = t_statistic(ic_values) if len(ic_values) >= 2 else None
    p_value = two_tailed_p_value_from_z(t_stat) if t_stat is not None else None

    quantile_report = cross_sectional_quantile_returns(panel_rows, config.feature_col, config.target_col, n_quantiles=config.n_quantiles, min_universe_size=config.min_universe_size)
    weighted = _weighted_long_short_return(panel_rows, config)

    return CrossSectionalAlphaReport(ic_summary=ic_summary, ic_t_statistic=t_stat, ic_p_value=p_value, quantile_report=quantile_report, weighted_portfolio=weighted)
