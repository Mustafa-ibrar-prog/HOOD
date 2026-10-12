"""Phase 38 Final Safety Check (Part 15/25): strategy VALIDATION only --
no order creation/submission/modification/cancellation, no execution.gateway
import, no live-authorization/emergency-stop mutation, no paper trading,
no simulated fills/positions/P&L, no .env/broker-config change.

Same static AST-scan + dynamic subprocess-isolated import check Phase
37 established (tests/test_phase37_no_trading_boundary.py), extended to
every new Phase 38 module.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE38_MODULES = [
    "src/options/phase38_causal_validation_dataset.py",
    "src/options/phase38_targets.py",
    "src/options/phase38_candidate_audit.py",
    "src/options/phase38_underlying_vs_option_edge.py",
    "src/options/phase38_chronological_split.py",
    "src/options/phase38_falsification.py",
    "src/options/phase38_test_registry_wiring.py",
    "src/options/phase38_economic_validation.py",
    "src/options/phase38_affordability.py",
    "src/options/phase38_live_replication.py",
    "src/options/phase38_validation_gate.py",
    "src/options/phase38_registry_integration.py",
    "src/options/phase38_campaign.py",
]

FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order",
    "submit_order", "cancel_order", "cancel_equity_order", "cancel_option_order", "cancel_crypto_order",
    "modify_order", "confirm_and_place", "review_option_order", "review_equity_order",
    "simulate_paper_order", "simulate_paper_exit",
)


def _all_files():
    return [REPO_ROOT / rel for rel in PHASE38_MODULES]


def _string_literal_spans(path: Path) -> list[tuple[int, int, int, int]]:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    return [
        (n.lineno, n.col_offset, n.end_lineno, n.end_col_offset)
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and hasattr(n, "end_col_offset")
    ]


def _blanked(path: Path) -> str:
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


def test_phase38_files_exist():
    for path in _all_files():
        assert path.is_file(), f"missing {path}"


def test_no_phase38_file_imports_a_forbidden_module_at_any_level():
    for path in _all_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in FORBIDDEN_IMPORT_PREFIXES:
                    assert not node.module.startswith(prefix), f"{path} imports {node.module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in FORBIDDEN_IMPORT_PREFIXES:
                        assert not alias.name.startswith(prefix), f"{path} imports {alias.name}"


def test_no_phase38_file_calls_an_order_function():
    for path in _all_files():
        source = _blanked(path)
        for call in FORBIDDEN_CALLS:
            assert f"{call}(" not in source, f"{path} appears to call {call!r} outside a string/comment"


def test_dynamic_import_of_every_phase38_module_never_pulls_in_the_execution_gateway():
    module_names = [rel.replace("/", ".").removesuffix(".py") for rel in PHASE38_MODULES]
    script = (
        "import sys\n" + "\n".join(f"import {name}" for name in module_names) + "\n"
        "forbidden = [m for m in sys.modules if m.startswith('src.execution.gateway') or m.startswith('src.execution.live_client')]\n"
        "print(','.join(forbidden))\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    forbidden_loaded = [m for m in result.stdout.strip().split(",") if m]
    assert forbidden_loaded == []


def test_no_phase38_file_enables_live_or_paper_trading():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_files():
        source = _blanked(path)
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r}"


def test_no_phase38_file_clears_or_activates_the_emergency_stop():
    for path in _all_files():
        source = _blanked(path)
        assert ".clear(" not in source, f"{path} appears to touch the emergency stop"
        assert ".activate(" not in source, f"{path} appears to touch the emergency stop"


def test_no_phase38_file_records_a_human_authorized_system_state_transition():
    for path in _all_files():
        source = _blanked(path)
        assert "record_human_authorized_transition(" not in source
        assert "record_code_transition(" not in source


def test_no_phase38_file_creates_simulated_fills_or_positions():
    forbidden = ("SimulatedFill", "simulated_fill", "simulated_entry", "simulated_exit", "simulated_position", "paper_account_balance")
    for path in _all_files():
        source = path.read_text()
        for pattern in forbidden:
            assert pattern not in source, f"{path} contains {pattern!r}"


def test_only_registry_integration_may_reference_mark_validated():
    """Part 14: the ONLY function permitted to call
    StrategyRegistry.mark_validated is promote_if_validated
    (phase38_registry_integration.py), and only after a passed gate."""
    for path in _all_files():
        if path.name == "phase38_registry_integration.py":
            continue
        source = _blanked(path)
        assert ".mark_validated(" not in source, f"{path} calls mark_validated -- only phase38_registry_integration.py may"
        assert "StrategyStatus.VALIDATED" not in source, f"{path} references StrategyStatus.VALIDATED directly"


def test_promote_if_validated_structurally_cannot_bypass_the_gate():
    import inspect

    from src.options.phase38_registry_integration import promote_if_validated

    source = inspect.getsource(promote_if_validated)
    assert "gate_result.passed" in source
    assert "raise GateNotPassedError" in source


def test_env_file_untouched_by_this_phase():
    """Checks the repo-tracked .env.example template, not a real .env --
    a developer's real .env is their own live config and isn't something
    "this phase" controls or should ever be asserted against."""
    env_path = REPO_ROOT / ".env.example"
    content = env_path.read_text()
    assert "TRADING_MODE=paper" in content
    assert "LIVE_TRADING_CONFIRMED=false" in content


def test_live_authorization_remains_off(tmp_path):
    from src.execution.system_state import SystemStateAuditLog, is_live_trading_authorized
    log = SystemStateAuditLog(tmp_path / "missing.jsonl")
    assert is_live_trading_authorized(log) is False


def test_emergency_stop_remains_active(tmp_path):
    from src.execution.emergency_stop import EmergencyStopStore
    assert EmergencyStopStore(tmp_path / "missing.json").is_stopped() is True


def test_momentum_breakout_still_not_ready_in_the_default_registry():
    from src.production.registry import StrategyStatus, build_default_registry
    registry = build_default_registry()
    entry = registry.get("MOMENTUM_BREAKOUT_EXISTING_V1", "1.0")
    assert entry.status == StrategyStatus.NOT_READY
    assert registry.production_eligible_strategies() == ()


def test_place_option_order_still_called_from_exactly_one_place_after_phase38():
    import re

    def_pattern = re.compile(r"\bdef\s+\w*place_option_order\s*\(")
    call_sites = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        source = _blanked(path)
        for line in source.splitlines():
            if "place_option_order(" in line and not def_pattern.search(line):
                call_sites.append(path)
                break
    assert call_sites == [REPO_ROOT / "src/execution/gateway.py"], call_sites


def test_real_campaign_result_does_not_reach_validated_strategy():
    """The single, most important safety assertion this phase can make:
    running the REAL campaign against the REAL (currently empty) Phase
    37 data never produces a VALIDATED_STRATEGY outcome."""
    from pathlib import Path as _Path

    from src.options.phase38_campaign import default_recorder_stores, run_phase38_campaign

    stores = default_recorder_stores(_Path("logs/research_data/phase37"))
    result = run_phase38_campaign(stores=stores)
    assert not result.gate_result.passed
