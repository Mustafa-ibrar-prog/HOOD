"""Phase 25, Parts 21/22 — architecture preservation and a
provider-neutral ingestion flow DESIGN. Nothing here is implemented
against any real provider (Part 22's explicit "design, do not
implement"): every class is a `typing.Protocol` or a plain dataclass,
exactly like Phase 24's `historical_data_interfaces.py`, which this
module reuses rather than re-deriving (`ContractIdentity`,
`ContractLifecycle`, and `OptionDataProvenance` are the Phase 24 types
already shaped for the NORMALIZED/LIFECYCLE/PROVENANCE stages below).

Part 21's architecture-preservation instruction: this project's existing
Robinhood MCP connection remains the LIVE/ACCOUNT/EXECUTION source. A
historical data provider (ORATS or otherwise) is a RESEARCH/BACKTEST-ONLY
addition -- it never places an order, never supplies a live quote used
for execution, and never replaces Robinhood in that role.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable

from src.options.historical_data_interfaces import (
    ContractIdentity,
    ContractLifecycle,
    OptionDataProvenance,
)

# Part 21's exact flow, preserved verbatim for testability (see
# tests/test_options_provider_ingestion_pipeline.py) -- Robinhood's role
# is RESEARCH-EXCLUDED and LIVE/ACCOUNT/EXECUTION-ONLY; no historical
# provider is ever positioned upstream of order placement.
ARCHITECTURE_ROLE_PRESERVATION = (
    "Historical Provider -> Research Dataset -> Strategy -> Live Robinhood Scanner -> "
    "Risk Engine -> OPTIONS_ONLY Execution. "
    "Robinhood (this project's existing HOOD MCP connector) remains the sole LIVE, ACCOUNT, and "
    "EXECUTION source -- it is not replaced, downgraded, or bypassed by any historical provider "
    "evaluated in Phase 25. A historical provider (ORATS or any future alternative) supplies the "
    "RESEARCH DATASET a strategy is developed and backtested against; it never supplies a live quote "
    "used for sizing or execution, and never places, reviews, or cancels an order. This mirrors the "
    "project's existing, already-enforced boundary (Phase 15's PartitionLifecycleStage discipline, "
    "Phase 24's forbidden-import safety tests) between research code and the live/paper/execution path."
)


class IngestionStage(enum.Enum):
    """Part 22's exact 11-stage flow, in order. Every stage below is a
    distinct type in this module (or reused from Phase 24) -- no stage
    is skipped or merged."""

    PROVIDER_RAW_DATA = "provider_raw_data"
    RAW_ARCHIVE = "raw_archive"
    NORMALIZED_OPTION_CONTRACT = "normalized_option_contract"
    HISTORICAL_QUOTE = "historical_quote"
    HISTORICAL_TRADE = "historical_trade"
    HISTORICAL_CHAIN = "historical_chain"
    HISTORICAL_IV_GREEKS = "historical_iv_greeks"
    CONTRACT_LIFECYCLE = "contract_lifecycle"
    PROVENANCE = "provenance"
    QUALITY_VALIDATION = "quality_validation"
    RESEARCH_DATASET = "research_dataset"


PROVIDER_NEUTRAL_INGESTION_FLOW: tuple[IngestionStage, ...] = (
    IngestionStage.PROVIDER_RAW_DATA,
    IngestionStage.RAW_ARCHIVE,
    IngestionStage.NORMALIZED_OPTION_CONTRACT,
    IngestionStage.HISTORICAL_QUOTE,
    IngestionStage.HISTORICAL_TRADE,
    IngestionStage.HISTORICAL_CHAIN,
    IngestionStage.HISTORICAL_IV_GREEKS,
    IngestionStage.CONTRACT_LIFECYCLE,
    IngestionStage.PROVENANCE,
    IngestionStage.QUALITY_VALIDATION,
    IngestionStage.RESEARCH_DATASET,
)


@dataclass(frozen=True)
class RawProviderPayload:
    """Stage 1. The ONLY place a provider-specific field name (e.g.
    ORATS's `call_bid_iv`, or some future vendor's own naming) is allowed
    to appear as raw, unstructured data. Every later stage must consume
    only the NORMALIZED types below -- provider-specific fields must not
    leak past this and the raw-archive stage (module docstring's core
    design rule, and Part 22's explicit requirement)."""

    provider: str
    endpoint: str
    raw_payload: dict
    retrieved_at: datetime


@dataclass(frozen=True)
class RawArchiveRecord:
    """Stage 2. An immutable, content-addressed copy of exactly what the
    provider returned, kept for reproducibility/audit -- never mutated
    once written."""

    payload: RawProviderPayload
    archive_path: str
    checksum: str


@dataclass(frozen=True)
class QualityValidationResult:
    """Stage 10. A pass/fail record against Part 23's future
    certification criteria (see data_quality_certification.py) --
    produced per normalized record, before that record is allowed into
    the research dataset."""

    record_key: str
    checks_passed: tuple[str, ...]
    checks_failed: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return len(self.checks_failed) == 0


@dataclass(frozen=True)
class ResearchDatasetRecord:
    """Stage 11. The only type a strategy/hypothesis is ever allowed to
    read from (Part 21's architecture boundary) -- fully normalized,
    provider-agnostic, and quality-validated."""

    contract: ContractIdentity
    lifecycle: ContractLifecycle
    provenance: OptionDataProvenance
    quality: QualityValidationResult


@runtime_checkable
class RawArchiveStage(Protocol):
    def archive(self, payload: RawProviderPayload) -> RawArchiveRecord: ...


@runtime_checkable
class NormalizationStage(Protocol):
    """Stage 3. Translates one provider's raw payload into
    provider-agnostic `ContractIdentity` -- the one place a
    provider-specific-to-normalized field mapping is allowed to live."""

    def normalize_contract(self, record: RawArchiveRecord) -> ContractIdentity: ...


@runtime_checkable
class HistoricalQuoteIngestionStage(Protocol):
    def ingest_quotes(self, record: RawArchiveRecord, contract: ContractIdentity) -> list: ...


@runtime_checkable
class HistoricalTradeIngestionStage(Protocol):
    def ingest_trades(self, record: RawArchiveRecord, contract: ContractIdentity) -> list: ...


@runtime_checkable
class HistoricalChainIngestionStage(Protocol):
    def ingest_chain(self, record: RawArchiveRecord, as_of: datetime) -> list[ContractIdentity]: ...


@runtime_checkable
class HistoricalIVGreeksIngestionStage(Protocol):
    def ingest_iv_greeks(self, record: RawArchiveRecord, contract: ContractIdentity) -> list: ...


@runtime_checkable
class ContractLifecycleIngestionStage(Protocol):
    def ingest_lifecycle(self, record: RawArchiveRecord, contract: ContractIdentity) -> ContractLifecycle: ...


@runtime_checkable
class ProvenanceIngestionStage(Protocol):
    def attach_provenance(self, record: RawArchiveRecord) -> OptionDataProvenance: ...


@runtime_checkable
class QualityValidationStage(Protocol):
    def validate(self, contract: ContractIdentity, lifecycle: ContractLifecycle) -> QualityValidationResult: ...


@runtime_checkable
class ResearchDatasetStage(Protocol):
    def build_dataset_record(
        self,
        contract: ContractIdentity,
        lifecycle: ContractLifecycle,
        provenance: OptionDataProvenance,
        quality: QualityValidationResult,
    ) -> ResearchDatasetRecord: ...

    def save(self, records: Sequence[ResearchDatasetRecord]) -> object: ...
