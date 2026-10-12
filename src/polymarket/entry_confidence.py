"""Deterministic 0-100 confidence score for a Coinbase-driven entry
candidate (see btc_entry_signal.py) — decides WHETHER to enter and HOW
MUCH to risk, never WHICH DIRECTION. Direction is decided entirely by
btc_entry_signal.assess_btc_entry_direction(); this module only reads
that decision's own already-computed evidence (edge_points,
fired_signal_count) — never a second indicator engine, never an LLM
judgment, never a claim that this score is a calibrated win
probability.

A "neutral" direction (insufficient/stale/conflicting/non-directional
BTC evidence — see btc_entry_signal.py) always scores 0 — there is no
entry candidate to size at all in that case.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Base confidence formula -------------------------------------------------
# Deliberately simple and linear: a baseline (the minimum any
# entry-worthy direction can score, since assess_btc_entry_direction's
# own gate already requires edge_points > 0 and
# fired_signal_count >= min_strengthening_signals) plus a fixed weight
# per edge point and per fired signal. Tunable constants, not a
# calibrated model -- see module docstring.
_BASE_CONFIDENCE_INTERCEPT = 35.0
_EDGE_POINTS_WEIGHT = 5.0
_FIRED_SIGNAL_WEIGHT = 5.0

# --- Confidence buckets -> behavior -----------------------------------------
# (lower_bound_inclusive, label, size_usd). Checked in order; the last
# bucket whose lower bound the score clears wins. $20 is a HARD
# ceiling (never exceeded); $5 is the minimum any APPROVED trade may
# be (a score below the first bucket's lower bound is NO_TRADE / $0,
# never a smaller approved size).
_BUCKETS: tuple[tuple[int, str, float], ...] = (
    (0, "NO_TRADE", 0.0),
    (50, "MINIMUM", 5.0),
    (60, "MODERATE", 7.5),
    (70, "STRONG", 10.0),
    (80, "VERY_STRONG", 15.0),
    (90, "EXTREME", 20.0),
)

MIN_APPROVED_TRADE_SIZE_USD = 5.0
MAX_APPROVED_TRADE_SIZE_USD = 20.0


@dataclass(frozen=True)
class ConfidenceAssessment:
    """The full, inspectable sizing decision for one entry candidate."""

    base_confidence: int  # 0-100
    bucket: str  # "NO_TRADE" | "MINIMUM" | "MODERATE" | "STRONG" | "VERY_STRONG" | "EXTREME"
    recommended_size_usd: float  # 0.0, or in [MIN_APPROVED_TRADE_SIZE_USD, MAX_APPROVED_TRADE_SIZE_USD]

    @property
    def approved(self) -> bool:
        return self.recommended_size_usd > 0


def compute_base_confidence(*, direction: str, edge_points: float, fired_signal_count: int) -> int:
    """Pure, deterministic, 0-100. `direction == "neutral"` (no
    directional thesis at all — see btc_entry_signal.py) always scores
    0, regardless of edge_points/fired_signal_count (which are
    meaningless without a direction)."""
    if direction == "neutral":
        return 0
    score = _BASE_CONFIDENCE_INTERCEPT + edge_points * _EDGE_POINTS_WEIGHT + fired_signal_count * _FIRED_SIGNAL_WEIGHT
    return max(0, min(100, round(score)))


def confidence_bucket(confidence: int) -> str:
    bucket = _BUCKETS[0][1]
    for lower_bound, label, _ in _BUCKETS:
        if confidence >= lower_bound:
            bucket = label
        else:
            break
    return bucket


def recommended_size_usd(confidence: int) -> float:
    bucket = confidence_bucket(confidence)
    for _, label, size in _BUCKETS:
        if label == bucket:
            return size
    raise AssertionError(f"unreachable: unknown bucket {bucket!r}")  # pragma: no cover


def assess_confidence(*, direction: str, edge_points: float, fired_signal_count: int) -> ConfidenceAssessment:
    """The single entry point engine.py calls — combines the three
    pure functions above into one inspectable result."""
    base_confidence = compute_base_confidence(
        direction=direction, edge_points=edge_points, fired_signal_count=fired_signal_count,
    )
    bucket = confidence_bucket(base_confidence)
    size = recommended_size_usd(base_confidence)
    return ConfidenceAssessment(base_confidence=base_confidence, bucket=bucket, recommended_size_usd=size)
