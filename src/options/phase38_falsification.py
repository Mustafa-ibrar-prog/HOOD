"""Phase 38, Part 9 — required falsification tests, operating on
`ForwardOutcome` records (Phase 38's own live-observation-derived trade
shape, distinct from `BacktestTrade` -- see `phase38_targets.py`'s
module docstring for why a new shape was needed here).

Every test reports an honest `INSUFFICIENT_SAMPLE` outcome rather than
fabricating a verdict when there isn't enough data -- reusing this
project's established `t_test_p_value` (`src.research.stats_utils`) and
the same `MIN_SAMPLE_FOR_A_VERDICT` floor `phase38_underlying_vs_option_edge.py`
already established, rather than inventing new statistical machinery or
a new sample-size floor.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from src.options.phase38_causal_validation_dataset import CausalFeatureRow
from src.options.phase38_targets import ForwardHorizon, ForwardOutcome, compute_forward_outcome
from src.options.phase38_underlying_vs_option_edge import MIN_SAMPLE_FOR_A_VERDICT
from src.research.stats_utils import t_test_p_value

INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


@dataclass(frozen=True)
class OutcomeStats:
    n: int
    mean_return: float | None
    median_return: float | None
    win_rate: float | None
    p_value_vs_zero: float | None


def outcome_stats(outcomes: Sequence[ForwardOutcome]) -> OutcomeStats:
    returns = [o.executable_return_pct for o in outcomes if o.executable_return_pct is not None]
    n = len(returns)
    if n == 0:
        return OutcomeStats(0, None, None, None, None)
    return OutcomeStats(
        n=n, mean_return=statistics.mean(returns), median_return=statistics.median(returns),
        win_rate=sum(1 for r in returns if r > 0) / n, p_value_vs_zero=t_test_p_value(returns) if n >= 2 else None,
    )


@dataclass(frozen=True)
class PlaceboResult:
    method: str
    n_observed: int
    n_trials: int
    observed_statistic: float | None
    empirical_p_value: float | None
    classification: str  # INSUFFICIENT_SAMPLE | "OBSERVED_NOT_DISTINGUISHABLE_FROM_PLACEBO" | "OBSERVED_EXCEEDS_PLACEBO"


def randomized_signal_placebo(
    observed: Sequence[ForwardOutcome], candidate_pool: Sequence[ForwardOutcome], *, n_trials: int = 30, seed: int = 42,
) -> PlaceboResult:
    """Draws `n_trials` random subsets of `candidate_pool`, each the same
    size as `observed`, and compares mean executable return. Part 9:
    'if placebo strategies perform similarly or better, reject/invalidate.'"""
    n = len(observed)
    if n < MIN_SAMPLE_FOR_A_VERDICT or len(candidate_pool) < n:
        return PlaceboResult("randomized_signal_placebo", n, 0, None, None, INSUFFICIENT_SAMPLE)

    observed_mean = outcome_stats(observed).mean_return
    if observed_mean is None:
        return PlaceboResult("randomized_signal_placebo", n, 0, None, None, INSUFFICIENT_SAMPLE)

    rng = random.Random(seed)
    pool = list(candidate_pool)
    at_or_above = 0
    for _ in range(n_trials):
        sample = rng.sample(pool, n)
        trial_mean = outcome_stats(sample).mean_return
        if trial_mean is not None and trial_mean >= observed_mean:
            at_or_above += 1
    p = at_or_above / n_trials
    classification = "OBSERVED_NOT_DISTINGUISHABLE_FROM_PLACEBO" if p >= 0.10 else "OBSERVED_EXCEEDS_PLACEBO"
    return PlaceboResult("randomized_signal_placebo", n, n_trials, observed_mean, p, classification)


def shuffled_feature_association_test(
    observed: Sequence[ForwardOutcome], feature_values: Sequence[float | None], *, feature_name: str, n_trials: int = 500, seed: int = 42,
) -> PlaceboResult:
    """Permutation test for whether `feature_name` (e.g. moneyness, IV,
    delta -- passed in as a parallel sequence to `observed`) is
    genuinely associated with the realized return, or whether the same
    correlation magnitude arises just as often from a random pairing."""
    paired = [(f, o.executable_return_pct) for f, o in zip(feature_values, observed) if f is not None and o.executable_return_pct is not None]
    n = len(paired)
    if n < MIN_SAMPLE_FOR_A_VERDICT:
        return PlaceboResult(f"shuffled_feature:{feature_name}", n, 0, None, None, INSUFFICIENT_SAMPLE)

    features = [f for f, _ in paired]
    returns = [r for _, r in paired]
    observed_corr = _correlation(features, returns)
    if observed_corr is None:
        return PlaceboResult(f"shuffled_feature:{feature_name}", n, 0, None, None, INSUFFICIENT_SAMPLE)

    rng = random.Random(seed)
    at_or_above = 0
    for _ in range(n_trials):
        shuffled = returns[:]
        rng.shuffle(shuffled)
        trial_corr = _correlation(features, shuffled)
        if trial_corr is not None and abs(trial_corr) >= abs(observed_corr):
            at_or_above += 1
    p = at_or_above / n_trials
    classification = "OBSERVED_NOT_DISTINGUISHABLE_FROM_PLACEBO" if p >= 0.10 else "OBSERVED_EXCEEDS_PLACEBO"
    return PlaceboResult(f"shuffled_feature:{feature_name}", n, n_trials, observed_corr, p, classification)


def _correlation(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    try:
        return statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        return None


@dataclass(frozen=True)
class TimingRobustnessResult:
    method: str
    n_original: int
    n_recomputed: int
    original_mean_return: float | None
    recomputed_mean_return: float | None
    classification: str


def _recompute_with_entry_offset(
    entry_rows: Sequence[CausalFeatureRow], full_dataset_by_option: Mapping[str, list[CausalFeatureRow]],
    *, horizon: ForwardHorizon, offset_cycles: int,
) -> list[ForwardOutcome]:
    recomputed = []
    for entry in entry_rows:
        chronology = sorted(full_dataset_by_option.get(entry.option_id, []), key=lambda r: r.observation_timestamp)
        try:
            idx = next(i for i, r in enumerate(chronology) if r.observation_cycle_id == entry.observation_cycle_id)
        except StopIteration:
            continue
        shifted_idx = idx + offset_cycles
        if shifted_idx < 0 or shifted_idx >= len(chronology):
            continue
        shifted_entry = chronology[shifted_idx]
        later_rows = chronology[shifted_idx + 1:]
        recomputed.append(compute_forward_outcome(shifted_entry, later_rows, horizon=horizon))
    return recomputed


def shifted_signal_test(
    entry_rows: Sequence[CausalFeatureRow], full_dataset_by_option: Mapping[str, list[CausalFeatureRow]],
    *, horizon: ForwardHorizon, shift_cycles: int = 1,
) -> TimingRobustnessResult:
    """Part 9: does the strategy's apparent edge depend on the EXACT
    signal timing? Re-derives each outcome using an entry `shift_cycles`
    observation cycles later than the real signal, holding everything
    else identical."""
    original = [compute_forward_outcome(e, sorted((r for r in full_dataset_by_option.get(e.option_id, []) if r.observation_timestamp > e.observation_timestamp), key=lambda r: r.observation_timestamp), horizon=horizon) for e in entry_rows]
    shifted = _recompute_with_entry_offset(entry_rows, full_dataset_by_option, horizon=horizon, offset_cycles=shift_cycles)
    orig_stats, shifted_stats = outcome_stats(original), outcome_stats(shifted)
    if orig_stats.n < MIN_SAMPLE_FOR_A_VERDICT or shifted_stats.n < MIN_SAMPLE_FOR_A_VERDICT:
        return TimingRobustnessResult("shifted_signal", orig_stats.n, shifted_stats.n, orig_stats.mean_return, shifted_stats.mean_return, INSUFFICIENT_SAMPLE)
    same_sign = (orig_stats.mean_return > 0) == (shifted_stats.mean_return > 0)
    classification = "ROBUST_TO_SIGNAL_SHIFT" if same_sign else "SIGN_FLIPS_UNDER_SIGNAL_SHIFT"
    return TimingRobustnessResult("shifted_signal", orig_stats.n, shifted_stats.n, orig_stats.mean_return, shifted_stats.mean_return, classification)


def execution_delay_test(
    entry_rows: Sequence[CausalFeatureRow], full_dataset_by_option: Mapping[str, list[CausalFeatureRow]],
    *, horizon: ForwardHorizon, delay_cycles: int = 1,
) -> TimingRobustnessResult:
    """Same mechanism as `shifted_signal_test`, distinct label: models
    'the real fill happened N cycles after the signal was recognized'
    (a realistic execution-latency scenario) rather than 'the signal
    itself occurred at a different time.'"""
    result = shifted_signal_test(entry_rows, full_dataset_by_option, horizon=horizon, shift_cycles=delay_cycles)
    return TimingRobustnessResult("execution_delay", result.n_original, result.n_recomputed, result.original_mean_return, result.recomputed_mean_return, result.classification)


