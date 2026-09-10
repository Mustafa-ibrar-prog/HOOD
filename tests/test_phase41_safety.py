"""Phase 41 -- the automatic scheduler must remain exactly as unable to
place a real order as Phase 40's manual CLI was. Mirrors
tests/test_phase40_safety.py's static-AST + forbidden-call +
subprocess-isolated dynamic-import technique, extended to every new
Phase 41 file (src/paper_trading/{market_calendar,data_acquisition,
scheduler_events,cycle_runner,scheduler}.py, scripts/run_paper_
scheduler.py) plus the refactored scripts/paper_experiment.py.

Covers comprehensive-test-list items 14 (no real execution imports), 15
(no place_option_order call), 17 (strategy remains NOT_READY), 18 (paper
experiment remains isolated) -- for the SCHEDULER specifically, on top of
Phase 40's own already-passing equivalents which this phase does not
touch or weaken.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE41_SRC_MODULES = [
    "src/paper_trading/market_calendar.py",
    "src/paper_trading/data_acquisition.py",
    "src/paper_trading/scheduler_events.py",
    "src/paper_trading/cycle_runner.py",
    "src/paper_trading/scheduler.py",
]
PHASE41_SCRIPTS = [REPO_ROOT / "scripts/run_paper_scheduler.py", REPO_ROOT / "scripts/paper_experiment.py"]

# Deliberately does NOT include "src.execution.gateway" -- like Phase 40,
# this package legitimately reaches it TRANSITIVELY through
# src.orchestrator (via cycle_runner -> engine.run_paper_experiment_cycle
# -> run_trading_cycle), never directly.
FORBIDDEN_DIRECT_IMPORT_PREFIXES = ("src.execution.live_client",)

FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order",
    "submit_order", "cancel_order", "cancel_equity_order", "cancel_option_order", "cancel_crypto_order",
    "modify_order", "confirm_and_place", "review_option_order", "review_equity_order",
)


def _all_files() -> list[Path]:
    return [REPO_ROOT / rel for rel in PHASE41_SRC_MODULES] + list(PHASE41_SCRIPTS)


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


def test_phase41_files_exist():
    for path in _all_files():
        assert path.is_file(), f"missing {path}"


def test_no_phase41_file_imports_a_forbidden_module_directly():
    for path in _all_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in FORBIDDEN_DIRECT_IMPORT_PREFIXES:
                    assert not node.module.startswith(prefix), f"{path} imports {node.module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in FORBIDDEN_DIRECT_IMPORT_PREFIXES:
                        assert not alias.name.startswith(prefix), f"{path} imports {alias.name}"


def test_no_phase41_file_imports_execution_gateway_or_live_client_directly():
    for path in _all_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in ("src.execution.gateway", "src.execution.live_client"), (
                    f"{path} directly imports {node.module}"
                )


def test_no_phase41_file_calls_an_order_function():
    for path in _all_files():
        source = _blanked(path)
        for call in FORBIDDEN_CALLS:
            def_pattern = re.compile(rf"\bdef\s+\w*{re.escape(call)}\s*\(")
            for line in source.splitlines():
                if def_pattern.search(line):
                    continue
                assert f"{call}(" not in line, f"{path} appears to call {call!r} outside a string/comment/def: {line!r}"


def test_dynamic_import_of_every_phase41_module_never_pulls_in_live_client():
    """Item 14/15's dynamic proof: importing every new Phase 41 module for
    real (subprocess-isolated) never pulls src.execution.live_client into
    sys.modules -- the same technique Phase 37/38/39/40 already used."""
    module_names = [rel.replace("/", ".").removesuffix(".py") for rel in PHASE41_SRC_MODULES]
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT / 'scripts')!r})\n"
        + "\n".join(f"import {name}" for name in module_names) + "\n"
        "import run_paper_scheduler\n"
        "import paper_experiment\n"
        "forbidden = [m for m in sys.modules if m.startswith('src.execution.live_client')]\n"
        "print(','.join(forbidden))\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    forbidden_loaded = [m for m in result.stdout.strip().split(",") if m]
    assert forbidden_loaded == []


def test_no_phase41_file_enables_live_or_forces_live_trading_mode():
    for path in _all_files():
        source = _blanked(path)
        for pattern in ("live_trading_confirmed=True", "live_auto_execute=True", 'trading_mode="live"', "trading_mode='live'"):
            assert pattern not in source, f"{path} appears to force live trading via {pattern!r}"


def test_no_phase41_file_touches_the_emergency_stop():
    for path in _all_files():
        source = _blanked(path)
        assert ".clear(" not in source, f"{path} appears to touch the emergency stop"
        assert ".activate(" not in source, f"{path} appears to touch the emergency stop"


def test_no_phase41_file_records_a_human_authorized_system_state_transition():
    for path in _all_files():
        source = _blanked(path)
        assert "record_human_authorized_transition(" not in source
        assert "record_code_transition(" not in source


def test_no_phase41_file_mutates_the_strategy_registry():
    """Item 17/18: the automatic scheduler never touches
    src.production.registry at all -- PAPER_EXPERIMENT_ONLY stays
    Phase-40-local and Phase-41-local, never a path to VALIDATED."""
    for path in _all_files():
        source = _blanked(path)
        assert ".mark_validated(" not in source, f"{path} appears to mutate the strategy registry"
        assert "StrategyStatus.VALIDATED" not in source, f"{path} references StrategyStatus.VALIDATED"
        assert "src.production.registry" not in source or path.name == "paper_experiment.py", (
            f"{path} references src.production.registry -- only the CLI's read-only report command may"
        )


def test_momentum_breakout_still_not_ready_in_the_default_registry():
    """Item 17: unaffected by Phase 41 -- read-only, exactly like Phase 40's own version of this test."""
    from src.production.registry import StrategyStatus, build_default_registry

    registry = build_default_registry()
    entry = registry.get("MOMENTUM_BREAKOUT_EXISTING_V1", "1.0")
    assert entry.status == StrategyStatus.NOT_READY
    assert registry.production_eligible_strategies() == ()


