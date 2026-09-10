"""Phase 42 -- the new acquisition-planning/near-the-money/atomic-sentinel
code must remain exactly as unable to reach real order placement as every
prior phase, AND must never fake MCP connectivity (subprocess-spawn a
`claude` CLI, or construct anything resembling a mock Robinhood client).
Mirrors tests/test_phase40_safety.py / test_phase41_safety.py's
static-AST + forbidden-call + subprocess-isolated dynamic-import
technique."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE42_SRC_MODULES = [
    "src/paper_trading/near_the_money.py",
    "src/paper_trading/acquisition_planning.py",
    "src/paper_trading/data_acquisition.py",  # modified this phase (atomic sentinel)
]
PHASE42_SCRIPTS = [REPO_ROOT / "scripts/prepare_acquisition_plan.py"]

FORBIDDEN_DIRECT_IMPORT_PREFIXES = ("src.execution.live_client",)

FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order",
    "submit_order", "cancel_order", "cancel_equity_order", "cancel_option_order", "cancel_crypto_order",
    "modify_order", "confirm_and_place", "review_option_order", "review_equity_order",
)

# Phase 42-specific: nothing here may spawn a `claude` subprocess or a
# generic subprocess of any kind (see docs/phase42_data_acquisition_
# automation_investigation.md -- a raw `claude -p` subprocess has zero
# MCP access in this environment, confirmed empirically; using one here
# would be exactly the kind of fake automation this phase was told not
# to build). Nor may anything here construct a mock/fake MCP client.
FORBIDDEN_FAKE_AUTOMATION_PATTERNS = ("subprocess.", "Popen(", "os.system(", "MockHoodClient", "FakeMcpClient", "mcp__")


def _all_files() -> list[Path]:
    return [REPO_ROOT / rel for rel in PHASE42_SRC_MODULES] + list(PHASE42_SCRIPTS)


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


def test_phase42_files_exist():
    for path in _all_files():
        assert path.is_file(), f"missing {path}"


def test_no_phase42_file_imports_a_forbidden_module_directly():
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


def test_no_phase42_file_calls_an_order_function():
    for path in _all_files():
        source = _blanked(path)
        for call in FORBIDDEN_CALLS:
            def_pattern = re.compile(rf"\bdef\s+\w*{re.escape(call)}\s*\(")
            for line in source.splitlines():
                if def_pattern.search(line):
                    continue
                assert f"{call}(" not in line, f"{path} appears to call {call!r} outside a string/comment/def: {line!r}"


def test_no_phase42_file_fakes_mcp_automation_or_spawns_a_subprocess():
    """The core Phase 42 guardrail: no new file may spawn a `claude`
    subprocess, shell out, or construct a mock/fake MCP client -- the
    investigation concluded no such mechanism is genuinely available, and
    the instructions explicitly forbid faking one."""
    for path in _all_files():
        source = _blanked(path)
        for pattern in FORBIDDEN_FAKE_AUTOMATION_PATTERNS:
            assert pattern not in source, f"{path} contains {pattern!r} -- forbidden fake-automation pattern"


def test_dynamic_import_of_every_phase42_module_never_pulls_in_live_client():
    module_names = [rel.replace("/", ".").removesuffix(".py") for rel in PHASE42_SRC_MODULES]
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT / 'scripts')!r})\n"
        + "\n".join(f"import {name}" for name in module_names) + "\n"
        "import prepare_acquisition_plan\n"
        "forbidden = [m for m in sys.modules if m.startswith('src.execution.live_client')]\n"
        "print(','.join(forbidden))\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    forbidden_loaded = [m for m in result.stdout.strip().split(",") if m]
    assert forbidden_loaded == []


def test_no_phase42_file_touches_the_emergency_stop():
    for path in _all_files():
        source = _blanked(path)
        assert ".clear(" not in source
        assert ".activate(" not in source


def test_no_phase42_file_mutates_the_strategy_registry():
    for path in _all_files():
        source = _blanked(path)
        assert ".mark_validated(" not in source
        assert "StrategyStatus.VALIDATED" not in source


def test_momentum_breakout_still_not_ready_after_phase42():
    from src.production.registry import StrategyStatus, build_default_registry

    registry = build_default_registry()
    entry = registry.get("MOMENTUM_BREAKOUT_EXISTING_V1", "1.0")
    assert entry.status == StrategyStatus.NOT_READY
    assert registry.production_eligible_strategies() == ()


def test_place_option_order_still_called_from_exactly_one_place_after_phase42():
    def_pattern = re.compile(r"\bdef\s+\w*place_option_order\s*\(")
    call_sites = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        source = _blanked(path)
        for line in source.splitlines():
            if "place_option_order(" in line and not def_pattern.search(line):
                call_sites.append(path)
                break
    assert call_sites == [REPO_ROOT / "src/execution/gateway.py"], call_sites


def test_live_authorization_remains_off_after_phase42(tmp_path):
    from src.execution.system_state import SystemStateAuditLog, is_live_trading_authorized

    log = SystemStateAuditLog(tmp_path / "missing.jsonl")
    assert is_live_trading_authorized(log) is False


def test_emergency_stop_remains_active_after_phase42(tmp_path):
    from src.execution.emergency_stop import EmergencyStopStore

    assert EmergencyStopStore(tmp_path / "missing.json").is_stopped() is True


def test_get_execution_gateway_returns_paper_after_phase42(tmp_path):
    from src.config.settings import Settings
    from src.execution.gateway import PaperExecutionGateway, get_execution_gateway
    from src.logging.decision_logger import DecisionLogger

    settings = Settings.from_env(env={"TRADING_MODE": "paper"})
    logger = DecisionLogger(path=tmp_path / "decisions.jsonl", also_console=False)
    gateway = get_execution_gateway(settings, logger)
    assert isinstance(gateway, PaperExecutionGateway)


def test_env_file_untouched_by_phase42():
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        content = env_path.read_text()
        assert "TRADING_MODE=paper" in content
        assert "LIVE_TRADING_CONFIRMED=false" in content


def test_no_credential_shaped_string_literal_in_any_phase42_file():
    from src.research_recorder.security import assert_no_credential_shaped_content

    for path in _all_files():
        assert_no_credential_shaped_content(path.read_text())


def test_experiment_id_exp_20260908_still_running_and_untouched():
    """Item 14 in the Phase 42 report: confirms the pre-existing real
    experiment was neither recreated nor reset by anything added this
    phase (this phase's own tests never touch the real logs/ tree --
    every test above uses tmp_path)."""
    from src.paper_trading.engine import experiment_paths
    from src.paper_trading.experiment_config import ExperimentConfigStore
    from src.paper_trading.state_machine import ExperimentStateStore, ExperimentStatus

    experiment_id = "exp-20260908T183001Z-21ca70b3"
    paths = experiment_paths(experiment_id)
    if not paths.experiment_config_file.is_file():
        return  # real experiment state isn't present in this test environment -- nothing to assert
    config = ExperimentConfigStore(paths.experiment_config_file).get()
    assert config is not None
    assert config.starting_capital_usd == 1000.0
    status = ExperimentStateStore(paths.experiment_state_file).current_status()
    assert status in (ExperimentStatus.RUNNING, ExperimentStatus.PAUSED, ExperimentStatus.COMPLETED)
