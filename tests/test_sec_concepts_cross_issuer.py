"""Phase 17, Part 21C — taxonomy/concept mapping audit tests: multiple
source concepts per normalized concept, reliable vs unreliable mappings,
no silent semantic equivalence. Deterministic (CONCEPT_MAP is a static
table, no network)."""

from __future__ import annotations

from src.data.sec_concepts import CONCEPT_MAP_BY_SOURCE, is_known_reliable_concept, normalized_concept_for, source_concepts_for


def test_revenue_has_two_verified_source_concepts():
    concepts = source_concepts_for("revenue")
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" in concepts
    assert "Revenues" in concepts
    assert len(concepts) == 2


def test_both_revenue_source_concepts_are_reliable():
    assert is_known_reliable_concept("RevenueFromContractWithCustomerExcludingAssessedTax") is True
    assert is_known_reliable_concept("Revenues") is True


def test_both_revenue_source_concepts_normalize_to_the_same_concept():
    assert normalized_concept_for("RevenueFromContractWithCustomerExcludingAssessedTax") == "revenue"
    assert normalized_concept_for("Revenues") == "revenue"


def test_cash_and_due_from_banks_is_present_but_not_reliable():
    """Part 6: 'no silent semantic equivalence' -- JPM's real,
    consolidated cash-like concept is documented but NOT certified."""
    assert "CashAndDueFromBanks" in CONCEPT_MAP_BY_SOURCE
    assert is_known_reliable_concept("CashAndDueFromBanks") is False
    assert normalized_concept_for("CashAndDueFromBanks") == "cash_and_equivalents"  # mapped for traceability, but unreliable


def test_capital_expenditures_is_a_known_reliable_source_concept():
    assert is_known_reliable_concept("PaymentsToAcquirePropertyPlantAndEquipment") is True
    assert normalized_concept_for("PaymentsToAcquirePropertyPlantAndEquipment") == "capital_expenditures"


def test_unknown_concept_is_not_reliable_and_has_no_normalized_mapping():
    assert is_known_reliable_concept("SomeCompanySpecificExtensionTag") is False
    assert normalized_concept_for("SomeCompanySpecificExtensionTag") is None


def test_source_concepts_for_unmapped_normalized_concept_is_empty():
    assert source_concepts_for("not_a_real_normalized_concept") == ()


def test_every_concept_map_entry_has_documented_notes():
    for mapping in CONCEPT_MAP_BY_SOURCE.values():
        assert mapping.notes, f"{mapping.source_concept} has no documented evidence"
