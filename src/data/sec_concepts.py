"""Phase 16, Part 10 — a small, explicit concept whitelist and
normalization layer.

Real probe evidence (sec_filing_store.py's module docstring): AAPL's
FY2022 10-K does NOT tag revenue as "Revenues" — a request for that exact
concept returned zero rows; the real tag is
"RevenueFromContractWithCustomerExcludingAssessedTax". This is exactly
the "not every company reports under identical taxonomy identifiers"
risk Part 10 names. Rather than guess a single canonical tag per concept,
`CONCEPT_MAP` lists every SOURCE concept this phase independently
verified (by real probe) resolves correctly, each mapped to one
NORMALIZED concept name — never the reverse (no code path invents a
mapping for an unverified source concept). A source concept that isn't
in this map is, by construction, REQUIRES_NORMALIZATION (see
sec_fact_quality.classify_fact) — never silently coerced.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConceptMapping:
    source_concept: str
    normalized_concept: str
    taxonomy: str  # implicit in the raw response (see sec_filing_store.py) — recorded explicitly here since it IS known for every concept in this whitelist (they are all standard us-gaap tags)
    expected_unit: str
    reliable: bool
    notes: str


# Only concepts independently confirmed, by a real get_sec_filing_facts probe against at least
# one US_DIVERSIFIED issuer during this phase's development, to (a) exist under this exact tag
# and (b) produce a value matching that issuer's real, publicly reported figure for that period.
# NOT a general-purpose XBRL taxonomy map -- deliberately small (Part 10: "the objective is data
# correctness, not maximum coverage").
CONCEPT_MAP: tuple[ConceptMapping, ...] = (
    ConceptMapping(
        source_concept="RevenueFromContractWithCustomerExcludingAssessedTax", normalized_concept="revenue",
        taxonomy="us-gaap", expected_unit="iso4217:USD", reliable=True,
        notes="Confirmed via real probe: AAPL FY2022 (period 2021-09-26/2022-09-24), axises=(), value=394,328,000,000 -- matches Apple's real reported FY2022 revenue. NOTE: plain 'Revenues' returned ZERO rows for the same filing -- do not assume that tag works.",
    ),
    ConceptMapping(
        source_concept="OperatingIncomeLoss", normalized_concept="operating_income",
        taxonomy="us-gaap", expected_unit="iso4217:USD", reliable=True,
        notes="Confirmed present with axises=() for AAPL FY2022 (119,437,000,000).",
    ),
    ConceptMapping(
        source_concept="NetIncomeLoss", normalized_concept="net_income",
        taxonomy="us-gaap", expected_unit="iso4217:USD", reliable=True,
        notes="Confirmed present with axises=() for AAPL FY2022 (99,803,000,000).",
    ),
    ConceptMapping(
        source_concept="EarningsPerShareDiluted", normalized_concept="diluted_eps",
        taxonomy="us-gaap", expected_unit="iso4217:USD/xbrli:shares", reliable=True,
        notes="Confirmed present with axises=() for AAPL FY2022 (6.11).",
    ),
    ConceptMapping(
        source_concept="CashAndCashEquivalentsAtCarryingValue", normalized_concept="cash_and_equivalents",
        taxonomy="us-gaap", expected_unit="iso4217:USD", reliable=True,
        notes="Confirmed present with axises=() for AAPL FY2022 (23,646,000,000) -- NOTE: this concept also appears with MANY axis-qualified breakdowns (by fair-value level, by instrument type) in the same filing; only axises=() is this normalized concept.",
    ),
    ConceptMapping(
        source_concept="Assets", normalized_concept="total_assets",
        taxonomy="us-gaap", expected_unit="iso4217:USD", reliable=True,
        notes="Confirmed present with axises=() for AAPL FY2022 (352,755,000,000).",
    ),
    ConceptMapping(
        source_concept="Liabilities", normalized_concept="total_liabilities",
        taxonomy="us-gaap", expected_unit="iso4217:USD", reliable=True,
        notes="Confirmed present with axises=() for AAPL FY2022 (302,083,000,000).",
    ),
    ConceptMapping(
        source_concept="StockholdersEquity", normalized_concept="stockholders_equity",
        taxonomy="us-gaap", expected_unit="iso4217:USD", reliable=True,
        notes="Confirmed present with axises=() for AAPL FY2022 (50,672,000,000) -- NOTE: this concept ALSO appears with many equity-component-axis breakdowns (retained earnings, AOCI, common stock) in the same filing; only axises=() is the total.",
    ),
    ConceptMapping(
        source_concept="NetCashProvidedByUsedInOperatingActivities", normalized_concept="operating_cash_flow",
        taxonomy="us-gaap", expected_unit="iso4217:USD", reliable=True,
        notes="Confirmed present with axises=() for AAPL FY2022 (122,151,000,000).",
    ),
)

CONCEPT_MAP_BY_SOURCE: dict[str, ConceptMapping] = {m.source_concept: m for m in CONCEPT_MAP}

# Part 10 explicitly lists capital expenditures as "if reliably available" -- it was NOT probed
# this phase (no real call verified a CapitalExpenditures-shaped concept against a real reported
# figure), so it is deliberately absent from CONCEPT_MAP rather than guessed. Any source concept
# not in CONCEPT_MAP_BY_SOURCE, capex included, is REQUIRES_NORMALIZATION by construction.


def is_known_reliable_concept(source_concept: str) -> bool:
    mapping = CONCEPT_MAP_BY_SOURCE.get(source_concept)
    return mapping is not None and mapping.reliable


def normalized_concept_for(source_concept: str) -> str | None:
    mapping = CONCEPT_MAP_BY_SOURCE.get(source_concept)
    return mapping.normalized_concept if mapping else None
