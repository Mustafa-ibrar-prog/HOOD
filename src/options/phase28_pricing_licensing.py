"""Phase 28, Part 5/6 — pricing and licensing evidence for the 4
non-eliminated finalists (ORATS, ThetaData, Databento, Polygon/Massive).
No new pricing/licensing page was reachable this phase (every vendor
pricing/legal domain remains EGRESS_BLOCKED, re-confirmed) -- every
figure below is `UNVERIFIED_REPORTED`, carried forward from Phase 24/25's
third-party research. Nothing is invented; a gap is left as an explicit
`LICENSING_UNVERIFIED` classification rather than a guessed value.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class PricingEvidenceLevel(enum.Enum):
    """Part 5's exact 2-value vocabulary."""

    VERIFIED_CURRENT = "verified_current"
    UNVERIFIED_REPORTED = "unverified_reported"


class LicensingStatus(enum.Enum):
    """Part 6's explicit fallback value, plus the two positive outcomes a
    real licensing read could produce (neither reached by any provider
    this phase -- every one below is `LICENSING_UNVERIFIED`)."""

    PERMITS_PERSONAL_RESEARCH_CONFIRMED = "permits_personal_research_confirmed"
    RESTRICTS_INTENDED_USE_CONFIRMED = "restricts_intended_use_confirmed"
    LICENSING_UNVERIFIED = "licensing_unverified"


@dataclass(frozen=True)
class PricingRecord:
    provider: str
    monthly_price: str
    annual_price: str
    trial: str
    historical_data_fees: str
    api_fees: str
    download_limits: str
    rate_limits: str
    contract_limits: str
    commercial_restrictions: str
    evidence_level: PricingEvidenceLevel


@dataclass(frozen=True)
class LicensingRecord:
    provider: str
    personal_quantitative_research: str
    local_storage: str
    backtesting: str
    derived_research_results: str
    redistribution_restrictions: str
    commercial_restrictions: str
    api_restrictions: str
    storage_restrictions: str
    derived_data_restrictions: str
    status: LicensingStatus


PRICING_RECORDS: tuple[PricingRecord, ...] = (
    PricingRecord(
        provider="ORATS",
        monthly_price="Reported: Delayed Data API ~$99/mo; Live Data API ~$199/mo; Live Intraday API ~$399/mo (third-party sources, in apparent tension with each other)",
        annual_price="Not found in any source reached any phase",
        trial="A free-trial signup page exists (info.orats.com/free-trial) but is reported to require a credit card before any sample data is issued -- PAID_PROOF_REQUIRED, never pursued (Phase 25)",
        historical_data_fees="Not itemized separately from the tiered monthly figures above in sources reviewed",
        api_fees="Reported request-count caps per tier (e.g. 20,000/100,000/1,000,000 requests) -- not independently confirmed",
        download_limits="Not itemized beyond the request-count caps above",
        rate_limits="Not itemized in sources reviewed any phase",
        contract_limits="Not itemized in sources reviewed any phase",
        commercial_restrictions="Not found in any source reached any phase",
        evidence_level=PricingEvidenceLevel.UNVERIFIED_REPORTED,
    ),
    PricingRecord(
        provider="ThetaData",
        monthly_price="Reported: Standard/real-time tier ~$25/mo (third-party); historical/Value/Pro tier pricing not fully itemized",
        annual_price="Not found in any source reached any phase",
        trial="Reported (third-party, not independently confirmed this phase) to have a free tier without a credit card, but limited to ~30 rolling days of end-of-day data -- insufficient depth for this project's actual research window, and not itself confirmed via a direct probe (docs/pricing pages EGRESS_BLOCKED)",
        historical_data_fees="Not itemized separately in sources reviewed",
        api_fees="Not itemized in sources reviewed",
        download_limits="Not itemized in sources reviewed",
        rate_limits="Not itemized in sources reviewed",
        contract_limits="Not itemized in sources reviewed",
        commercial_restrictions="Not found in any source reached any phase",
        evidence_level=PricingEvidenceLevel.UNVERIFIED_REPORTED,
    ),
    PricingRecord(
        provider="Databento",
        monthly_price="Pay-as-you-go, no flat monthly figure found in sources reviewed",
        annual_price="Not found in any source reached any phase",
        trial="A $125 free-credit pool is described, but is Stripe-gated -- payment information is collected up front even to draw down the free credits (PAID_PROOF_REQUIRED, Phase 25, never pursued)",
        historical_data_fees="Usage-based, described as billed per query/byte -- exact rate not itemized in sources reviewed",
        api_fees="Same usage-based model as historical-data fees; not separately itemized",
        download_limits="Not itemized in sources reviewed",
        rate_limits="Not itemized in sources reviewed",
        contract_limits="Not itemized in sources reviewed",
        commercial_restrictions="Raw OPRA redistribution typically carries exchange-license obligations (a general market fact, not confirmed specifically for Databento's own terms)",
        evidence_level=PricingEvidenceLevel.UNVERIFIED_REPORTED,
    ),
    PricingRecord(
        provider="Polygon.io / Massive",
        monthly_price="Reported: options-specific tiers (Basic/Starter/Developer/Advanced/Business) from ~$29/mo up to ~$399/mo, billed separately from stocks/forex/crypto plans",
        annual_price="Not found in any source reached any phase",
        trial="Not confirmed in sources reviewed any phase",
        historical_data_fees="Bundled into the tiered monthly figures above, per sources reviewed",
        api_fees="Bundled into the tiered monthly figures above",
        download_limits="Not itemized in sources reviewed",
        rate_limits="Tier-dependent, not itemized in sources reviewed",
        contract_limits="Not itemized in sources reviewed",
        commercial_restrictions="Not itemized in sources reviewed",
        evidence_level=PricingEvidenceLevel.UNVERIFIED_REPORTED,
    ),
)


LICENSING_RECORDS: tuple[LicensingRecord, ...] = tuple(
    LicensingRecord(
        provider=p,
        personal_quantitative_research="Not confirmed -- plausible given the product's positioning, never independently verified",
        local_storage="Not confirmed in any source reached any phase",
        backtesting="Not confirmed in any source reached any phase",
        derived_research_results="Not confirmed in any source reached any phase",
        redistribution_restrictions="Not itemized in any source reached any phase",
        commercial_restrictions="Not itemized in any source reached any phase",
        api_restrictions="Not itemized in any source reached any phase",
        storage_restrictions="Not itemized in any source reached any phase",
        derived_data_restrictions="Not itemized in any source reached any phase",
        status=LicensingStatus.LICENSING_UNVERIFIED,
    )
    for p in ("ORATS", "ThetaData", "Databento", "Polygon.io / Massive")
)


def pricing_for(provider: str) -> PricingRecord | None:
    return next((r for r in PRICING_RECORDS if r.provider == provider), None)


def licensing_for(provider: str) -> LicensingRecord | None:
    return next((r for r in LICENSING_RECORDS if r.provider == provider), None)
