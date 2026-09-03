"""Phase 16/17, Part 10, Phase 17 Part 6 — a small, explicit concept
whitelist and normalization layer.

Real probe evidence (Phase 16): AAPL's FY2022 10-K does NOT tag revenue
as "Revenues" — a request for that exact concept returned zero rows; the
real tag is "RevenueFromContractWithCustomerExcludingAssessedTax". Phase
17 extended this to MSFT/NVDA/JPM and found the split is real and
issuer-grouped, not random: AAPL and MSFT both use
RevenueFromContractWithCustomerExcludingAssessedTax; NVDA and JPM both
use the plain "Revenues" tag instead (confirmed: neither NVDA's nor
JPM's filing has a single row under
RevenueFromContractWithCustomerExcludingAssessedTax). Rather than guess a
single canonical tag per concept, `CONCEPT_MAP` lists every SOURCE
concept this phase independently verified (by real probe) resolves
correctly, each mapped to one NORMALIZED concept name — never the
reverse (no code path invents a mapping for an unverified source
concept). A source concept that isn't in this map is, by construction,
REQUIRES_NORMALIZATION (see sec_fact_quality.classify_fact) — never
silently coerced. A source concept present but marked `reliable=False`
(see CashAndDueFromBanks below) is likewise NOT treated as certified —
its semantic equivalence to the normalized concept is genuinely
ambiguous, and Part 6 of Phase 17 is explicit: "No silent semantic
equivalence."
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
    # --- Phase 17 additions --------------------------------------------------------------------
    ConceptMapping(
        source_concept="Revenues", normalized_concept="revenue",
        taxonomy="us-gaap", expected_unit="iso4217:USD", reliable=True,
        notes="Confirmed via real probe: NVDA FY2023 10-K (period 2022-01-31/2023-01-29), axises=(), "
              "value=26,974,000,000; JPM FY2022 10-K (period 2022-01-01/2022-12-31), axises=(), "
              "value=128,695,000,000. Neither NVDA's nor JPM's filing has ANY row under "
              "RevenueFromContractWithCustomerExcludingAssessedTax (0 rows for both) -- this is the "
              "issuer's ONLY revenue tag, not a duplicate/alternate of the other mapping above. "
              "AAPL/MSFT use RevenueFromContractWithCustomerExcludingAssessedTax exclusively; NVDA/JPM "
              "use Revenues exclusively -- confirmed disjoint across all 4 issuers probed, no issuer "
              "populates both tags for the same period this phase observed.",
    ),
    ConceptMapping(
        source_concept="PaymentsToAcquirePropertyPlantAndEquipment", normalized_concept="capital_expenditures",
        taxonomy="us-gaap", expected_unit="iso4217:USD", reliable=True,
        notes="Confirmed via real probe: AAPL FY2022 10-K, axises=(), 3 years present "
              "(FY2020=7,309,000,000; FY2021=11,085,000,000; FY2022=10,708,000,000). Only confirmed for "
              "AAPL this phase -- MSFT/NVDA/JPM capex was not independently probed, so cross-issuer "
              "reliability for this concept is UNVERIFIED beyond AAPL (see sec_certification.py, which "
              "certifies this concept CONDITIONALLY_CERTIFIED, restricted to AAPL, for exactly this reason).",
    ),
    ConceptMapping(
        source_concept="CashAndDueFromBanks", normalized_concept="cash_and_equivalents",
        taxonomy="us-gaap", expected_unit="iso4217:USD", reliable=False,
        notes="JPM does NOT report CashAndCashEquivalentsAtCarryingValue at all (0 rows, confirmed by "
              "real probe) -- CashAndDueFromBanks is JPM's own real, consolidated (axises=()) cash-like "
              "balance (FY2021=26,438,000,000; FY2022=27,697,000,000). Deliberately marked "
              "reliable=False and NOT treated as equivalent to cash_and_equivalents: a bank's 'cash and "
              "due from banks' may or may not include the same scope of short-term instruments as a "
              "non-bank's 'cash and cash equivalents' (e.g. it may exclude money-market/short-term-"
              "investment balances the other concept includes) -- Part 6's explicit 'no silent semantic "
              "equivalence' rule. Recorded here so the real, verified alternative concept is documented "
              "and traceable, not silently dropped -- but it stays REQUIRES_NORMALIZATION until someone "
              "explicitly reviews and defends the equivalence.",
    ),
)

CONCEPT_MAP_BY_SOURCE: dict[str, ConceptMapping] = {m.source_concept: m for m in CONCEPT_MAP}


def source_concepts_for(normalized_concept: str) -> tuple[str, ...]:
    """Every source concept (reliable or not) that maps to
    `normalized_concept` -- e.g. source_concepts_for("revenue") ==
    ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues")."""
    return tuple(m.source_concept for m in CONCEPT_MAP if m.normalized_concept == normalized_concept)


def is_known_reliable_concept(source_concept: str) -> bool:
    mapping = CONCEPT_MAP_BY_SOURCE.get(source_concept)
    return mapping is not None and mapping.reliable


def normalized_concept_for(source_concept: str) -> str | None:
    mapping = CONCEPT_MAP_BY_SOURCE.get(source_concept)
    return mapping.normalized_concept if mapping else None
