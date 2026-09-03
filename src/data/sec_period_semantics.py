"""Phase 17, Parts 8-9 — instant/duration semantics and annual/quarterly
period-span classification.

REAL PROBE EVIDENCE driving this module: AAPL's Q3 FY2023 10-Q (filing_id
f0c81217-...) reports the SAME concept (RevenueFromContractWithCustomer-
ExcludingAssessedTax, NetIncomeLoss, OperatingIncomeLoss), for the SAME
filing, as BOTH a standalone-quarter duration fact (period
2023-04-02/2023-07-01, ~90 days, axises=()) AND a year-to-date duration
fact (period 2022-09-25/2023-07-01, ~279 days, axises=()) -- confirmed
concretely: Q3-standalone revenue=81,797,000,000 vs 9-month-YTD
revenue=293,787,000,000 (both real, both axises=(), both present in the
same get_sec_filing_facts response). This means Part 9's derivation
concern ("if a quarterly value must be derived from a YTD value...") does
NOT apply to this data source for the periods probed -- the source
already supplies genuine standalone-quarter facts directly. It does NOT
mean querying "the fact for this concept at this period_end" is safe
without a span check, since more than one duration fact can share the
same period_end with different period_start (and therefore different
values) -- that disambiguation is this module's job. No YTD-minus-prior-
quarter derivation is implemented anywhere in this codebase; Part 9
"prefer raw source facts over derived facts" is honored by construction
(there is no derivation code path at all).

Instant-vs-duration semantics (Part 8): confirmed real balance-sheet
facts (Assets/Liabilities/StockholdersEquity/CashAndCashEquivalents) are
always INSTANT (period_start is always None; end_date always present) and
income-statement/cash-flow facts (revenue/operating_income/net_income/
operating_cash_flow/capital_expenditures/diluted_eps) are always DURATION
(both start_date and end_date present) -- confirmed across every real
fact ingested in Phase 16 and Phase 17. This module makes that pairing
explicit and validates against it.
"""

from __future__ import annotations

import enum
from datetime import date, timedelta

from src.data.sec_filing_store import SECFactRecord


class FactPeriodKind(enum.Enum):
    INSTANT = "instant"
    DURATION = "duration"


class DurationSpanClass(enum.Enum):
    """Classifies a duration fact's period_start..period_end span by
    length, so a caller can pick "the standalone quarter" vs "the 9-month
    YTD figure" vs "the full fiscal year" for the same concept and
    period_end, rather than getting whichever one a naive lookup happens
    to return first. Boundaries are generous (+/- a few days) to tolerate
    real fiscal-calendar variation (AAPL's ~13-week quarters, JPM's
    calendar-month quarters, etc. all land inside these windows in every
    real period this phase observed)."""

    QUARTERLY = "quarterly"  # ~1 fiscal quarter, ~80-100 days
    SEMIANNUAL_YTD = "semiannual_ytd"  # ~2 quarters YTD, ~170-190 days
    NINE_MONTH_YTD = "nine_month_ytd"  # ~3 quarters YTD, ~260-285 days
    ANNUAL = "annual"  # ~1 fiscal year, ~350-380 days
    OTHER = "other"  # anything outside the above windows -- not silently guessed


# (normalized_concept -> expected FactPeriodKind), built from real, observed data only.
EXPECTED_PERIOD_KIND: dict[str, FactPeriodKind] = {
    "total_assets": FactPeriodKind.INSTANT,
    "total_liabilities": FactPeriodKind.INSTANT,
    "stockholders_equity": FactPeriodKind.INSTANT,
    "cash_and_equivalents": FactPeriodKind.INSTANT,
    "revenue": FactPeriodKind.DURATION,
    "operating_income": FactPeriodKind.DURATION,
    "net_income": FactPeriodKind.DURATION,
    "diluted_eps": FactPeriodKind.DURATION,
    "operating_cash_flow": FactPeriodKind.DURATION,
    "capital_expenditures": FactPeriodKind.DURATION,
}


def actual_period_kind(fact: SECFactRecord) -> FactPeriodKind:
    return FactPeriodKind.DURATION if fact.is_duration_fact else FactPeriodKind.INSTANT


def validate_period_kind(fact: SECFactRecord, *, normalized_concept: str) -> tuple[bool, str]:
    """Part 8: reject a fact whose instant/duration shape doesn't match
    what this normalized concept is known to be. Returns
    (is_valid, reason). A concept with no known expectation (not in
    EXPECTED_PERIOD_KIND) is reported, never silently assumed either
    way."""
    expected = EXPECTED_PERIOD_KIND.get(normalized_concept)
    if expected is None:
        return False, f"no known instant/duration expectation for normalized_concept={normalized_concept!r}"
    actual = actual_period_kind(fact)
    if actual != expected:
        return False, f"expected {expected.value} for {normalized_concept!r} but fact is {actual.value} (period_start={fact.period_start}, period_end={fact.period_end})"
    return True, "matches expected instant/duration shape"


def classify_duration_span(period_start: date | None, period_end: date) -> DurationSpanClass:
    """Classifies a duration fact by span length. Returns OTHER for an
    instant fact (period_start is None) -- callers should check
    is_duration_fact first; this function does not raise, since a
    quality report needs to be able to classify malformed input too."""
    if period_start is None:
        return DurationSpanClass.OTHER
    days = (period_end - period_start).days
    if 80 <= days <= 100:
        return DurationSpanClass.QUARTERLY
    if 170 <= days <= 190:
        return DurationSpanClass.SEMIANNUAL_YTD
    if 260 <= days <= 285:
        return DurationSpanClass.NINE_MONTH_YTD
    if 350 <= days <= 380:
        return DurationSpanClass.ANNUAL
    return DurationSpanClass.OTHER


def select_by_span(facts: list[SECFactRecord], *, span: DurationSpanClass) -> list[SECFactRecord]:
    """Filters a list of same-concept duration facts down to only those
    matching `span` -- the disambiguation primitive a caller needs before
    trusting "the" value for a (concept, period_end) pair, given a single
    filing can report both a standalone-quarter and a YTD figure for the
    same concept (real, confirmed AAPL Q3 FY2023 10-Q finding, see module
    docstring)."""
    return [f for f in facts if f.is_duration_fact and classify_duration_span(f.period_start, f.period_end) == span]
