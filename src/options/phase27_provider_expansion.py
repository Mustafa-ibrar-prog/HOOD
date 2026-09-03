"""Phase 27, Part 5 — provider expansion status. Reconfirms (does not
merely assume) Phase 24/25/26's network-egress findings by directly
re-testing 2 representative domains this phase, plus reports the ONE
genuinely new, actually-accessed real source (QuantConnect/Lean's wider
directory tree -- Part 4/7's expansion).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class ProviderAccessStatus(enum.Enum):
    """Part 5's exact 3-value vocabulary."""

    EGRESS_BLOCKED = "egress_blocked"
    CLAIMED_UNVERIFIED = "claimed_unverified"
    VERIFIED_BY_ACTUAL_DATA = "verified_by_actual_data"


@dataclass(frozen=True)
class ProviderExpansionRecord:
    provider: str
    status: ProviderAccessStatus
    evidence: str


PROVIDER_EXPANSION_RECORDS: tuple[ProviderExpansionRecord, ...] = (
    ProviderExpansionRecord(
        "ORATS", ProviderAccessStatus.EGRESS_BLOCKED,
        "docs.orats.com re-tested this phase via WebFetch -- still EGRESS_BLOCKED, identical to Phase 24/25/26. No new access attempted or found.",
    ),
    ProviderExpansionRecord(
        "Polygon/Massive", ProviderAccessStatus.EGRESS_BLOCKED,
        "polygon.io re-tested this phase via WebFetch -- still EGRESS_BLOCKED.",
    ),
    ProviderExpansionRecord(
        "ThetaData", ProviderAccessStatus.EGRESS_BLOCKED,
        "Carried over from Phase 25/26 (docs.thetadata.us / http-docs.thetadata.us both EGRESS_BLOCKED); not re-tested this phase, no reason to expect a change given the two domains re-tested above are unchanged.",
    ),
    ProviderExpansionRecord(
        "Databento", ProviderAccessStatus.EGRESS_BLOCKED,
        "Carried over from Phase 25 (databento.com EGRESS_BLOCKED); not re-tested this phase.",
    ),
    ProviderExpansionRecord(
        "Cboe DataShop", ProviderAccessStatus.EGRESS_BLOCKED,
        "Carried over from Phase 26 (datashop.cboe.com EGRESS_BLOCKED); not re-tested this phase.",
    ),
    ProviderExpansionRecord(
        "OptionMetrics", ProviderAccessStatus.CLAIMED_UNVERIFIED,
        "Institutional/WRDS-distributed; domain never directly tested any phase (known to require an institutional subscription/WRDS access this project does not have) -- status carried over from Phase 24's scorecard as CLAIMED_UNVERIFIED, not re-investigated.",
    ),
    ProviderExpansionRecord(
        "EODHD", ProviderAccessStatus.EGRESS_BLOCKED,
        "Carried over from Phase 26 (eodhd.com EGRESS_BLOCKED); not re-tested this phase.",
    ),
    ProviderExpansionRecord(
        "Tradier", ProviderAccessStatus.EGRESS_BLOCKED,
        "Carried over from Phase 26 (tradier.com EGRESS_BLOCKED); not re-tested this phase.",
    ),
    ProviderExpansionRecord(
        "Intrinio", ProviderAccessStatus.EGRESS_BLOCKED,
        "Carried over from Phase 26 (intrinio.com EGRESS_BLOCKED); not re-tested this phase.",
    ),
    ProviderExpansionRecord(
        "QuantConnect/AlgoSeek (LIVE platform/API, distinct from the open-source Lean repository)",
        ProviderAccessStatus.EGRESS_BLOCKED,
        "www.quantconnect.com (the live platform, requiring an account) EGRESS_BLOCKED, carried over from Phase 26. NOT the same as the source this phase actually used.",
    ),
    ProviderExpansionRecord(
        "QuantConnect/Lean (open-source GitHub repository -- the ACTUAL source this phase used)",
        ProviderAccessStatus.VERIFIED_BY_ACTUAL_DATA,
        "37 additional real files fetched and ingested this phase (FOXA/GOOG/NWSA/TWX daily options, real "
        "multi-day GOOG/AAPL/FOXA/NWSA/TWX minute options, 3 paired underlying equity files) -- see "
        "scripts/phase27_step0_fetch_expansion_sample.py for the exact real URLs and byte counts.",
    ),
    ProviderExpansionRecord(
        "Alpha Vantage", ProviderAccessStatus.EGRESS_BLOCKED,
        "Carried over from Phase 26 (alphavantage.co EGRESS_BLOCKED); not re-tested this phase.",
    ),
)


def records_by_status() -> dict[ProviderAccessStatus, list[str]]:
    out: dict[ProviderAccessStatus, list[str]] = {}
    for r in PROVIDER_EXPANSION_RECORDS:
        out.setdefault(r.status, []).append(r.provider)
    return out