@dataclass(frozen=True)
class CostStressResult:
    multiplier: float
    n: int
    mean_return_after_cost: float | None
    survives: bool | None  # None when insufficient sample


def spread_stress_test(observed: Sequence[ForwardOutcome], *, multipliers: Sequence[float] = (1.0, 2.0, 3.0, 5.0)) -> tuple[CostStressResult, ...]:
    """Assumes the REAL round-trip cost is at least the entry/exit
    bid-ask spread already embedded in `executable_return_pct`
    (buy-ask/sell-bid) -- this stress test asks 'what if the effective
    spread were N times wider than what was actually quoted,' an
    explicitly disclosed ASSUMPTION, never a fabricated historical
    spread."""
    results = []
    for m in multipliers:
        adjusted = []
        for o in observed:
            if o.entry_ask is None or o.entry_bid is None or o.exit_bid is None or o.exit_ask is None or o.executable_return_pct is None:
                continue
            extra_half_spread_entry = (o.entry_ask - o.entry_bid) / 2 * (m - 1)
            extra_half_spread_exit = (o.exit_ask - o.exit_bid) / 2 * (m - 1)
            stressed_entry_cost = o.entry_ask + extra_half_spread_entry
            stressed_exit_proceeds = o.exit_bid - extra_half_spread_exit
            adjusted.append((stressed_exit_proceeds - stressed_entry_cost) / stressed_entry_cost if stressed_entry_cost > 0 else None)
        adjusted = [a for a in adjusted if a is not None]
        n = len(adjusted)
        if n < MIN_SAMPLE_FOR_A_VERDICT:
            results.append(CostStressResult(m, n, None, None))
        else:
            mean_after = statistics.mean(adjusted)
            results.append(CostStressResult(m, n, mean_after, mean_after > 0))
    return tuple(results)


