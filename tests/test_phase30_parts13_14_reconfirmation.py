"""Phase 30, Parts 13-14/17 — reconfirmation (not modification) of the
autonomous architecture chain and OPTIONS_ONLY structural enforcement.

No src/ change belongs to these parts -- Phase 28 built `system_state.py`
and the autonomous architecture audit; Phase 28/29 already confirmed
OPTIONS_ONLY. This file re-verifies both remain exactly as they were,
the same discipline Phase 29's own safety test applied to Phase 28's
work.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_system_state_still_exactly_seven_states_no_per_trade_approval():
    from src.execution.system_state import SystemState

    assert len(SystemState) == 7
    names = {s.name for s in SystemState}
    assert names == {
        "RESEARCH", "PAPER_TRADING", "PAPER_VALIDATED", "HUMAN_LIVE_AUTHORIZATION",
        "LIVE_AUTONOMOUS_TRADING", "LIVE_PAUSED", "EMERGENCY_STOP",
    }
    assert "WAITING_FOR_TRADE_APPROVAL" not in names
    assert not any("PER_TRADE" in n or "TRADE_APPROVAL" in n for n in names)


def test_code_computable_states_unchanged():
    from src.execution.system_state import CODE_COMPUTABLE_STATES, SystemState

    assert CODE_COMPUTABLE_STATES == frozenset({SystemState.RESEARCH, SystemState.PAPER_TRADING, SystemState.PAPER_VALIDATED})


def test_human_authorized_transition_still_rejects_system_authorized_by():
    from src.execution.system_state import SystemState, record_human_authorized_transition
    import pytest

    with pytest.raises(ValueError):
        record_human_authorized_transition(
            SystemState.PAPER_VALIDATED, SystemState.HUMAN_LIVE_AUTHORIZATION,
            authorized_by="system:auto", reason="test",
        )


def test_autonomous_pipeline_still_fifteen_stages_none_missing():
    from src.execution.autonomous_architecture_audit import PIPELINE_READINESS, ReadinessStatus

    assert len(PIPELINE_READINESS) == 15
    assert all(a.status != ReadinessStatus.MISSING for a in PIPELINE_READINESS)


def test_live_auto_execute_path_still_exists_unmodified():
    """The pre-existing no-per-trade-approval mechanism Phase 28 audited
    (live_auto_execute -> _place_pending(approved_by='system:auto_execute'))
    must still exist -- Phase 30 does not touch execution/gateway.py."""
    src = (REPO_ROOT / "src/execution/gateway.py").read_text()
    assert "live_auto_execute" in src
    assert "system:auto_execute" in src


def test_options_only_structural_enforcement_still_holds():
    src = (REPO_ROOT / "src/execution/orders.py").read_text()
    assert "class OrderLeg" in src
    assert "option_id: str" in src
    # No equity/share order shape exists anywhere in the real order types.
    assert "share_quantity" not in src
    assert "class EquityOrderLeg" not in src


def test_no_phase30_module_imports_the_live_order_placement_path():
    import ast

    phase30_modules = [
        "src/options/research_dataset.py", "src/options/research_features.py",
        "src/options/contract_selection.py", "src/options/research_opportunity_score.py",
        "src/options/affordability.py", "src/options/execution_realism_pricing.py",
        "src/options/research_position_view.py", "src/options/research_risk_engine.py",
        "src/options/research_events.py", "src/options/free_dataset_limitations.py",
        "src/options/live_research_bridge.py",
    ]
    forbidden_prefixes = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
    for rel in phase30_modules:
        path = REPO_ROOT / rel
        assert path.is_file(), f"missing {rel}"
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in forbidden_prefixes:
                    assert not node.module.startswith(prefix), f"{path} imports {node.module}"
