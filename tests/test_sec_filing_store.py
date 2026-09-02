"""Phase 16, Part 15A/15E — SEC filing/fact store tests: round-trip
persistence, accession(filing_id) preservation, form classification,
duplicate handling, and Protocol interop. Deterministic fixtures only —
no network call."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.data.sec_filing_store import (
    FORM_PROFILES,
    UNKNOWN_FORM_PROFILE,
    SECFactRecord,
    SECFilingRecord,
    SECFilingStore,
    SECFilingStoreError,
    classify_form,
)
from src.data.store_interfaces import FundamentalStore


def _filing(filing_id="f1", form_type="10-K", filed=date(2022, 10, 28)) -> SECFilingRecord:
    return SECFilingRecord(issuer_symbol="AAPL", filing_id=filing_id, form_type=form_type, description="d", date_filed=filed)


def _fact(filing_id="f1", concept="Assets", value=100.0, end=date(2022, 9, 24), start=None, axises=()) -> SECFactRecord:
    return SECFactRecord(
        issuer_symbol="AAPL", filing_id=filing_id, concept=concept, entity_cik="0000320193", unit="iso4217:USD",
        value=value, period_end=end, period_start=start, axises=axises, date_filed=date(2022, 10, 28),
        retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_filing_round_trip(tmp_path):
    store = SECFilingStore(tmp_path)
    filing = _filing()
    store.save_filings("AAPL", [filing])
    loaded = store.load_filings("AAPL")
    assert loaded == [filing]


def test_filing_id_is_preserved_exactly_not_reformatted(tmp_path):
    """filing_id is a connector UUID, not a real EDGAR accession number
    (see module docstring) -- it must round-trip byte-for-byte, never
    reformatted or truncated."""
    store = SECFilingStore(tmp_path)
    filing = _filing(filing_id="27c07064-a0ab-4224-92ea-2637d8e23c9c")
    store.save_filings("AAPL", [filing])
    assert store.load_filings("AAPL")[0].filing_id == "27c07064-a0ab-4224-92ea-2637d8e23c9c"


def test_fact_round_trip(tmp_path):
    store = SECFilingStore(tmp_path)
    fact = _fact()
    store.save_facts("AAPL", [fact])
    assert store.load_facts("AAPL") == [fact]


def test_duration_vs_instant_fact_distinction(tmp_path):
    instant = _fact(concept="Assets", end=date(2022, 9, 24), start=None)
    duration = _fact(concept="NetIncomeLoss", end=date(2022, 9, 24), start=date(2021, 9, 26))
    assert instant.is_duration_fact is False
    assert duration.is_duration_fact is True


def test_consolidated_vs_dimensional_fact_distinction():
    total = _fact(axises=())
    dimensional = _fact(axises=("ProductOrServiceAxis: IPhoneMember",))
    assert total.is_consolidated_total is True
    assert dimensional.is_consolidated_total is False


def test_save_facts_dedupes_on_natural_key(tmp_path):
    store = SECFilingStore(tmp_path)
    fact_a = _fact(value=100.0)
    fact_b = _fact(value=100.0)  # identical natural key
    store.save_facts("AAPL", [fact_a, fact_b])
    assert len(store.load_facts("AAPL")) == 1


def test_amendment_is_a_separate_filing_never_overwrites_original(tmp_path):
    store = SECFilingStore(tmp_path)
    original = _filing(filing_id="orig", form_type="10-K", filed=date(2022, 10, 28))
    amendment = _filing(filing_id="amend", form_type="10-K/A", filed=date(2022, 12, 1))
    store.save_filings("AAPL", [original, amendment])
    loaded = {f.filing_id: f for f in store.load_filings("AAPL")}
    assert "orig" in loaded and "amend" in loaded  # both present, neither overwritten
    assert loaded["amend"].is_amendment is True
    assert loaded["orig"].is_amendment is False


def test_corrupted_filing_file_raises_not_silently_empty(tmp_path):
    store = SECFilingStore(tmp_path)
    path = tmp_path / "AAPL" / "sec_filings.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json\n")
    with pytest.raises(SECFilingStoreError):
        store.load_filings("AAPL")


def test_classify_form_known_forms():
    assert classify_form("10-K").enters_historical_fact_store is True
    assert classify_form("10-Q").enters_historical_fact_store is True
    assert classify_form("10-K/A").is_amendment is True
    assert classify_form("8-K").contains_structured_facts is False
    assert classify_form("8-K").enters_historical_fact_store is False


def test_classify_form_unknown_form_is_conservative():
    assert classify_form("S-1") == UNKNOWN_FORM_PROFILE
    assert UNKNOWN_FORM_PROFILE.enters_historical_fact_store is False


def test_every_known_form_profile_has_notes_documented():
    for form_type, profile in FORM_PROFILES.items():
        assert profile.notes, f"{form_type} has no documented rationale"


def test_store_load_satisfies_fundamental_store_protocol_shape(tmp_path):
    store = SECFilingStore(tmp_path)
    assert isinstance(store, FundamentalStore)
    store.save_facts("AAPL", [_fact()])
    observations = store.load("AAPL")
    assert len(observations) == 1
    assert observations[0].key == "AAPL"


def test_missing_symbol_returns_empty_not_error(tmp_path):
    store = SECFilingStore(tmp_path)
    assert store.load_filings("ZZZZ") == []
    assert store.load_facts("ZZZZ") == []
