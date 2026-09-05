"""Phase 38, Part 7 — chronological DEVELOPMENT -> VALIDATION ->
FINAL_HOLDOUT split.

Never a random shuffle -- outcomes are sorted by `entry_timestamp` and
sliced in order. `src.research.validation.generate_walk_forward_windows`/
`run_walk_forward` (reused unchanged elsewhere in this project) are
built for a rolling walk-forward over a continuous historical bar
series with fixed train/validation/test day counts; Phase 38's real
input is a sparse, irregularly-spaced set of live observations, so a
simple, honest three-way proportional split is the right tool here --
not a duplicate of that machinery, a different shape of input entirely.
If the sample is too small for a meaningful three-way split, this
function says so explicitly (Part 7: "do not manufacture additional
observations... report insufficient sample size").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.options.phase38_targets import ForwardOutcome

# Each split needs at least MIN_SAMPLE_FOR_A_VERDICT (20, this project's
# established floor) to be individually meaningful -- so the minimum
# total is 3x that.
MIN_TOTAL_FOR_CHRONOLOGICAL_SPLIT = 60


@dataclass(frozen=True)
class ChronologicalSplit:
    development: tuple[ForwardOutcome, ...]
    validation: tuple[ForwardOutcome, ...]
    final_holdout: tuple[ForwardOutcome, ...]
    sufficient: bool
    reason: str


def split_chronologically(
    outcomes: Sequence[ForwardOutcome], *, development_frac: float = 0.5, validation_frac: float = 0.25,
) -> ChronologicalSplit:
    n = len(outcomes)
    if n < MIN_TOTAL_FOR_CHRONOLOGICAL_SPLIT:
        return ChronologicalSplit(
            (), (), (), False,
            f"Only {n} outcome(s) available (< {MIN_TOTAL_FOR_CHRONOLOGICAL_SPLIT} required for a meaningful "
            "three-way chronological split of >= 20 each) -- reporting insufficient sample, not relaxing the requirement.",
        )
    ordered = sorted(outcomes, key=lambda o: o.entry_timestamp)
    dev_end = int(n * development_frac)
    val_end = dev_end + int(n * validation_frac)
    return ChronologicalSplit(
        tuple(ordered[:dev_end]), tuple(ordered[dev_end:val_end]), tuple(ordered[val_end:]), True,
        f"{dev_end} development / {val_end - dev_end} validation / {n - val_end} final holdout.",
    )
