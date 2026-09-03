"""Phase 26, Part 12/15 — dataset persistence: deterministic
fingerprinting, and normalized output that never touches the raw files
it was built from."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from src.options.phase26_dataset_builder import InMemoryLeanSampleStore, build_contract_identity, build_contract_lifecycle, build_provenance
from src.options.phase26_dataset_persistence import DATASET_VERSION, compute_source_fingerprint, write_normalized_dataset
from src.options.phase26_lean_sample_parser import LeanContractFileMeta

RETRIEVAL = datetime(2026, 9, 3, tzinfo=timezone.utc)


def test_fingerprint_is_deterministic_for_identical_bytes(tmp_path):
    d = tmp_path / "zips"
    d.mkdir()
    (d / "a.zip").write_bytes(b"hello world")
    (d / "b.zip").write_bytes(b"other bytes")
    fp1 = compute_source_fingerprint(d)
    fp2 = compute_source_fingerprint(d)
    assert fp1 == fp2
    assert len(fp1) == 64  # sha256 hex digest


def test_fingerprint_changes_when_a_byte_changes(tmp_path):
    d = tmp_path / "zips"
    d.mkdir()
    (d / "a.zip").write_bytes(b"hello world")
    fp1 = compute_source_fingerprint(d)
    (d / "a.zip").write_bytes(b"hello world!")
    fp2 = compute_source_fingerprint(d)
    assert fp1 != fp2


def test_fingerprint_is_order_independent_of_filesystem_listing(tmp_path):
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    (d1 / "z.zip").write_bytes(b"content-z")
    (d1 / "a.zip").write_bytes(b"content-a")
    (d2 / "a.zip").write_bytes(b"content-a")
    (d2 / "z.zip").write_bytes(b"content-z")
    assert compute_source_fingerprint(d1) == compute_source_fingerprint(d2)


def test_write_normalized_dataset_writes_a_manifest_and_one_line_per_contract(tmp_path):
    p = build_provenance(retrieval_timestamp=RETRIEVAL, adjustment_status="x")
    meta = LeanContractFileMeta("AAPL", "call", 100.0, date(2016, 1, 15), "quote", "american", None)
    c = build_contract_identity(meta, p)
    lc = build_contract_lifecycle(meta, [date(2015, 1, 2)], p, today=date(2026, 9, 3))
    store = InMemoryLeanSampleStore(contracts={c.option_id: c}, lifecycles={c.option_id: lc}, quotes={}, trades={}, open_interest={}, underlying={})

    out_path = tmp_path / "normalized.jsonl"
    manifest = write_normalized_dataset(store, out_path, source_fingerprint="deadbeef")

    lines = out_path.read_text().splitlines()
    assert len(lines) == 2  # manifest + 1 contract
    assert json.loads(lines[0]) == manifest
    assert manifest["dataset_version"] == DATASET_VERSION
    assert manifest["source_fingerprint"] == "deadbeef"
    assert manifest["n_contracts"] == 1

    record = json.loads(lines[1])
    assert record["option_id"] == c.option_id
    assert record["multiplier_source_confirmed"] is False
    assert record["lifecycle"]["first_listed_date"] is None


def test_write_normalized_dataset_never_writes_into_the_raw_directory(tmp_path):
    """Part 12: 'do not destroy raw data during normalization.'"""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "original.zip").write_bytes(b"untouched")
    out_path = tmp_path / "normalized_output" / "normalized.jsonl"

    store = InMemoryLeanSampleStore(contracts={}, lifecycles={}, quotes={}, trades={}, open_interest={}, underlying={})
    write_normalized_dataset(store, out_path, source_fingerprint="x")

    assert (raw_dir / "original.zip").read_bytes() == b"untouched"
    assert out_path.exists()
    assert out_path.parent != raw_dir
