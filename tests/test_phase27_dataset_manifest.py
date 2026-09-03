"""Phase 27, Part 11/16 — the canonical dataset manifest: every field
populated, licensing and provider correctly recorded, known limitations
honestly listed."""

from __future__ import annotations

from src.options.phase27_dataset_manifest import build_manifest_entry


def test_manifest_entry_has_every_required_field_populated():
    entry = build_manifest_entry(
        contract_count=7358, contract_day_count=12345, underlyings=("AAPL", "SPY", "GOOG"),
        date_range="2013-2016, 2023-08-03", sha256_fingerprint="abc123", retrieval_date="2026-09-03",
    )
    for field_name in (
        "provider", "product", "dataset_version", "source_url_or_repository", "license", "retrieval_date",
        "date_range", "resolution", "pit_status", "execution_grade", "quality_score",
    ):
        value = getattr(entry, field_name)
        assert isinstance(value, str) and len(value) > 0, field_name


def test_manifest_records_apache_license():
    entry = build_manifest_entry(contract_count=1, contract_day_count=1, underlyings=("AAPL",),
                                  date_range="x", sha256_fingerprint="x", retrieval_date="2026-09-03")
    assert "Apache" in entry.license


def test_manifest_records_known_limitations_including_missing_target_underlyings():
    entry = build_manifest_entry(contract_count=1, contract_day_count=1, underlyings=("AAPL",),
                                  date_range="x", sha256_fingerprint="x", retrieval_date="2026-09-03")
    joined = " ".join(entry.known_limitations)
    assert "NVDA" in joined
    assert "TSLA" in joined
    assert "IV/Greeks" in joined


def test_manifest_preserves_the_real_fingerprint_and_counts_passed_in():
    entry = build_manifest_entry(contract_count=42, contract_day_count=99, underlyings=("AAPL", "SPY"),
                                  date_range="2013-2016", sha256_fingerprint="deadbeef", retrieval_date="2026-09-03")
    assert entry.contract_count == 42
    assert entry.contract_day_count == 99
    assert entry.sha256_fingerprint == "deadbeef"
    assert entry.underlyings == ("AAPL", "SPY")
