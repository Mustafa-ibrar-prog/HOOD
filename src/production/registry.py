"""Phase 36, Part 4 — the strategy registry.

Every strategy that wants to participate in the live decision pipeline
must be registered here with real metadata. The registry REJECTS a
strategy from `production_eligible_strategies()` (the only list
`pipeline.py` ever reads) unless its status is exactly VALIDATED or
LIVE_AUTHORIZED, AND a genuine, matching `ValidationArtifact` exists in
the injected `ValidationArtifactStore` (Part 5: no strategy becomes
VALIDATED by an enum flip alone).

`MOMENTUM_BREAKOUT_EXISTING_V1` is pre-registered at NOT_READY, matching
Phase 35's own real classification (`src.options.phase35_strategy_gate`)
exactly -- this module does not reclassify it, it reads that
classification and records it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.production.validation_artifact import ValidationArtifactStore


class StrategyStatus(str, Enum):
    RESEARCH = "RESEARCH"
    VALIDATION_PENDING = "VALIDATION_PENDING"
    VALIDATED = "VALIDATED"
    LIVE_AUTHORIZED = "LIVE_AUTHORIZED"
    DISABLED = "DISABLED"
    REJECTED = "REJECTED"
    NOT_READY = "NOT_READY"


_PRODUCTION_ELIGIBLE_STATUSES = frozenset({StrategyStatus.VALIDATED, StrategyStatus.LIVE_AUTHORIZED})


class StrategyNotEligibleError(RuntimeError):
    """Raised by mark_validated when no genuine ValidationArtifact backs
    the requested status change."""


@dataclass(frozen=True)
class StrategyMetadata:
    strategy_id: str
    version: str
    status: StrategyStatus
    created_at: datetime
    validation_status: str  # free-text summary, e.g. Phase 35's Strategy Gate classification value
    historical_evidence_status: str  # e.g. "NOT_READY: 0 completed backtest trades (Phase 35)"
    live_data_compatibility_status: str  # e.g. "no required feature unavailable live (Phase 35 Part L)"
    allowed_option_structures: tuple[str, ...]  # e.g. ("long_call",)
    parameter_specification: str  # a pointer to the frozen spec, e.g. "src.options.phase35_frozen_strategy_spec.MOMENTUM_BREAKOUT_EXISTING_V1"
    risk_profile: str
    author_or_research_provenance: str


class StrategyRegistry:
    """In-memory registry; a caller is free to persist StrategyMetadata
    however it likes (this class does not prescribe a file format --
    unlike FrozenStrategyStore/ValidationArtifactStore, which explicitly
    need append-only immutability, a registry's STATUS is expected to
    change over a strategy's lifecycle, so it is not itself
    append-only)."""

    def __init__(self, artifact_store: "ValidationArtifactStore | None" = None):
        self._entries: dict[tuple[str, str], StrategyMetadata] = {}
        self._artifact_store = artifact_store

    def register(self, metadata: StrategyMetadata) -> None:
        self._entries[(metadata.strategy_id, metadata.version)] = metadata

    def get(self, strategy_id: str, version: str) -> StrategyMetadata | None:
        return self._entries.get((strategy_id, version))

    def all(self) -> tuple[StrategyMetadata, ...]:
        return tuple(self._entries.values())

    def mark_validated(self, strategy_id: str, version: str, *, target_status: StrategyStatus = StrategyStatus.VALIDATED) -> StrategyMetadata:
        """The ONLY way a strategy's status may become VALIDATED or
        LIVE_AUTHORIZED. Requires a real, matching ValidationArtifact in
        the injected store -- raises otherwise. This is the enforcement
        of Part 5's 'a strategy cannot become VALIDATED by changing one
        enum.'"""
        if target_status not in _PRODUCTION_ELIGIBLE_STATUSES:
            raise ValueError(f"target_status must be VALIDATED or LIVE_AUTHORIZED, got {target_status}")
        existing = self.get(strategy_id, version)
        if existing is None:
            raise StrategyNotEligibleError(f"{strategy_id} {version} is not registered")
        if self._artifact_store is None:
            raise StrategyNotEligibleError("No ValidationArtifactStore configured -- cannot verify evidence")
        artifact = self._artifact_store.get(strategy_id, version)
        if artifact is None:
            raise StrategyNotEligibleError(
                f"No approved ValidationArtifact exists for {strategy_id} {version} -- "
                "a status cannot become VALIDATED by an enum change alone."
            )
        updated = StrategyMetadata(
            strategy_id=existing.strategy_id, version=existing.version, status=target_status,
            created_at=existing.created_at, validation_status=existing.validation_status,
            historical_evidence_status=existing.historical_evidence_status,
            live_data_compatibility_status=existing.live_data_compatibility_status,
            allowed_option_structures=existing.allowed_option_structures,
            parameter_specification=existing.parameter_specification, risk_profile=existing.risk_profile,
            author_or_research_provenance=existing.author_or_research_provenance,
        )
        self.register(updated)
        return updated

    def production_eligible_strategies(self) -> tuple[StrategyMetadata, ...]:
        """The ONLY list `pipeline.py` ever reads to decide whether ANY
        strategy may run live. Never returns a NOT_READY/RESEARCH/
        VALIDATION_PENDING/REJECTED/DISABLED entry, regardless of how
        confident its metadata otherwise looks."""
        return tuple(m for m in self._entries.values() if m.status in _PRODUCTION_ELIGIBLE_STATUSES)


def build_default_registry(artifact_store: "ValidationArtifactStore | None" = None) -> StrategyRegistry:
    """Pre-registers MOMENTUM_BREAKOUT_EXISTING_V1 at NOT_READY, matching
    Phase 35's real classification exactly (src.options.phase35_strategy_gate
    classified it NOT_READY: 0 completed backtest trades). This function
    does not change that classification -- it records it."""
    from datetime import timezone

    from src.options.phase35_frozen_strategy_spec import FROZEN_AS_OF, STRATEGY_ID

    registry = StrategyRegistry(artifact_store)
    registry.register(StrategyMetadata(
        strategy_id=STRATEGY_ID, version="1.0", status=StrategyStatus.NOT_READY,
        created_at=datetime.fromisoformat(FROZEN_AS_OF).replace(tzinfo=timezone.utc),
        validation_status="NOT_READY (src.options.phase35_strategy_gate.classify_strategy: 0 completed backtest trades, < 20-trade floor)",
        historical_evidence_status="2,071 causal entry signals; 2 matched to a real historical option contract; 0 completed round-trip trades (Phase 35)",
        live_data_compatibility_status="No required feature is unavailable live (Phase 35 Part L, src.options.phase35_live_feature_compatibility.blockers() == ())",
        allowed_option_structures=("long_call",),
        parameter_specification="src.options.phase35_frozen_strategy_spec.MOMENTUM_BREAKOUT_EXISTING_V1",
        risk_profile="Single-leg long call, 1 contract, flat USD position-size cap (RiskManager.check_position_size)",
        author_or_research_provenance="Phase 35 -- existing strategy validation + live execution boundary hardening",
    ))
    return registry
