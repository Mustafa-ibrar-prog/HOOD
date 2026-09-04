"""Phase 29, Part 1/17 — ORATS field provenance table."""

from __future__ import annotations

from src.options.orats_field_provenance import (
    ORATS_FIELD_PROVENANCE,
    FieldProvenanceClassification,
    mapping_for,
    rows_by_classification,
)


def test_exactly_four_classification_values():
    assert {v.value for v in FieldProvenanceClassification} == {
        "vendor_supplied", "reconstructed", "derived", "unavailable",
    }


def test_part1s_required_fields_are_all_present():
    required = (
        "contract_identity", "underlying", "option_type_call_put", "strike", "expiration", "multiplier",
        "timestamp", "ohlc_underlying", "bid", "ask", "bid_size", "ask_size", "volume", "open_interest",
        "iv", "delta", "gamma", "theta", "vega", "rho", "underlying_price",
    )
    mapped = {r.normalized_field for r in ORATS_FIELD_PROVENANCE}
    for field in required:
        assert field in mapped, field


def test_bid_size_and_ask_size_are_vendor_supplied_corrected():
    """The Phase 29 self-correction: these were mistakenly scored as
    unavailable-tier in Phase 28; the real schema has them."""
    bid_size = mapping_for("bid_size")
    ask_size = mapping_for("ask_size")
    assert bid_size.classification == FieldProvenanceClassification.VENDOR_SUPPLIED
    assert ask_size.classification == FieldProvenanceClassification.VENDOR_SUPPLIED
    assert "call_bid_size" in bid_size.orats_source_field
    assert "call_ask_size" in ask_size.orats_source_field


def test_multiplier_is_unavailable_not_assumed_confirmed():
    m = mapping_for("multiplier")
    assert m.classification == FieldProvenanceClassification.UNAVAILABLE
    assert m.orats_source_field is None


def test_unavailable_rows_never_carry_a_source_field():
    for row in ORATS_FIELD_PROVENANCE:
        if row.classification == FieldProvenanceClassification.UNAVAILABLE:
            assert row.orats_source_field is None, row.normalized_field


def test_no_row_is_reconstructed_or_derived():
    """Every ORATS field this phase mapped is either real (VENDOR_
    SUPPLIED) or genuinely absent (UNAVAILABLE) -- nothing in this
    adapter reconstructs/derives a field from other ORATS fields."""
    for row in ORATS_FIELD_PROVENANCE:
        assert row.classification in (FieldProvenanceClassification.VENDOR_SUPPLIED, FieldProvenanceClassification.UNAVAILABLE)


def test_iv_and_greeks_are_vendor_supplied():
    """Unlike the free QuantConnect/Lean dataset (zero native IV/
    Greeks, everything reconstructed), ORATS supplies these natively."""
    for field in ("iv", "delta", "gamma", "theta", "vega", "rho"):
        m = mapping_for(field)
        assert m.classification == FieldProvenanceClassification.VENDOR_SUPPLIED, field


def test_rows_by_classification_covers_every_row_exactly_once():
    grouped = rows_by_classification()
    total = sum(len(v) for v in grouped.values())
    assert total == len(ORATS_FIELD_PROVENANCE)


def test_mapping_for_unknown_field_returns_none():
    assert mapping_for("not_a_real_field") is None


def test_every_row_has_real_evidence_text():
    for row in ORATS_FIELD_PROVENANCE:
        assert len(row.note) > 10
