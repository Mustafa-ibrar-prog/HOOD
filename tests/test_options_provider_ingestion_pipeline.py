"""Phase 25, Parts 21/22 — architecture preservation and the
provider-neutral ingestion flow design: Robinhood stays the live/
execution source, the flow has exactly the 11 named stages in order,
and every stage type is a Protocol or dataclass (design only, no
concrete provider implementation)."""

from __future__ import annotations

import ast
from pathlib import Path

from src.options.provider_ingestion_pipeline import (
    ARCHITECTURE_ROLE_PRESERVATION,
    PROVIDER_NEUTRAL_INGESTION_FLOW,
    IngestionStage,
    RawArchiveRecord,
    RawProviderPayload,
    ResearchDatasetRecord,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "src/options/provider_ingestion_pipeline.py"


def test_architecture_role_preservation_names_the_exact_flow():
    text = ARCHITECTURE_ROLE_PRESERVATION
    assert "Historical Provider" in text
    assert "Research Dataset" in text
    assert "Strategy" in text
    assert "Live Robinhood Scanner" in text
    assert "Risk Engine" in text
    assert "OPTIONS_ONLY Execution" in text


def test_architecture_role_preservation_explicitly_says_robinhood_is_not_replaced():
    text = ARCHITECTURE_ROLE_PRESERVATION.lower()
    assert "not replaced" in text
    assert "sole live" in text
    assert "never" in text


def test_ingestion_flow_has_exactly_eleven_stages_in_order():
    assert len(PROVIDER_NEUTRAL_INGESTION_FLOW) == 11
    assert PROVIDER_NEUTRAL_INGESTION_FLOW == (
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


def test_no_stage_is_duplicated_or_skipped():
    assert len(set(PROVIDER_NEUTRAL_INGESTION_FLOW)) == len(IngestionStage)


def test_raw_payload_is_the_only_type_holding_a_raw_dict():
    """Provider-specific field names must be contained to the raw stage
    -- ResearchDatasetRecord must not expose a raw dict anywhere in its
    own fields."""
    import dataclasses
    field_types = {f.name: f.type for f in dataclasses.fields(ResearchDatasetRecord)}
    assert "raw_payload" not in field_types
    for name in field_types:
        assert "dict" not in str(field_types[name]).lower()


def test_raw_provider_payload_and_archive_record_exist_and_are_dataclasses():
    import dataclasses
    assert dataclasses.is_dataclass(RawProviderPayload)
    assert dataclasses.is_dataclass(RawArchiveRecord)


def test_module_defines_only_protocols_dataclasses_and_enums_no_concrete_implementation():
    tree = ast.parse(MODULE_PATH.read_text(), filename=str(MODULE_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = [b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in node.bases]

            def _decorator_name(d):
                target = d.func if isinstance(d, ast.Call) else d
                return target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")

            decorators = [_decorator_name(d) for d in node.decorator_list]
            is_protocol = "Protocol" in bases
            is_dataclass = "dataclass" in decorators
            is_enum = "Enum" in bases
            assert is_protocol or is_dataclass or is_enum, (
                f"{node.name} is neither a Protocol, dataclass, nor Enum -- looks like a concrete "
                f"provider implementation, forbidden by Part 22"
            )
