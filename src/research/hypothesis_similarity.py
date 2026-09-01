"""Phase 7, Part 4: defense against p-hacking via undisclosed repeated
experimentation.

The canonical example this exists to catch: testing 5-day, 10-day,
15-day, 20-day, 25-day, 30-day momentum and reporting only the winner as
"the" momentum hypothesis. `canonical_hash` reduces a hypothesis's
research-relevant dimensions (family, feature, target horizon, universe,
cost/execution assumptions) to a stable fingerprint; `similarity_score`
measures how close two hypotheses are along those same dimensions;
`check_research_reuse` flags — but never blocks — a new hypothesis that is
materially similar to something already tested, and explains why.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

POTENTIAL_RESEARCH_REUSE = "POTENTIAL_RESEARCH_REUSE"


@dataclass(frozen=True)
class HypothesisFingerprint:
    hypothesis_id: str
    family: str  # e.g. "momentum", "mean_reversion" — src.research.hypothesis_generator.HypothesisFamily.value
    feature_variant: str  # e.g. "roc_20", "zscore_5"
    target_horizon_bars: int
    universe_name: str
    threshold_bucket: str  # a coarse bucket, not the exact threshold — see _bucket_threshold
    cost_assumptions: str
    execution_assumptions: str

    def canonical_hash(self) -> str:
        """A stable hash over every dimension EXCEPT hypothesis_id — two
        hypotheses with different IDs but identical research-relevant
        dimensions hash identically, which is exactly the "materially
        similar" signal this module looks for."""
        payload = {
            "family": self.family, "feature_variant": self.feature_variant, "target_horizon_bars": self.target_horizon_bars,
            "universe_name": self.universe_name, "threshold_bucket": self.threshold_bucket,
            "cost_assumptions": self.cost_assumptions, "execution_assumptions": self.execution_assumptions,
        }
        blob = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def bucket_threshold(value: float, *, bucket_width: float) -> str:
    """Coarsens a continuous threshold/lookback into a bucket so that
    "20-day momentum" and "22-day momentum" land in the SAME bucket (they
    are testing essentially the same idea) while "20-day" and "60-day"
    land in different buckets (a genuinely different horizon). This is
    what lets canonical_hash catch a family of near-identical parameter
    sweeps rather than only exact duplicates."""
    if bucket_width <= 0:
        raise ValueError("bucket_width must be > 0")
    bucket_index = round(value / bucket_width)
    return f"[{bucket_index * bucket_width:g}..{(bucket_index + 1) * bucket_width:g})"


_DIMENSION_WEIGHTS: Mapping[str, float] = {
    "family": 0.35, "feature_variant": 0.20, "target_horizon_bars": 0.15,
    "universe_name": 0.10, "threshold_bucket": 0.15, "cost_assumptions": 0.025, "execution_assumptions": 0.025,
}


def similarity_score(a: HypothesisFingerprint, b: HypothesisFingerprint) -> float:
    """A weighted fraction-of-matching-dimensions score in [0, 1]. Family
    and feature_variant dominate the weighting deliberately — the whole
    point is to catch "same mechanism, different lookback" reuse, which
    is exactly a family+feature match with a different threshold_bucket."""
    score = 0.0
    if a.family == b.family:
        score += _DIMENSION_WEIGHTS["family"]
    if a.feature_variant == b.feature_variant:
        score += _DIMENSION_WEIGHTS["feature_variant"]
    if a.target_horizon_bars == b.target_horizon_bars:
        score += _DIMENSION_WEIGHTS["target_horizon_bars"]
    if a.universe_name == b.universe_name:
        score += _DIMENSION_WEIGHTS["universe_name"]
    if a.threshold_bucket == b.threshold_bucket:
        score += _DIMENSION_WEIGHTS["threshold_bucket"]
    if a.cost_assumptions == b.cost_assumptions:
        score += _DIMENSION_WEIGHTS["cost_assumptions"]
    if a.execution_assumptions == b.execution_assumptions:
        score += _DIMENSION_WEIGHTS["execution_assumptions"]
    return round(score, 6)


@dataclass(frozen=True)
class ResearchReuseCheck:
    new_hypothesis_id: str
    flagged: bool
    matches: tuple[tuple[str, float], ...]  # (prior_hypothesis_id, similarity_score), only entries >= threshold
    explanation: str


def check_research_reuse(new_fp: HypothesisFingerprint, prior_fingerprints: Sequence[HypothesisFingerprint], *, similarity_threshold: float = 0.70) -> ResearchReuseCheck:
    """Never blocks — only flags. A flagged hypothesis should still run;
    its experiment record should just carry the prior related tests
    alongside it (see src.research.research_family), so a reviewer can see
    the whole family rather than one cherry-picked result."""
    matches = []
    for prior in prior_fingerprints:
        if prior.hypothesis_id == new_fp.hypothesis_id:
            continue
        s = similarity_score(new_fp, prior)
        if s >= similarity_threshold:
            matches.append((prior.hypothesis_id, s))
    matches.sort(key=lambda m: m[1], reverse=True)
    flagged = len(matches) > 0
    if flagged:
        explanation = (
            f"{new_fp.hypothesis_id} scores >= {similarity_threshold} similarity against {len(matches)} prior "
            f"hypothesis/hypotheses ({', '.join(f'{h}={s:.2f}' for h, s in matches)}) — same family/feature with a "
            "different threshold is the classic 'tested 6 lookbacks, reported the winner' pattern. Not blocked, but "
            "the experiment record must list these as related prior tests."
        )
    else:
        explanation = f"{new_fp.hypothesis_id}: no prior hypothesis scores >= {similarity_threshold} similarity — appears materially distinct."
    return ResearchReuseCheck(new_hypothesis_id=new_fp.hypothesis_id, flagged=flagged, matches=tuple(matches), explanation=explanation)
