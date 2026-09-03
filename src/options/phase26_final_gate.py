"""Phase 26, Part 11 — the minimum research-ready standard gates."""

from __future__ import annotations

import enum

from src.options.phase26_certification_score import CertificationDimension, DatasetCertificationScore


class ResearchReadinessGate(enum.Enum):
    HISTORICAL_OPTIONS_DATA_INSUFFICIENT = "historical_options_data_insufficient"
    HISTORICAL_OPTIONS_DATA_PARTIAL = "historical_options_data_partial"
    HISTORICAL_OPTIONS_RESEARCH_READY = "historical_options_research_ready"
    HISTORICAL_OPTIONS_BACKTEST_READY = "historical_options_backtest_ready"
    HISTORICAL_OPTIONS_PRODUCTION_RESEARCH_READY = "historical_options_production_research_ready"


# The minimum score (out of 5) below which a dimension counts as "missing"
# for gate purposes (Part 11: "important fields are missing"). 3 is chosen
# deliberately: 3/5 in this module's scoring convention means "real,
# working, evidence-backed but incomplete" -- that already clears the bar
# for RESEARCH/BACKTEST readiness; only a 0-2 genuinely means the field is
# unreliable or absent for practical use.
MINIMUM_ADEQUATE_SCORE = 3

RESEARCH_READY_REQUIRED_DIMENSIONS = frozenset({
    CertificationDimension.CONTRACT_IDENTITY,
    CertificationDimension.TIMESTAMP_QUALITY,
    CertificationDimension.HISTORICAL_OHLC,
    CertificationDimension.POINT_IN_TIME_SAFETY,
})

BACKTEST_READY_ADDITIONAL_DIMENSIONS = frozenset({
    CertificationDimension.HISTORICAL_BID_ASK,
    CertificationDimension.EXECUTION_REALISM,
})

PRODUCTION_READY_ADDITIONAL_DIMENSIONS = frozenset({
    CertificationDimension.LICENSING_ACCESS_CLARITY,
    CertificationDimension.PROVENANCE,
})


def _clears(score: DatasetCertificationScore, dims: frozenset) -> bool:
    return all(score.score_for(d) >= MINIMUM_ADEQUATE_SCORE for d in dims)


def evaluate_gate(score: DatasetCertificationScore, *, coverage_is_general_purpose: bool) -> ResearchReadinessGate:
    """`coverage_is_general_purpose` must be supplied explicitly by the
    caller (Part 11: "Do not call something backtest-ready merely
    because OHLC exists") -- per-field quality and dataset BREADTH are
    two different questions, and this function refuses to conflate them:
    a narrow-but-high-quality sample cannot silently earn a
    general-research-ready classification just because its own fields
    score well."""
    if score.disqualified():
        return ResearchReadinessGate.HISTORICAL_OPTIONS_DATA_INSUFFICIENT

    if not _clears(score, RESEARCH_READY_REQUIRED_DIMENSIONS):
        return ResearchReadinessGate.HISTORICAL_OPTIONS_DATA_PARTIAL

    if not coverage_is_general_purpose:
        # Real, working, PIT-safe research capability exists, but only over
        # a narrow slice (this phase's real finding: 5 underlyings 2013-2016
        # daily + one SPY day in 2023; no NVDA/TSLA at all; no native IV/
        # Greeks) -- honest ceiling is PARTIAL for the project's general
        # research need, regardless of how well the narrow slice itself scores.
        return ResearchReadinessGate.HISTORICAL_OPTIONS_DATA_PARTIAL

    if not _clears(score, BACKTEST_READY_ADDITIONAL_DIMENSIONS):
        return ResearchReadinessGate.HISTORICAL_OPTIONS_RESEARCH_READY

    if not _clears(score, PRODUCTION_READY_ADDITIONAL_DIMENSIONS):
        return ResearchReadinessGate.HISTORICAL_OPTIONS_BACKTEST_READY

    return ResearchReadinessGate.HISTORICAL_OPTIONS_PRODUCTION_RESEARCH_READY
