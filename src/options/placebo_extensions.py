"""Phase 21, Part 13 — placebo tests beyond Phase 7's
`src.research.cross_sectional_placebo` battery (reused directly for 4 of
the 7 required placebo types: `shuffled_signal_placebo` = cross-sectional
feature shuffle, `shifted_signal_placebo` = the temporal-shift test
[Part 14], `random_feature_control` = randomized signal,
`time_shuffled_target_placebo` = randomized target). This module adds
the 3 that aren't already reusable: a within-symbol time shuffle, a
symbol-identity shuffle, and a block-preserving shuffle -- plus a
sign-flip manipulation check.

Same `CrossSectionalPlaceboResult` shape as Phase 7's module (reused,
not duplicated) so every placebo result renders and compares uniformly.

IMPORTANT: every function above this line computes an IC-based statistic
(`_observed_ic`) and is only valid for candidates whose PRIMARY metric
IS a cross-sectional IC (P19-OPT-009-EXPANDED). P19-OPT-005-EXPANDED's
primary metric is a GROUP MEAN GAP (mean(call target) - mean(put
target)), not an IC of a binary-encoded call/put feature -- those are
different statistics with different scales, and reporting the IC-based
placebo's `observed_statistic` next to the candidate's real pooled gap
effect would silently compare two unrelated numbers. The `_gap`-suffixed
functions below mirror each placebo type's exact randomization logic but
compute the GAP statistic instead, so P19-OPT-005-EXPANDED's placebo
battery is honestly testing the same statistic as its pooled effect.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Sequence

from src.research.cross_sectional_placebo import CrossSectionalPlaceboResult
from src.research.ic import compute_ic_series, summarize_ic


def _observed_ic(panel_rows: Sequence[dict], feature_col: str, target_col: str, min_universe_size: int) -> float | None:
    """Local copy of `cross_sectional_placebo`'s private helper (that
    module deliberately doesn't export it) -- same one-line computation,
    kept in sync by construction since both just wrap the public
    compute_ic_series/summarize_ic."""
    points = compute_ic_series(panel_rows, feature_col, target_col, min_universe_size=min_universe_size)
    return summarize_ic(points, feature_name=feature_col, target_name=target_col).average_ic


def _empirical_p(observed: float | None, distribution: Sequence[float]) -> float | None:
    if observed is None or not distribution:
        return None
    return sum(1 for d in distribution if abs(d) >= abs(observed)) / len(distribution)


def within_symbol_time_shuffle_placebo(
    panel_rows: Sequence[dict], *, feature_col: str, target_col: str, n_trials: int = 200, seed: int = 46, min_universe_size: int = 3,
) -> CrossSectionalPlaceboResult:
    """Part 13.2 'Time shuffle': WITHIN each symbol's own row set,
    shuffles which of ITS OWN target values pairs with which of its own
    feature observations (seeded) -- unlike `time_shuffled_target_placebo`
    (which shuffles globally, mixing symbols), this preserves each
    symbol's own marginal target distribution and the cross-sectional
    universe composition at every timestamp, destroying ONLY the
    within-symbol temporal correspondence."""
    observed = _observed_ic(panel_rows, feature_col, target_col, min_universe_size)

    by_symbol: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(panel_rows):
        by_symbol[row.get("symbol", "")].append(i)

    distribution = []
    for trial in range(n_trials):
        rng = random.Random(seed * 1_000_003 + trial)
        shuffled_rows = [dict(r) for r in panel_rows]
        for _sym, indices in by_symbol.items():
            targets = [shuffled_rows[i][target_col] for i in indices]
            rng.shuffle(targets)
            for i, t in zip(indices, targets):
                shuffled_rows[i][target_col] = t
        stat = _observed_ic(shuffled_rows, feature_col, target_col, min_universe_size)
        if stat is not None:
            distribution.append(stat)

    return CrossSectionalPlaceboResult(
        method="within_symbol_time_shuffle_placebo", n_trials=n_trials, seed=seed, observed_statistic=observed,
        placebo_distribution=tuple(distribution), empirical_p_value=_empirical_p(observed, distribution),
        what_was_randomized="which of a symbol's OWN target values pairs with which of its OWN feature observations",
        what_was_preserved="each symbol's own marginal target distribution; the cross-sectional universe at every timestamp",
        what_was_destroyed="the within-symbol temporal t -> t+horizon correspondence",
    )


def symbol_identity_shuffle_placebo(
    panel_rows: Sequence[dict], *, feature_col: str, target_col: str, n_trials: int = 200, seed: int = 47, min_universe_size: int = 3,
) -> CrossSectionalPlaceboResult:
    """Part 13.3 'Symbol shuffle': reassigns each symbol's ENTIRE target
    time series to a different, randomly chosen symbol's feature time
    series (seeded), matched by row position within each symbol's own
    chronological order (shorter series are truncated to the shorter
    length of the pair). Tests whether the relationship depends on a
    real (feature, target) correspondence for the SAME underlying,
    versus being an artifact that would appear for arbitrary symbol
    pairings too."""
    observed = _observed_ic(panel_rows, feature_col, target_col, min_universe_size)

    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for row in panel_rows:
        by_symbol[row.get("symbol", "")].append(row)
    for rows in by_symbol.values():
        rows.sort(key=lambda r: r["timestamp"])
    symbols = list(by_symbol.keys())

    distribution = []
    for trial in range(n_trials):
        rng = random.Random(seed * 1_000_003 + trial)
        permuted = symbols[:]
        rng.shuffle(permuted)
        mapping = dict(zip(symbols, permuted))
        synthetic_rows = []
        for sym, rows in by_symbol.items():
            target_rows = by_symbol[mapping[sym]]
            n = min(len(rows), len(target_rows))
            for i in range(n):
                synthetic_rows.append({"timestamp": rows[i]["timestamp"], "symbol": sym, feature_col: rows[i][feature_col], target_col: target_rows[i][target_col]})
        stat = _observed_ic(synthetic_rows, feature_col, target_col, min_universe_size)
        if stat is not None:
            distribution.append(stat)

    return CrossSectionalPlaceboResult(
        method="symbol_identity_shuffle_placebo", n_trials=n_trials, seed=seed, observed_statistic=observed,
        placebo_distribution=tuple(distribution), empirical_p_value=_empirical_p(observed, distribution),
        what_was_randomized="which symbol's target time series is paired with which symbol's feature time series",
        what_was_preserved="each series' own internal chronological order and marginal distribution",
        what_was_destroyed="the correspondence between a feature and target belonging to the SAME real underlying",
    )


def block_preserving_shuffle_placebo(
    panel_rows: Sequence[dict], *, feature_col: str, target_col: str, block_size: int = 5, n_trials: int = 200, seed: int = 48, min_universe_size: int = 3,
) -> CrossSectionalPlaceboResult:
    """Part 13.6 'Block-preserving shuffle': within each symbol's own
    chronological row order, shuffles contiguous BLOCKS of `block_size`
    (feature, target) pairs as units (seeded) rather than individual
    rows -- preserves local (within-block) autocorrelation structure
    while destroying the specific alignment between a block's feature
    level and where that block sits in the target sequence. A real
    relationship that only shows up when individual rows are shuffled
    (and disappears under block shuffling too) is a weaker finding than
    one that survives block shuffling's gentler randomization."""
    observed = _observed_ic(panel_rows, feature_col, target_col, min_universe_size)

    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for row in panel_rows:
        by_symbol[row.get("symbol", "")].append(row)
    for rows in by_symbol.values():
        rows.sort(key=lambda r: r["timestamp"])

    distribution = []
    for trial in range(n_trials):
        rng = random.Random(seed * 1_000_003 + trial)
        synthetic_rows = []
        for sym, rows in by_symbol.items():
            n = len(rows)
            blocks = [rows[i:i + block_size] for i in range(0, n, block_size)]
            targets_by_block = [[r[target_col] for r in b] for b in blocks]
            rng.shuffle(targets_by_block)
            flat_targets = [t for block in targets_by_block for t in block]
            for row, t in zip(rows, flat_targets):
                synthetic_rows.append({"timestamp": row["timestamp"], "symbol": sym, feature_col: row[feature_col], target_col: t})
        stat = _observed_ic(synthetic_rows, feature_col, target_col, min_universe_size)
        if stat is not None:
            distribution.append(stat)

    return CrossSectionalPlaceboResult(
        method=f"block_preserving_shuffle_placebo(block_size={block_size})", n_trials=n_trials, seed=seed, observed_statistic=observed,
        placebo_distribution=tuple(distribution), empirical_p_value=_empirical_p(observed, distribution),
        what_was_randomized=f"the order of contiguous {block_size}-row target BLOCKS, within each symbol's own chronological order",
        what_was_preserved="within-block autocorrelation structure; each symbol's own marginal target distribution",
        what_was_destroyed="the alignment between a specific block's feature level and its position in the target sequence",
    )


