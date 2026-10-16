"""The weighted scoring formula. Scores are heuristic estimates, not view predictions."""
from __future__ import annotations

from ..models import ScoreBreakdown

WEIGHTS: dict[str, float] = {
    "hook": 0.25,
    "emotion": 0.20,
    "clarity": 0.20,
    "payoff": 0.15,
    "pacing": 0.10,
    "shareability": 0.10,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

LABELS = {
    "hook": "Opening hook",
    "emotion": "Emotional / entertainment impact",
    "clarity": "Standalone clarity",
    "payoff": "Payoff & completeness",
    "pacing": "Pacing & retention",
    "shareability": "Shareability & discussion",
}


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def weighted_total(b: ScoreBreakdown) -> float:
    return round(sum(getattr(b, k) * w for k, w in WEIGHTS.items()), 1)


def blend(primary: ScoreBreakdown, secondary: ScoreBreakdown, primary_weight: float) -> ScoreBreakdown:
    """Per-dimension blend, used to combine LLM judgement with heuristic signals."""
    pw = clamp(primary_weight, 0, 1)
    return ScoreBreakdown(**{k: round(clamp(getattr(primary, k) * pw + getattr(secondary, k) * (1 - pw)), 1) for k in WEIGHTS})
