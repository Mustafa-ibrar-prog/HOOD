"""Phase 20, Part 11/12 — the mechanical-baseline philosophy, formalized
and reusable (Phase 19's discovery campaign did this inline for one
comparison; this module makes it a named, testable primitive so the
Phase 20 replication campaign -- and any future phase -- doesn't
reimplement it ad hoc).

For any apparently-predictive option relationship, computes the SAME
feature's relationship to the UNDERLYING's own forward return, so a
reader can see directly whether the option relationship is genuinely
option-specific or is simply inherited (often via leverage/convexity)
from a relationship that already exists in the underlying equity. This
module does not compute IC itself -- it wraps
`src.research.ic.compute_ic_series`/`summarize_ic` (reused, not
duplicated) and packages the two results side by side with an explicit
classification.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.research.ic import compute_ic_series, summarize_ic


class BaselineClassification:
    OPTION_ADDS_INFORMATION = "option_adds_information"  # |option_IC| meaningfully exceeds |underlying_IC|
    INHERITED_FROM_UNDERLYING = "inherited_from_underlying"  # |option_IC| does not meaningfully exceed |underlying_IC| -- the option relationship is mechanically explained by the underlying's own
    BOTH_WEAK_OR_UNDEFINED = "both_weak_or_undefined"  # neither IC is usable (None or near zero) -- no claim either way


@dataclass(frozen=True)
class MechanicalBaselineComparison:
    feature_name: str
    option_target: str
    underlying_target: str
    option_ic: float | None
    underlying_ic: float | None
    gap: float | None  # |option_ic| - |underlying_ic|; None if either input is None
    classification: str  # one of BaselineClassification's values

    def render(self) -> str:
        return (
            f"{self.feature_name}: option_IC={self.option_ic}, underlying_IC={self.underlying_ic}, "
            f"gap={self.gap} -> {self.classification}"
        )


def compare_option_vs_underlying_signal(
    panel_rows: Sequence[dict], *, feature_col: str, option_target_col: str, underlying_target_col: str,
    min_universe_size: int = 3, material_gap: float = 0.01,
) -> MechanicalBaselineComparison:
    """`material_gap` is the minimum |option_IC| - |underlying_IC| this
    function requires before calling the option relationship genuinely
    additive (Part 11: 'Do not claim an options-specific edge when the
    relationship is simply inherited from the underlying') -- a fixed,
    documented threshold, not tuned per-feature to manufacture a
    favorable classification."""
    option_ic = summarize_ic(compute_ic_series(panel_rows, feature_col, option_target_col, min_universe_size=min_universe_size), feature_name=feature_col, target_name=option_target_col).average_ic
    underlying_ic = summarize_ic(compute_ic_series(panel_rows, feature_col, underlying_target_col, min_universe_size=min_universe_size), feature_name=feature_col, target_name=underlying_target_col).average_ic

    gap = None
    if option_ic is not None and underlying_ic is not None:
        gap = abs(option_ic) - abs(underlying_ic)

    if gap is None:
        classification = BaselineClassification.BOTH_WEAK_OR_UNDEFINED
    elif gap > material_gap:
        classification = BaselineClassification.OPTION_ADDS_INFORMATION
    else:
        classification = BaselineClassification.INHERITED_FROM_UNDERLYING

    return MechanicalBaselineComparison(
        feature_name=feature_col, option_target=option_target_col, underlying_target=underlying_target_col,
        option_ic=option_ic, underlying_ic=underlying_ic, gap=gap, classification=classification,
    )