def sign_flipped_target_diagnostic(panel_rows: Sequence[dict], *, feature_col: str, target_col: str, min_universe_size: int = 3) -> CrossSectionalPlaceboResult:
    """Part 13.7 'Sign-flipped target': a deterministic MANIPULATION
    CHECK, not a null-hypothesis placebo -- negates every target value
    and recomputes the IC. For a rank-correlation statistic this must
    equal exactly -1 * the observed IC; anything else indicates a bug in
    the surrounding pipeline (e.g. a target column silently containing
    non-numeric or already-transformed values) rather than a genuine
    finding about the data."""
    observed = _observed_ic(panel_rows, feature_col, target_col, min_universe_size)
    flipped_rows = [dict(r, **{target_col: (-r[target_col] if r.get(target_col) is not None else None)}) for r in panel_rows]
    flipped = _observed_ic(flipped_rows, feature_col, target_col, min_universe_size)
    return CrossSectionalPlaceboResult(
        method="sign_flipped_target_diagnostic", n_trials=1, seed=0, observed_statistic=observed,
        placebo_distribution=(flipped,) if flipped is not None else (), empirical_p_value=None,
        what_was_randomized="nothing -- deterministic sign negation of the entire target column",
        what_was_preserved="every row's feature value and cross-sectional structure",
        what_was_destroyed="nothing meaningful; this is a pipeline sanity check (flipped IC must equal -observed IC exactly)",
    )


