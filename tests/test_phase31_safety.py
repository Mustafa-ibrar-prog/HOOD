"""Phase 31 Final Safety Check (Part 17/18): research only -- no live
order, no paper order, no autonomous live trading activation, no new
trading STRATEGY object created from a discovery-supported hypothesis,
no paid data purchase, no ORATS activation.

Same AST-based string/comment-blanking technique established in Phase
28/29/30 -- this phase's modules legitimately DISCUSS real mechanisms in
docstrings/comments, so forbidden-pattern checks scan real code
structure only.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE31_SRC_MODULES = [
    "src/options/phase31_panel_builder.py",
    "src/options/phase31_hypotheses.py",
    "src/options/phase31_underlying_control.py",
    "src/options/phase31_evidence.py",
    "src/options/phase31_affordability_liquidity.py",
    "src/options/phase31_robustness.py",
    "src/options/phase31_classification.py",
    "src/options/phase31_gate.py",
    "src/options/phase31_campaign.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order", "submit_order",
    "cancel_equity_order", "cancel_option_order", "review_option_order", "review_equity_order",
    "simulate_paper_order", "simulate_paper_exit",  # Phase 30's paper-trading simulation -- not this phase's job either
)


def _all_phase31_files():
    return [REPO_ROOT / rel for rel in PHASE31_SRC_MODULES]


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


def test_phase31_files_exist():
    for rel in PHASE31_SRC_MODULES:
        assert (REPO_ROOT / rel).is_file(), f"missing {rel}"


def test_no_phase31_file_imports_the_live_order_placement_path():
    for path in _all_phase31_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in FORBIDDEN_IMPORT_PREFIXES:
                    assert not node.module.startswith(prefix), f"{path} imports {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in FORBIDDEN_IMPORT_PREFIXES:
                        assert not alias.name.startswith(prefix), f"{path} imports {alias.name}"


def test_no_phase31_file_calls_a_live_paper_or_simulated_order_function():
    for path in _all_phase31_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        for call in FORBIDDEN_CALLS:
            assert f"{call}(" not in source, f"{path} appears to call {call!r} outside a string/comment"


def test_no_phase31_file_creates_a_strategy_object():
    forbidden_patterns = (
        "LiveStrategy(", "PaperStrategy(", "StrategyExecutor(", "connect_alpha_to_execution",
        "FrozenStrategyStore(", "grid_search(", "run_backtest(",
    )
    for path in _all_phase31_files():
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to create a trading strategy via {pattern!r}"


def test_no_phase31_file_declares_a_hypothesis_validated():
    """A DISCOVERY_SUPPORTED classification and a PromisingFindingGate
    pass are explicitly RESEARCH CANDIDATES (Part 16), never 'validated'
    or 'ready for production' -- no Phase 31 module may claim otherwise."""
    forbidden_phrases = ("is validated", "ready for production", "approved for live trading", "VALIDATED = True")
    for path in _all_phase31_files():
        source = path.read_text().lower()
        for phrase in forbidden_phrases:
            assert phrase.lower() not in source, f"{path} appears to declare a hypothesis validated via {phrase!r}"


def test_no_live_or_paper_trading_enabled_by_this_phase():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_phase31_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r} outside a string/comment"


def test_no_phase31_file_records_a_human_authorized_system_state_transition():
    for path in _all_phase31_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        assert "record_human_authorized_transition(" not in source, f"{path} calls record_human_authorized_transition"


def test_no_phase31_file_purchases_or_activates_orats():
    forbidden_patterns = ("purchase(", "create_account(", "stripe.", "checkout.", "ORATS_API_KEY = \"", "ORATS_API_KEY='")
    for path in _all_phase31_files():
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to purchase/activate a paid provider via {pattern!r}"
        assert "orats_activation_state" not in source, f"{path} touches ORATS activation state -- out of scope this phase"


def test_orats_activation_state_still_pending_human():
    from src.options.orats_activation_state import CURRENT_STATE, ORATSActivationState
    assert CURRENT_STATE == ORATSActivationState.ORATS_ACTIVATION_PENDING_HUMAN


def test_system_state_still_unchanged_by_phase31():
    from src.execution.system_state import SystemState
    assert len(SystemState) == 7
    assert "WAITING_FOR_TRADE_APPROVAL" not in {s.name for s in SystemState}


def test_only_sixteen_hypotheses_registered_this_phase():
    from src.options.phase31_hypotheses import build_hypotheses
    assert len(build_hypotheses()) == 16


def test_discovery_classification_has_exactly_the_seven_required_labels():
    from src.options.phase31_classification import DiscoveryClassification
    assert {c.value for c in DiscoveryClassification} == {
        "discovery_supported", "promising", "inconclusive", "fragile", "rejected",
        "inherited_from_underlying", "not_ready",
    }
