"""Phase 16, Part 15C/15E — point-in-time snapshot engine tests (before/
after filing, same-day conservative handling, amendments, multiple
filings, duplicate observations) and dataset-generation/versioning tests
(different policy/fact-selection produces a different fingerprint,
deterministic hashing). Deterministic fixtures only."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.data.sec_dataset import SECDatasetSpec, generate_asof_instants, generate_sec_fundamentals_asof
from src.data.sec_filing_store import SECFactRecord, SECFilingRecord, SECFilingStore
from src.data.sec_snapshot import get_available_facts, get_available_facts_for_symbol, latest_known_value
from src.data.sec_timestamp_policy import SECCausalPolicy


def _fact(filing_id, concept, value, end, start, date_filed, axises=()) -> SECFactRecord:
    return SECFactRecord(
        issuer_symbol="AAPL", filing_id=filing_id, concept=concept, entity_cik="0000320193", unit="iso4217:USD",
        value=value, period_end=end, period_start=start, axises=axises, date_filed=date_filed,
        retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


REVENUE_CONCEPT = "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_get_available_facts_before_and_after_filing():
    fact = _fact("f1", REVENUE_CONCEPT, 100.0, date(2022, 9, 24), date(2021, 9, 26), date(2022, 10, 28))
    before = get_available_facts([fact], as_of=datetime(2022, 10, 1, tzinfo=timezone.utc))
    after = get_available_facts([fact], as_of=datetime(2022, 10, 29, tzinfo=timezone.utc))
    assert before == []
    assert after == [fact]


def test_get_available_facts_same_day_conservative():
    fact = _fact("f1", REVENUE_CONCEPT, 100.0, date(2022, 9, 24), date(2021, 9, 26), date(2022, 10, 28))
    same_day = get_available_facts([fact], as_of=datetime(2022, 10, 28, 23, 59, tzinfo=timezone.utc))
    assert same_day == []


def test_latest_known_value_picks_most_recent_fiscal_period():
    old = _fact("f1", REVENUE_CONCEPT, 365817000000.0, date(2021, 9, 25), date(2020, 9, 27), date(2021, 10, 29))
    new = _fact("f2", REVENUE_CONCEPT, 394328000000.0, date(2022, 9, 24), date(2021, 9, 26), date(2022, 10, 28))
    result = latest_known_value([old, new], normalized_concept="revenue")
    assert result.value == 394328000000.0


def test_latest_known_value_amendment_tie_break():
    """Two filings reporting the SAME fiscal period (an amendment) --
    the LATER-filed one (the amendment) wins, per Part 5 rule 4."""
    original = _fact("orig", REVENUE_CONCEPT, 394000000000.0, date(2022, 9, 24), date(2021, 9, 26), date(2022, 10, 28))
    amended = _fact("amend", REVENUE_CONCEPT, 394328000000.0, date(2022, 9, 24), date(2021, 9, 26), date(2022, 12, 1))
    result = latest_known_value([original, amended], normalized_concept="revenue")
    assert result.value == 394328000000.0
    assert result.filing_id == "amend"


def test_latest_known_value_ignores_dimensional_facts():
    total = _fact("f1", REVENUE_CONCEPT, 394328000000.0, date(2022, 9, 24), date(2021, 9, 26), date(2022, 10, 28), axises=())
    segment = _fact("f1", REVENUE_CONCEPT, 205489000000.0, date(2022, 9, 24), date(2021, 9, 26), date(2022, 10, 28), axises=("ProductOrServiceAxis: IPhoneMember",))
    result = latest_known_value([total, segment], normalized_concept="revenue")
    assert result.value == 394328000000.0


def test_latest_known_value_returns_none_when_nothing_available():
    assert latest_known_value([], normalized_concept="revenue") is None


def test_multiple_filings_same_concept_all_preserved_in_store(tmp_path):
    """Part 5 rule 7: multiple filings of the same concept must preserve
    their historical sequence -- not collapse into one value."""
    store = SECFilingStore(tmp_path)
    old = _fact("f1", REVENUE_CONCEPT, 365817000000.0, date(2021, 9, 25), date(2020, 9, 27), date(2021, 10, 29))
    new = _fact("f2", REVENUE_CONCEPT, 394328000000.0, date(2022, 9, 24), date(2021, 9, 26), date(2022, 10, 28))
    store.save_facts("AAPL", [old, new])
    loaded = store.load_facts("AAPL")
    assert len(loaded) == 2  # both preserved, not collapsed


def test_get_available_facts_for_symbol_reads_from_store(tmp_path):
    store = SECFilingStore(tmp_path)
    fact = _fact("f1", REVENUE_CONCEPT, 394328000000.0, date(2022, 9, 24), date(2021, 9, 26), date(2022, 10, 28))
    store.save_facts("AAPL", [fact])
    available = get_available_facts_for_symbol(store, "AAPL", as_of=datetime(2022, 11, 1, tzinfo=timezone.utc))
    assert available == [fact]


# --- dataset generation -------------------------------------------------------------------------


def test_generate_asof_instants_monthly():
    spec = SECDatasetSpec(
        universe_name="U", symbols=("AAPL",), start_date=date(2022, 9, 1), end_date=date(2022, 12, 1),
        observation_frequency="monthly", timestamp_policy=SECCausalPolicy.PUBLICATION_DATE_ONLY, filing_forms=("10-K",),
    )
    instants = generate_asof_instants(spec)
    assert [i.date() for i in instants] == [date(2022, 9, 1), date(2022, 10, 1), date(2022, 11, 1), date(2022, 12, 1)]


def test_generate_asof_instants_quarterly():
    spec = SECDatasetSpec(
        universe_name="U", symbols=("AAPL",), start_date=date(2022, 1, 1), end_date=date(2022, 10, 1),
        observation_frequency="quarterly", timestamp_policy=SECCausalPolicy.PUBLICATION_DATE_ONLY, filing_forms=("10-K",),
    )
    instants = generate_asof_instants(spec)
    assert [i.date() for i in instants] == [date(2022, 1, 1), date(2022, 4, 1), date(2022, 7, 1), date(2022, 10, 1)]


def test_generate_sec_fundamentals_asof_never_shows_value_before_filed(tmp_path):
    store = SECFilingStore(tmp_path)
    store.save_filings("AAPL", [SECFilingRecord(issuer_symbol="AAPL", filing_id="f1", form_type="10-K", description="d", date_filed=date(2022, 10, 28))])
    store.save_facts("AAPL", [_fact("f1", REVENUE_CONCEPT, 394328000000.0, date(2022, 9, 24), date(2021, 9, 26), date(2022, 10, 28))])
    spec = SECDatasetSpec(
        universe_name="U", symbols=("AAPL",), start_date=date(2022, 9, 1), end_date=date(2022, 12, 1),
        observation_frequency="monthly", timestamp_policy=SECCausalPolicy.PUBLICATION_DATE_ONLY, filing_forms=("10-K",),
    )
    observations, _ = generate_sec_fundamentals_asof(store, spec, retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
    revenue_obs = {o.as_of.date(): o.value for o in observations if o.normalized_concept == "revenue"}
    assert revenue_obs[date(2022, 9, 1)] is None
    assert revenue_obs[date(2022, 10, 1)] is None  # filed 2022-10-28, so Oct 1 predates it
    assert revenue_obs[date(2022, 11, 1)] == 394328000000.0
    assert revenue_obs[date(2022, 12, 1)] == 394328000000.0


def test_dataset_version_differs_by_timestamp_policy(tmp_path):
    store = SECFilingStore(tmp_path)
    spec_a = SECDatasetSpec(
        universe_name="U", symbols=("AAPL",), start_date=date(2022, 1, 1), end_date=date(2022, 6, 1),
        observation_frequency="monthly", timestamp_policy=SECCausalPolicy.PUBLICATION_DATE_ONLY, filing_forms=("10-K",),
    )
    _, version_a = generate_sec_fundamentals_asof(store, spec_a, retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
    fp_a = version_a.fingerprint()
    fp_b_same_inputs = SECDatasetSpec(
        universe_name="U", symbols=("AAPL",), start_date=date(2022, 1, 1), end_date=date(2022, 6, 1),
        observation_frequency="monthly", timestamp_policy=SECCausalPolicy.PUBLICATION_DATE_ONLY, filing_forms=("10-K",),
    )
    _, version_b = generate_sec_fundamentals_asof(store, fp_b_same_inputs, retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert version_a.fingerprint() == version_b.fingerprint()  # deterministic: identical inputs -> identical fingerprint

    spec_diff_forms = SECDatasetSpec(
        universe_name="U", symbols=("AAPL",), start_date=date(2022, 1, 1), end_date=date(2022, 6, 1),
        observation_frequency="monthly", timestamp_policy=SECCausalPolicy.PUBLICATION_DATE_ONLY, filing_forms=("10-K", "10-Q"),
    )
    _, version_diff_forms = generate_sec_fundamentals_asof(store, spec_diff_forms, retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert version_diff_forms.fingerprint() != fp_a  # different fact-selection scope -> different fingerprint


def test_dataset_version_differs_by_fact_whitelist(tmp_path):
    store = SECFilingStore(tmp_path)
    spec_a = SECDatasetSpec(
        universe_name="U", symbols=("AAPL",), start_date=date(2022, 1, 1), end_date=date(2022, 6, 1),
        observation_frequency="monthly", timestamp_policy=SECCausalPolicy.PUBLICATION_DATE_ONLY, filing_forms=("10-K",),
        fact_whitelist=("revenue",),
    )
    spec_b = SECDatasetSpec(
        universe_name="U", symbols=("AAPL",), start_date=date(2022, 1, 1), end_date=date(2022, 6, 1),
        observation_frequency="monthly", timestamp_policy=SECCausalPolicy.PUBLICATION_DATE_ONLY, filing_forms=("10-K",),
        fact_whitelist=("revenue", "net_income"),
    )
    _, version_a = generate_sec_fundamentals_asof(store, spec_a, retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
    _, version_b = generate_sec_fundamentals_asof(store, spec_b, retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert version_a.fingerprint() != version_b.fingerprint()
