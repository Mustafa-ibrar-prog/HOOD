"""Phase 27, Part 5/16 — provider expansion status: exactly one real
source verified by actual data, the rest honestly EGRESS_BLOCKED or
CLAIMED_UNVERIFIED, never silently upgraded."""

from __future__ import annotations

from src.options.phase27_provider_expansion import (
    PROVIDER_EXPANSION_RECORDS,
    ProviderAccessStatus,
    records_by_status,
)


def test_every_record_has_a_valid_status():
    for r in PROVIDER_EXPANSION_RECORDS:
        assert isinstance(r.status, ProviderAccessStatus)


def test_only_one_provider_is_verified_by_actual_data():
    verified = [r for r in PROVIDER_EXPANSION_RECORDS if r.status == ProviderAccessStatus.VERIFIED_BY_ACTUAL_DATA]
    assert len(verified) == 1
    assert "Lean" in verified[0].provider


def test_no_paid_vendor_is_verified_by_actual_data():
    paid_vendor_names = ("ORATS", "ThetaData", "Databento", "Polygon", "Cboe DataShop", "OptionMetrics", "EODHD", "Tradier", "Intrinio", "Alpha Vantage")
    for r in PROVIDER_EXPANSION_RECORDS:
        if any(name in r.provider for name in paid_vendor_names):
            assert r.status != ProviderAccessStatus.VERIFIED_BY_ACTUAL_DATA, r.provider


def test_records_by_status_covers_every_record_exactly_once():
    grouped = records_by_status()
    total = sum(len(v) for v in grouped.values())
    assert total == len(PROVIDER_EXPANSION_RECORDS)


def test_every_record_cites_real_evidence_text():
    for r in PROVIDER_EXPANSION_RECORDS:
        assert len(r.evidence) > 10
