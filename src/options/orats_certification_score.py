"""Phase 29, Part 13 — the ORATS dataset certification. Reuses Phase
26/27's exact `ResearchReadinessGate` 5-value OUTPUT vocabulary (Part
13's own "possible final states" list is IDENTICAL to it, letter for
letter) -- a new 15-dimension INPUT scorecard is built because Part
13's own dimension list (adding QUOTE_SIZES, INTRADAY, COVERAGE as
first-class dimensions; dropping CORPORATE_ACTIONS/TIMESTAMP_QUALITY/
LICENSING_ACCESS_CLARITY as separate ones) differs from Phase 26/27's
`CertificationDimension`, mirroring the same "new explicit vocabulary
gets a new enum; the scoring SHAPE (0-5 DimensionScore + critical-
blocker override) gets reused" pattern Phase 28 already established.

CRITICAL, HONEST FINDING driving every score below: this phase never
obtained a single real ORATS API response (`ORATS_ACTIVATION_PENDING_
HUMAN` -- see orats_activation_state.py). Every dimension is therefore
capped at the SAME evidence tier Phase 25/28 already established for
ORATS (real, independently-verified open-source client SCHEMA, never
an actual live sample) -- and COVERAGE scores an honest 0 (literally
zero real ORATS observations of any kind exist for ANY underlying,
target or otherwise), which is one of this module's own critical-
blocker dimensions. This is NOT a claim that ORATS's real data would
be insufficient once obtained -- it is the accurate statement that NO
real data was obtained THIS PHASE to certify at all.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from src.options.phase26_final_gate import ResearchReadinessGate


class ORATSCertificationDimension(enum.Enum):
    """Part 13's exact 15-item list."""

    CONTRACT_IDENTITY = "contract_identity"
    LIFECYCLE = "lifecycle"
    OHLC = "ohlc"
    BID_ASK = "bid_ask"
    QUOTE_SIZES = "quote_sizes"
    VOLUME = "volume"
    OPEN_INTEREST = "open_interest"
    IV = "iv"
    GREEKS = "greeks"
    HISTORICAL_CHAIN = "historical_chain"
    PIT = "pit"
    INTRADAY = "intraday"
    EXECUTION_REALISM = "execution_realism"
    COVERAGE = "coverage"
    PROVENANCE = "provenance"


CRITICAL_BLOCKER_DIMENSIONS = frozenset({
    ORATSCertificationDimension.CONTRACT_IDENTITY,
    ORATSCertificationDimension.HISTORICAL_CHAIN,
    ORATSCertificationDimension.PIT,
    ORATSCertificationDimension.COVERAGE,
})

DISQUALIFYING_SCORE = 0


@dataclass(frozen=True)
class ORATSDimensionScore:
    dimension: ORATSCertificationDimension
    score: int
    rationale: str

    def __post_init__(self):
        if not 0 <= self.score <= 5:
            raise ValueError(f"score must be 0-5, got {self.score}")


@dataclass(frozen=True)
class ORATSCertificationResult:
    scores: tuple[ORATSDimensionScore, ...]
    notes: str = ""

    def __post_init__(self):
        dims = {s.dimension for s in self.scores}
        missing = set(ORATSCertificationDimension) - dims
        if missing:
            raise ValueError(f"ORATS certification is missing dimensions: {missing}")

    def score_for(self, dimension: ORATSCertificationDimension) -> int:
        return next(s.score for s in self.scores if s.dimension == dimension)

    def total_score(self) -> int:
        return sum(s.score for s in self.scores)

    def max_possible_score(self) -> int:
        return len(self.scores) * 5

    def triggered_critical_blockers(self) -> tuple[ORATSCertificationDimension, ...]:
        return tuple(s.dimension for s in self.scores if s.dimension in CRITICAL_BLOCKER_DIMENSIONS and s.score == DISQUALIFYING_SCORE)

    def disqualified(self) -> bool:
        return len(self.triggered_critical_blockers()) > 0