def test_place_option_order_still_called_from_exactly_one_place_after_phase41():
    """Item 15, repo-wide: after adding the whole Phase 41 scheduler, the
    real order-placement call site count is unchanged."""
    def_pattern = re.compile(r"\bdef\s+\w*place_option_order\s*\(")
    call_sites = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        source = _blanked(path)
        for line in source.splitlines():
            if "place_option_order(" in line and not def_pattern.search(line):
                call_sites.append(path)
                break
    assert call_sites == [REPO_ROOT / "src/execution/gateway.py"], call_sites


def test_get_execution_gateway_returns_paper_for_this_repos_real_trading_mode(tmp_path):
    from src.config.settings import Settings
    from src.execution.gateway import PaperExecutionGateway, get_execution_gateway
    from src.logging.decision_logger import DecisionLogger

    settings = Settings.from_env(env={"TRADING_MODE": "paper"})
    logger = DecisionLogger(path=tmp_path / "decisions.jsonl", also_console=False)
    gateway = get_execution_gateway(settings, logger)
    assert isinstance(gateway, PaperExecutionGateway)


def test_live_authorization_remains_off(tmp_path):
    from src.execution.system_state import SystemStateAuditLog, is_live_trading_authorized

    log = SystemStateAuditLog(tmp_path / "missing.jsonl")
    assert is_live_trading_authorized(log) is False


def test_emergency_stop_remains_active(tmp_path):
    from src.execution.emergency_stop import EmergencyStopStore

    assert EmergencyStopStore(tmp_path / "missing.json").is_stopped() is True


def test_experiment_strategy_mode_still_has_no_import_relationship_to_strategy_status():
    """Item 18: paper-experiment isolation, re-verified after Phase 41 --
    none of the new scheduler files import StrategyStatus/StrategyRegistry."""
    for path in _all_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = {alias.name for alias in node.names}
                assert "StrategyStatus" not in names and "StrategyRegistry" not in names, f"{path} imports {names}"
            elif isinstance(node, ast.Import):
                assert not any(alias.name in ("StrategyStatus", "StrategyRegistry") for alias in node.names)


def test_paper_status_values_still_disjoint_from_production_system_state_values():
    from src.execution.system_state import SystemState
    from src.paper_trading.state_machine import ExperimentStatus

    assert {s.value for s in ExperimentStatus}.isdisjoint({s.value for s in SystemState})


def test_env_file_untouched_by_this_phase():
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        content = env_path.read_text()
        assert "TRADING_MODE=paper" in content
        assert "LIVE_TRADING_CONFIRMED=false" in content


def test_no_credential_shaped_string_literal_in_any_phase41_file():
    from src.research_recorder.security import assert_no_credential_shaped_content

    for path in _all_files():
        assert_no_credential_shaped_content(path.read_text())


def test_no_phase41_file_ever_writes_a_ready_broker_order_shaped_payload():
    """A scheduler-specific extra: no Phase 41 file constructs a dict/
    payload keyed the way a real order submission would be (side/
    quantity/limit_price/time_in_force together) -- the whole point of
    this phase is that the scheduler only ever feeds real market data
    INTO the isolated paper experiment, never anything order-shaped OUT."""
    for path in _all_files():
        source = _blanked(path)
        assert "time_in_force" not in source, f"{path} references time_in_force -- order-payload shaped content"
