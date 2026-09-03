"""Phase 17, Part 21E/F — instant/duration semantics and annual/quarterly
period-span classification tests. Boundary values are drawn from real
AAPL data (90-day quarter, 279-day 9-month YTD, 363-day fiscal year --
see sec_period_semantics.py's module docstring)."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.data.sec_filing_store import SECFactRecord
from src.data.sec_period_semantics import (
    DurationSpanClass,
    FactPeriodKind,
    actual_period_kind,
    classify_duration_span,
    select_by_span,
    validate_period_kind,
)


def _fact(concept, end, start=None) -> SECFactRecord:
    return SECFactRecord(
        issuer_symbol="AAPL", filing_id="f1", concept=concept, entity_cik="0000320193", unit="iso4217:USD",
        value=1.0, period_end=end, period_start=start, axises=(), date_filed=date(2022, 10, 28),
        retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


# --- instant vs duration --------------------------------------------------------------------------


def test_actual_period_kind_instant():
    fact = _fact("Assets", date(2022, 9, 24))
    assert actual_period_kind(fact) == FactPeriodKind.INSTANT


def test_actual_period_kind_duration():
    fact = _fact("NetIncomeLoss", date(2022, 9, 24), date(2021, 9, 26))
    assert actual_period_kind(fact) == FactPeriodKind.DURATION


def test_validate_period_kind_accepts_correct_instant():
    fact = _fact("Assets", date(2022, 9, 24))
    ok, _ = validate_period_kind(fact, normalized_concept="total_assets")
    assert ok is True


def test_validate_period_kind_accepts_correct_duration():
    fact = _fact("NetIncomeLoss", date(2022, 9, 24), date(2021, 9, 26))
    ok, _ = validate_period_kind(fact, normalized_concept="net_income")
    assert ok is True


def test_validate_period_kind_rejects_instant_fact_for_duration_concept():
    """A malformed 'revenue' fact with no period_start (i.e. shaped like
    an instant fact) must be rejected, not silently accepted."""
    malformed = _fact("RevenueFromContractWithCustomerExcludingAssessedTax", date(2022, 9, 24))  # no start_date
    ok, reason = validate_period_kind(malformed, normalized_concept="revenue")
    assert ok is False
    assert "duration" in reason


def test_validate_period_kind_rejects_duration_fact_for_instant_concept():
    malformed = _fact("Assets", date(2022, 9, 24), date(2021, 9, 26))  # Assets should never have a start_date
    ok, reason = validate_period_kind(malformed, normalized_concept="total_assets")
    assert ok is False
    assert "instant" in reason


def test_validate_period_kind_unknown_concept_is_not_silently_valid():
    fact = _fact("SomeTag", date(2022, 9, 24))
    ok, reason = validate_period_kind(fact, normalized_concept="not_a_real_concept")
    assert ok is False
    assert "no known instant/duration expectation" in reason


# --- annual/quarterly span classification -----------------------------------------------------


def test_classify_duration_span_quarterly_real_boundary():
    assert classify_duration_span(date(2023, 4, 2), date(2023, 7, 1)) == DurationSpanClass.QUARTERLY  # 90 days, real AAPL Q3 FY2023


def test_classify_duration_span_nine_month_ytd_real_boundary():
    assert classify_duration_span(date(2022, 9, 25), date(2023, 7, 1)) == DurationSpanClass.NINE_MONTH_YTD  # 279 days, real AAPL 9mo YTD FY2023


def test_classify_duration_span_annual_real_boundary():
    assert classify_duration_span(date(2021, 9, 26), date(2022, 9, 24)) == DurationSpanClass.ANNUAL  # 363 days, real AAPL FY2022


def test_classify_duration_span_semiannual():
    assert classify_duration_span(date(2022, 1, 1), date(2022, 6, 20)) == DurationSpanClass.SEMIANNUAL_YTD  # 170 days


def test_classify_duration_span_other_for_odd_span():
    assert classify_duration_span(date(2022, 1, 1), date(2022, 1, 15)) == DurationSpanClass.OTHER  # 14 days -- not a recognized fiscal span


def test_classify_duration_span_instant_fact_is_other():
    assert classify_duration_span(None, date(2022, 9, 24)) == DurationSpanClass.OTHER


def test_select_by_span_disambiguates_quarterly_from_ytd():
    """The real AAPL Q3 FY2023 10-Q scenario: same concept, same filing,
    two different spans -- select_by_span must pick only the requested
    one."""
    quarterly = _fact("RevenueFromContractWithCustomerExcludingAssessedTax", date(2023, 7, 1), date(2023, 4, 2))
    ytd = _fact("RevenueFromContractWithCustomerExcludingAssessedTax", date(2023, 7, 1), date(2022, 9, 25))
    result = select_by_span([quarterly, ytd], span=DurationSpanClass.QUARTERLY)
    assert result == [quarterly]
    result_ytd = select_by_span([quarterly, ytd], span=DurationSpanClass.NINE_MONTH_YTD)
    assert result_ytd == [ytd]
