"""Phase 25, Part 20 — a quantitative 0-5 readiness scorecard, applied
to ORATS (the only provider whose evidence this phase judged strong
enough to score in depth -- Part 19's "do not fully audit every
provider if ORATS is successfully verified" bounded the scope of this
phase's research to ORATS plus one light comparison point, ThetaData;
see docs/orats_provider_validation.md Part 19 for that comparison).

Scoring philosophy, stated once here rather than repeated per row:
every score below is capped at 3/5 ("plausible, schema-level evidence,
not independently confirmed") unless the evidence tier is
OWN_LIVE_API_PROBE (never reached this phase for any non-Robinhood
source) -- a scorecard built entirely from CLAIMED_AVAILABLE_UNVERIFIED
evidence must not produce scores that read as if they were verified.
This directly operationalizes Part 3's "do not silently downgrade
third-party information into verified" instruction into the numbers
themselves, not just the prose.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class ScorecardDimension(enum.Enum):
    HISTORICAL_DEPTH = "historical_depth"
    DAILY_OHLC = "daily_ohlc"
    INTRADAY = "intraday"
    BID_ASK_HISTORICAL = "bid_ask_historical"
    VOLUME = "volume"
    OPEN_INTEREST = "open_interest"
    IMPLIED_VOLATILITY = "implied_volatility"
    GREEKS = "greeks"
    EXPIRED_CONTRACTS = "expired_contracts"
    HISTORICAL_CHAIN = "historical_chain"
    CONTRACT_IDENTITY = "contract_identity"
    PIT_CAPABILITY = "pit_capability"
    API_ERGONOMICS = "api_ergonomics"
    COST_ACCESSIBILITY = "cost_accessibility"
    LICENSING_CLARITY = "licensing_clarity"


# Part 20: "critical blockers ... should disqualify a provider regardless
# of total score." These four dimensions are the literal blockers named
# in the prompt (no expired contracts / no historical bid-ask / no
# historical chain / no usable historical contract identity).
CRITICAL_BLOCKER_DIMENSIONS = frozenset(
    {
        ScorecardDimension.EXPIRED_CONTRACTS,
        ScorecardDimension.BID_ASK_HISTORICAL,
        ScorecardDimension.HISTORICAL_CHAIN,
        ScorecardDimension.CONTRACT_IDENTITY,
    }
)

# A dimension is disqualifying only if its score is 0 -- "no [capability]
# at all," not merely "unverified but plausible." A 0 means either
# VERIFIED_UNAVAILABLE or literally no evidence of the capability
# existing anywhere in the schema evidence gathered.
DISQUALIFYING_SCORE = 0


@dataclass(frozen=True)
class DimensionScore:
    dimension: ScorecardDimension
    score: int  # 0-5
    rationale: str

    def __post_init__(self):
        if not 0 <= self.score <= 5:
            raise ValueError(f"score must be 0-5, got {self.score}")


@dataclass(frozen=True)
class ProviderReadinessScorecard:
    provider: str
    scores: tuple[DimensionScore, ...]
    notes: str = ""

    def __post_init__(self):
        dims = {s.dimension for s in self.scores}
        missing = set(ScorecardDimension) - dims
        if missing:
            raise ValueError(f"{self.provider} scorecard is missing dimensions: {missing}")

    def score_for(self, dimension: ScorecardDimension) -> int:
        return next(s.score for s in self.scores if s.dimension == dimension)

    def total_score(self) -> int:
        return sum(s.score for s in self.scores)

    def max_possible_score(self) -> int:
        return len(self.scores) * 5

    def triggered_critical_blockers(self) -> tuple[ScorecardDimension, ...]:
        return tuple(
            s.dimension
            for s in self.scores
            if s.dimension in CRITICAL_BLOCKER_DIMENSIONS and s.score == DISQUALIFYING_SCORE
        )

    def disqualified(self) -> bool:
        """Part 20's override rule: a critical blocker disqualifies the
        provider REGARDLESS of total score."""
        return len(self.triggered_critical_blockers()) > 0


ORATS_READINESS_SCORECARD = ProviderReadinessScorecard(
    provider="ORATS",
    scores=(
        DimensionScore(
            ScorecardDimension.HISTORICAL_DEPTH, 2,
            "Depth claim (2007 EOD / Aug 2020 intraday) carried over unverified from Phase 24 web research; not independently reconfirmed this phase, and orats.com's own coverage pages were EGRESS_BLOCKED.",
        ),
        DimensionScore(
            ScorecardDimension.DAILY_OHLC, 3,
            "DailyPrice class confirms both adjusted and unadjusted OHLC fields exist in the real API schema (open_source_client_library_schema evidence tier).",
        ),
        DimensionScore(
            ScorecardDimension.INTRADAY, 1,
            "No intraday-specific field/endpoint was directly observed in the fetched data.py classes; the Aug-2020-intraday claim is carried over from Phase 24's weaker (marketing/third-party) evidence tier only.",
        ),
        DimensionScore(
            ScorecardDimension.BID_ASK_HISTORICAL, 3,
            "Strike class confirms call_bid_price/call_ask_price/put_bid_price/put_ask_price fields, keyed by trade_date -- real schema evidence, not a live-verified value.",
        ),
        DimensionScore(
            ScorecardDimension.VOLUME, 3,
            "Strike and Core classes both confirm real volume fields (call_volume/put_volume, total_stock_volume).",
        ),
        DimensionScore(
            ScorecardDimension.OPEN_INTEREST, 3,
            "Strike and Core classes both confirm real open-interest fields.",
        ),
        DimensionScore(
            ScorecardDimension.IMPLIED_VOLATILITY, 3,
            "Strike (raw + bid/mid/ask IV) and Money (21-point delta-bucketed smile) classes confirm unusually granular real IV schema.",
        ),
        DimensionScore(
            ScorecardDimension.GREEKS, 3,
            "Strike class confirms delta/gamma/theta/vega/rho/phi/driftless_theta fields; calculation methodology itself remains UNKNOWN (no rate-source/dividend-treatment/model evidence gathered).",
        ),
        DimensionScore(
            ScorecardDimension.EXPIRED_CONTRACTS, 2,
            "Inferred (not directly schema-confirmed) from the trade_date-scoped historical query design -- no explicit contract-state field was observed. Above the disqualifying floor because the inference is grounded in a real, specific mechanism (DataHistoryApiRequest's trade_date parameter), not pure assumption.",
        ),
        DimensionScore(
            ScorecardDimension.HISTORICAL_CHAIN, 4,
            "Strongest-evidenced dimension: the Strike class IS a per-trade_date, per-expiration, per-strike row -- structurally a historical chain snapshot by design, backed by the confirmed trade_date query parameter.",
        ),
        DimensionScore(
            ScorecardDimension.CONTRACT_IDENTITY, 2,
            "ticker+strike+expiration_date+call/put-prefix fields give a usable identity, but multiplier, exercise_style, and contract_status were not observed anywhere in the fetched schema -- a real gap versus Phase 24's ContractIdentity design target.",
        ),
        DimensionScore(
            ScorecardDimension.PIT_CAPABILITY, 3,
            "The trade_date-scoped query is a genuinely stronger practical PIT mechanism than Robinhood's eventual-existence-only capability (Part 7's reconciliation) -- still unverified via a live call, so capped below 4.",
        ),
        DimensionScore(
            ScorecardDimension.API_ERGONOMICS, 2,
            "A maintained typed Python client exists (evidence of a workable REST API shape), but no live authentication/rate-limit/error-handling behavior was ever exercised this phase.",
        ),
        DimensionScore(
            ScorecardDimension.COST_ACCESSIBILITY, 1,
            "Reported figures ($99-399/mo) are unverified and in apparent tension across different third-party sources found this phase; the official pricing page was EGRESS_BLOCKED; the free trial requires a credit card (PAID_PROOF_REQUIRED).",
        ),
        DimensionScore(
            ScorecardDimension.LICENSING_CLARITY, 0,
            "No licensing/redistribution/automated-trading-use terms were found anywhere in the sources reached this phase.",
        ),
    ),
    notes=(
        "Every score above is capped at 3/5 unless noted, because the evidence tier backing this entire "
        "scorecard is OPEN_SOURCE_CLIENT_LIBRARY_SCHEMA (real but secondary), never OWN_LIVE_API_PROBE. "
        "LICENSING_CLARITY scores 0 but is NOT a Part-20 critical-blocker dimension, so it lowers the total "
        "score without disqualifying the provider outright -- see disqualified()."
    ),
)
