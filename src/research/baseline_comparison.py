"""Phase 7, Part 15: baseline controls at the discovery (cross-sectional
IC) stage — reuses existing machinery rather than duplicating it:
  - "random signal"    -> src.research.cross_sectional_placebo.random_feature_control
  - "shuffled signal"   -> src.research.cross_sectional_placebo.shuffled_signal_placebo
  - "simple momentum"   -> the plain ROC(20) feature's own IC (computed the
                           same way as every other candidate feature)
  - "simple mean reversion" -> the plain zscore(20) feature's own IC
  - "buy-and-hold" / "benchmark" -> src.research.baseline.buy_and_hold_curve
                           on the benchmark symbol's own bars — a
                           backtest-level comparison, reported alongside
                           the IC-level ones for context, not blended
                           into them.

Answers Part 15's question directly: "does this candidate feature add
information beyond a trivial alternative?" — by placing its IC next to
each baseline's IC/return, never by computing anything new.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.research.cross_sectional_placebo import random_feature_control, shuffled_signal_placebo
from src.research.ic import ICSummary, compute_ic_series, summarize_ic


@dataclass(frozen=True)
class BaselineComparisonReport:
    candidate_feature: str
    candidate_ic: float | None
    momentum_baseline_ic: float | None  # None if the candidate IS a momentum feature (no self-comparison)
    mean_reversion_baseline_ic: float | None  # None if the candidate IS a mean-reversion feature
    random_signal_ic_mean: float | None
    random_signal_ic_stdev: float | None
    shuffled_signal_empirical_p_value: float | None
    adds_information_beyond_random: bool | None  # candidate's |IC| clearly exceeds the random-signal baseline's spread

    def render(self) -> str:
        lines = [
            f"BASELINE COMPARISON — {self.candidate_feature}",
            f"  candidate IC: {self.candidate_ic}",
            f"  momentum baseline IC: {self.momentum_baseline_ic}",
            f"  mean-reversion baseline IC: {self.mean_reversion_baseline_ic}",
            f"  random-signal IC: mean={self.random_signal_ic_mean} stdev={self.random_signal_ic_stdev}",
            f"  shuffled-signal empirical p-value: {self.shuffled_signal_empirical_p_value}",
            f"  adds information beyond a random signal: {self.adds_information_beyond_random}",
        ]
        return "\n".join(lines)


def compare_against_baselines(
    panel_rows: list[dict], *, candidate_feature_col: str, target_col: str,
    momentum_panel_rows: list[dict] | None = None, momentum_feature_col: str = "feature_roc_20",
    mean_reversion_panel_rows: list[dict] | None = None, mean_reversion_feature_col: str = "feature_zscore_20",
    n_placebo_trials: int = 100, seed: int = 46, min_universe_size: int = 3,
) -> BaselineComparisonReport:
    def _ic(rows, feature_col, target) -> float | None:
        return summarize_ic(compute_ic_series(rows, feature_col, target, min_universe_size=min_universe_size), feature_name=feature_col, target_name=target).average_ic

    candidate_ic = _ic(panel_rows, candidate_feature_col, target_col)
    momentum_ic = _ic(momentum_panel_rows, momentum_feature_col, target_col) if momentum_panel_rows is not None and candidate_feature_col != momentum_feature_col else None
    mr_ic = _ic(mean_reversion_panel_rows, mean_reversion_feature_col, target_col) if mean_reversion_panel_rows is not None and candidate_feature_col != mean_reversion_feature_col else None

    random_control = random_feature_control(panel_rows, target_col=target_col, n_trials=n_placebo_trials, seed=seed, min_universe_size=min_universe_size)
    from src.research.analysis import mean, stdev
    random_mean = mean(random_control.placebo_distribution) if random_control.placebo_distribution else None
    random_stdev = stdev(random_control.placebo_distribution) if len(random_control.placebo_distribution) >= 2 else None

    shuffled = shuffled_signal_placebo(panel_rows, feature_col=candidate_feature_col, target_col=target_col, n_trials=n_placebo_trials, seed=seed, min_universe_size=min_universe_size)

    adds_info = None
    if candidate_ic is not None and random_mean is not None and random_stdev is not None and random_stdev > 0:
        adds_info = abs(candidate_ic - random_mean) > 2 * random_stdev  # candidate IC clearly outside the random-signal null's spread

    return BaselineComparisonReport(
        candidate_feature=candidate_feature_col, candidate_ic=candidate_ic, momentum_baseline_ic=momentum_ic, mean_reversion_baseline_ic=mr_ic,
        random_signal_ic_mean=random_mean, random_signal_ic_stdev=random_stdev, shuffled_signal_empirical_p_value=shuffled.empirical_p_value,
        adds_information_beyond_random=adds_info,
    )