# --- GROUP-GAP variants: same 7 randomizations, but the observed/placebo
# statistic is mean(target | group_col == "call") - mean(target |
# group_col == "put") -- the actual primary metric for a group-mean-gap
# candidate (P19-OPT-005-EXPANDED), not an IC. See the module docstring.


def _gap_stat(panel_rows: Sequence[dict], target_col: str, group_col: str = "call_put", pos_label: str = "call", neg_label: str = "put") -> float | None:
    pos = [r[target_col] for r in panel_rows if r.get(group_col) == pos_label and r.get(target_col) is not None]
    neg = [r[target_col] for r in panel_rows if r.get(group_col) == neg_label and r.get(target_col) is not None]
    if not pos or not neg:
        return None
    return (sum(pos) / len(pos)) - (sum(neg) / len(neg))


def shuffled_group_gap_placebo(
    panel_rows: Sequence[dict], *, target_col: str, group_col: str = "call_put", n_trials: int = 200, seed: int = 4001,
) -> CrossSectionalPlaceboResult:
    """Gap-metric analogue of `shuffled_signal_placebo`: at each
    timestamp, shuffles WHICH contract got which call/put label (seeded)
    while leaving the target column and the set of contracts present at
    that timestamp untouched -- tests whether the call/put SPLIT itself
    (not just the target distribution) carries the gap."""
    observed = _gap_stat(panel_rows, target_col, group_col)
    by_ts: dict = defaultdict(list)
    for i, row in enumerate(panel_rows):
        by_ts[row["timestamp"]].append(i)

    distribution = []
    for trial in range(n_trials):
        rng = random.Random(seed * 1_000_003 + trial)
        shuffled_rows = [dict(r) for r in panel_rows]
        for _ts, indices in by_ts.items():
            labels = [shuffled_rows[i][group_col] for i in indices]
            rng.shuffle(labels)
            for i, lbl in zip(indices, labels):
                shuffled_rows[i][group_col] = lbl
        stat = _gap_stat(shuffled_rows, target_col, group_col)
        if stat is not None:
            distribution.append(stat)

    return CrossSectionalPlaceboResult(
        method="shuffled_group_gap_placebo", n_trials=n_trials, seed=seed, observed_statistic=observed, placebo_distribution=tuple(distribution),
        empirical_p_value=_empirical_p(observed, distribution),
        what_was_randomized="which contract received which call/put label, WITHIN each timestamp",
        what_was_preserved="the target column; the set of contracts present at each timestamp; the true call/put proportions at each timestamp",
        what_was_destroyed="any real correspondence between a specific contract's call/put identity and its own subsequent target",
    )


