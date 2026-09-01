"""Phase 9 Final Safety Check: discovery-only data access, no live/paper
orders, MR-002 untouched, P7-VOLANOM-A / P7-VOLANOM-A-DEV1 untouched
(read-only lookups only), no VALIDATION_DATA/FINAL_HOLDOUT_DATA access,
and the new DiscoveryDevelopmentStage gate is capped at
PAPER_TRADING_ELIGIBLE for anything code can set automatically.

Mirrors tests/test_phase8_safety.py's exact pattern for the new Phase 9
surface area (src/features/volume_clustering.py,
src/research/volatility_targets.py, src/research/regression.py,
src/research/discovery_development_gate.py, src/research/pearson_ic.py,
scripts/phase9_*.py).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.research.discovery_development_gate import CODE_COMPUTABLE_STAGES, DiscoveryDevelopmentStage
from src.research.hypothesis import Hypothesis, HypothesisRegistry
from src.research.preregistration import PreregistrationError, PreregistrationStore, require_preregistered

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE9_SRC_MODULES = [
    "src/features/volume_clustering.py",
    "src/research/volatility_targets.py",
    "src/research/regression.py",
    "src/research/discovery_development_gate.py",
    "src/research/pearson_ic.py",
]
PHASE9_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase9_*.py"))
FORBIDDEN_IMPORT_PREFIXES = ("src.execution", "src.orchestrator")
FORBIDDEN_CALLS = ("place_equity_order", "place_option_order", "place_crypto_order", "submit_order", "cancel_equity_order", "cancel_option_order")


def _all_phase9_files():
    return [REPO_ROOT / rel for rel in PHASE9_SRC_MODULES] + list(PHASE9_SCRIPTS)


def test_no_phase9_module_imports_the_live_execution_or_orchestrator_path():
    for path in _all_phase9_files():
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


def test_no_phase9_module_references_a_live_order_placement_call():
    for path in _all_phase9_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase9_script_functionally_touches_mr002():
    """MR-002 must remain untouched. What must never appear is a
    functional touch: loading FrozenStrategyStore, looking up "MR-002" as
    a hypothesis_id/strategy_id, or importing src.research.frozen_strategy."""
    forbidden_functional_patterns = ('FrozenStrategyStore', 'frozen_strategy', 'hypothesis_id="MR-002"', "hypothesis_id='MR-002'", 'strategy_id="MR-002"', "strategy_id='MR-002'", '.get("MR-002"', ".get('MR-002'")
    for path in PHASE9_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_functional_patterns:
            assert pattern not in source, f"{path} functionally references MR-002 via {pattern!r}"


def test_no_phase9_script_touches_validation_or_final_holdout_data():
    """Static guarantee: no Phase 9 script references VALIDATION_DATA or
    FINAL_HOLDOUT_DATA partitions by name in a way that could load them.
    Only PartitionLifecycleStage.DISCOVERY may appear."""
    for path in PHASE9_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase9_script_writes_to_p7_volanom_a_or_dev1():
    """P7-VOLANOM-A and P7-VOLANOM-A-DEV1 may only be READ (via
    HypothesisRegistry.get) this phase — never re-registered, never
    passed to a gate-transition or preregistration write call."""
    forbidden_write_patterns = (
        'hyp_registry.register(parent)', 'hyp_registry.register(dev)',
        'gate_store.transition(hypothesis_id="P7-VOLANOM-A"', "gate_store.transition(hypothesis_id='P7-VOLANOM-A'",
        'gate_store.transition(hypothesis_id="P7-VOLANOM-A-DEV1"', "gate_store.transition(hypothesis_id='P7-VOLANOM-A-DEV1'",
    )
    for path in PHASE9_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_write_patterns:
            assert pattern not in source, f"{path} appears to write to the parent/sibling hypothesis via {pattern!r}"


def test_discovery_development_stage_is_capped_for_code():
    """No code path in this phase can set the gate beyond
    PAPER_TRADING_ELIGIBLE — HUMAN_APPROVAL and everything after it stays
    a human decision."""
    assert DiscoveryDevelopmentStage.PAPER_TRADING_ELIGIBLE in CODE_COMPUTABLE_STAGES
    assert DiscoveryDevelopmentStage.HUMAN_APPROVAL not in CODE_COMPUTABLE_STAGES
    assert DiscoveryDevelopmentStage.PAPER_TRADING not in CODE_COMPUTABLE_STAGES
    assert DiscoveryDevelopmentStage.LIVE_TRADING not in CODE_COMPUTABLE_STAGES


def test_phase9_step2_script_never_reaches_development_or_validation_stage():
    """Static guarantee: the discovery-only script only ever transitions
    P9-VOLCLUST-A through IDEA/PREREGISTERED/DISCOVERY_TESTED/
    DISCOVERY_SUPPORTED/NOT_READY — never DEVELOPMENT_* or beyond."""
    forbidden_stage_names = (
        "DEVELOPMENT_PREREGISTERED", "DEVELOPMENT_TESTED", "DEVELOPMENT_SUPPORTED",
        "VALIDATION", "HOLDOUT", "PAPER_TRADING_ELIGIBLE", "HUMAN_APPROVAL", "PAPER_TRADING", "LIVE_ELIGIBLE", "LIVE_TRADING",
    )
    for path in PHASE9_SCRIPTS:
        source = path.read_text()
        for stage in forbidden_stage_names:
            assert f"DiscoveryDevelopmentStage.{stage}" not in source, f"{path} references DiscoveryDevelopmentStage.{stage}"


# --- preregistration requirement -----------------------------------------------------------


def test_p9_hypothesis_cannot_run_without_preregistration(tmp_path):
    store = PreregistrationStore(tmp_path / "prereg.jsonl")
    with pytest.raises(PreregistrationError):
        require_preregistered(store, "P9-VOLCLUST-A")


def test_p9_hypothesis_runs_once_preregistered(tmp_path):
    from datetime import datetime, timezone

    from src.research.preregistration import PreregistrationRecord

    store = PreregistrationStore(tmp_path / "prereg.jsonl")
    store.register(PreregistrationRecord(
        hypothesis_id="P9-VOLCLUST-A", hypothesis_version="1.0", rationale="r", expected_direction="positive",
        target_definition="t", features=("relative_volume_10",), universe_name="U", time_horizon_bars=5,
        parameter_ranges={}, validation_methodology="m", cost_assumptions="c", success_criteria=(), falsification_criteria=(),
        registered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ))
    record = require_preregistered(store, "P9-VOLCLUST-A")
    assert record.hypothesis_id == "P9-VOLCLUST-A"


# --- parent-hypothesis immutability (P9 is registered with parent_hypothesis_id, never mutating it) ---


def test_p9_hypothesis_is_not_a_parameter_variation_of_its_parent(tmp_path):
    registry = HypothesisRegistry(tmp_path / "hyps.jsonl")
    parent = Hypothesis(
        hypothesis_id="P7-VOLANOM-A", name="parent", description="d", economic_intuition="e", mathematical_definition="feature=RelativeVolume(10)",
        required_data=(), required_features=("relative_volume_10",), prediction_horizon_bars=5, test_methodology="t",
        expected_direction="positive", assumptions=(),
    )
    registry.register(parent)
    before = registry.get("P7-VOLANOM-A")

    p9 = Hypothesis(
        hypothesis_id="P9-VOLCLUST-A", name="p9", description="d", economic_intuition="e", mathematical_definition="m2",
        required_data=(), required_features=(), prediction_horizon_bars=5, test_methodology="t", expected_direction="positive",
        assumptions=(), parent_hypothesis_id="P7-VOLANOM-A", development_version=None,
    )
    registry.register(p9)

    after = registry.get("P7-VOLANOM-A")
    assert before == after  # byte-for-byte unchanged by registering the new, related hypothesis
    p9_loaded = registry.get("P9-VOLCLUST-A")
    assert p9_loaded.parent_hypothesis_id == "P7-VOLANOM-A"
    assert p9_loaded.development_version is None  # NOT a development version of the parent


def test_the_actual_phase9_gate_transitions_file_never_mentions_mr002():
    """Data-level check: if the real Phase 9 gate-transition log is
    present, confirm no record in it concerns MR-002."""
    path = Path("logs/research_data/phase9_gate_transitions.jsonl")
    if not path.is_file():
        pytest.skip("phase9_gate_transitions.jsonl not present in this environment")
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        assert record.get("hypothesis_id") != "MR-002"


def test_the_actual_phase9_gate_transitions_file_never_touches_p7_volanom_a():
    """Data-level check: the real Phase 9 gate-transition log only ever
    concerns P9-VOLCLUST-A — never re-transitions the parent or sibling."""
    path = Path("logs/research_data/phase9_gate_transitions.jsonl")
    if not path.is_file():
        pytest.skip("phase9_gate_transitions.jsonl not present in this environment")
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        assert record.get("hypothesis_id") not in ("P7-VOLANOM-A", "P7-VOLANOM-A-DEV1")
