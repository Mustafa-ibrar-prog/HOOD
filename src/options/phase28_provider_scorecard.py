"""Phase 28, Part 1/8 — the provider decision scorecard.

Audit note (Part 1's explicit requirement): this is a DELIBERATE, new
20-dimension scorecard, not a duplicate of Phase 25's 15-dimension
`ProviderReadinessScorecard` or Phase 26/27's 15-dimension
`DatasetCertificationScore`. Part 8's own text enumerates exactly 20
named dimensions, five of which (QUOTE_SIZES, EXECUTION_REALISM,
UNDERLYING_COVERAGE, EXPIRATION_STRIKE_BREADTH, CORPORATE_ACTIONS,
COST_VALUE -- six, not five) have no counterpart in Phase 25's vendor-
readiness list. The SHAPE is reused deliberately (0-5 `DimensionScore`,
a critical-blocker override that disqualifies regardless of total
score) because Phase 25/26/27 already proved that shape is right for
exactly this kind of decision; only the dimension list and scope
(comparing several vendors here, vs. one already-obtained dataset in
Phase 26/27, vs. one single vendor's claims in Phase 25) differ.

Evidence basis: every score below is built from real evidence already
gathered in Phase 24 (`vendor_scorecard.py`, third-party/marketing-tier
research), Phase 25 (`provider_field_validation.py`/
`provider_readiness_scorecard.py`, ORATS's real open-source-client
schema -- the single strongest evidence tier any candidate has), and
this phase's own re-confirmation that `thetadata.net`/`databento.com`
remain EGRESS_BLOCKED (unchanged). No new vendor API call, sample, or
official documentation page was reached this phase -- every score stays
capped exactly as conservatively as Phase 25's discipline required
("nothing here reached the strongest evidence tier, so nothing scores a
5").
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class ProviderScorecardDimension(enum.Enum):
    """Part 8's exact 20-item list."""

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
    PIT_SAFETY = "pit_safety"
    INTRADAY = "intraday"
    EXECUTION_REALISM = "execution_realism"
    UNDERLYING_COVERAGE = "underlying_coverage"
    HISTORICAL_COVERAGE = "historical_coverage"
    EXPIRATION_STRIKE_BREADTH = "expiration_strike_breadth"
    CORPORATE_ACTIONS = "corporate_actions"
    API_DOWNLOAD_USABILITY = "api_download_usability"
    LICENSING_CLARITY = "licensing_clarity"
    COST_VALUE = "cost_value"


# The 3 dimensions whose complete absence (score 0) makes a provider
# fundamentally unusable for this project's research regardless of
# everything else -- consistent with Phase 25/26/27's precedent
# (contract identity, historical chain reconstruction, and PIT safety
# have been the load-bearing blockers in every prior phase's scorecard).
# LICENSING_CLARITY is deliberately NOT a scorecard-disqualifying
# dimension here (every one of this phase's 4 real finalists scores 0
# on it -- see module-level finding below) -- instead it is treated as
# a mandatory PURCHASE-GATE caveat (Part 10's report), exactly how
# Phase 25's PurchaseRecommendation handled the identical gap without
# that alone erasing ORATS as a candidate.
CRITICAL_BLOCKER_DIMENSIONS = frozenset({
    ProviderScorecardDimension.CONTRACT_IDENTITY,
    ProviderScorecardDimension.HISTORICAL_CHAIN,
    ProviderScorecardDimension.PIT_SAFETY,
})

DISQUALIFYING_SCORE = 0


@dataclass(frozen=True)
class ProviderDimensionScore:
    dimension: ProviderScorecardDimension
    score: int  # 0-5
    rationale: str

    def __post_init__(self):
        if not 0 <= self.score <= 5:
            raise ValueError(f"score must be 0-5, got {self.score}")


