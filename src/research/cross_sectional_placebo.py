"""Phase 7, Part 10: placebo / negative-control tests at the FEATURE/
TARGET (panel, discovery-stage) level — a different layer than
src.research.placebo's TRADE-level placebo tests (Phase 5/6, which need an
actual backtest to have run first). These run on a panel of
(timestamp, symbol, feature, target) rows straight out of
ResearchDatasetGenerator, before any backtest exists — matching Part 10's
"estimate how frequently a seemingly strong result appears by chance"
applied to the discovery stage itself.

Every function reports `empirical_p_value` = the fraction of placebo
trials that matched or beat the observed statistic — explicitly NOT
called "significant" just because it beats one sample; every result
documents this and requires a configurable, sufficiently large trial
count (default 200, matching src.research.placebo's convention).
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Sequence

from src.research.analysis import mean
from src.research.ic import compute_ic_series, summarize_ic


@dataclass(frozen=True)
class CrossSectionalPlaceboResult:
    method: str
    n_trials: int
    seed: int
    observed_statistic: float | None
    placebo_distribution: tuple[float, ...]
    empirical_p_value: float | None  # fraction of placebo trials with |statistic| >= |observed| (two-sided)
    what_was_randomized: str
    what_was_preserved: str
    what_was_destroyed: str

    def render(self) -> str:
        return (
            f"{self.method} (n_trials={self.n_trials}, seed={self.seed})\n"
            f"  observed={self.observed_statistic}  empirical_p_value={self.empirical_p_value}\n"
            f"  randomized: {self.what_was_randomized}\n  preserved: {self.what_was_preserved}\n  destroyed: {self.what_was_destroyed}\n"
            "  NOTE: empirical_p_value is NOT a formal significance guarantee — see this codebase's placebo docs."
        )


def _observed_ic(panel_rows: Sequence[dict], feature_col: str, target_col: str, min_universe_size: int) -> float | None:
    points = compute_ic_series(panel_rows, feature_col, target_col, min_universe_size=min_universe_size)
    return summarize_ic(points, feature_name=feature_col, target_name=target_col).average_ic


def _empirical_p(observed: float | None, distribution: Sequence[float]) -> float | None:
    if observed is None or not distribution:
        return None
    return sum(1 for d in distribution if abs(d) >= abs(observed)) / len(distribution)


def shuffled_signal_placebo(
    panel_rows: Sequence[dict], *, feature_col: str, target_col: str, n_trials: int = 200, seed: int = 42, min_universe_size: int = 3,
) -> CrossSectionalPlaceboResult:
    """At each timestamp, shuffles WHICH symbol got which feature value
    (seeded) while leaving the target column and the set of symbols
    present at that timestamp untouched — tests whether the feature's
    cross-sectional RANKING (not just its marginal distribution) carries
    information, the most direct cross-sectional analogue of a placebo."""
    observed = _observed_ic(panel_rows, feature_col, target_col, min_universe_size)

    by_ts: dict = defaultdict(list)
    for i, row in enumerate(panel_rows):
        by_ts[row["timestamp"]].append(i)

    distribution = []
    for trial in range(n_trials):
        rng = random.Random(seed * 1_000_003 + trial)
        shuffled_rows = [dict(r) for r in panel_rows]
        for _ts, indices in by_ts.items():
            values = [shuffled_rows[i][feature_col] for i in indices]
            rng.shuffle(values)
            for i, v in zip(indices, values):
                shuffled_rows[i][feature_col] = v
        stat = _observed_ic(shuffled_rows, feature_col, target_col, min_universe_size)
        if stat is not None:
            distribution.append(stat)

    return CrossSectionalPlaceboResult(
        method="shuffled_signal_placebo", n_trials=n_trials, seed=seed, observed_statistic=observed, placebo_distribution=tuple(distribution),
        empirical_p_value=_empirical_p(observed, distribution),
        what_was_randomized="which symbol received which feature value, WITHIN each timestamp",
        what_was_preserved="the target column; the set of symbols present at each timestamp; the feature's own cross-sectional distribution at each timestamp",
        what_was_destroyed="any real correspondence between a specific symbol's feature value and its own subsequent target",
    )


def shifted_signal_placebo(
    panel_rows: Sequence[dict], *, feature_col: str, target_col: str, shift_bars: int = 5, min_universe_size: int = 3,
) -> CrossSectionalPlaceboResult:
    """Deliberately misaligns feature and target by `shift_bars` WITHIN
    each symbol's own chronological row order (feature at row i is paired
    with the target that originally belonged to row i - shift_bars) —
    an obviously-wrong causal alignment. If the real (unshifted) IC
    persists at a similar magnitude after this shift, that is a red flag:
    the "predictive" relationship may just reflect general
    autocorrelation/trend rather than a genuine t -> t+horizon
    relationship. Deterministic (no seed needed) — same shift every time."""
    observed = _observed_ic(panel_rows, feature_col, target_col, min_universe_size)

    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for row in panel_rows:
        by_symbol[row.get("symbol", "")].append(row)
    for rows in by_symbol.values():
        rows.sort(key=lambda r: r["timestamp"])

    shifted_rows: list[dict] = []
    for rows in by_symbol.values():
        n = len(rows)
        if n <= shift_bars:
            continue
        for i in range(shift_bars, n):
            shifted_rows.append({"timestamp": rows[i]["timestamp"], "symbol": rows[i].get("symbol", ""), feature_col: rows[i][feature_col], target_col: rows[i - shift_bars][target_col]})

    shifted_ic = _observed_ic(shifted_rows, feature_col, target_col, min_universe_size)
    return CrossSectionalPlaceboResult(
        method=f"shifted_signal_placebo(shift={shift_bars})", n_trials=1, seed=0, observed_statistic=observed,
        placebo_distribution=(shifted_ic,) if shifted_ic is not None else (),
        empirical_p_value=None,  # not a distribution-based test — see the docstring; the shifted IC itself is the diagnostic
        what_was_randomized="nothing — this is a deterministic misalignment, not a randomization",
        what_was_preserved="each symbol's own chronological order",
        what_was_destroyed=f"the true t -> t+horizon correspondence — target at row i is replaced with the target from {shift_bars} rows earlier",
    )


def random_feature_control(
    panel_rows: Sequence[dict], *, target_col: str, n_trials: int = 200, seed: int = 44, min_universe_size: int = 3,
) -> CrossSectionalPlaceboResult:
    """Generates a PURELY RANDOM (seeded Gaussian) synthetic feature —
    unrelated to any real market data — and measures its IC against the
    real target. This establishes what "IC from a feature with zero
    genuine information" looks like on THIS exact dataset (same
    timestamps, same universe sizes, same target), a baseline the real
    feature's IC should clearly exceed."""
    distribution = []
    for trial in range(n_trials):
        rng = random.Random(seed * 1_000_003 + trial)
        synthetic_rows = [dict(r, __random_feature__=rng.gauss(0, 1)) for r in panel_rows]
        stat = _observed_ic(synthetic_rows, "__random_feature__", target_col, min_universe_size)
        if stat is not None:
            distribution.append(stat)
    return CrossSectionalPlaceboResult(
        method="random_feature_control", n_trials=n_trials, seed=seed, observed_statistic=None, placebo_distribution=tuple(distribution),
        empirical_p_value=None,  # this IS the null distribution, not a comparison against one observed value — see the CALLER for how to compare a real feature's IC against it
        what_was_randomized="an entirely synthetic feature (i.i.d. Gaussian noise, seeded), independent of any real market data",
        what_was_preserved="the real target column; the real timestamps and universe composition",
        what_was_destroyed="nothing — there is no real feature involved to destroy anything of; this is a from-scratch null baseline",
    )