def cost_stress_test(observed: Sequence[ForwardOutcome], *, per_side_cost_pct: float = 0.005, multipliers: Sequence[float] = (1.0, 2.0, 3.0, 5.0)) -> tuple[CostStressResult, ...]:
    """A separate, disclosed flat-commission-style assumption (per-side
    cost as a % of premium) stacked ON TOP of the already-executable
    bid/ask return -- distinct from spread_stress_test's spread-widening
    assumption."""
    results = []
    for m in multipliers:
        adjusted = [o.executable_return_pct - 2 * per_side_cost_pct * m for o in observed if o.executable_return_pct is not None]
        n = len(adjusted)
        if n < MIN_SAMPLE_FOR_A_VERDICT:
            results.append(CostStressResult(m, n, None, None))
        else:
            mean_after = statistics.mean(adjusted)
            results.append(CostStressResult(m, n, mean_after, mean_after > 0))
    return tuple(results)


def leave_one_symbol_out(observed: Sequence[ForwardOutcome]) -> dict[str, OutcomeStats]:
    symbols = sorted({o.underlying_symbol for o in observed})
    return {s: outcome_stats([o for o in observed if o.underlying_symbol != s]) for s in symbols}


def leave_one_period_out(observed: Sequence[ForwardOutcome]) -> dict[str, OutcomeStats]:
    def _period(t: datetime) -> str:
        return f"{t.year}-{t.month:02d}"
    periods = sorted({_period(o.entry_timestamp) for o in observed})
    return {p: outcome_stats([o for o in observed if _period(o.entry_timestamp) != p]) for p in periods}