@dataclass(frozen=True)
class ProviderScorecard:
    provider: str
    scores: tuple[ProviderDimensionScore, ...]
    eliminated: bool = False
    elimination_reason: str = ""

    def __post_init__(self):
        if self.eliminated:
            return  # an eliminated provider is not required to carry all 20 dimensions -- Part 2's "efficiently eliminate" instruction
        dims = {s.dimension for s in self.scores}
        missing = set(ProviderScorecardDimension) - dims
        if missing:
            raise ValueError(f"{self.provider} scorecard is missing dimensions: {missing}")

    def score_for(self, dimension: ProviderScorecardDimension) -> int:
        return next(s.score for s in self.scores if s.dimension == dimension)

    def total_score(self) -> int:
        return sum(s.score for s in self.scores)

    def max_possible_score(self) -> int:
        return len(self.scores) * 5

    def triggered_critical_blockers(self) -> tuple[ProviderScorecardDimension, ...]:
        return tuple(s.dimension for s in self.scores if s.dimension in CRITICAL_BLOCKER_DIMENSIONS and s.score == DISQUALIFYING_SCORE)

    def disqualified(self) -> bool:
        if self.eliminated:
            return True
        return len(self.triggered_critical_blockers()) > 0


def _s(dim: ProviderScorecardDimension, score: int, rationale: str) -> ProviderDimensionScore:
    return ProviderDimensionScore(dim, score, rationale)


D = ProviderScorecardDimension

ORATS_SCORECARD = ProviderScorecard(
    provider="ORATS",
    scores=(
        _s(D.CONTRACT_IDENTITY, 2, "ticker+strike+expiration+call/put-prefix confirmed real (open-source client schema, Phase 25); no multiplier/exercise-style/exchange field observed"),
        _s(D.LIFECYCLE, 2, "no explicit contract-state/listing-date field observed; trade_date-scoped design implies eventual coverage, not directly confirmed"),
        _s(D.OHLC, 3, "DailyPrice class confirms real adjusted+unadjusted OHLC fields"),
        _s(D.BID_ASK, 3, "Strike class confirms real call/put bid+ask price fields, keyed by trade_date"),
        _s(D.QUOTE_SIZES, 1, "no bid/ask SIZE field observed anywhere in the fetched schema -- a real, confirmed gap"),
        _s(D.VOLUME, 3, "Strike+Core classes confirm real per-strike and aggregate volume fields"),
        _s(D.OPEN_INTEREST, 3, "Strike+Core classes confirm real per-strike and aggregate OI fields"),
        _s(D.IV, 3, "raw+bid/mid/ask IV plus a 21-point delta-bucketed smile (Money class) -- the richest real IV schema of any candidate"),
        _s(D.GREEKS, 3, "delta/gamma/theta/vega/rho/phi/driftless_theta confirmed real fields"),
        _s(D.HISTORICAL_CHAIN, 4, "a confirmed real trade_date query parameter -- the strongest historical-chain-reconstruction mechanism of any candidate evaluated any phase"),
        _s(D.PIT_SAFETY, 3, "the trade_date parameter is a genuine practical PIT mechanism, still never exercised via a live call"),
        _s(D.INTRADAY, 1, "1-minute-since-2020 claim carried over from Phase 24's weaker (marketing) evidence tier only; no intraday field/endpoint directly observed in the real schema"),
        _s(D.EXECUTION_REALISM, 2, "real bid/ask price fields exist but no size/trade fields observed -- incomplete execution-modeling evidence"),
        _s(D.UNDERLYING_COVERAGE, 3, "broad equity/ETF options coverage claimed (third-party/marketing tier), not independently confirmed"),
        _s(D.HISTORICAL_COVERAGE, 2, "reported since-2007-EOD/since-Aug-2020-intraday, unverified, orats.com itself EGRESS_BLOCKED every phase tried"),
        _s(D.EXPIRATION_STRIKE_BREADTH, 3, "Strike/Money schema design strongly implies full per-expiration/per-strike granularity"),
        _s(D.CORPORATE_ACTIONS, 3, "dedicated real /splits and /divs endpoints confirmed via the open-source client schema -- strongest corporate-action evidence of any candidate"),
        _s(D.API_DOWNLOAD_USABILITY, 2, "a maintained typed Python client exists (real evidence of a workable REST shape); no live auth/rate-limit behavior ever exercised"),
        _s(D.LICENSING_CLARITY, 0, "no licensing/redistribution/automated-trading-use terms found in any source reached any phase"),
        _s(D.COST_VALUE, 1, "reported $99-399/mo tiers in apparent tension across third-party sources; free trial requires a credit card (PAID_PROOF_REQUIRED, never pursued)"),
    ),
)