def irrelevant_feature_control(panel_rows: Sequence[dict], *, irrelevant_feature_col: str, target_col: str, min_universe_size: int = 3) -> CrossSectionalPlaceboResult:
    """Reports the IC of a feature chosen for having NO plausible
    economic mechanism connecting it to the target (e.g. day-of-week, or
    an already-known-negative-result feature) — a real-data reference
    point distinct from random_feature_control's synthetic-noise baseline.
    Caller supplies which column counts as "irrelevant" and must document
    WHY it's expected to be irrelevant (this function doesn't verify the
    economic claim, only computes the number)."""
    ic = _observed_ic(panel_rows, irrelevant_feature_col, target_col, min_universe_size)
    return CrossSectionalPlaceboResult(
        method=f"irrelevant_feature_control({irrelevant_feature_col})", n_trials=1, seed=0, observed_statistic=ic,
        placebo_distribution=(ic,) if ic is not None else (), empirical_p_value=None,
        what_was_randomized="nothing",
        what_was_preserved="everything — this uses a real feature column as-is",
        what_was_destroyed="nothing; this is a reference point, not a randomization",
    )


def time_shuffled_target_placebo(
    panel_rows: Sequence[dict], *, feature_col: str, target_col: str, n_trials: int = 200, seed: int = 45, min_universe_size: int = 3,
) -> CrossSectionalPlaceboResult:
    """Shuffles the TARGET column across ALL rows (seeded), globally —
    breaking BOTH temporal alignment AND cross-sectional structure. This
    is the most destructive placebo here and is only "statistically
    appropriate" (per Part 10's own caveat) as a coarse sanity floor: if
    even this fully-scrambled null occasionally produces an IC close to
    the observed one, the observed result is not distinguishable from
    noise at all. It does NOT respect per-symbol autocorrelation the way
    shuffled_signal_placebo does, so a low empirical_p_value here is a
    weaker claim than the same result from shuffled_signal_placebo."""
    observed = _observed_ic(panel_rows, feature_col, target_col, min_universe_size)
    targets = [r.get(target_col) for r in panel_rows]

    distribution = []
    for trial in range(n_trials):
        rng = random.Random(seed * 1_000_003 + trial)
        shuffled_targets = list(targets)
        rng.shuffle(shuffled_targets)
        synthetic_rows = [dict(r, **{target_col: t}) for r, t in zip(panel_rows, shuffled_targets)]
        stat = _observed_ic(synthetic_rows, feature_col, target_col, min_universe_size)
        if stat is not None:
            distribution.append(stat)

    return CrossSectionalPlaceboResult(
        method="time_shuffled_target_placebo", n_trials=n_trials, seed=seed, observed_statistic=observed, placebo_distribution=tuple(distribution),
        empirical_p_value=_empirical_p(observed, distribution),
        what_was_randomized="the ENTIRE target column, globally across all rows (seeded)",
        what_was_preserved="the feature column and the marginal distribution of target values",
        what_was_destroyed="both temporal alignment AND cross-sectional structure — the coarsest, most destructive null this module offers",
    )