def within_symbol_time_shuffle_gap_placebo(
    panel_rows: Sequence[dict], *, target_col: str, group_col: str = "call_put", n_trials: int = 200, seed: int = 4002,
) -> CrossSectionalPlaceboResult:
    """Gap-metric analogue of `within_symbol_time_shuffle_placebo`:
    within each symbol's own row set, shuffles which of its own target
    values pairs with which of its own call/put labels."""
    observed = _gap_stat(panel_rows, target_col, group_col)
    by_symbol: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(panel_rows):
        by_symbol[row.get("underlying_symbol", row.get("symbol", ""))].append(i)

    distribution = []
    for trial in range(n_trials):
        rng = random.Random(seed * 1_000_003 + trial)
        shuffled_rows = [dict(r) for r in panel_rows]
        for _sym, indices in by_symbol.items():
            targets = [shuffled_rows[i][target_col] for i in indices]
            rng.shuffle(targets)
            for i, t in zip(indices, targets):
                shuffled_rows[i][target_col] = t
        stat = _gap_stat(shuffled_rows, target_col, group_col)
        if stat is not None:
            distribution.append(stat)

    return CrossSectionalPlaceboResult(
        method="within_symbol_time_shuffle_gap_placebo", n_trials=n_trials, seed=seed, observed_statistic=observed,
        placebo_distribution=tuple(distribution), empirical_p_value=_empirical_p(observed, distribution),
        what_was_randomized="which of a symbol's OWN target values pairs with which of its OWN call/put-labeled contracts",
        what_was_preserved="each symbol's own marginal target distribution; the cross-sectional universe at every timestamp",
        what_was_destroyed="the within-symbol temporal t -> t+horizon correspondence",
    )


def symbol_identity_shuffle_gap_placebo(
    panel_rows: Sequence[dict], *, target_col: str, group_col: str = "call_put", n_trials: int = 200, seed: int = 4003,
) -> CrossSectionalPlaceboResult:
    """Gap-metric analogue of `symbol_identity_shuffle_placebo`:
    reassigns each symbol's entire target time series to a different,
    randomly chosen symbol's call/put-label time series (seeded), matched
    by row position within each symbol's own chronological order."""
    observed = _gap_stat(panel_rows, target_col, group_col)
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for row in panel_rows:
        by_symbol[row.get("underlying_symbol", row.get("symbol", ""))].append(row)
    for rows in by_symbol.values():
        rows.sort(key=lambda r: r["timestamp"])
    symbols = list(by_symbol.keys())

    distribution = []
    for trial in range(n_trials):
        rng = random.Random(seed * 1_000_003 + trial)
        permuted = symbols[:]
        rng.shuffle(permuted)
        mapping = dict(zip(symbols, permuted))
        synthetic_rows = []
        for sym, rows in by_symbol.items():
            target_rows = by_symbol[mapping[sym]]
            n = min(len(rows), len(target_rows))
            for i in range(n):
                synthetic_rows.append({group_col: rows[i][group_col], target_col: target_rows[i][target_col]})
        stat = _gap_stat(synthetic_rows, target_col, group_col)
        if stat is not None:
            distribution.append(stat)

    return CrossSectionalPlaceboResult(
        method="symbol_identity_shuffle_gap_placebo", n_trials=n_trials, seed=seed, observed_statistic=observed,
        placebo_distribution=tuple(distribution), empirical_p_value=_empirical_p(observed, distribution),
        what_was_randomized="which symbol's target time series is paired with which symbol's call/put-label time series",
        what_was_preserved="each series' own internal chronological order and marginal distribution",
        what_was_destroyed="the correspondence between a call/put label and a target belonging to the SAME real underlying",
    )