THETADATA_SCORECARD = ProviderScorecard(
    provider="ThetaData",
    scores=(
        _s(D.CONTRACT_IDENTITY, 2, "root/exp/strike/isCall/isOption confirmed real fields in the (deprecated) legacy client; no multiplier/exercise-style field observed"),
        _s(D.LIFECYCLE, 1, "no evidence found any phase"),
        _s(D.OHLC, 3, "OHLCVC confirmed real fields in the legacy client schema"),
        _s(D.BID_ASK, 3, "Quote.bid_price/ask_price confirmed real fields"),
        _s(D.QUOTE_SIZES, 3, "Quote.bid_size/ask_size confirmed real fields -- the only candidate with confirmed (not merely claimed) quote-size fields"),
        _s(D.VOLUME, 3, "Trade.size confirmed real field"),
        _s(D.OPEN_INTEREST, 3, "a dedicated OpenInterest tick type confirmed real"),
        _s(D.IV, 1, "claimed (bisection-computed from NBBO+underlying) but NOT present as a field in the actual legacy client schema inspected -- a real, negative finding"),
        _s(D.GREEKS, 1, "same as IV -- claimed but confirmed ABSENT from the real legacy client schema (Phase 25's direct finding)"),
        _s(D.HISTORICAL_CHAIN, 2, "tick-level intraday chain access claimed, not independently confirmed; current v3 REST docs EGRESS_BLOCKED"),
        _s(D.PIT_SAFETY, 2, "plausible given tick-level claims, never independently confirmed"),
        _s(D.INTRADAY, 3, "tick-level trade+quote pairing is the core claimed strength"),
        _s(D.EXECUTION_REALISM, 3, "confirmed real bid/ask+size+trade+size fields -- the most complete CONFIRMED (not just claimed) execution-data field set of any candidate"),
        _s(D.UNDERLYING_COVERAGE, 2, "broad US options claimed, unverified"),
        _s(D.HISTORICAL_COVERAGE, 2, "'since 2018' claimed (third-party), unverified"),
        _s(D.EXPIRATION_STRIKE_BREADTH, 2, "unconfirmed"),
        _s(D.CORPORATE_ACTIONS, 1, "no evidence found any phase"),
        _s(D.API_DOWNLOAD_USABILITY, 2, "an official client existed but is deprecated in favor of an undocumented-from-here v3 REST API"),
        _s(D.LICENSING_CLARITY, 0, "no evidence found any phase"),
        _s(D.COST_VALUE, 2, "reported ~$25/mo real-time tier (third-party, unverified) -- the cheapest reported figure among the finalists"),
    ),
)

