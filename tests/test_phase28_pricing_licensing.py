"""Phase 28, Part 5/6/17 — pricing and licensing evidence classification."""

from __future__ import annotations

from src.options.phase28_pricing_licensing import (
    LICENSING_RECORDS,
    PRICING_RECORDS,
    LicensingStatus,
    PricingEvidenceLevel,
    licensing_for,
    pricing_for,
)


def test_four_finalists_have_pricing_records():
    providers = {r.provider for r in PRICING_RECORDS}
    assert providers == {"ORATS", "ThetaData", "Databento", "Polygon.io / Massive"}


def test_four_finalists_have_licensing_records():
    providers = {r.provider for r in LICENSING_RECORDS}
    assert providers == {"ORATS", "ThetaData", "Databento", "Polygon.io / Massive"}


def test_no_pricing_record_is_verified_current():
    """No vendor pricing page was reachable this phase -- every figure
    must honestly be UNVERIFIED_REPORTED."""
    for r in PRICING_RECORDS:
        assert r.evidence_level == PricingEvidenceLevel.UNVERIFIED_REPORTED


def test_every_licensing_record_is_unverified():
    for r in LICENSING_RECORDS:
        assert r.status == LicensingStatus.LICENSING_UNVERIFIED


def test_no_pricing_figure_is_invented_as_a_bare_number():
    """Every pricing field must carry hedging/sourcing language, never a
    bare unqualified dollar figure presented as fact."""
    hedge_words = ("report", "claim", "not found", "not itemized", "not confirmed", "described", "no flat")
    for r in PRICING_RECORDS:
        for field_name in ("monthly_price", "annual_price", "trial"):
            value = getattr(r, field_name).lower()
            assert any(w in value for w in hedge_words), f"{r.provider}.{field_name} reads as unhedged fact: {value!r}"


def test_pricing_for_and_licensing_for_lookups_work():
    assert pricing_for("ORATS") is not None
    assert pricing_for("NoSuchProvider") is None
    assert licensing_for("ThetaData") is not None
    assert licensing_for("NoSuchProvider") is None