def parameter_neighborhood_test(
    entry_rows: Sequence[CausalFeatureRow], full_dataset_by_option: Mapping[str, list[CausalFeatureRow]],
    *, base_horizon: ForwardHorizon, tolerance_deltas: Sequence[float] = (-5.0, 0.0, 5.0),
) -> dict[float, OutcomeStats]:
    """Robustness-only, never selection (Part 7's own prohibition on
    tuning against the final holdout applies equally here) -- perturbs
    ONLY the tolerance window around the SAME frozen target horizon,
    never the horizon's target_minutes itself, and never re-picks a
    'best' delta."""
    results = {}
    for delta in tolerance_deltas:
        perturbed = ForwardHorizon(base_horizon.label, base_horizon.target_minutes, max(1.0, base_horizon.tolerance_minutes + delta))
        outcomes = []
        for entry in entry_rows:
            later = sorted((r for r in full_dataset_by_option.get(entry.option_id, []) if r.observation_timestamp > entry.observation_timestamp), key=lambda r: r.observation_timestamp)
            outcomes.append(compute_forward_outcome(entry, later, horizon=perturbed))
        results[delta] = outcome_stats(outcomes)
    return results


@dataclass(frozen=True)
class OutlierAnalysisResult:
    n: int
    top1pct_contribution_fraction: float | None
    stats_excluding_top1pct: OutcomeStats


def outlier_removal_test(observed: Sequence[ForwardOutcome]) -> OutlierAnalysisResult:
    returns = sorted((o.executable_return_pct for o in observed if o.executable_return_pct is not None), reverse=True)
    n = len(returns)
    if n == 0:
        return OutlierAnalysisResult(0, None, outcome_stats([]))
    k = max(1, n // 100)
    top = returns[:k]
    total_positive = sum(r for r in returns if r > 0)
    fraction = (sum(top) / total_positive) if total_positive > 0 else None
    threshold = returns[k - 1]
    remaining = [o for o in observed if o.executable_return_pct is None or o.executable_return_pct < threshold]
    return OutlierAnalysisResult(n, fraction, outcome_stats(remaining))


@dataclass(frozen=True)
class ConcentrationResult:
    by_underlying: dict[str, float]
    by_expiration: dict[str, float]
    max_underlying_concentration_pct: float | None
    max_expiration_concentration_pct: float | None


def concentration_analysis(
    observed: Sequence[ForwardOutcome], *, expiration_by_option_id: Mapping[str, str] | None = None,
) -> ConcentrationResult:
    n = len(observed)
    if n == 0:
        return ConcentrationResult({}, {}, None, None)
    by_underlying_counts: dict[str, int] = {}
    for o in observed:
        by_underlying_counts[o.underlying_symbol] = by_underlying_counts.get(o.underlying_symbol, 0) + 1
    by_underlying = {k: v / n for k, v in by_underlying_counts.items()}

    by_expiration: dict[str, float] = {}
    max_expiration = None
    if expiration_by_option_id:
        by_expiration_counts: dict[str, int] = {}
        for o in observed:
            exp = expiration_by_option_id.get(o.option_id)
            if exp is not None:
                by_expiration_counts[exp] = by_expiration_counts.get(exp, 0) + 1
        if by_expiration_counts:
            by_expiration = {k: v / n for k, v in by_expiration_counts.items()}
            max_expiration = max(by_expiration.values())

    return ConcentrationResult(by_underlying, by_expiration, max(by_underlying.values()), max_expiration)
