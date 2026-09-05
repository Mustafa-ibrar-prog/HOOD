"""Phase 35 Final Safety Check (Part R/S): existing-strategy validation +
execution-boundary hardening ONLY -- no live order, no paper order, no
strategy deployment, no strategy optimization/creation/substitution, no
paid data purchase, no autonomous live trading activation. Emergency
stop defaults active; live authorization is NOT active.

Same AST-based string/comment-blanking technique established in Phase
28-33 -- forbidden-pattern checks scan real code structure only, never
docstring/comment prose.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE35_RESEARCH_MODULES = [
    "src/options/phase35_frozen_strategy_spec.py",
    "src/options/phase35_options_only_verification.py",
    "src/options/phase35_underlying_signal.py",
    "src/options/phase35_option_trade_matching.py",
    "src/options/phase35_option_research_strategy.py",
    "src/options/phase35_backtest_campaign.py",
    "src/options/phase35_statistical_validation.py",
    "src/options/phase35_strategy_gate.py",
    "src/options/phase35_live_feature_compatibility.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order", "submit_order",
    "cancel_equity_order", "cancel_option_order", "review_option_order", "review_equity_order",
    "simulate_paper_order", "simulate_paper_exit",
)


def _all_phase35_research_files():
    return [REPO_ROOT / rel for rel in PHASE35_RESEARCH_MODULES]


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


def test_phase35_research_files_exist():
    for rel in PHASE35_RESEARCH_MODULES:
        assert (REPO_ROOT / rel).is_file(), f"missing {rel}"


def test_no_phase35_research_file_imports_the_live_order_placement_path():
    for path in _all_phase35_research_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in FORBIDDEN_IMPORT_PREFIXES:
                    assert not node.module.startswith(prefix), f"{path} imports {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in FORBIDDEN_IMPORT_PREFIXES:
                        assert not alias.name.startswith(prefix), f"{path} imports {alias.name}"


def test_no_phase35_research_file_calls_a_live_paper_or_simulated_order_function():
    for path in _all_phase35_research_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        for call in FORBIDDEN_CALLS:
            assert f"{call}(" not in source, f"{path} appears to call {call!r} outside a string/comment"


def test_no_phase35_research_file_declares_the_strategy_validated():
    forbidden_phrases = ("is validated", "ready for production", "approved for live trading", "VALIDATED = True", "is_validated = True")
    for path in _all_phase35_research_files():
        source = path.read_text().lower()
        for phrase in forbidden_phrases:
            assert phrase.lower() not in source, f"{path} appears to declare the strategy validated via {phrase!r}"


def test_frozen_strategy_spec_is_never_marked_validated():
    from src.options.phase35_frozen_strategy_spec import MOMENTUM_BREAKOUT_EXISTING_V1
    assert MOMENTUM_BREAKOUT_EXISTING_V1.is_validated is False


def test_no_live_or_paper_trading_enabled_by_this_phase():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_phase35_research_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r} outside a string/comment"


def test_no_phase35_research_file_records_a_human_authorized_system_state_transition():
    for path in _all_phase35_research_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        assert "record_human_authorized_transition(" not in source, f"{path} calls record_human_authorized_transition"


def test_no_phase35_research_file_clears_the_emergency_stop():
    for path in _all_phase35_research_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        assert ".clear(" not in source, f"{path} appears to call EmergencyStopStore.clear"


def test_no_phase35_research_file_purchases_or_activates_a_paid_provider():
    forbidden_patterns = ("purchase(", "create_account(", "stripe.", "checkout.", "ORATS_API_KEY = \"", "ORATS_API_KEY='")
    for path in _all_phase35_research_files():
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to purchase/activate a paid provider via {pattern!r}"


# --- place_option_order remains reachable from exactly one place -----------------------------


def test_place_option_order_is_called_from_exactly_one_place_in_all_of_src():
    """Locks in the same invariant Phase 18 onward has repeatedly
    reconfirmed: after Phase 35's execution-boundary hardening (new
    imports/checks added to gateway.py, a new emergency_stop.py module,
    new phase35_* research modules), `place_option_order(` still appears
    as an executable CALL in exactly one file, inside `_place_pending`.
    `def place_option_order(` (the Protocol's own declaration in
    live_client.py, and StaticLiveOrderPlacer's implementation in
    live_bridge.py -- which never calls a real broker, it only replays an
    already-recorded response) are deliberately excluded -- those are
    definitions, not calls."""
    import re

    def_pattern = re.compile(r"\bdef\s+\w*place_option_order\s*\(")
    call_sites = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        source = _code_with_string_literals_and_comments_blanked(path)
        for line in source.splitlines():
            if "place_option_order(" in line and not def_pattern.search(line):
                call_sites.append(path)
                break
    assert call_sites == [REPO_ROOT / "src/execution/gateway.py"], call_sites


# --- Part O/P: the new gates are wired in, real, and fail closed -----------------------------


def test_system_state_still_exactly_six_states_after_this_phase():
    from src.execution.system_state import SystemState
    assert len(SystemState) == 6
    assert "WAITING_FOR_TRADE_APPROVAL" not in {s.name for s in SystemState}


def test_emergency_stop_defaults_to_stopped_with_no_file(tmp_path):
    from src.execution.emergency_stop import EmergencyStopStore
    store = EmergencyStopStore(tmp_path / "does_not_exist.json")
    assert store.is_stopped() is True


def test_no_system_state_record_means_not_authorized(tmp_path):
    from src.execution.system_state import SystemStateAuditLog, is_live_trading_authorized
    log = SystemStateAuditLog(tmp_path / "audit.jsonl")
    assert log.current_state() is None
    assert is_live_trading_authorized(log) is False


def test_gateway_wires_options_only_emergency_stop_and_authorization_check():
    """Structural confirmation that _place_pending references all three
    Phase 35 guards -- catches an accidental revert of the wiring itself,
    independent of the behavioral tests in test_phase35_execution_boundary.py."""
    source = (REPO_ROOT / "src/execution/gateway.py").read_text()
    assert "assert_options_only(order)" in source
    assert "self._emergency_stop_store" in source
    assert "is_live_trading_authorized(self._system_state_audit_log)" in source


# --- Part S: safety verification before completion --------------------------------------------


def test_settings_still_default_to_paper_unconfirmed_no_auto_execute():
    from src.config.settings import Settings
    settings = Settings.from_env(env={})
    assert settings.trading_mode == "paper"
    assert settings.is_paper is True
    assert settings.live_trading_confirmed is False
    assert settings.live_auto_execute is False


def test_orchestrator_never_clears_the_emergency_stop_or_authorizes_live_trading():
    source = _code_with_string_literals_and_comments_blanked(REPO_ROOT / "src/orchestrator.py")
    assert ".clear(" not in source
    assert "record_human_authorized_transition(" not in source
    assert "record_code_transition(" not in source
