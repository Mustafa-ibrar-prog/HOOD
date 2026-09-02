"""Phase 10 Final Safety Check: discovery-only data access, no live/paper
orders, MR-002 untouched, P7-VOLANOM-A / P7-VOLANOM-A-DEV1 / P9-VOLCLUST-A
untouched (read-only lookups only), no DEVELOPMENT_DATA/VALIDATION_DATA/
FINAL_HOLDOUT_DATA access, and every P10-VP-* hypothesis stays capped
below PAPER_TRADING_ELIGIBLE for code.

Mirrors tests/test_phase8_safety.py / tests/test_phase9_safety.py's exact
pattern for the Phase 10 surface area.
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

PHASE10_SRC_MODULES = [
    "src/features/volatility_persistence.py",
    "src/research/phase10_targets.py",
    "src/research/regime_transitions.py",
    "src/research/state_conditional_stats.py",
]
PHASE10_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase10_*.py"))
FORBIDDEN_IMPORT_PREFIXES = ("src.execution", "src.orchestrator")
FORBIDDEN_CALLS = ("place_equity_order", "place_option_order", "place_crypto_order", "submit_order", "cancel_equity_order", "cancel_option_order")
P10_HYPOTHESIS_IDS = tuple(f"P10-VP-{i:03d}" for i in range(1, 11))


def _all_phase10_files():
    return [REPO_ROOT / rel for rel in PHASE10_SRC_MODULES] + list(PHASE10_SCRIPTS)


def test_no_phase10_module_imports_the_live_execution_or_orchestrator_path():
    for path in _all_phase10_files():
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


def test_no_phase10_module_references_a_live_order_placement_call():
    for path in _all_phase10_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase10_script_functionally_touches_mr002():
    forbidden_functional_patterns = ('FrozenStrategyStore', 'frozen_strategy', 'hypothesis_id="MR-002"', "hypothesis_id='MR-002'", 'strategy_id="MR-002"', "strategy_id='MR-002'", '.get("MR-002"', ".get('MR-002'")
    for path in PHASE10_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_functional_patterns:
            assert pattern not in source, f"{path} functionally references MR-002 via {pattern!r}"


def test_no_phase10_script_touches_development_validation_or_final_holdout_data():
    """Static guarantee: no Phase 10 script references DEVELOPMENT_DATA,
    VALIDATION_DATA, or FINAL_HOLDOUT_DATA partitions by name. Only
    PartitionLifecycleStage.DISCOVERY may appear."""
    for path in PHASE10_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase10_script_writes_to_a_prior_phase_hypothesis():
    """P7-VOLANOM-A, P7-VOLANOM-A-DEV1, and P9-VOLCLUST-A may only be
    READ this phase — never re-registered, never passed to a
    gate-transition or preregistration write call."""
    forbidden_write_patterns = tuple(
        f'gate_store.transition(hypothesis_id="{hid}"' for hid in ("P7-VOLANOM-A", "P7-VOLANOM-A-DEV1", "P9-VOLCLUST-A")
    ) + tuple(
        f"gate_store.transition(hypothesis_id='{hid}'" for hid in ("P7-VOLANOM-A", "P7-VOLANOM-A-DEV1", "P9-VOLCLUST-A")
    ) + ("hyp_registry.register(parent)",)
    for path in PHASE10_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_write_patterns:
            assert pattern not in source, f"{path} appears to write to a prior-phase hypothesis via {pattern!r}"


def test_discovery_development_stage_is_capped_for_code():
    assert DiscoveryDevelopmentStage.PAPER_TRADING_ELIGIBLE in CODE_COMPUTABLE_STAGES
    assert DiscoveryDevelopmentStage.HUMAN_APPROVAL not in CODE_COMPUTABLE_STAGES
    assert DiscoveryDevelopmentStage.PAPER_TRADING not in CODE_COMPUTABLE_STAGES
    assert DiscoveryDevelopmentStage.LIVE_TRADING not in CODE_COMPUTABLE_STAGES


def test_phase10_step2_script_never_reaches_development_or_beyond():
    """Static guarantee: the discovery-only script only ever transitions
    P10-VP-* hypotheses through IDEA/PREREGISTERED/DISCOVERY_TESTED/
    DISCOVERY_SUPPORTED/NOT_READY (Part 27's explicit cap) — never
    DEVELOPMENT_* or beyond."""
    forbidden_stage_names = (
        "DEVELOPMENT_PREREGISTERED", "DEVELOPMENT_TESTED", "DEVELOPMENT_SUPPORTED",
        "VALIDATION", "HOLDOUT", "PAPER_TRADING_ELIGIBLE", "HUMAN_APPROVAL", "PAPER_TRADING", "LIVE_ELIGIBLE", "LIVE_TRADING",
    )
    for path in PHASE10_SCRIPTS:
        source = path.read_text()
        for stage in forbidden_stage_names:
            assert f"DiscoveryDevelopmentStage.{stage}" not in source, f"{path} references DiscoveryDevelopmentStage.{stage}"


def test_no_phase10_script_creates_a_trading_strategy_class():
    """Part 24: this phase is DISCOVERY ONLY — no live/paper/trading
    strategy class or position-sizing system may be created here."""
    forbidden_patterns = ("class VolatilityRegimeStrategy", "class VolatilityTargetedStrategy", "class VolatilityBreakoutStrategy", "PositionSizer(")
    for path in PHASE10_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to define a trading strategy: {pattern!r}"


# --- preregistration requirement -----------------------------------------------------------


@pytest.mark.parametrize("hyp_id", P10_HYPOTHESIS_IDS + ("P10-VOLPERSIST",))
def test_p10_hypothesis_cannot_run_without_preregistration(tmp_path, hyp_id):
    store = PreregistrationStore(tmp_path / "prereg.jsonl")
    with pytest.raises(PreregistrationError):
        require_preregistered(store, hyp_id)


def test_p10_hypothesis_runs_once_preregistered(tmp_path):
    from datetime import datetime, timezone

    from src.research.preregistration import PreregistrationRecord

    store = PreregistrationStore(tmp_path / "prereg.jsonl")
    store.register(PreregistrationRecord(
        hypothesis_id="P10-VP-001", hypothesis_version="1.0", rationale="r", expected_direction="positive",
        target_definition="future_realized_volatility", features=("realized_vol_20",), universe_name="U", time_horizon_bars=5,
        parameter_ranges={}, validation_methodology="m", cost_assumptions="c", success_criteria=(), falsification_criteria=(),
        registered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ))
    record = require_preregistered(store, "P10-VP-001")
    assert record.hypothesis_id == "P10-VP-001"


# --- parent-hypothesis immutability (P10 hypotheses have NO parent — a genuinely new family) ----


def test_p10_hypotheses_have_no_parent_and_do_not_mutate_prior_phase_hypotheses(tmp_path):
    registry = HypothesisRegistry(tmp_path / "hyps.jsonl")
    parent = Hypothesis(
        hypothesis_id="P9-VOLCLUST-A", name="parent", description="d", economic_intuition="e", mathematical_definition="original",
        required_data=(), required_features=(), prediction_horizon_bars=5, test_methodology="t", expected_direction="positive", assumptions=(),
    )
    registry.register(parent)
    before = registry.get("P9-VOLCLUST-A")

    p10 = Hypothesis(
        hypothesis_id="P10-VP-001", name="p10", description="d", economic_intuition="e", mathematical_definition="m2",
        required_data=(), required_features=(), prediction_horizon_bars=5, test_methodology="t", expected_direction="positive",
        assumptions=(), parent_hypothesis_id=None, development_version=None,
    )
    registry.register(p10)

    after = registry.get("P9-VOLCLUST-A")
    assert before == after  # byte-for-byte unchanged
    p10_loaded = registry.get("P10-VP-001")
    assert p10_loaded.parent_hypothesis_id is None  # a genuinely NEW family, not derived from any prior hypothesis


def test_the_actual_phase10_gate_transitions_file_never_mentions_mr002_or_prior_phase_hypotheses():
    path = Path("logs/research_data/phase10_gate_transitions.jsonl")
    if not path.is_file():
        pytest.skip("phase10_gate_transitions.jsonl not present in this environment")
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        assert record.get("hypothesis_id") not in ("MR-002", "P7-VOLANOM-A", "P7-VOLANOM-A-DEV1", "P9-VOLCLUST-A")


def test_the_actual_phase10_gate_transitions_file_never_exceeds_discovery_supported():
    """Data-level check: no recorded transition in the real Phase 10 gate
    log ever reaches DEVELOPMENT_* or beyond."""
    path = Path("logs/research_data/phase10_gate_transitions.jsonl")
    if not path.is_file():
        pytest.skip("phase10_gate_transitions.jsonl not present in this environment")
    allowed = {"IDEA", "PREREGISTERED", "DISCOVERY_TESTED", "DISCOVERY_SUPPORTED", "NOT_READY"}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        assert record.get("to_stage") in allowed, f"unexpected stage reached: {record.get('to_stage')}"
