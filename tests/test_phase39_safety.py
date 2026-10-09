"""Phase 39, Part 13 — Live Research Safety Barrier.

Same defense-in-depth Phase 37/38 established: (1) static AST import
scan, (2) forbidden order-call scan (def-aware — src/live_bridge.py
legitimately DEFINES place_option_order/review_option_order/
cancel_option_order/record_place_option_order as part of its pre-existing,
already-documented REPLAY class for the separate, human-approved
live-order confirmation bridge; this scan must distinguish a definition
from an actual call, exactly as
tests/test_phase38_safety.py::test_place_option_order_still_called_from_exactly_one_place_after_phase38
already does), (3) subprocess-isolated dynamic import scan.

Covers every file this phase added or touched:
  - scripts/run_live_research_cycle.py  (new)
  - src/research_recorder/coverage_report.py  (new)
  - src/options/phase39_readiness.py  (new)
  - src/live_bridge.py  (touched -- added load_static_hood_client_from_dir)
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE39_SRC_MODULES = [
    "src/research_recorder/coverage_report.py",
    "src/options/phase39_readiness.py",
    "src/live_bridge.py",
]
PHASE39_SCRIPT = REPO_ROOT / "scripts/run_live_research_cycle.py"

FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order",
    "submit_order", "cancel_order", "cancel_equity_order", "cancel_option_order", "cancel_crypto_order",
    "modify_order", "confirm_and_place", "review_option_order", "review_equity_order",
    "simulate_paper_order", "simulate_paper_exit",
)


def _all_files() -> list[Path]:
    return [REPO_ROOT / rel for rel in PHASE39_SRC_MODULES] + [PHASE39_SCRIPT]


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


def test_phase39_files_exist():
    for path in _all_files():
        assert path.is_file(), f"missing {path}"


def test_no_phase39_file_imports_a_forbidden_module_at_any_level():
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


def test_no_phase39_file_calls_an_order_function():
    """def-aware: a DEFINITION of one of these names (src/live_bridge.py's
    pre-existing StaticLiveOrderPlacer replay class) is not itself a call.
    Only an actual invocation `name(...)` outside a string/comment and
    outside a `def` line is treated as a violation."""
    for path in _all_files():
        source = _blanked(path)
        for call in FORBIDDEN_CALLS:
            def_pattern = re.compile(rf"\bdef\s+\w*{re.escape(call)}\s*\(")
            for line in source.splitlines():
                if def_pattern.search(line):
                    continue
                assert f"{call}(" not in line, f"{path} appears to call {call!r} outside a string/comment/def: {line!r}"


def test_dynamic_import_of_every_phase39_module_never_pulls_in_the_execution_gateway():
    module_names = [rel.replace("/", ".").removesuffix(".py") for rel in PHASE39_SRC_MODULES]
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT / 'scripts')!r})\n"
        + "\n".join(f"import {name}" for name in module_names) + "\n"
        "import run_live_research_cycle\n"
        "forbidden = [m for m in sys.modules if m.startswith('src.execution.gateway') or m.startswith('src.execution.live_client')]\n"
        "print(','.join(forbidden))\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    forbidden_loaded = [m for m in result.stdout.strip().split(",") if m]
    assert forbidden_loaded == []


def test_no_phase39_file_enables_live_or_paper_trading():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_files():
        source = _blanked(path)
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r}"


def test_no_phase39_file_clears_or_activates_the_emergency_stop():
    for path in _all_files():
        source = _blanked(path)
        assert ".clear(" not in source, f"{path} appears to touch the emergency stop"
        assert ".activate(" not in source, f"{path} appears to touch the emergency stop"


def test_no_phase39_file_creates_simulated_fills_positions_or_paper_trading():
    forbidden = (
        "SimulatedFill", "simulated_fill", "simulated_entry", "simulated_exit", "simulated_position",
        "paper_account_balance", "simulated_order", "paper_order", "PaperOrder", "simulated_p&l", "simulated_pnl",
    )
    for path in _all_files():
        source = path.read_text()
        for pattern in forbidden:
            assert pattern not in source, f"{path} contains {pattern!r}"


def test_no_new_phase39_module_references_a_paper_or_live_broker():
    """The newly-CREATED files (not src/live_bridge.py, whose own
    pre-existing, already-documented replay design legitimately discusses
    the live-order confirmation bridge) must not reference paper/live
    broker machinery at all."""
    for path in (REPO_ROOT / rel for rel in ("src/research_recorder/coverage_report.py", "src/options/phase39_readiness.py")):
        source = path.read_text()
        for pattern in ("PaperExecutionGateway", "LiveExecutionGateway", "PendingOrderStore", "LiveOrderPlacer"):
            assert pattern not in source, f"{path} references {pattern!r}"


def test_runner_script_never_prints_raw_response_payloads():
    """Part 13/15: the runner only prints observation SUMMARIES (counts,
    decisions, symbol/status), never a raw response dict that could carry
    account numbers or other sensitive content verbatim."""
    source = PHASE39_SCRIPT.read_text()
    for banned in ("equity_response", "option_response", "response.json()", "print(response"):
        assert banned not in source


def test_no_phase39_file_records_a_human_authorized_system_state_transition():
    for path in _all_files():
        source = _blanked(path)
        assert "record_human_authorized_transition(" not in source
        assert "record_code_transition(" not in source


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


def test_place_option_order_still_called_from_exactly_one_place_after_phase39():
    def_pattern = re.compile(r"\bdef\s+\w*place_option_order\s*\(")
    call_sites = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        source = _blanked(path)
        for line in source.splitlines():
            if "place_option_order(" in line and not def_pattern.search(line):
                call_sites.append(path)
                break
    assert call_sites == [REPO_ROOT / "src/execution/gateway.py"], call_sites


def test_env_file_untouched_by_this_phase():
    """Checks the repo-tracked .env.example template, not a real .env --
    a developer's real .env is their own live config and isn't something
    "this phase" controls or should ever be asserted against."""
    env_path = REPO_ROOT / ".env.example"
    content = env_path.read_text()
    assert "TRADING_MODE=paper" in content
    assert "LIVE_TRADING_CONFIRMED=false" in content


def test_no_credential_shaped_string_literal_in_any_phase39_file():
    from src.research_recorder.security import assert_no_credential_shaped_content

    for path in _all_files():
        assert_no_credential_shaped_content(path.read_text())