DATABENTO_SCORECARD = ProviderScorecard(
    provider="Databento",
    scores=(
        _s(D.CONTRACT_IDENTITY, 3, "instrument-definition schema described as covering the full historical instrument universe -- plausible, not independently confirmed"),
        _s(D.LIFECYCLE, 2, "plausible via the instrument-definition schema, unconfirmed"),
        _s(D.OHLC, 3, "OHLCV aggregates at multiple intervals, claimed"),
        _s(D.BID_ASK, 3, "consolidated NBBO across all 17 national options exchanges, claimed"),
        _s(D.QUOTE_SIZES, 2, "implied by MBP-1 top-of-book design, size granularity not independently confirmed"),
        _s(D.VOLUME, 3, "volume claimed as part of the standard trade/OHLCV schema, not independently confirmed"),
        _s(D.OPEN_INTEREST, 1, "a statistics schema is described; OI itself not itemized in sources reviewed"),
        _s(D.IV, 0, "explicitly NOT a raw field -- this is a raw-tape feed; IV would need downstream computation, never supplied directly"),
        _s(D.GREEKS, 0, "same reasoning as IV -- a raw-tape feed, no native Greeks field"),
        _s(D.HISTORICAL_CHAIN, 3, "instrument-definition schema plausible for chain reconstruction, unconfirmed"),
        _s(D.PIT_SAFETY, 3, "true raw-tape reconstruction is, by architecture, the most PIT-faithful design of any candidate -- still unconfirmed via a live query"),
        _s(D.INTRADAY, 3, "true tick-level MBP-1/CBBO-1m claimed"),
        _s(D.EXECUTION_REALISM, 3, "consolidated NBBO + true tick trades claimed -- architecturally strong, unconfirmed"),
        _s(D.UNDERLYING_COVERAGE, 3, "full US options market claimed"),
        _s(D.HISTORICAL_COVERAGE, 2, "~2013+ per a vendor blog post, unverified"),
        _s(D.EXPIRATION_STRIKE_BREADTH, 3, "full instrument universe claimed"),
        _s(D.CORPORATE_ACTIONS, 1, "no explicit evidence found"),
        _s(D.API_DOWNLOAD_USABILITY, 2, "real Python/Rust/C++ clients exist"),
        _s(D.LICENSING_CLARITY, 0, "no evidence found any phase; raw OPRA redistribution typically carries exchange-license obligations not itemized here"),
        _s(D.COST_VALUE, 1, "pay-as-you-go, no flat figure found; even its free-credit pool is Stripe-gated (PAID_PROOF_REQUIRED, Phase 25)"),
    ),
)

POLYGON_MASSIVE_SCORECARD = ProviderScorecard(
    provider="Polygon.io / Massive",
    scores=(
        _s(D.CONTRACT_IDENTITY, 2, "contract identity claimed in vendor documentation summaries, not independently confirmed"),
        _s(D.LIFECYCLE, 1, "not confirmed in sources reviewed"),
        _s(D.OHLC, 3, "daily/intraday OHLC claimed in vendor documentation summaries"),
        _s(D.BID_ASK, 3, "NBBO quotes claimed"),
        _s(D.QUOTE_SIZES, 2, "implied by NBBO design, not directly confirmed"),
        _s(D.VOLUME, 3, "volume claimed as part of the standard trade schema"),
        _s(D.OPEN_INTEREST, 3, "claimed, via a chain snapshot endpoint"),
        _s(D.IV, 2, "implied volatility claimed as part of the chain snapshot endpoint"),
        _s(D.GREEKS, 2, "greeks claimed as part of the chain snapshot endpoint"),
        _s(D.HISTORICAL_CHAIN, 3, "a complete option chain snapshot endpoint including greeks/OI is claimed"),
        _s(D.PIT_SAFETY, 1, "no specific PIT-query mechanism described (unlike ORATS's trade_date parameter or Databento's raw-tape design)"),
        _s(D.INTRADAY, 3, "full tick-level trades/quotes claimed"),
        _s(D.EXECUTION_REALISM, 3, "NBBO quotes + trades claimed"),
        _s(D.UNDERLYING_COVERAGE, 3, "full US options market claimed"),
        _s(D.HISTORICAL_COVERAGE, 2, "since 2014 claimed"),
        _s(D.EXPIRATION_STRIKE_BREADTH, 3, "full chain claimed"),
        _s(D.CORPORATE_ACTIONS, 1, "no explicit evidence found"),
        _s(D.API_DOWNLOAD_USABILITY, 3, "REST + WebSocket + flat-file downloads, a mature and well-documented-elsewhere API shape"),
        _s(D.LICENSING_CLARITY, 0, "not itemized in sources reviewed"),
        _s(D.COST_VALUE, 2, "tiered ~$29-399/mo options-specific plans reported"),
    ),
)

