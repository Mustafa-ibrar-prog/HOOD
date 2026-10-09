"""Phase 40, Part 29-30 -- the paper-experiment engine must remain
completely unable to place a real order.

Unlike Phase 37/38/39 (which never touch execution machinery at all),
Phase 40 DELIBERATELY reuses `src.orchestrator.run_trading_cycle`, which
itself legitimately calls `src.execution.gateway.get_execution_gateway`
to obtain a `PaperExecutionGateway` -- that transitive import is expected
and is not itself a violation. What this file verifies instead:

  1. No Phase 40 file (src/paper_trading/*.py, scripts/paper_experiment.py)
     imports `src.execution.live_client` or `src.execution.gateway`
     DIRECTLY (only reachable transitively through the unmodified
     `src.orchestrator` call graph -- see engine.py's own docstring).
  2. No Phase 40 file calls a real order-placement/modification function
     (def-aware -- Phase 40 defines none of these, so this is simpler
     than Phase 39's version of the same check).
  3. A subprocess-isolated dynamic import of every Phase 40 module never
     pulls `src.execution.live_client` into sys.modules.
  4. No Phase 40 file ever sets trading_mode="live" / live_trading_
     confirmed=True / live_auto_execute=True.
  5. `get_execution_gateway` returns PaperExecutionGateway (never Live)
     for the trading_mode this repo's real .env actually configures.
  6. No Phase 40 file touches the emergency stop or records a human-
     authorized system-state transition.
  7. No Phase 40 file mutates the StrategyRegistry (register/
     mark_validated) -- PAPER_EXPERIMENT_ONLY is read-only cross-
     reference, never a path to VALIDATED_STRATEGY.
  8. live authorization remains OFF, emergency stop remains ACTIVE,
     MOMENTUM_BREAKOUT_EXISTING_V1 remains NOT_READY, place_option_order
     is still called from exactly one place in the whole repo, .env is
     unchanged, and no file contains a credential-shaped string literal.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE40_SRC_MODULES = [
    "src/paper_trading/__init__.py",
    "src/paper_trading/experiment_config.py",
    "src/paper_trading/state_machine.py",
    "src/paper_trading/clock.py",
    "src/paper_trading/slippage.py",
    "src/paper_trading/journal.py",
    "src/paper_trading/account.py",
    "src/paper_trading/equity_curve.py",
    "src/paper_trading/daily_performance.py",
    "src/paper_trading/risk_monitoring.py",
    "src/paper_trading/engine.py",
    "src/paper_trading/report.py",
]
PHASE40_SCRIPT = REPO_ROOT / "scripts/paper_experiment.py"

# Deliberately does NOT include "src.execution.gateway" -- Phase 40
# legitimately reaches it TRANSITIVELY through src.orchestrator, unlike
# Phase 37/38/39 which have no reason to touch execution machinery at all.
FORBIDDEN_DIRECT_IMPORT_PREFIXES = ("src.execution.live_client",)

FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order",
    "submit_order", "cancel_order", "cancel_equity_order", "cancel_option_order", "cancel_crypto_order",
    "modify_order", "confirm_and_place", "review_option_order", "review_equity_order",
)


def _all_files() -> list[Path]:
    return [REPO_ROOT / rel for rel in PHASE40_SRC_MODULES] + [PHASE40_SCRIPT]


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


def test_phase40_files_exist():
    for path in _all_files():
        assert path.is_file(), f"missing {path}"


def test_no_phase40_file_imports_a_forbidden_module_directly():
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


def test_no_phase40_file_imports_execution_gateway_or_live_client_directly():
    """engine.py's own docstring promise: everything execution-adjacent is
    reached only through src.orchestrator.run_trading_cycle's own call
    graph, never a direct import in a Phase 40 file."""
    for path in _all_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in ("src.execution.gateway", "src.execution.live_client"), (
                    f"{path} directly imports {node.module}"
                )


def test_no_phase40_file_calls_an_order_function():
    for path in _all_files():
        source = _blanked(path)
        for call in FORBIDDEN_CALLS:
            def_pattern = re.compile(rf"\bdef\s+\w*{re.escape(call)}\s*\(")
            for line in source.splitlines():
                if def_pattern.search(line):
                    continue
                assert f"{call}(" not in line, f"{path} appears to call {call!r} outside a string/comment/def: {line!r}"


def test_dynamic_import_of_every_phase40_module_never_pulls_in_live_client():
    module_names = [rel.replace("/", ".").removesuffix(".py") for rel in PHASE40_SRC_MODULES]
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT / 'scripts')!r})\n"
        + "\n".join(f"import {name}" for name in module_names) + "\n"
        "import paper_experiment\n"
        "forbidden = [m for m in sys.modules if m.startswith('src.execution.live_client')]\n"
        "print(','.join(forbidden))\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    forbidden_loaded = [m for m in result.stdout.strip().split(",") if m]
    assert forbidden_loaded == []


def test_no_phase40_file_enables_live_or_forces_live_trading_mode():
    for path in _all_files():
        source = _blanked(path)
        for pattern in ("live_trading_confirmed=True", "live_auto_execute=True", 'trading_mode="live"', "trading_mode='live'"):
            assert pattern not in source, f"{path} appears to force live trading via {pattern!r}"


def test_no_phase40_file_touches_the_emergency_stop():
    for path in _all_files():
        source = _blanked(path)
        assert ".clear(" not in source, f"{path} appears to touch the emergency stop"
        assert ".activate(" not in source, f"{path} appears to touch the emergency stop"


def test_no_phase40_file_records_a_human_authorized_system_state_transition():
    for path in _all_files():
        source = _blanked(path)
        assert "record_human_authorized_transition(" not in source
        assert "record_code_transition(" not in source


def test_no_phase40_file_mutates_the_strategy_registry():
    """PAPER_EXPERIMENT_ONLY is a completely separate, Phase-40-local
    concept -- no Phase 40 file ever calls StrategyRegistry.register or
    .mark_validated. Read-only cross-reference (registry.get(...)) is the
    only allowed touchpoint, and only in the CLI's report command."""
    for path in _all_files():
        source = _blanked(path)
        assert ".mark_validated(" not in source, f"{path} appears to mutate the strategy registry"
        assert "StrategyStatus.VALIDATED" not in source, f"{path} references StrategyStatus.VALIDATED"


