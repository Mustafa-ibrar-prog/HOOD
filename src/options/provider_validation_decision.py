"""Phase 25, Parts 26/27 — the final decision and (if warranted) the
purchase recommendation. Deciding, never purchasing: Part 27 is explicit
that any recommendation here "requires human approval" and must never be
auto-acted-upon -- nothing in this module creates an account, stores a
credential, or spends money (enforced by tests/test_phase25_safety.py,
mirroring Phase 24's identical guard).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class FinalDecision(enum.Enum):
    """Part 26's exact, fixed 5-value vocabulary."""

    ORATS_VERIFIED_RESEARCH_READY = "orats_verified_research_ready"
    ORATS_PROMISING_BUT_UNVERIFIED = "orats_promising_but_unverified"
    ALTERNATIVE_PROVIDER_VERIFIED = "alternative_provider_verified"
    NO_PROVIDER_VERIFIED = "no_provider_verified"
    HISTORICAL_OPTIONS_DATA_STILL_INSUFFICIENT = "historical_options_data_still_insufficient"


# ORATS's evidence this phase is real and materially stronger than Phase 24's
# (open-source client library schema vs. pure marketing/third-party summary),
# but no live API call, no real response payload, and no independently-confirmed
# depth/methodology/licensing figure was ever obtained (PAID_PROOF_REQUIRED
# stopped direct testing at the credit-card-gated free trial) -- this is the
# textbook shape of ORATS_PROMISING_BUT_UNVERIFIED, not
# ORATS_VERIFIED_RESEARCH_READY (which would require a real sample/live probe)
# and not NO_PROVIDER_VERIFIED (which would understate the real evidence
# gathered this phase).
FINAL_DECISION = FinalDecision.ORATS_PROMISING_BUT_UNVERIFIED

FINAL_DECISION_RATIONALE = (
    "ORATS's field-level schema is now backed by real, independently-fetched open-source client library "
    "source code (FyZyX/orats-python), confirming a genuinely richer and more transparent field set than "
    "any provider in Phase 24's scorecard, plus a real trade_date-scoped historical query mechanism -- a "
    "meaningfully stronger practical PIT tool than Robinhood's own capability. However, ORATS's own official "
    "documentation and pricing pages were EGRESS_BLOCKED this phase, its free trial requires a credit card "
    "(PAID_PROOF_REQUIRED, per Part 2), and no live API call, real response payload, historical-depth "
    "reconfirmation, methodology detail, or licensing term was ever independently obtained. Every field in "
    "the Part 4 matrix is CLAIMED_AVAILABLE_UNVERIFIED or UNKNOWN -- never VERIFIED_AVAILABLE. A single "
    "bounded comparison against ThetaData (Part 19) found its official docs equally EGRESS_BLOCKED and its "
    "actively-maintained client library deprecated in favor of an undocumented-from-here REST API, so ORATS "
    "remains the strongest available candidate without displacing the UNVERIFIED qualifier."
)


@dataclass(frozen=True)
class PurchaseRecommendation:
    """Part 27's exact required fields. `awaiting_human_approval` is
    always True by construction here -- this codebase does not, and
    structurally cannot via this dataclass, mark a recommendation as
    acted upon."""

    recommended_provider: str
    exact_product: str
    why: str
    fields_available: str
    historical_depth: str
    approximate_cost: str
    trial_availability: str
    licensing: str
    expected_research_gain: str
    awaiting_human_approval: bool = True

    def __post_init__(self):
        if not self.awaiting_human_approval:
            raise ValueError("A PurchaseRecommendation must always await human approval.")


PURCHASE_RECOMMENDATION = PurchaseRecommendation(
    recommended_provider="ORATS",
    exact_product="Delayed Data API (reported ~$99/mo tier) -- the entry tier sufficient to validate the "
                   "field matrix in Part 4 before considering the pricier Live/Intraday tiers.",
    why="Of every source evaluated across Phase 24 and Phase 25, ORATS is the only one with (a) a real, "
        "independently-fetched field-level schema (not just marketing prose), (b) an explicit historical "
        "trade_date query mechanism structurally suited to this project's PIT chain-reconstruction need, and "
        "(c) dedicated endpoints for dividends/splits/earnings that directly support this project's existing "
        "corporate-action and earnings research (Phases 9/13).",
    fields_available="See src.options.provider_field_validation.ORATS_FIELD_VALIDATION_MATRIX -- contract "
                      "identity (partial), underlying OHLC (adjusted+unadjusted), bid/ask+sizes, volume, "
                      "open interest, IV (raw+bid/mid/ask+21-point delta smile), IV rank/percentile, full "
                      "Greeks, historical volatility (11 windows), dividends, splits, earnings -- every field "
                      "CLAIMED_AVAILABLE_UNVERIFIED pending a real API key.",
    historical_depth="Reported (unverified, orats.com itself EGRESS_BLOCKED both phases): near-EOD since "
                      "2007, 1-minute intraday since August 2020.",
    approximate_cost="Reported (unverified, in apparent tension across third-party sources): $99/mo "
                      "(Delayed Data API) to $399/mo (Live Intraday API); a $29 14-day trial reported in one "
                      "source, in tension with a separate report that the free trial requires a credit card.",
    trial_availability="PAID_PROOF_REQUIRED -- the free-trial signup found this phase "
                        "(info.orats.com/free-trial) is reported to require a credit card before any sample "
                        "data is issued. No trial was started this phase.",
    licensing="UNKNOWN -- not found in any source reached this phase; must be confirmed in writing before "
              "any purchase, given this project's automated-trading intent (Part 18).",
    expected_research_gain="Would let this project move from its current Phase 19-24 hand-selected, "
                            "2-3-strikes-per-underlying OHLC panel to a genuine multi-year, full-chain, "
                            "bid/ask+volume+OI+IV+Greeks research dataset -- directly unblocking every "
                            "P22/P23-style hypothesis that was previously INHERITED_FROM_UNDERLYING purely "
                            "for lack of real option-specific historical fields.",
)