def random_group_gap_control(
    panel_rows: Sequence[dict], *, target_col: str, n_trials: int = 100, seed: int = 4004, true_group_col: str = "call_put",
) -> CrossSectionalPlaceboResult:
    """Gap-metric analogue of `random_feature_control`: assigns each row
    a synthetic random binary label (seeded, matching the real call/put
    proportion), unrelated to the real call/put identity, and measures
    the resulting group-mean gap against the real target. Establishes
    what 'gap from a meaningless split' looks like on this exact dataset."""
    true_labels = [r.get(true_group_col) for r in panel_rows]
    call_frac = (sum(1 for x in true_labels if x == "call") / len(true_labels)) if true_labels else 0.5
    distribution = []
    for trial in range(n_trials):
        rng = random.Random(seed * 1_000_003 + trial)
        synthetic_rows = [dict(r, __random_group__=("call" if rng.random() < call_frac else "put")) for r in panel_rows]
        stat = _gap_stat(synthetic_rows, target_col, "__random_group__")
        if stat is not None:
            distribution.append(stat)
    return CrossSectionalPlaceboResult(
        method="random_group_gap_control", n_trials=n_trials, seed=seed, observed_statistic=None, placebo_distribution=tuple(distribution),
        empirical_p_value=None,  # this IS the null distribution, not a comparison against one observed value -- see the CALLER
        what_was_randomized="an entirely synthetic binary group label (seeded, matching the real call/put proportion), independent of any real call/put identity",
        what_was_preserved="the real target column; the real call/put proportion",
        what_was_destroyed="nothing -- there is no real feature involved to destroy anything of; this is a from-scratch null baseline",
    )


def time_shuffled_target_gap_placebo(
    panel_rows: Sequence[dict], *, target_col: str, group_col: str = "call_put", n_trials: int = 200, seed: int = 4005,
) -> CrossSectionalPlaceboResult:
    """Gap-metric analogue of `time_shuffled_target_placebo`: shuffles
    the target column across ALL rows (seeded), globally, breaking both
    temporal alignment and cross-sectional structure, then recomputes the
    gap using the TRUE call/put labels."""
    observed = _gap_stat(panel_rows, target_col, group_col)
    targets = [r.get(target_col) for r in panel_rows]

    distribution = []
    for trial in range(n_trials):
        rng = random.Random(seed * 1_000_003 + trial)
        shuffled_targets = list(targets)
        rng.shuffle(shuffled_targets)
        synthetic_rows = [dict(r, **{target_col: t}) for r, t in zip(panel_rows, shuffled_targets)]
        stat = _gap_stat(synthetic_rows, target_col, group_col)
        if stat is not None:
            distribution.append(stat)

    return CrossSectionalPlaceboResult(
        method="time_shuffled_target_gap_placebo", n_trials=n_trials, seed=seed, observed_statistic=observed, placebo_distribution=tuple(distribution),
        empirical_p_value=_empirical_p(observed, distribution),
        what_was_randomized="the ENTIRE target column, globally across all rows (seeded)",
        what_was_preserved="the call/put label column and the marginal distribution of target values",
        what_was_destroyed="both temporal alignment AND cross-sectional structure -- the coarsest, most destructive null this module offers",
    )


