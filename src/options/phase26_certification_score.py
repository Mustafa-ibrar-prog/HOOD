"""Phase 26, Part 1/10 — the dataset certification score.

Audit note (Part 1's explicit requirement): this is a DELIBERATE,
NARROW extension of Phase 25's `ProviderReadinessScorecard` pattern
(`src.options.provider_readiness_scorecard`), not a duplicate of it.
Phase 25's scorecard evaluates a VENDOR'S CLAIMS about a dataset it had
not yet obtained (every score there was capped at 3/5 because no live
probe existed). This module certifies an ACTUALLY-OBTAINED, ACTUALLY-
INGESTED, ACTUALLY-TESTED dataset -- a genuinely different evaluation
(retrospective and evidence-grounded, not prospective and claims-based),
over a genuinely different dimension list (Part 10 adds
POINT_IN_TIME_SAFETY, EXECUTION_REALISM, TIMESTAMP_QUALITY, and
PROVENANCE as first-class dimensions that Phase 25's vendor-level
scorecard did not need). The SHAPE is intentionally the same
(`DimensionScore`-style 0-5 scores plus a critical-blocker override that
disqualifies regardless of total score) because that shape is exactly
right for both jobs -- reusing the pattern, not the class, since the two
scorecards' field lists and disqualification triggers are genuinely
different (Part 1: "do not duplicate provider interfaces
unnecessarily" is honored by sharing the PATTERN, not by force-fitting
one dataclass to two different dimension enums).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class CertificationDimension(enum.Enum):
    CONTRACT_IDENTITY = "contract_identity"
    CONTRACT_LIFECYCLE = "contract_lifecycle"
    HISTORICAL_OHLC = "historical_ohlc"
    HISTORICAL_BID_ASK = "historical_bid_ask"
    VOLUME = "volume"
    OPEN_INTEREST = "open_interest"
    IMPLIED_VOLATILITY = "implied_volatility"
    GREEKS = "greeks"
    HISTORICAL_CHAIN_RECONSTRUCTION = "historical_chain_reconstruction"
    POINT_IN_TIME_SAFETY = "point_in_time_safety"
    EXECUTION_REALISM = "execution_realism"
    CORPORATE_ACTIONS = "corporate_actions"
    TIMESTAMP_QUALITY = "timestamp_quality"
    PROVENANCE = "provenance"
    LICENSING_ACCESS_CLARITY = "licensing_access_clarity"


# Part 10's literal critical-blocker list, mapped onto this module's dimensions.
CRITICAL_BLOCKER_DIMENSIONS = frozenset({
    CertificationDimension.CONTRACT_IDENTITY,       # "no reliable contract identity"
    CertificationDimension.POINT_IN_TIME_SAFETY,     # "severe point-in-time leakage" / "inability to establish whether contracts existed"
    CertificationDimension.TIMESTAMP_QUALITY,        # "unusable timestamps"
    CertificationDimension.LICENSING_ACCESS_CLARITY,  # "unknown licensing for intended research use"
})

DISQUALIFYING_SCORE = 0


@dataclass(frozen=True)
class DimensionScore:
    dimension: CertificationDimension
    score: int  # 0-5
    rationale: str
    evidence: str  # what REAL check/number this score is based on

    def __post_init__(self):
        if not 0 <= self.score <= 5:
            raise ValueError(f"score must be 0-5, got {self.score}")


@dataclass(frozen=True)
class DatasetCertificationScore:
    dataset_label: str
    scores: tuple[DimensionScore, ...]
    notes: str = ""

    def __post_init__(self):
        dims = {s.dimension for s in self.scores}
        missing = set(CertificationDimension) - dims
        if missing:
            raise ValueError(f"{self.dataset_label} certification is missing dimensions: {missing}")

    def score_for(self, dimension: CertificationDimension) -> int:
        return next(s.score for s in self.scores if s.dimension == dimension)

    def total_score(self) -> int:
        return sum(s.score for s in self.scores)

    def max_possible_score(self) -> int:
        return len(self.scores) * 5

    def triggered_critical_blockers(self) -> tuple[CertificationDimension, ...]:
        return tuple(s.dimension for s in self.scores if s.dimension in CRITICAL_BLOCKER_DIMENSIONS and s.score == DISQUALIFYING_SCORE)

    def disqualified(self) -> bool:
        """Part 10's override rule: a critical blocker disqualifies
        regardless of total score."""
        return len(self.triggered_critical_blockers()) > 0
