"""Phase 7, Part 8: alpha decay analysis — does a feature's predictive
power persist, or does it vanish after a few bars? Reuses
src.research.dataset.ResearchDatasetGenerator (already supports multiple
horizons in one call) and src.research.ic for the actual IC computation —
this module only adds the "measure across horizons and classify the decay
shape" layer, nothing new at the statistics level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.research.ic import ICSummary, compute_ic_series, summarize_ic

STANDARD_DECAY_HORIZONS: tuple[int, ...] = (1, 2, 3, 5, 10, 20, 40)


@dataclass(frozen=True)
class HorizonPoint:
    horizon_bars: int
    ic_summary: ICSummary
    effect_size: float | None  # == ic_summary.average_ic, named for Part 8's explicit vocabulary
    sign: int | None  # +1 / -1 / 0, sign of average_ic; None if unavailable


@dataclass(frozen=True)
class AlphaDecayReport:
    feature_col: str
    points: tuple[HorizonPoint, ...]
    sign_stable: bool | None  # True if every available horizon's IC sign agrees
    classification: str  # "SHORT_LIVED" | "MEDIUM_LIVED" | "LONG_LIVED" | "NO_MEASURABLE_DECAY_SIGNAL" | "INCONSISTENT_SIGN"
    classification_reason: str

    def render(self) -> str:
        lines = [f"ALPHA DECAY — {self.feature_col}", ""]
        for p in self.points:
            lines.append(f"  horizon={p.horizon_bars}bar: IC={p.effect_size} sign={p.sign}")
        lines.append("")
        lines.append(f"Sign stable across horizons: {self.sign_stable}")
        lines.append(f"Classification: {self.classification} ({self.classification_reason})")
        return "\n".join(lines)


def measure_alpha_decay(
    panel_rows_by_horizon: dict[int, Sequence[dict]], *, feature_col: str, min_universe_size: int = 3, meaningful_ic_threshold: float = 0.01,
) -> AlphaDecayReport:
    """`panel_rows_by_horizon[h]` is a panel (rows carrying `feature_col`
    and a `target_future_return_{h}bar` column) for horizon h — build this
    from ONE ResearchDatasetGenerator(horizons=STANDARD_DECAY_HORIZONS)
    call per symbol, concatenated across symbols (the target columns
    already differ per horizon in the same row, so panel_rows_by_horizon
    can literally be the SAME panel repeated under each horizon's target
    column name — see scripts/phase7_step3_discovery_campaign.py for the
    concrete construction). Horizons with no data are simply omitted, not
    forced to a default.

    Classification is a fixed, documented rule — not fit to produce a
    nice-looking curve:
      NO_MEASURABLE_DECAY_SIGNAL - no horizon's |IC| clears meaningful_ic_threshold
      INCONSISTENT_SIGN          - the sign of IC flips across horizons that DO clear the threshold
      SHORT_LIVED                - only horizons <= 5 bars clear the threshold
      MEDIUM_LIVED                - the longest horizon clearing the threshold is > 5 and <= 20 bars
      LONG_LIVED                  - a horizon > 20 bars still clears the threshold
    """
    points: list[HorizonPoint] = []
    for h in sorted(panel_rows_by_horizon):
        target_col = f"target_future_return_{h}bar"
        rows = panel_rows_by_horizon[h]
        ic_points = compute_ic_series(rows, feature_col, target_col, min_universe_size=min_universe_size)
        summary = summarize_ic(ic_points, feature_name=feature_col, target_name=target_col)
        effect = summary.average_ic
        sign = None if effect is None else (1 if effect > 0 else -1 if effect < 0 else 0)
        points.append(HorizonPoint(horizon_bars=h, ic_summary=summary, effect_size=effect, sign=sign))

    meaningful = [p for p in points if p.effect_size is not None and abs(p.effect_size) >= meaningful_ic_threshold]
    if not meaningful:
        return AlphaDecayReport(feature_col=feature_col, points=tuple(points), sign_stable=None, classification="NO_MEASURABLE_DECAY_SIGNAL", classification_reason=f"no horizon's |IC| reached the {meaningful_ic_threshold} threshold")

    signs = {p.sign for p in meaningful}
    sign_stable = len(signs) == 1
    if not sign_stable:
        return AlphaDecayReport(feature_col=feature_col, points=tuple(points), sign_stable=False, classification="INCONSISTENT_SIGN", classification_reason="IC sign flips across horizons that individually clear the meaningful-effect threshold — not a coherent decaying signal")

    longest_meaningful = max(p.horizon_bars for p in meaningful)
    if longest_meaningful <= 5:
        classification, reason = "SHORT_LIVED", f"longest horizon with |IC| >= {meaningful_ic_threshold} is {longest_meaningful} bars"
    elif longest_meaningful <= 20:
        classification, reason = "MEDIUM_LIVED", f"longest horizon with |IC| >= {meaningful_ic_threshold} is {longest_meaningful} bars"
    else:
        classification, reason = "LONG_LIVED", f"a horizon > 20 bars ({longest_meaningful}) still has |IC| >= {meaningful_ic_threshold}"

    return AlphaDecayReport(feature_col=feature_col, points=tuple(points), sign_stable=True, classification=classification, classification_reason=reason)