def evaluate_orats_gate(result: ORATSCertificationResult) -> ResearchReadinessGate:
    """Part 13: 'critical blockers override aggregate score.' A
    disqualified result is always HISTORICAL_OPTIONS_DATA_INSUFFICIENT,
    regardless of how high any individual non-blocker score is."""
    if result.disqualified():
        return ResearchReadinessGate.HISTORICAL_OPTIONS_DATA_INSUFFICIENT
    if result.total_score() < result.max_possible_score() * 0.3:
        return ResearchReadinessGate.HISTORICAL_OPTIONS_DATA_PARTIAL
    if result.total_score() < result.max_possible_score() * 0.6:
        return ResearchReadinessGate.HISTORICAL_OPTIONS_RESEARCH_READY
    if result.total_score() < result.max_possible_score() * 0.8:
        return ResearchReadinessGate.HISTORICAL_OPTIONS_BACKTEST_READY
    return ResearchReadinessGate.HISTORICAL_OPTIONS_PRODUCTION_RESEARCH_READY


def _s(dim: ORATSCertificationDimension, score: int, rationale: str) -> ORATSDimensionScore:
    return ORATSDimensionScore(dim, score, rationale)


D = ORATSCertificationDimension

# The real, current, honest ORATS certification -- Path A, zero real API
# calls made. Every non-zero score reflects ONLY the real open-source
# client schema evidence (Phase 25, corrected this phase -- see
# orats_field_provenance.py); COVERAGE (a critical-blocker dimension)
# is an honest 0 because zero real observations of any underlying exist.
ORATS_CERTIFICATION = ORATSCertificationResult(
    scores=(
        _s(D.CONTRACT_IDENTITY, 2, "Real schema field names confirmed (ticker/strike/expirDate/call-put-prefix); no multiplier/exercise-style/exchange field; never queried live."),
        _s(D.LIFECYCLE, 1, "No first-listed-date field in the schema (PIT_CONTRACT_EXISTENCE_LIMITED); never queried live."),
        _s(D.OHLC, 2, "DailyPrice schema confirmed real (adjusted+unadjusted); never queried live for any contract."),
        _s(D.BID_ASK, 2, "Strike.call_bid_price/call_ask_price confirmed real schema fields; never queried live."),
        _s(D.QUOTE_SIZES, 2, "Strike.call_bid_size/call_ask_size confirmed real schema fields (corrected this phase, see orats_field_provenance.py); never queried live."),
        _s(D.VOLUME, 2, "Strike.call_volume confirmed real schema field; never queried live."),
        _s(D.OPEN_INTEREST, 2, "Strike.call_open_interest confirmed real schema field; never queried live."),
        _s(D.IV, 2, "Strike.iv (+bid/mid/ask IV, 21-point delta smile via Money) confirmed real schema fields, the richest of any provider evaluated; never queried live."),
        _s(D.GREEKS, 2, "Strike.delta/gamma/theta/vega/rho confirmed real schema fields; never queried live."),
        _s(D.HISTORICAL_CHAIN, 2, "A real, confirmed trade_date query parameter exists (the strongest PIT-chain mechanism of any candidate evaluated); never actually exercised via a live call."),
        _s(D.PIT, 2, "Same real trade_date mechanism; PIT_CONTRACT_EXISTENCE_LIMITED still applies (no listing-date field); never verified live."),
        _s(D.INTRADAY, 0, "1-minute-since-2020 is a third-party marketing claim, never confirmed in the real schema evidence or by any live query."),
        _s(D.EXECUTION_REALISM, 2, "Real bid/ask+size fields confirmed; no real trade-tick field confirmed (see orats_execution_certification.py); never queried live."),
        _s(D.COVERAGE, 0, "Zero real ORATS observations exist for ANY underlying, target or otherwise -- no live API call was ever made this phase (ORATS_ACTIVATION_PENDING_HUMAN)."),
        _s(D.PROVENANCE, 3, "Every normalized record this phase's adapter WOULD build carries a complete, real OptionDataProvenance/EventTimestamps pair (orats_schema_mapping.py, tested) -- the adapter's provenance DISCIPLINE is real and verified even though no real DATA has flowed through it yet."),
    ),
    notes=(
        "This is a certification of what evidence EXISTS about ORATS, not a certification of ORATS's real "
        "data (none was obtained this phase). COVERAGE, a critical-blocker dimension, honestly scores 0 -- "
        "the disqualification this produces reflects 'no real data was obtained,' not 'ORATS's data would be "
        "insufficient once obtained.' This result must be re-run once real credentials exist and a real "
        "sample is retrieved (Path B, a future phase)."
    ),
)

ORATS_GATE = evaluate_orats_gate(ORATS_CERTIFICATION)
