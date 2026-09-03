"""Phase 17, Part 21G/L/M/N — certification-level and dataset
certification tests. CERTIFICATION_TABLE assertions are checked against
the real, evidence-backed table in src/data/sec_certification.py;
certify_sec_fundamentals_asof_dataset is tested with both a real-shaped
passing dataset and deliberately broken fixtures."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.data.sec_certification import (
    CERTIFICATION_BY_CONCEPT,
    CERTIFICATION_TABLE,
    CertificationLevel,
    MissingDataReason,
    certification_for,
    certify_sec_fundamentals_asof_dataset,
    is_safe_for_issuer,
)
from src.data.sec_dataset import SECDatasetSpec, SECFundamentalObservation, generate_sec_fundamentals_asof
from src.data.sec_filing_store import SECFactRecord, SECFilingRecord, SECFilingStore
from src.data.sec_timestamp_policy import SECCausalPolicy
from src.data.versioning import DatasetVersionRecord


# --- certification levels ------------------------------------------------------------------------


def test_revenue_is_fully_certified():
    cert = certification_for("revenue")
    assert cert.level == CertificationLevel.CERTIFIED
    assert all(status == "SAFE_FOR_RESEARCH" for status in cert.per_issuer_status.values())


def test_operating_income_is_conditionally_certified_excluding_jpm():
    cert = certification_for("operating_income")
    assert cert.level == CertificationLevel.CONDITIONALLY_CERTIFIED
    assert cert.per_issuer_status["JPM"] == "MISSING_OR_UNSUPPORTED"
    assert cert.missing_reason["JPM"] == MissingDataReason.SOURCE_DOES_NOT_REPORT_CONCEPT
    assert cert.per_issuer_status["AAPL"] == "SAFE_FOR_RESEARCH"


def test_cash_and_equivalents_is_conditionally_certified_excluding_jpm():
    cert = certification_for("cash_and_equivalents")
    assert cert.level == CertificationLevel.CONDITIONALLY_CERTIFIED
    assert cert.per_issuer_status["JPM"] == "MISSING_OR_UNSUPPORTED"
    assert cert.missing_reason["JPM"] == MissingDataReason.SOURCE_REPORTS_UNDER_DIFFERENT_TAXONOMY


def test_capital_expenditures_only_certified_for_aapl():
    cert = certification_for("capital_expenditures")
    assert cert.level == CertificationLevel.CONDITIONALLY_CERTIFIED
    assert cert.per_issuer_status["AAPL"] == "SAFE_FOR_RESEARCH"
    assert cert.per_issuer_status["MSFT"] == "UNVERIFIED"
    assert cert.per_issuer_status["NVDA"] == "UNVERIFIED"
    assert cert.per_issuer_status["JPM"] == "UNVERIFIED"


def test_no_concept_is_certified_without_being_verified_for_at_least_one_issuer():
    for cert in CERTIFICATION_TABLE:
        assert any(status == "SAFE_FOR_RESEARCH" for status in cert.per_issuer_status.values()), cert.normalized_concept


def test_not_certified_level_is_never_used_without_a_reason():
    for cert in CERTIFICATION_TABLE:
        if cert.level == CertificationLevel.NOT_CERTIFIED:
            assert cert.reason


def test_is_safe_for_issuer():
    assert is_safe_for_issuer("revenue", "JPM") is True
    assert is_safe_for_issuer("operating_income", "JPM") is False
    assert is_safe_for_issuer("operating_income", "AAPL") is True
    assert is_safe_for_issuer("not_a_real_concept", "AAPL") is False


def test_certification_for_unknown_concept_returns_none():
    assert certification_for("not_a_real_concept") is None


def test_every_certified_or_conditional_concept_has_a_nonempty_reason():
    for cert in CERTIFICATION_TABLE:
        assert cert.reason, f"{cert.normalized_concept} has no documented certification reason"


# --- dataset certification -----------------------------------------------------------------------


def _real_shaped_store(tmp_path) -> SECFilingStore:
    store = SECFilingStore(tmp_path)
    store.save_filings("AAPL", [SECFilingRecord(issuer_symbol="AAPL", filing_id="f1", form_type="10-K", description="d", date_filed=date(2022, 10, 28))])
    store.save_facts("AAPL", [SECFactRecord(
        issuer_symbol="AAPL", filing_id="f1", concept="RevenueFromContractWithCustomerExcludingAssessedTax",
        entity_cik="0000320193", unit="iso4217:USD", value=394328000000.0, period_end=date(2022, 9, 24),
        period_start=date(2021, 9, 26), axises=(), date_filed=date(2022, 10, 28),
        retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )])
    return store


def test_dataset_certification_passes_on_real_shaped_data(tmp_path):
    store = _real_shaped_store(tmp_path)
    spec = SECDatasetSpec(
        universe_name="U", symbols=("AAPL",), start_date=date(2022, 9, 1), end_date=date(2023, 1, 1),
        observation_frequency="monthly", timestamp_policy=SECCausalPolicy.PUBLICATION_DATE_ONLY, filing_forms=("10-K",),
    )
    observations, version = generate_sec_fundamentals_asof(store, spec, retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
    result = certify_sec_fundamentals_asof_dataset(observations, version, declared_universe_symbols=("AAPL",))
    assert result.passed is True
    assert all(result.checks.values())


def test_dataset_certification_fails_on_undeclared_issuer(tmp_path):
    store = _real_shaped_store(tmp_path)
    spec = SECDatasetSpec(
        universe_name="U", symbols=("AAPL",), start_date=date(2022, 9, 1), end_date=date(2023, 1, 1),
        observation_frequency="monthly", timestamp_policy=SECCausalPolicy.PUBLICATION_DATE_ONLY, filing_forms=("10-K",),
    )
    observations, version = generate_sec_fundamentals_asof(store, spec, retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
    result = certify_sec_fundamentals_asof_dataset(observations, version, declared_universe_symbols=("MSFT",))  # AAPL not declared
    assert result.passed is False
    assert result.checks["every_issuer_in_declared_universe"] is False


def test_dataset_certification_fails_on_unclassified_concept():
    fake_obs = [SECFundamentalObservation(symbol="AAPL", as_of=datetime(2023, 1, 1, tzinfo=timezone.utc), normalized_concept="not_a_real_concept", value=1.0, fact_period_end=date(2022, 9, 24), fact_date_filed=date(2022, 10, 28))]
    version = DatasetVersionRecord(
        source="test", retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), source_version=None,
        schema_version="s", adjustment_status="a", universe_version="u", fact_selection_version="f", timestamp_policy_version="t",
    )
    result = certify_sec_fundamentals_asof_dataset(fake_obs, version, declared_universe_symbols=("AAPL",))
    assert result.passed is False
    assert result.checks["every_concept_classified"] is False


def test_dataset_certification_fails_on_missing_version_field():
    fake_obs = [SECFundamentalObservation(symbol="AAPL", as_of=datetime(2023, 1, 1, tzinfo=timezone.utc), normalized_concept="revenue", value=1.0, fact_period_end=date(2022, 9, 24), fact_date_filed=date(2022, 10, 28))]
    version = DatasetVersionRecord(
        source="test", retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), source_version=None,
        schema_version="s", adjustment_status="a", universe_version="u", fact_selection_version=None, timestamp_policy_version="t",
    )
    result = certify_sec_fundamentals_asof_dataset(fake_obs, version, declared_universe_symbols=("AAPL",))
    assert result.passed is False
    assert result.checks["dataset_version_present"] is False


def test_dataset_certification_fails_on_publication_policy_violation():
    """A hand-constructed observation whose fact was 'filed' on the same
    date as the as_of instant -- a direct violation of PUBLICATION_DATE_ONLY."""
    bad_obs = [SECFundamentalObservation(symbol="AAPL", as_of=datetime(2022, 10, 28, tzinfo=timezone.utc), normalized_concept="revenue", value=1.0, fact_period_end=date(2022, 9, 24), fact_date_filed=date(2022, 10, 28))]
    version = DatasetVersionRecord(
        source="test", retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), source_version=None,
        schema_version="s", adjustment_status="a", universe_version="u", fact_selection_version="f", timestamp_policy_version="t",
    )
    result = certify_sec_fundamentals_asof_dataset(bad_obs, version, declared_universe_symbols=("AAPL",))
    assert result.passed is False
    assert result.checks["no_publication_policy_violation"] is False


def test_dataset_certification_none_valued_observation_is_not_a_provenance_violation():
    """A None-valued observation (nothing was knowable yet) legitimately
    has no fact_date_filed/fact_period_end -- must NOT be flagged."""
    none_obs = [SECFundamentalObservation(symbol="AAPL", as_of=datetime(2022, 9, 1, tzinfo=timezone.utc), normalized_concept="revenue", value=None, fact_period_end=None, fact_date_filed=None)]
    version = DatasetVersionRecord(
        source="test", retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), source_version=None,
        schema_version="s", adjustment_status="a", universe_version="u", fact_selection_version="f", timestamp_policy_version="t",
    )
    result = certify_sec_fundamentals_asof_dataset(none_obs, version, declared_universe_symbols=("AAPL",))
    assert result.checks["every_observation_has_provenance"] is True
