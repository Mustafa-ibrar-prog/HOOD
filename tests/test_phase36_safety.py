"""Phase 36 Final Safety Check (Part 21/22): production strategy contract
+ live decision pipeline ARCHITECTURE only -- no live order, no paper
order, no strategy deployed, no strategy declared VALIDATED without a
genuine artifact, no paid data/provider, no live authorization active,
emergency stop active by default, MomentumBreakoutStrategy remains
NOT_READY.

Same AST-based string/comment-blanking technique established in Phase
28-35's safety tests.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE36_SRC_MODULES = [
    "src/production/__init__.py",
    "src/production/provenance.py",
    "src/production/decision.py",
    "src/production/live_snapshot.py",
    "src/production/snapshot.py",
    "src/production/strategy_interface.py",
    "src/production/timestamps.py",
    "src/production/contract_validation.py",
    "src/production/liquidity.py",
    "src/production/opportunity.py",
    "src/production/registry.py",
    "src/production/validation_artifact.py",
    "src/production/risk_handoff.py",
    "src/production/ranking.py",
    "src/production/failure_modes.py",
    "src/production/pipeline.py",
    "src/production/momentum_breakout_adapter.py",
]
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order",
    "cancel_equity_order", "cancel_option_order", "review_option_order", "review_equity_order",
    "simulate_paper_order", "simulate_paper_exit",
)


def _all_phase36_files():
    return [REPO_ROOT / rel for rel in PHASE36_SRC_MODULES]


def _string_literal_spans(path: Path) -> list[tuple[int, int, int, int]]:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and hasattr(node, "end_col_offset"):
            spans.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset))
    return spans


def _code_with_string_literals_and_comments_blanked(path: Path) -> str:
    lines = path.read_text().splitlines(keepends=True)
    for lineno, col, end_lineno, end_col in _string_literal_spans(path):
        if lineno == end_lineno:
            line = lines[lineno - 1]
            lines[lineno - 1] = line[:col] + "_" * (end_col - col) + line[end_col:]
        else:
            for ln in range(lineno, end_lineno + 1):
                line = lines[ln - 1]
                start = col if ln == lineno else 0
                end = end_col if ln == end_lineno else len(line.rstrip("\n"))
                lines[ln - 1] = line[:start] + "_" * (end - start) + line[end:]
    for i, line in enumerate(lines):
        hash_pos = line.find("#")
        if hash_pos != -1:
            lines[i] = line[:hash_pos] + "\n" if line.endswith("\n") else line[:hash_pos]
    return "".join(lines)


def test_phase36_files_exist():
    for rel in PHASE36_SRC_MODULES:
        assert (REPO_ROOT / rel).is_file(), f"missing {rel}"


def test_no_phase36_file_calls_a_live_paper_or_simulated_order_function():
    for path in _all_phase36_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        for call in FORBIDDEN_CALLS:
            assert f"{call}(" not in source, f"{path} appears to call {call!r} outside a string/comment"


def test_no_phase36_file_calls_submit_order_or_confirm_and_place():
    for path in _all_phase36_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        assert "submit_order(" not in source, f"{path} calls submit_order"
        assert "confirm_and_place(" not in source, f"{path} calls confirm_and_place"


def test_no_phase36_file_records_a_human_authorized_system_state_transition():
    for path in _all_phase36_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        assert "record_human_authorized_transition(" not in source, f"{path} calls record_human_authorized_transition"
        assert "record_code_transition(" not in source, f"{path} calls record_code_transition"


def test_no_phase36_file_clears_or_activates_the_emergency_stop():
    for path in _all_phase36_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        assert ".clear(" not in source, f"{path} appears to clear the emergency stop"
        assert ".activate(" not in source, f"{path} appears to activate the emergency stop"


def test_no_phase36_file_marks_a_strategy_validated_directly():
    """Only StrategyRegistry.mark_validated (registry.py itself, which
    requires a real ValidationArtifact) may ever transition a status to
    VALIDATED/LIVE_AUTHORIZED -- no OTHER phase36 file may call it or
    construct a StrategyMetadata with that status directly."""
    for path in _all_phase36_files():
        if path.name in ("registry.py",):
            continue
        source = _code_with_string_literals_and_comments_blanked(path)
        assert "StrategyStatus.VALIDATED" not in source, f"{path} references StrategyStatus.VALIDATED directly"
        assert "StrategyStatus.LIVE_AUTHORIZED" not in source, f"{path} references StrategyStatus.LIVE_AUTHORIZED directly"
        assert ".mark_validated(" not in source, f"{path} calls mark_validated"


def test_no_phase36_file_purchases_or_activates_a_paid_provider():
    forbidden_patterns = ("purchase(", "create_account(", "stripe.", "checkout.", "ORATS_API_KEY = \"", "ORATS_API_KEY='")
    for path in _all_phase36_files():
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to purchase/activate a paid provider via {pattern!r}"


def test_orchestrator_does_not_import_the_production_pipeline():
    """Phase 36 is explicitly 'connect ... without activating it' -- the
    real live orchestrator must NOT call run_live_decision_cycle or
    import anything from src.production this phase."""
    source = (REPO_ROOT / "src/orchestrator.py").read_text()
    assert "src.production" not in source
    assert "run_live_decision_cycle" not in source


# --- MomentumBreakoutStrategy remains NOT_READY -------------------------------------------------


def test_momentum_breakout_still_not_ready_in_the_default_registry():
    from src.production.registry import StrategyStatus, build_default_registry

    registry = build_default_registry()
    entry = registry.get("MOMENTUM_BREAKOUT_EXISTING_V1", "1.0")
    assert entry is not None
    assert entry.status == StrategyStatus.NOT_READY
    assert registry.production_eligible_strategies() == ()


def test_frozen_strategy_spec_still_reports_is_validated_false():
    from src.options.phase35_frozen_strategy_spec import MOMENTUM_BREAKOUT_EXISTING_V1
    assert MOMENTUM_BREAKOUT_EXISTING_V1.is_validated is False


# --- No strategy can become VALIDATED without a genuine artifact --------------------------------


def test_mark_validated_requires_a_real_artifact_end_to_end(tmp_path):
    from datetime import datetime, timezone

    from src.production.registry import StrategyMetadata, StrategyNotEligibleError, StrategyRegistry, StrategyStatus
    from src.production.validation_artifact import ValidationArtifactStore

    registry = StrategyRegistry(ValidationArtifactStore(tmp_path / "artifacts.jsonl"))
    registry.register(StrategyMetadata(
        strategy_id="X", version="1.0", status=StrategyStatus.RESEARCH, created_at=datetime.now(timezone.utc),
        validation_status="x", historical_evidence_status="x", live_data_compatibility_status="x",
        allowed_option_structures=(), parameter_specification="x", risk_profile="x", author_or_research_provenance="x",
    ))
    with pytest.raises(StrategyNotEligibleError):
        registry.mark_validated("X", "1.0")


# --- Emergency stop / authorization defaults -----------------------------------------------------


def test_emergency_stop_defaults_active_with_no_record(tmp_path):
    from src.execution.emergency_stop import EmergencyStopStore
    assert EmergencyStopStore(tmp_path / "missing.json").is_stopped() is True


def test_no_system_state_record_means_unauthorized(tmp_path):
    from src.execution.system_state import SystemStateAuditLog, is_live_trading_authorized
    log = SystemStateAuditLog(tmp_path / "missing.jsonl")
    assert is_live_trading_authorized(log) is False


def test_current_env_still_paper_and_unconfirmed():
    from src.config.settings import Settings
    settings = Settings.from_env(env={})
    assert settings.trading_mode == "paper"
    assert settings.live_trading_confirmed is False
    assert settings.live_auto_execute is False
