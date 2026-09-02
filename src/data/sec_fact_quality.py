"""Phase 16, Part 7 — SEC fact quality classification.

Real probe evidence (sec_filing_store.py's module docstring) showed SEC
facts are not automatically safe just because they are point-in-time: the
SAME concept+period appears many times with different XBRL dimensional
("axis") breakdowns, only one of which (axises == ()) is the consolidated
total. This module implements Part 7's four-way classification
(SAFE_FOR_RESEARCH / REQUIRES_NORMALIZATION / METADATA_ONLY / REJECTED)
plus the duplicate/unit/period-ordering checks Part 7 asks for, reusing
src.data.generic_quality's timestamp checks where they apply rather than
reimplementing them.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Sequence

from src.data.sec_filing_store import SECFactRecord


class FactQualityClass(enum.Enum):
    SAFE_FOR_RESEARCH = "safe_for_research"
    REQUIRES_NORMALIZATION = "requires_normalization"
    METADATA_ONLY = "metadata_only"
    REJECTED = "rejected"


@dataclass(frozen=True)
class FactClassification:
    fact: SECFactRecord
    quality_class: FactQualityClass
    reason: str


def classify_fact(fact: SECFactRecord, *, known_normalized_concept: bool) -> FactClassification:
    """Rules, in order:

    1. A non-positive-or-nonsensical value (negative where the concept is
       an inherently non-negative stock, e.g. Assets/StockholdersEquity/
       CashAndCashEquivalents reported negative) is REJECTED. Note: some
       concepts (NetIncomeLoss, OperatingIncomeLoss) are legitimately
       negative (a loss) — only a small, explicit set of "should never be
       negative" concepts triggers this.
    2. A dimensionally-qualified fact (axises != ()) is METADATA_ONLY: a
       real, legitimate SEC disclosure (a segment/product/fair-value
       breakdown), but not the consolidated figure a neutral
       "latest_known_X" representation should ever use.
    3. A consolidated fact (axises == ()) whose concept is not in the
       Part 10 whitelist's known-normalized set is REQUIRES_NORMALIZATION
       — real data, but this phase has not verified what it means.
    4. A consolidated fact with a known, reliable normalized-concept
       mapping is SAFE_FOR_RESEARCH.
    """
    always_nonnegative_concepts = {
        "Assets", "Liabilities", "StockholdersEquity", "CashAndCashEquivalentsAtCarryingValue",
        "CommonStockSharesOutstanding",
    }
    if fact.concept in always_nonnegative_concepts and fact.value < 0:
        return FactClassification(fact, FactQualityClass.REJECTED, f"{fact.concept} is a non-negative-by-definition concept but value={fact.value}")

    if not fact.is_consolidated_total:
        return FactClassification(
            fact, FactQualityClass.METADATA_ONLY,
            f"dimensionally-qualified fact (axises={fact.axises}) -- a real disclosure, not the consolidated total",
        )

    if not known_normalized_concept:
        return FactClassification(
            fact, FactQualityClass.REQUIRES_NORMALIZATION,
            f"concept {fact.concept!r} is not in the Part 10 whitelist's verified-reliable mapping",
        )

    return FactClassification(fact, FactQualityClass.SAFE_FOR_RESEARCH, "consolidated total, known reliable concept mapping")


def find_duplicate_facts(facts: Sequence[SECFactRecord]) -> dict[tuple, int]:
    """Part 7: duplicate accession/concept/unit combinations. Keys on
    (filing_id, concept, period_end, period_start, unit, axises) — the
    same natural key SECFilingStore.save_facts dedupes on, so this check
    independently re-verifies what the store's own write path assumes."""
    counts: dict[tuple, int] = {}
    for f in facts:
        key = (f.filing_id, f.concept, f.period_end, f.period_start, f.unit, f.axises)
        counts[key] = counts.get(key, 0) + 1
    return {k: n for k, n in counts.items() if n > 1}


def find_unit_inconsistencies(facts: Sequence[SECFactRecord]) -> dict[str, set[str]]:
    """Part 7: inconsistent units for the same concept across filings
    (e.g. one filing tagging EarningsPerShareDiluted in
    iso4217:USD/xbrli:shares and another using a bare xbrli:shares would
    be a real anomaly worth flagging, not silently averaging together)."""
    units_by_concept: dict[str, set[str]] = {}
    for f in facts:
        units_by_concept.setdefault(f.concept, set()).add(f.unit)
    return {concept: units for concept, units in units_by_concept.items() if len(units) > 1}


def find_impossible_period_ordering(facts: Sequence[SECFactRecord]) -> list[SECFactRecord]:
    """Part 7: a duration fact whose period_start is not strictly before
    its period_end is impossible and must be flagged, never silently
    used."""
    return [f for f in facts if f.period_start is not None and f.period_start >= f.period_end]


@dataclass(frozen=True)
class SECQualityReport:
    issuers_tested: tuple[str, ...]
    filings_by_form: dict[str, int]
    filing_date_range: tuple[str, str] | None
    total_fact_count: int
    duplicate_count: int
    missing_publication_timestamp_count: int  # always == total filing count for this connector (Part 3/5 finding: no time-of-day ever supplied)
    amended_filing_count: int
    unit_anomaly_count: int
    unsupported_concept_count: int
    safe_for_research_count: int
    requires_normalization_count: int
    metadata_only_count: int
    rejected_count: int

    def render(self) -> str:
        lines = [
            "SEC Data Quality Report",
            f"  issuers_tested: {list(self.issuers_tested)}",
            f"  filings_by_form: {self.filings_by_form}",
            f"  filing_date_range: {self.filing_date_range}",
            f"  total_fact_count: {self.total_fact_count}",
            f"  duplicate_count: {self.duplicate_count}",
            f"  missing_publication_timestamp_count: {self.missing_publication_timestamp_count}",
            f"  amended_filing_count: {self.amended_filing_count}",
            f"  unit_anomaly_count: {self.unit_anomaly_count}",
            f"  unsupported_concept_count: {self.unsupported_concept_count}",
            f"  SAFE_FOR_RESEARCH: {self.safe_for_research_count}",
            f"  REQUIRES_NORMALIZATION: {self.requires_normalization_count}",
            f"  METADATA_ONLY: {self.metadata_only_count}",
            f"  REJECTED: {self.rejected_count}",
        ]
        return "\n".join(lines)