# --- Efficiently eliminated (Part 2: "eliminate clearly unsuitable providers
# efficiently... not a huge vendor report") -- carried forward from Phase 24's
# real vendor_scorecard.py findings, not re-investigated in depth this phase.
CBOE_DATASHOP_SCORECARD = ProviderScorecard(
    provider="Cboe DataShop", scores=(), eliminated=True,
    elimination_reason="Exchange-of-record data, plausibly the most authoritative source, but licensing is 'contact for pricing' bulk-file/institutional-oriented (Phase 24) -- the least accessible cost/access model of any candidate for a ~$1,000-account personal project.",
)
OPTIONMETRICS_SCORECARD = ProviderScorecard(
    provider="OptionMetrics IvyDB", scores=(), eliminated=True,
    elimination_reason="Academic-grade, survivorship-bias-free gold standard, but distributed almost exclusively via institutional WRDS subscriptions (Phase 24) -- inaccessible without a university affiliation this project does not have.",
)
EODHD_SCORECARD = ProviderScorecard(
    provider="EODHD", scores=(), eliminated=True,
    elimination_reason="The '30+ years' headline coverage claim almost certainly describes the vendor's equity/EOD catalog broadly, not its options product specifically (Phase 24's own finding) -- the single largest unresolved verification gap of any vendor reviewed, never itemized further.",
)
TRADIER_SCORECARD = ProviderScorecard(
    provider="Tradier", scores=(), eliminated=True,
    elimination_reason="Its own native API has no bid/ask/Greeks/IV -- those are supplied through Tradier's own ORATS partnership (Phase 24). Not a genuinely separate candidate from ORATS itself; evaluating it adds no information ORATS's own scorecard doesn't already carry.",
)
INTRINIO_SCORECARD = ProviderScorecard(
    provider="Intrinio", scores=(), eliminated=True,
    elimination_reason="Insufficient public information gathered any phase to grade with any confidence; described only as institutional-targeted/expensive in third-party sources (Phase 24).",
)
QUANTCONNECT_ALGOSEEK_LIVE_SCORECARD = ProviderScorecard(
    provider="QuantConnect/AlgoSeek (live platform subscription, distinct from the free open-source Lean sample already fully exploited in Phase 26/27)", scores=(), eliminated=True,
    elimination_reason="Data is primarily consumed WITHIN QuantConnect's own cloud research/backtesting environment, not necessarily portable to this project's own src/ pipeline (Phase 24); www.quantconnect.com itself is EGRESS_BLOCKED, re-confirmed this phase. The free, open-source Lean sample (a DIFFERENT, already-exploited real source) is not affected by this elimination.",
)

ALL_SCORECARDS: tuple[ProviderScorecard, ...] = (
    ORATS_SCORECARD, THETADATA_SCORECARD, DATABENTO_SCORECARD, POLYGON_MASSIVE_SCORECARD,
    CBOE_DATASHOP_SCORECARD, OPTIONMETRICS_SCORECARD, EODHD_SCORECARD, TRADIER_SCORECARD,
    INTRINIO_SCORECARD, QUANTCONNECT_ALGOSEEK_LIVE_SCORECARD,
)


def non_eliminated_scorecards() -> tuple[ProviderScorecard, ...]:
    return tuple(sc for sc in ALL_SCORECARDS if not sc.eliminated)


def ranked_by_total_score() -> tuple[ProviderScorecard, ...]:
    return tuple(sorted(non_eliminated_scorecards(), key=lambda sc: sc.total_score(), reverse=True))
