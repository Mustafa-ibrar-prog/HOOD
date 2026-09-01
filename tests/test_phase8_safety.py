"""Phase 8, Part 27 & Final Safety Check: preregistration requirement,
development-only data access, holdout isolation, MR-002 untouched, no
live/paper orders, parent-hypothesis immutability.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.research.hypothesis import Hypothesis, HypothesisRegistry
from src.research.partition import PartitionLifecycleStage, PartitionStore, assert_stage_allows_parameter_selection
from src.research.preregistration import PreregistrationError, PreregistrationStore, require_preregistered

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE8_SRC_MODULES = ["volume_anomaly_strategy.py", "autocorrelation.py"]
PHASE8_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase8_*.py"))
FORBIDDEN_IMPORT_PREFIXES = ("src.execution", "src.orchestrator")
FORBIDDEN_CALLS = ("place_equity_order", "place_option_order", "place_crypto_order", "submit_order", "cancel_equity_order", "cancel_option_order")


def _all_phase8_files():
    return [REPO_ROOT / "src" / "research" / name for name in PHASE8_SRC_MODULES] + list(PHASE8_SCRIPTS)


def test_no_phase8_module_imports_the_live_execution_or_orchestrator_path():
    for path in _all_phase8_files():
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in FORBIDDEN_IMPORT_PREFIXES:
                    assert not node.module.startswith(prefix), f"{path} imports {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in FORBIDDEN_IMPORT_PREFIXES:
                        assert not alias.name.startswith(prefix), f"{path} imports {alias.name}"


def test_no_phase8_module_references_a_live_order_placement_call():
    for path in _all_phase8_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase8_script_functionally_touches_mr002():
    """MR-002 must remain untouched. A COMMENT explaining that MR-002's
    Phase 5/6 experience was deliberately NOT used to influence parameter
    selection (Part 5's explicit instruction) is fine and expected — what
    must never appear is a functional touch: loading FrozenStrategyStore,
    looking up "MR-002" as a hypothesis_id/strategy_id, or importing
    src.research.frozen_strategy."""
    forbidden_functional_patterns = ('FrozenStrategyStore', 'frozen_strategy', 'hypothesis_id="MR-002"', "hypothesis_id='MR-002'", 'strategy_id="MR-002"', "strategy_id='MR-002'", '.get("MR-002"', ".get('MR-002'")
    for path in PHASE8_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_functional_patterns:
            assert pattern not in source, f"{path} functionally references MR-002 via {pattern!r}"


def test_no_phase8_script_touches_validation_or_final_holdout_data():
    """Static guarantee: no Phase 8 script references VALIDATION_DATA or
    FINAL_HOLDOUT_DATA partitions by name in a way that could load them."""
    for path in PHASE8_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source


# --- preregistration requirement -----------------------------------------------------------


def test_dev_hypothesis_cannot_run_without_preregistration(tmp_path):
    store = PreregistrationStore(tmp_path / "prereg.jsonl")
    with pytest.raises(PreregistrationError):
        require_preregistered(store, "P7-VOLANOM-A-DEV1")


def test_dev_hypothesis_runs_once_preregistered(tmp_path):
    from datetime import datetime, timezone

    from src.research.preregistration import PreregistrationRecord

    store = PreregistrationStore(tmp_path / "prereg.jsonl")
    store.register(PreregistrationRecord(
        hypothesis_id="P7-VOLANOM-A-DEV1", hypothesis_version="1.0", rationale="r", expected_direction="positive",
        target_definition="t", features=("relative_volume_10",), universe_name="U", time_horizon_bars=5,
        parameter_ranges={}, validation_methodology="m", cost_assumptions="c", success_criteria=(), falsification_criteria=(),
        registered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ))
    record = require_preregistered(store, "P7-VOLANOM-A-DEV1")
    assert record.hypothesis_id == "P7-VOLANOM-A-DEV1"


# --- development-only data access / holdout isolation ---------------------------------------


def test_development_only_partitions_allow_parameter_selection():
    from datetime import date, datetime, timezone

    from src.research.partition import ResearchDatasetPartition

    discovery = ResearchDatasetPartition(dataset_id="d", universe_name="U", start_date=date(2021, 1, 1), end_date=date(2022, 1, 1), partition_type=PartitionLifecycleStage.DISCOVERY, created_at=datetime.now(timezone.utc), source_version="v", data_version="v", feature_version="v", status="ACTIVE", immutable=True)
    development = ResearchDatasetPartition(dataset_id="d2", universe_name="U", start_date=date(2022, 1, 2), end_date=date(2023, 1, 1), partition_type=PartitionLifecycleStage.DEVELOPMENT, created_at=datetime.now(timezone.utc), source_version="v", data_version="v", feature_version="v", status="ACTIVE", immutable=True)
    assert_stage_allows_parameter_selection(discovery, context="test")
    assert_stage_allows_parameter_selection(development, context="test")


def test_validation_and_final_holdout_partitions_block_parameter_selection():
    from datetime import date, datetime, timezone

    from src.research.partition import PartitionAccessError, ResearchDatasetPartition

    validation = ResearchDatasetPartition(dataset_id="d3", universe_name="U", start_date=date(2023, 1, 2), end_date=date(2023, 6, 1), partition_type=PartitionLifecycleStage.VALIDATION, created_at=datetime.now(timezone.utc), source_version="v", data_version="v", feature_version="v", status="ACTIVE", immutable=True)
    holdout = ResearchDatasetPartition(dataset_id="d4", universe_name="U", start_date=date(2023, 6, 2), end_date=date(2024, 1, 1), partition_type=PartitionLifecycleStage.FINAL_HOLDOUT, created_at=datetime.now(timezone.utc), source_version="v", data_version="v", feature_version="v", status="ACTIVE", immutable=True)
    with pytest.raises(PartitionAccessError):
        assert_stage_allows_parameter_selection(validation, context="phase8 grid search")
    with pytest.raises(PartitionAccessError):
        assert_stage_allows_parameter_selection(holdout, context="phase8 grid search")


def test_the_actual_phase7_partitions_file_has_the_expected_stages_and_holdout_is_untouched_by_phase8():
    """If the real Phase 7 partition file is present, confirm the holdout
    stage exists and is distinct from what Phase 8's dev scripts read."""
    path = Path("logs/research_data/phase7_partitions.jsonl")
    if not path.is_file():
        pytest.skip("phase7_partitions.jsonl not present in this environment")
    store = PartitionStore(path)
    holdout_partitions = store.active_by_stage(PartitionLifecycleStage.FINAL_HOLDOUT)
    dev_partitions = store.active_by_stage(PartitionLifecycleStage.DEVELOPMENT)
    assert holdout_partitions and dev_partitions
    assert holdout_partitions[0].start_date > dev_partitions[0].end_date  # strictly later, non-overlapping


# --- parent hypothesis immutability ----------------------------------------------------------


def test_parent_hypothesis_record_is_never_modified_by_registering_a_dev_version(tmp_path):
    registry = HypothesisRegistry(tmp_path / "hyps.jsonl")
    parent = Hypothesis(
        hypothesis_id="P7-VOLANOM-A", name="parent", description="d", economic_intuition="e", mathematical_definition="feature=RelativeVolume(10)",
        required_data=(), required_features=("relative_volume_10",), prediction_horizon_bars=5, test_methodology="t",
        expected_direction="positive", assumptions=(),
    )
    registry.register(parent)
    before = registry.get("P7-VOLANOM-A")

    dev = Hypothesis(
        hypothesis_id="P7-VOLANOM-A-DEV1", name="dev", description="d", economic_intuition="e", mathematical_definition="m2",
        required_data=(), required_features=(), prediction_horizon_bars=5, test_methodology="t", expected_direction="positive",
        assumptions=(), parent_hypothesis_id="P7-VOLANOM-A", development_version="DEV1",
    )
    registry.register(dev)

    after = registry.get("P7-VOLANOM-A")
    assert before == after  # byte-for-byte unchanged
    assert before.mathematical_definition == "feature=RelativeVolume(10)"

    dev_loaded = registry.get("P7-VOLANOM-A-DEV1")
    assert dev_loaded.parent_hypothesis_id == "P7-VOLANOM-A"


def test_the_actual_phase8_gate_transitions_file_never_mentions_mr002():
    """Data-level check (not just source-scanning): if the real Phase 8
    gate-transition log is present, confirm no record in it concerns
    MR-002."""
    path = Path("logs/research_data/phase8_gate_transitions.jsonl")
    if not path.is_file():
        pytest.skip("phase8_gate_transitions.jsonl not present in this environment")
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        assert record.get("hypothesis_id") != "MR-002"


def test_cannot_register_a_second_hypothesis_under_the_same_id_as_the_parent(tmp_path):
    """The registry's existing append-only guard already forbids
    re-registering P7-VOLANOM-A under its own ID — confirms Phase 8 cannot
    accidentally overwrite the frozen parent."""
    from src.research.hypothesis import HypothesisRegistryError

    registry = HypothesisRegistry(tmp_path / "hyps.jsonl")
    parent = Hypothesis(
        hypothesis_id="P7-VOLANOM-A", name="parent", description="d", economic_intuition="e", mathematical_definition="original",
        required_data=(), required_features=(), prediction_horizon_bars=5, test_methodology="t", expected_direction="positive", assumptions=(),
    )
    registry.register(parent)
    tampered = Hypothesis(
        hypothesis_id="P7-VOLANOM-A", name="tampered", description="d", economic_intuition="e", mathematical_definition="MODIFIED",
        required_data=(), required_features=(), prediction_horizon_bars=5, test_methodology="t", expected_direction="positive", assumptions=(),
    )
    with pytest.raises(HypothesisRegistryError):
        registry.register(tampered)
