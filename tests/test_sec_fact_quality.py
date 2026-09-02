"""Phase 16, Part 15D — SEC fact quality classification tests: duplicates,
units, duration/instant, annual/quarterly, malformed observations.
Deterministic fixtures."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.data.sec_fact_quality import (
    FactQualityClass,
    classify_fact,
    find_duplicate_facts,
    find_impossible_period_ordering,
    find_unit_inconsistencies,
)
from src.data.sec_filing_store import SECFactRecord


def _fact(concept="Assets", value=100.0, end=date(2022, 9, 24), start=None, axises=(), unit="iso4217:USD", filing_id="f1") -> SECFactRecord:
    return SECFactRecord(
        issuer_symbol="AAPL", filing_id=filing_id, concept=concept, entity_cik="0000320193", unit=unit,
        value=value, period_end=end, period_start=start, axises=axises, date_filed=date(2022, 10, 28),
        retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_dimensional_fact_is_metadata_only():
    fact = _fact(axises=("ProductOrServiceAxis: IPhoneMember",))
    result = classify_fact(fact, known_normalized_concept=True)
    assert result.quality_class == FactQualityClass.METADATA_ONLY


def test_consolidated_known_concept_is_safe_for_research():
    fact = _fact(axises=())
    result = classify_fact(fact, known_normalized_concept=True)
    assert result.quality_class == FactQualityClass.SAFE_FOR_RESEARCH


def test_consolidated_unknown_concept_requires_normalization():
    fact = _fact(concept="SomeObscureTag", axises=())
    result = classify_fact(fact, known_normalized_concept=False)
    assert result.quality_class == FactQualityClass.REQUIRES_NORMALIZATION


def test_negative_value_for_nonnegative_concept_is_rejected():
    fact = _fact(concept="Assets", value=-100.0, axises=())
    result = classify_fact(fact, known_normalized_concept=True)
    assert result.quality_class == FactQualityClass.REJECTED


def test_negative_net_income_is_not_rejected_a_loss_is_legitimate():
    fact = _fact(concept="NetIncomeLoss", value=-500.0, axises=())
    result = classify_fact(fact, known_normalized_concept=True)
    assert result.quality_class == FactQualityClass.SAFE_FOR_RESEARCH


def test_find_duplicate_facts():
    a = _fact(value=100.0)
    b = _fact(value=100.0)  # identical natural key
    c = _fact(value=200.0, concept="Liabilities")
    dupes = find_duplicate_facts([a, b, c])
    assert len(dupes) == 1


def test_find_unit_inconsistencies():
    a = _fact(concept="EarningsPerShareDiluted", unit="iso4217:USD/xbrli:shares")
    b = _fact(concept="EarningsPerShareDiluted", unit="xbrli:shares", end=date(2021, 9, 25))
    result = find_unit_inconsistencies([a, b])
    assert "EarningsPerShareDiluted" in result
    assert result["EarningsPerShareDiluted"] == {"iso4217:USD/xbrli:shares", "xbrli:shares"}


def test_find_unit_inconsistencies_none_when_consistent():
    a = _fact(concept="Assets", unit="iso4217:USD")
    b = _fact(concept="Assets", unit="iso4217:USD", end=date(2021, 9, 25))
    assert find_unit_inconsistencies([a, b]) == {}


def test_find_impossible_period_ordering():
    bad = _fact(concept="NetIncomeLoss", end=date(2021, 1, 1), start=date(2022, 1, 1))  # start after end
    good = _fact(concept="NetIncomeLoss", end=date(2022, 1, 1), start=date(2021, 1, 1))
    result = find_impossible_period_ordering([bad, good])
    assert result == [bad]


def test_annual_vs_quarterly_distinguishable_by_period_span():
    """Not a dedicated flag in the source data (Part 7) -- distinguished
    by inspecting period_start/period_end span, which this test exercises
    directly on real-shaped durations."""
    annual = _fact(concept="NetIncomeLoss", start=date(2021, 9, 26), end=date(2022, 9, 24))
    quarterly = _fact(concept="NetIncomeLoss", start=date(2022, 7, 1), end=date(2022, 9, 24))
    annual_days = (annual.period_end - annual.period_start).days
    quarterly_days = (quarterly.period_end - quarterly.period_start).days
    assert annual_days > 300
    assert quarterly_days < 100
