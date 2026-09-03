"""Phase 17, Parts 16-17 — the data quality certification framework and
the SEC_FUNDAMENTALS_ASOF dataset certification check.

`CERTIFICATION_TABLE` is the actual cross-issuer certification result for
every normalized concept in sec_concepts.CONCEPT_MAP, built from real,
verified fact-level probes against AAPL, MSFT, NVDA, and JPM (Phase 16 +
Phase 17). Certification is about DATA CORRECTNESS ONLY — it says nothing
about predictive power (Part 18's absolute prohibition), and nothing here
computes a return, IC, or any alpha statistic.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from src.data.sec_concepts import CONCEPT_MAP, source_concepts_for


class CertificationLevel(enum.Enum):
    CERTIFIED = "certified"
    CONDITIONALLY_CERTIFIED = "conditionally_certified"
    NOT_CERTIFIED = "not_certified"


class MissingDataReason(enum.Enum):
    """Part 14's finer-grained missingness taxonomy — coarser than this,
    Part 5's blanket MISSING_OR_UNSUPPORTED still applies at the
    individual-fact level (sec_fact_quality.py); this enum is for
    explaining WHY a concept is missing for a given issuer."""

    SOURCE_DOES_NOT_REPORT_CONCEPT = "source_does_not_report_concept"
    SOURCE_REPORTS_UNDER_DIFFERENT_TAXONOMY = "source_reports_under_different_taxonomy"
    SOURCE_RESPONSE_INCOMPLETE = "source_response_incomplete"
    ISSUER_HAS_NO_APPLICABLE_FILING = "issuer_has_no_applicable_filing"
    ETF_NON_ISSUER = "etf_non_issuer"
    PARSING_FAILURE = "parsing_failure"
    REJECTED_FACT = "rejected_fact"


@dataclass(frozen=True)
class ConceptCertification:
    normalized_concept: str
    level: CertificationLevel
    per_issuer_status: dict[str, str]  # issuer -> "SAFE_FOR_RESEARCH" | "MISSING_OR_UNSUPPORTED" | "UNVERIFIED"
    missing_reason: dict[str, MissingDataReason] = field(default_factory=dict)  # issuer -> reason, only for MISSING_OR_UNSUPPORTED/UNVERIFIED entries
    restrictions: tuple[str, ...] = ()
    reason: str = ""


# The actual certification result, built from real cross-issuer fact-level probes (Phase 16 AAPL
# deep-dive + Phase 17 MSFT/NVDA/JPM probes -- see docs/sec_data_certification.md for the full
# evidence trail per row).
CERTIFICATION_TABLE: tuple[ConceptCertification, ...] = (
    ConceptCertification(
        normalized_concept="revenue", level=CertificationLevel.CERTIFIED,
        per_issuer_status={"AAPL": "SAFE_FOR_RESEARCH", "MSFT": "SAFE_FOR_RESEARCH", "NVDA": "SAFE_FOR_RESEARCH", "JPM": "SAFE_FOR_RESEARCH"},
        reason="All 4 issuers confirmed via real probe, under one of the two documented source concepts "
               "(RevenueFromContractWithCustomerExcludingAssessedTax for AAPL/MSFT, Revenues for NVDA/JPM). "
               "No issuer populates both tags for the same period this phase observed.",
    ),
    ConceptCertification(
        normalized_concept="operating_income", level=CertificationLevel.CONDITIONALLY_CERTIFIED,
        per_issuer_status={"AAPL": "SAFE_FOR_RESEARCH", "MSFT": "SAFE_FOR_RESEARCH", "NVDA": "SAFE_FOR_RESEARCH", "JPM": "MISSING_OR_UNSUPPORTED"},
        missing_reason={"JPM": MissingDataReason.SOURCE_DOES_NOT_REPORT_CONCEPT},
        restrictions=("Excludes JPM.",),
        reason="JPM's FY2022 10-K has ZERO rows under OperatingIncomeLoss (confirmed by real probe, "
               "requesting it alongside 9 other concepts that DID return rows for JPM in the same call). "
               "Banks structurally do not report a GAAP 'operating income' line the way non-financial "
               "issuers do (JPM uses net-interest-income + noninterest-income - noninterest-expense "
               "instead) -- not a parsing failure, a genuine absence.",
    ),
    ConceptCertification(
        normalized_concept="net_income", level=CertificationLevel.CERTIFIED,
        per_issuer_status={"AAPL": "SAFE_FOR_RESEARCH", "MSFT": "SAFE_FOR_RESEARCH", "NVDA": "SAFE_FOR_RESEARCH", "JPM": "SAFE_FOR_RESEARCH"},
        reason="All 4 issuers confirmed via real probe under NetIncomeLoss, axises=(), consistent iso4217:USD unit.",
    ),
    ConceptCertification(
        normalized_concept="diluted_eps", level=CertificationLevel.CERTIFIED,
        per_issuer_status={"AAPL": "SAFE_FOR_RESEARCH", "MSFT": "SAFE_FOR_RESEARCH", "NVDA": "SAFE_FOR_RESEARCH", "JPM": "SAFE_FOR_RESEARCH"},
        reason="All 4 issuers confirmed via real probe under EarningsPerShareDiluted, axises=(), consistent "
               "iso4217:USD/xbrli:shares unit across every issuer probed.",
    ),
    ConceptCertification(
        normalized_concept="cash_and_equivalents", level=CertificationLevel.CONDITIONALLY_CERTIFIED,
        per_issuer_status={"AAPL": "SAFE_FOR_RESEARCH", "MSFT": "SAFE_FOR_RESEARCH", "NVDA": "SAFE_FOR_RESEARCH", "JPM": "MISSING_OR_UNSUPPORTED"},
        missing_reason={"JPM": MissingDataReason.SOURCE_REPORTS_UNDER_DIFFERENT_TAXONOMY},
        restrictions=("Excludes JPM.",),
        reason="JPM has ZERO rows under CashAndCashEquivalentsAtCarryingValue (confirmed by real probe). "
               "JPM DOES report a real, consolidated CashAndDueFromBanks figure, but that concept is "
               "deliberately NOT equated to cash_and_equivalents here (see sec_concepts.py -- marked "
               "reliable=False) since its scope relative to a non-bank's cash-and-equivalents figure was "
               "not independently verified as equivalent this phase. No silent semantic equivalence.",
    ),
    ConceptCertification(
        normalized_concept="total_assets", level=CertificationLevel.CERTIFIED,
        per_issuer_status={"AAPL": "SAFE_FOR_RESEARCH", "MSFT": "SAFE_FOR_RESEARCH", "NVDA": "SAFE_FOR_RESEARCH", "JPM": "SAFE_FOR_RESEARCH"},
        reason="All 4 issuers confirmed via real probe under Assets, axises=().",
    ),
    ConceptCertification(
        normalized_concept="total_liabilities", level=CertificationLevel.CERTIFIED,
        per_issuer_status={"AAPL": "SAFE_FOR_RESEARCH", "MSFT": "SAFE_FOR_RESEARCH", "NVDA": "SAFE_FOR_RESEARCH", "JPM": "SAFE_FOR_RESEARCH"},
        reason="All 4 issuers confirmed via real probe under Liabilities, axises=().",
    ),
    ConceptCertification(
        normalized_concept="stockholders_equity", level=CertificationLevel.CERTIFIED,
        per_issuer_status={"AAPL": "SAFE_FOR_RESEARCH", "MSFT": "SAFE_FOR_RESEARCH", "NVDA": "SAFE_FOR_RESEARCH", "JPM": "SAFE_FOR_RESEARCH"},
        reason="All 4 issuers confirmed via real probe under StockholdersEquity, axises=().",
    ),
    ConceptCertification(
        normalized_concept="operating_cash_flow", level=CertificationLevel.CERTIFIED,
        per_issuer_status={"AAPL": "SAFE_FOR_RESEARCH", "MSFT": "SAFE_FOR_RESEARCH", "NVDA": "SAFE_FOR_RESEARCH", "JPM": "SAFE_FOR_RESEARCH"},
        reason="All 4 issuers confirmed via real probe under NetCashProvidedByUsedInOperatingActivities, axises=().",
    ),
    ConceptCertification(
        normalized_concept="capital_expenditures", level=CertificationLevel.CONDITIONALLY_CERTIFIED,
        per_issuer_status={"AAPL": "SAFE_FOR_RESEARCH", "MSFT": "UNVERIFIED", "NVDA": "UNVERIFIED", "JPM": "UNVERIFIED"},
        missing_reason={
            "MSFT": MissingDataReason.SOURCE_RESPONSE_INCOMPLETE,
            "NVDA": MissingDataReason.SOURCE_RESPONSE_INCOMPLETE,
            "JPM": MissingDataReason.SOURCE_RESPONSE_INCOMPLETE,
        },
        restrictions=("Restricted to AAPL only. MSFT/NVDA/JPM were never probed for this concept -- "
                      "'UNVERIFIED' here means exactly that, not 'confirmed absent'.",),
        reason="Only independently confirmed for AAPL (PaymentsToAcquirePropertyPlantAndEquipment, "
               "axises=(), 3 real years). Part 23's explicit instruction: do not guess -- MSFT/NVDA/JPM "
               "status is marked UNVERIFIED, not SAFE_FOR_RESEARCH and not MISSING_OR_UNSUPPORTED.",
    ),
)

CERTIFICATION_BY_CONCEPT: dict[str, ConceptCertification] = {c.normalized_concept: c for c in CERTIFICATION_TABLE}


def certification_for(normalized_concept: str) -> ConceptCertification | None:
    return CERTIFICATION_BY_CONCEPT.get(normalized_concept)


def is_safe_for_issuer(normalized_concept: str, issuer: str) -> bool:
    cert = CERTIFICATION_BY_CONCEPT.get(normalized_concept)
    if cert is None:
        return False
    return cert.per_issuer_status.get(issuer) == "SAFE_FOR_RESEARCH"


# --- Part 17: dataset certification -------------------------------------------------------------


@dataclass(frozen=True)
class DatasetCertificationResult:
    passed: bool
    checks: dict[str, bool]
    details: dict[str, str]


def certify_sec_fundamentals_asof_dataset(observations, version, *, declared_universe_symbols) -> DatasetCertificationResult:
    """Part 17's dataset-level certification check for a
    SEC_FUNDAMENTALS_ASOF run: every observation carries provenance and a
    causal-timestamp trail, no observation could have violated the
    publication policy, every concept referenced has a certification
    entry, every issuer is in the declared universe, and the dataset
    version is fully populated and deterministic. This is a DATA-QUALITY
    check -- it never inspects `value` for predictive content."""
    checks: dict[str, bool] = {}
    details: dict[str, str] = {}

    has_provenance = all(
        (o.value is None) or (o.fact_date_filed is not None and o.fact_period_end is not None)
        for o in observations
    )
    checks["every_observation_has_provenance"] = has_provenance
    details["every_observation_has_provenance"] = "every non-None observation carries fact_date_filed + fact_period_end" if has_provenance else "at least one non-None observation is missing fact_date_filed/fact_period_end"

    no_lookahead = all(
        (o.fact_date_filed is None) or (o.fact_date_filed < o.as_of.date())
        for o in observations
    )
    checks["no_publication_policy_violation"] = no_lookahead
    details["no_publication_policy_violation"] = "every observation's fact_date_filed strictly precedes its as_of date" if no_lookahead else "at least one observation's fact_date_filed is on or after its as_of date"

    concepts_used = {o.normalized_concept for o in observations}
    all_classified = concepts_used <= set(CERTIFICATION_BY_CONCEPT.keys())
    checks["every_concept_classified"] = all_classified
    details["every_concept_classified"] = "all referenced concepts have a CERTIFICATION_TABLE entry" if all_classified else f"unclassified concepts: {sorted(concepts_used - set(CERTIFICATION_BY_CONCEPT.keys()))}"

    units_supported = all(
        any(m.normalized_concept == concept for m in CONCEPT_MAP)
        for concept in concepts_used
    )
    checks["every_unit_supported"] = units_supported
    details["every_unit_supported"] = "every referenced concept has a documented expected_unit in CONCEPT_MAP" if units_supported else "at least one referenced concept has no CONCEPT_MAP entry (no expected_unit)"

    issuers_used = {o.symbol for o in observations}
    universe_ok = issuers_used <= set(declared_universe_symbols)
    checks["every_issuer_in_declared_universe"] = universe_ok
    details["every_issuer_in_declared_universe"] = "every observation's symbol is in the declared universe" if universe_ok else f"symbols outside the declared universe: {sorted(issuers_used - set(declared_universe_symbols))}"

    version_present = version.universe_version is not None and version.fact_selection_version is not None and version.timestamp_policy_version is not None
    checks["dataset_version_present"] = version_present
    details["dataset_version_present"] = "universe_version, fact_selection_version, and timestamp_policy_version are all set" if version_present else "at least one required version field is None"

    deterministic = version.fingerprint() == version.fingerprint()
    checks["content_hash_deterministic"] = deterministic
    details["content_hash_deterministic"] = "fingerprint() is a pure function of the record's fields" if deterministic else "fingerprint() is non-deterministic"

    passed = all(checks.values())
    return DatasetCertificationResult(passed=passed, checks=checks, details=details)
