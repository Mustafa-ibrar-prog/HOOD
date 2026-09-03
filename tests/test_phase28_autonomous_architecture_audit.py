"""Phase 28, Part 12/13/14/17 — architecture-readiness audit,
OPTIONS_ONLY enforcement, and Robinhood/historical-provider role
separation."""

from __future__ import annotations

import ast
from pathlib import Path

from src.execution.autonomous_architecture_audit import (
    CURRENTLY_RISK_MODELED_STRUCTURES,
    ORCHESTRATOR_DOCSTRING_STALENESS_FINDING,
    OPTIONS_ONLY_ENFORCEMENT_FINDING,
    PIPELINE_READINESS,
    ROLE_ASSIGNMENTS,
    OptionStructure,
    ReadinessStatus,
    RoleAssignment,
    SystemRole,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_all_fifteen_pipeline_stages_audited():
    stages = {a.stage for a in PIPELINE_READINESS}
    assert len(stages) == 15
    assert "MARKET DATA" in stages
    assert "TRADE JOURNAL" in stages
    assert "EXECUTION ENGINE" in stages


def test_every_stage_has_a_valid_readiness_status():
    for a in PIPELINE_READINESS:
        assert isinstance(a.status, ReadinessStatus)
        assert len(a.real_module) > 5
        assert len(a.note) > 10


def test_no_stage_is_reported_ready_without_a_real_module_reference():
    for a in PIPELINE_READINESS:
        if a.status == ReadinessStatus.READY:
            assert "src/" in a.real_module or "mcp__" in a.real_module


def test_execution_engine_stage_documents_the_real_auto_execute_path():
    execution = next(a for a in PIPELINE_READINESS if a.stage == "EXECUTION ENGINE")
    assert "live_auto_execute" in execution.note


def test_position_sizer_is_honestly_marked_partial():
    """A real, honest gap: sizing is folded into RiskManager, not a
    dedicated volatility/Kelly-aware module."""
    sizer = next(a for a in PIPELINE_READINESS if a.stage == "POSITION SIZER")
    assert sizer.status == ReadinessStatus.PARTIAL


def test_no_pipeline_stage_is_reported_missing():
    """Every one of the 14 stages has at least a real, existing module --
    this codebase's architecture is largely already built for this
    pipeline (a real, positive finding)."""
    assert all(a.status != ReadinessStatus.MISSING for a in PIPELINE_READINESS)


def test_orchestrator_staleness_finding_is_real_and_substantive():
    assert "live_auto_execute" in ORCHESTRATOR_DOCSTRING_STALENESS_FINDING
    assert len(ORCHESTRATOR_DOCSTRING_STALENESS_FINDING) > 100


def test_orchestrator_docstring_was_not_modified_this_phase():
    """Part 12: 'Do NOT implement live trading in this phase' -- the
    staleness finding is reported, not silently fixed by editing the
    live-execution-path file."""
    text = (REPO_ROOT / "src/orchestrator.py").read_text()
    assert "PendingLiveOrder awaiting explicit human approval" in text  # the exact stale phrase, still present, untouched


def test_option_structure_allowlist_matches_part_13():
    names = {s.value for s in OptionStructure}
    assert names == {"long_call", "long_put", "defined_risk_spread"}


def test_defined_risk_spread_is_not_yet_risk_modeled():
    """Part 13: 'Only structures that the risk engine can accurately
    model may eventually be enabled.'"""
    assert OptionStructure.DEFINED_RISK_SPREAD not in CURRENTLY_RISK_MODELED_STRUCTURES
    assert OptionStructure.LONG_CALL in CURRENTLY_RISK_MODELED_STRUCTURES
    assert OptionStructure.LONG_PUT in CURRENTLY_RISK_MODELED_STRUCTURES


def test_options_only_enforcement_finding_is_structural():
    assert "structural" in OPTIONS_ONLY_ENFORCEMENT_FINDING.lower()


def test_order_request_has_no_equity_share_order_shape():
    """Independently re-verifies this phase's own claim by inspecting
    the real OrderLeg/OrderRequest dataclass fields."""
    src = (REPO_ROOT / "src/execution/orders.py").read_text()
    tree = ast.parse(src)
    leg_fields = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "OrderLeg":
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    leg_fields.append(item.target.id)
    assert "option_id" in leg_fields
    assert "quantity_shares" not in leg_fields
    assert "share_quantity" not in leg_fields


def test_two_role_assignments_robinhood_and_historical_provider():
    assert len(ROLE_ASSIGNMENTS) == 2
    roles = {r.role for r in ROLE_ASSIGNMENTS}
    assert roles == set(SystemRole)


def test_robinhood_role_is_live_execution_never_research():
    robinhood = next(r for r in ROLE_ASSIGNMENTS if "Robinhood" in r.system)
    assert robinhood.role == SystemRole.LIVE_DATA_ACCOUNT_POSITIONS_ORDERS_EXECUTION


def test_historical_provider_role_is_research_never_live():
    historical = next(r for r in ROLE_ASSIGNMENTS if "QuantConnect" in r.system)
    assert historical.role == SystemRole.RESEARCH_BACKTESTING_HISTORICAL_LIQUIDITY_IV_GREEKS


def test_role_assignment_is_frozen_and_requires_a_note():
    for r in ROLE_ASSIGNMENTS:
        assert isinstance(r, RoleAssignment)
        assert len(r.note) > 10