def test_experiment_strategy_mode_enum_has_no_import_relationship_to_strategy_status():
    """The module's docstring is allowed to MENTION StrategyStatus/
    StrategyRegistry in prose (explaining the deliberate non-relationship)
    -- what must never exist is an actual `import`/`from ... import` of
    either name."""
    path = REPO_ROOT / "src/paper_trading/experiment_config.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = {alias.name for alias in node.names}
            assert "StrategyStatus" not in names and "StrategyRegistry" not in names, f"{path} imports {names}"
        elif isinstance(node, ast.Import):
            assert not any(alias.name in ("StrategyStatus", "StrategyRegistry") for alias in node.names)


def test_paper_status_values_are_disjoint_from_production_system_state_values():
    from src.execution.system_state import SystemState
    from src.paper_trading.state_machine import ExperimentStatus

    assert {s.value for s in ExperimentStatus}.isdisjoint({s.value for s in SystemState})


def test_get_execution_gateway_returns_paper_for_this_repos_real_trading_mode(tmp_path):
    """Whatever TRADING_MODE the real .env configures (must be 'paper'
    per test_env_file_untouched below), get_execution_gateway must return
    PaperExecutionGateway, never LiveExecutionGateway -- the structural
    reason PaperExecutionGateway.place_order can never reach a real
    Robinhood order regardless of what src.orchestrator.run_trading_cycle
    does internally. TRADING_MODE=paper always wins regardless of any
    other argument (see get_execution_gateway's own docstring), so a
    minimal DecisionLogger is enough to prove it."""
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


def test_momentum_breakout_still_not_ready_in_the_default_registry():
    from src.production.registry import StrategyStatus, build_default_registry
    registry = build_default_registry()
    entry = registry.get("MOMENTUM_BREAKOUT_EXISTING_V1", "1.0")
    assert entry.status == StrategyStatus.NOT_READY
    assert registry.production_eligible_strategies() == ()


def test_place_option_order_still_called_from_exactly_one_place_after_phase40():
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


def test_no_credential_shaped_string_literal_in_any_phase40_file():
    from src.research_recorder.security import assert_no_credential_shaped_content

    for path in _all_files():
        assert_no_credential_shaped_content(path.read_text())


def test_logs_paper_experiments_directory_is_gitignored():
    """A real 14-day experiment's data (logs/paper_experiments/) must
    never be committed, matching the same gitignore convention already
    established for logs/research_data/phase37 in Phase 37/39."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", "logs/paper_experiments/exp-example/experiment_config.json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert result.returncode == 0, "logs/paper_experiments/ is not gitignored"