def block_preserving_shuffle_gap_placebo(
    panel_rows: Sequence[dict], *, target_col: str, group_col: str = "call_put", block_size: int = 5, n_trials: int = 200, seed: int = 4006,
) -> CrossSectionalPlaceboResult:
    """Gap-metric analogue of `block_preserving_shuffle_placebo`: within
    each symbol's own chronological row order, shuffles contiguous
    BLOCKS of target values as units (seeded) rather than individual
    rows, then recomputes the gap using the true call/put labels."""
    observed = _gap_stat(panel_rows, target_col, group_col)
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for row in panel_rows:
        by_symbol[row.get("underlying_symbol", row.get("symbol", ""))].append(row)
    for rows in by_symbol.values():
        rows.sort(key=lambda r: r["timestamp"])

    distribution = []
    for trial in range(n_trials):
        rng = random.Random(seed * 1_000_003 + trial)
        synthetic_rows = []
        for sym, rows in by_symbol.items():
            n = len(rows)
            blocks = [rows[i:i + block_size] for i in range(0, n, block_size)]
            targets_by_block = [[r[target_col] for r in b] for b in blocks]
            rng.shuffle(targets_by_block)
            flat_targets = [t for block in targets_by_block for t in block]
            for row, t in zip(rows, flat_targets):
                synthetic_rows.append({group_col: row[group_col], target_col: t})
        stat = _gap_stat(synthetic_rows, target_col, group_col)
        if stat is not None:
            distribution.append(stat)

    return CrossSectionalPlaceboResult(
        method=f"block_preserving_shuffle_gap_placebo(block_size={block_size})", n_trials=n_trials, seed=seed, observed_statistic=observed,
        placebo_distribution=tuple(distribution), empirical_p_value=_empirical_p(observed, distribution),
        what_was_randomized=f"the order of contiguous {block_size}-row target BLOCKS, within each symbol's own chronological order",
        what_was_preserved="within-block autocorrelation structure; each symbol's own marginal target distribution; the true call/put labels",
        what_was_destroyed="the alignment between a specific block's target level and its position in the original sequence",
    )


def sign_flipped_target_gap_diagnostic(panel_rows: Sequence[dict], *, target_col: str, group_col: str = "call_put") -> CrossSectionalPlaceboResult:
    """Gap-metric analogue of `sign_flipped_target_diagnostic`: negates
    every target value and recomputes the gap. Since gap =
    mean(call_target) - mean(put_target), negating every target negates
    the gap exactly; anything else indicates a pipeline bug."""
    observed = _gap_stat(panel_rows, target_col, group_col)
    flipped_rows = [dict(r, **{target_col: (-r[target_col] if r.get(target_col) is not None else None)}) for r in panel_rows]
    flipped = _gap_stat(flipped_rows, target_col, group_col)
    return CrossSectionalPlaceboResult(
        method="sign_flipped_target_gap_diagnostic", n_trials=1, seed=0, observed_statistic=observed,
        placebo_distribution=(flipped,) if flipped is not None else (), empirical_p_value=None,
        what_was_randomized="nothing -- deterministic sign negation of the entire target column",
        what_was_preserved="every row's call/put label",
        what_was_destroyed="nothing meaningful; this is a pipeline sanity check (flipped gap must equal -observed gap exactly)",
    )


def shifted_group_gap_placebo(
    panel_rows: Sequence[dict], *, target_col: str, group_col: str = "call_put", shift_bars: int = 5,
) -> CrossSectionalPlaceboResult:
    """Gap-metric analogue of `shifted_signal_placebo` (Part 14): within
    each symbol's own chronological row order, the call/put label at row
    i is paired with the target that originally belonged to row i -
    shift_bars. If the real (unshifted) gap persists at similar
    magnitude after this deliberately-wrong alignment, that is a red
    flag for autocorrelation/mechanical identity rather than a genuine
    t -> t+horizon relationship."""
    observed = _gap_stat(panel_rows, target_col, group_col)
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for row in panel_rows:
        by_symbol[row.get("underlying_symbol", row.get("symbol", ""))].append(row)
    for rows in by_symbol.values():
        rows.sort(key=lambda r: r["timestamp"])

    shifted_rows: list[dict] = []
    for rows in by_symbol.values():
        n = len(rows)
        if n <= shift_bars:
            continue
        for i in range(shift_bars, n):
            shifted_rows.append({group_col: rows[i][group_col], target_col: rows[i - shift_bars][target_col]})

    shifted_gap = _gap_stat(shifted_rows, target_col, group_col)
    return CrossSectionalPlaceboResult(
        method=f"shifted_group_gap_placebo(shift={shift_bars})", n_trials=1, seed=0, observed_statistic=observed,
        placebo_distribution=(shifted_gap,) if shifted_gap is not None else (),
        empirical_p_value=None,  # not a distribution-based test -- the shifted gap itself is the diagnostic
        what_was_randomized="nothing -- this is a deterministic misalignment, not a randomization",
        what_was_preserved="each symbol's own chronological order and call/put labels",
        what_was_destroyed=f"the true t -> t+horizon correspondence -- target at row i is replaced with the target from {shift_bars} rows earlier",
    )
