"""Phase 29, Part 3/10/17 — ORATS ingestion: verification records, real
fingerprints, and raw/normalized separation."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from src.options.orats_ingest import (
    DATASET_VERSION,
    build_verification_record,
    fingerprint_raw_response,
    ingest_strike_rows,
    write_normalized_dataset,
    write_raw_archive,
)
from src.options.phase26_quality_rules import run_all_quality_checks
from tests.orats_fixtures import SYNTHETIC_AAPL_STRIKES_20211201, SYNTHETIC_AAPL_STRIKES_20211202

RETRIEVAL = datetime(2026, 9, 4, tzinfo=timezone.utc)


def test_ingest_produces_a_contract_per_call_and_put_side():
    store = ingest_strike_rows(SYNTHETIC_AAPL_STRIKES_20211201, retrieval_timestamp=RETRIEVAL, today=date(2026, 9, 4))
    assert len(store.contracts) == 6  # 3 rows x 2 sides
    assert "AAPL_call_150.0000_2022-01-21" in store.contracts
    assert "AAPL_put_150.0000_2022-01-21" in store.contracts


def test_ingest_passes_every_critical_quality_check():
    store = ingest_strike_rows(SYNTHETIC_AAPL_STRIKES_20211201, retrieval_timestamp=RETRIEVAL, today=date(2026, 9, 4))
    flags = run_all_quality_checks(store)
    critical = [f for f in flags if f.severity == "critical"]
    assert critical == []


def test_ingest_multi_day_merges_the_same_contract_correctly():
    rows = SYNTHETIC_AAPL_STRIKES_20211201 + SYNTHETIC_AAPL_STRIKES_20211202
    store = ingest_strike_rows(rows, retrieval_timestamp=RETRIEVAL, today=date(2026, 9, 4))
    cid = "AAPL_call_150.0000_2022-01-21"
    lc = store.lifecycles[cid]
    assert lc.first_observable_date == date(2021, 12, 1)
    assert lc.last_trade_date == date(2021, 12, 2)


def test_fingerprint_is_deterministic():
    fp1 = fingerprint_raw_response(SYNTHETIC_AAPL_STRIKES_20211201)
    fp2 = fingerprint_raw_response(SYNTHETIC_AAPL_STRIKES_20211201)
    assert fp1 == fp2
    assert len(fp1) == 64


def test_fingerprint_changes_with_content():
    fp1 = fingerprint_raw_response(SYNTHETIC_AAPL_STRIKES_20211201)
    fp2 = fingerprint_raw_response(SYNTHETIC_AAPL_STRIKES_20211202)
    assert fp1 != fp2


def test_verification_record_has_every_part3_required_field():
    rec = build_verification_record(
        SYNTHETIC_AAPL_STRIKES_20211201, product="Delayed Data API",
        query_params={"tickers": "AAPL", "tradeDate": "2021-12-01"},
        retrieval_timestamp=RETRIEVAL, underlying="AAPL", actually_returned_by_provider=False,
    )
    assert rec.provider == "ORATS"
    assert rec.contract_count == 3
    assert len(rec.fields_returned) > 0
    assert len(rec.raw_response_fingerprint) == 64
    assert rec.actually_returned_by_provider is False


def test_verification_record_never_defaults_actually_returned_to_true():
    """Must be explicitly passed -- no default that could silently
    claim real provider data."""
    import inspect
    sig = inspect.signature(build_verification_record)
    assert sig.parameters["actually_returned_by_provider"].default is inspect.Parameter.empty


def test_write_raw_archive_is_immutable(tmp_path):
    path = tmp_path / "raw.json"
    fp = write_raw_archive(SYNTHETIC_AAPL_STRIKES_20211201, path)
    assert path.exists()
    assert len(fp) == 64
    with pytest.raises(FileExistsError):
        write_raw_archive(SYNTHETIC_AAPL_STRIKES_20211202, path)


def test_write_normalized_dataset_never_touches_the_raw_file(tmp_path):
    raw_path = tmp_path / "raw" / "raw.json"
    write_raw_archive(SYNTHETIC_AAPL_STRIKES_20211201, raw_path)
    original_bytes = raw_path.read_bytes()

    store = ingest_strike_rows(SYNTHETIC_AAPL_STRIKES_20211201, retrieval_timestamp=RETRIEVAL, today=date(2026, 9, 4))
    norm_path = tmp_path / "normalized" / "normalized.jsonl"
    manifest = write_normalized_dataset(store, norm_path, source_fingerprint="deadbeef")

    assert raw_path.read_bytes() == original_bytes
    assert manifest["dataset_version"] == DATASET_VERSION
    assert manifest["provider"] == "orats"
    lines = norm_path.read_text().splitlines()
    assert len(lines) == 1 + len(store.contracts)
    first_record = json.loads(lines[1])
    assert first_record["multiplier_source_confirmed"] is False
