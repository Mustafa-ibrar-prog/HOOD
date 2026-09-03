"""Phase 25, Part 23 — a FUTURE 15-point data quality certification
specification. This module DEFINES the spec only; it does not assess,
score, or certify ORATS or any other provider against it (Part 23's
explicit "design a specification, do not implement" instruction). No
`CertificationResult` instances exist anywhere in this repository yet --
that is deliberate, and is enforced by
tests/test_options_data_quality_certification.py.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class CertificationStatus(enum.Enum):
    """The only status any provider may carry today. A future phase that
    actually purchases and tests a provider is the one allowed to
    introduce CERTIFIED/PARTIALLY_CERTIFIED/FAILED results -- not this
    one."""

    NOT_YET_ASSESSED = "not_yet_assessed"


@dataclass(frozen=True)
class CertificationCriterion:
    criterion_id: str
    title: str
    description: str


DATA_QUALITY_CERTIFICATION_SPEC: tuple[CertificationCriterion, ...] = (
    CertificationCriterion(
        "DQC-01", "Point-in-time chain completeness",
        "For a sample of historical dates, the provider's chain-as-of-date matches an independent "
        "reconstruction (e.g. cross-checked against a second source or known corporate-action calendar) "
        "within a documented tolerance.",
    ),
    CertificationCriterion(
        "DQC-02", "Expired-contract coverage depth",
        "The provider's earliest queryable expired contract per underlying is directly confirmed via a "
        "live probe, not inferred from a query-parameter design.",
    ),
    CertificationCriterion(
        "DQC-03", "Bid/ask presence and snapshot timing",
        "Historical bid/ask fields are populated for a statistically meaningful fraction of sampled "
        "contract-days, and the exact intraday snapshot time (or continuous-tick nature) is documented.",
    ),
    CertificationCriterion(
        "DQC-04", "Quote staleness bound",
        "A documented maximum age for any 'as of' quote/greeks value -- no silently stale value presented "
        "as current.",
    ),
    CertificationCriterion(
        "DQC-05", "Volume/open-interest internal consistency",
        "Volume and open-interest series pass basic sanity checks (non-negative, OI roll-forward "
        "consistency around expiration) across a sampled window.",
    ),
    CertificationCriterion(
        "DQC-06", "IV methodology disclosure",
        "The provider states (in its own documentation, confirmed via a live account) the option-pricing "
        "model, interest-rate source, and dividend treatment used to compute IV.",
    ),
    CertificationCriterion(
        "DQC-07", "Greeks methodology disclosure",
        "Same as DQC-06, specifically for delta/gamma/theta/vega/rho -- including whether Greeks are "
        "computed per-contract or smile-fitted.",
    ),
    CertificationCriterion(
        "DQC-08", "Corporate-action adjustment transparency",
        "Split/dividend adjustment methodology for both the underlying OHLC series and any option-implied "
        "fields is documented and testable against a known historical split/dividend event.",
    ),
    CertificationCriterion(
        "DQC-09", "Survivorship-bias freedom",
        "Delisted/expired/merged-away underlyings remain queryable for their full historical window -- "
        "confirmed via a live probe against at least one known delisted name, not assumed from vendor "
        "positioning.",
    ),
    CertificationCriterion(
        "DQC-10", "Contract identity completeness",
        "Every contract record carries underlying, strike, expiration, right, multiplier, and exercise "
        "style -- none silently defaulted.",
    ),
    CertificationCriterion(
        "DQC-11", "Timestamp and timezone clarity",
        "Every timestamp field's timezone and exchange-session convention (e.g. is a 'trade_date' field "
        "the US/Eastern session date) is explicitly documented, not assumed.",
    ),
    CertificationCriterion(
        "DQC-12", "Data revision policy disclosure",
        "The provider states whether historical values are ever silently revised/restated after initial "
        "publication, and if so, whether prior versions remain accessible.",
    ),
    CertificationCriterion(
        "DQC-13", "Sample validation against an independent source",
        "A sample of the provider's historical option prices/Greeks is cross-checked against at least one "
        "independently obtained real observation (e.g. this project's own Robinhood-sourced OHLC panel "
        "for overlapping dates/contracts) and the discrepancy is quantified, not merely asserted absent.",
    ),
    CertificationCriterion(
        "DQC-14", "Licensing and redistribution clarity",
        "The provider's terms explicitly cover automated-trading use and this project's specific "
        "redistribution/storage pattern (a locally persisted research dataset) -- confirmed in writing, "
        "not inferred.",
    ),
    CertificationCriterion(
        "DQC-15", "API reliability and rate-limit documentation",
        "Documented uptime/rate-limit/error-handling behavior is confirmed against real, sustained usage "
        "(not a single successful call) before the provider is relied on for ongoing research.",
    ),
)


def criterion_ids() -> tuple[str, ...]:
    return tuple(c.criterion_id for c in DATA_QUALITY_CERTIFICATION_SPEC)
