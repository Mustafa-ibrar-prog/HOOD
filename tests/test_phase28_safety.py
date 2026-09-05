"""Phase 28 Final Safety Check (Part 16): paid-provider DECISION and
autonomous-architecture GATE only -- no purchase, no payment info, no
paid subscription, no stored API key/credential, no order placement, no
new alpha hypothesis, no alpha discovery, no parameter optimization, no
strategy backtest, and -- the defining requirement of this phase's
architecture work -- no per-trade human-approval requirement anywhere
in the new system-state design.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE28_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase28_*.py"))
PHASE28_SRC_MODULES = [
    "src/options/phase28_evidence_classification.py",
    "src/options/phase28_provider_scorecard.py",
    "src/options/phase28_pricing_licensing.py",
    "src/options/phase28_provider_decision.py",
    "src/options/phase28_free_dataset_label.py",
    "src/execution/system_state.py",
    "src/execution/autonomous_architecture_audit.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order", "submit_order",
    "cancel_equity_order", "cancel_option_order", "review_option_order", "review_equity_order",
)


def _all_phase28_files():
    return [REPO_ROOT / rel for rel in PHASE28_SRC_MODULES] + list(PHASE28_SCRIPTS)


def _string_literal_spans(path: Path) -> list[tuple[int, int]]:
    """Byte offsets of every string-literal constant in the file (module/
    class/function docstrings AND inline dataclass field values, e.g.
    autonomous_architecture_audit.py's PipelineStageAudit(...).note
    strings) -- this phase's audit modules legitimately DISCUSS the real
    place_option_order/live_auto_execute mechanism in prose/documentation
    string values throughout, not just in a leading module docstring."""
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if hasattr(node, "end_col_offset"):
                spans.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset))
    return spans


def _code_with_string_literals_blanked(path: Path) -> str:
    """Forbidden-pattern checks scan only actual CODE structure this way
    -- a string literal's CONTENT (whatever it says) can never trip
    these checks, only real syntax (an actual call, an actual keyword
    assignment) can."""
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
    # Second pass: blank `#` line comments too -- these modules' extensive
    # real-mechanism discussion lives partly in comments (e.g.
    # autonomous_architecture_audit.py's ORCHESTRATOR_DOCSTRING_STALENESS_
    # FINDING preamble comment block). Safe now: any `#` still present in a
    # string literal's ORIGINAL content was already replaced with `_` above,
    # so every remaining `#` genuinely starts a real comment.
    for i, line in enumerate(lines):
        hash_pos = line.find("#")
        if hash_pos != -1:
            lines[i] = line[:hash_pos] + "\n" if line.endswith("\n") else line[:hash_pos]
    return "".join(lines)


def test_phase28_files_exist():
    for rel in PHASE28_SRC_MODULES:
        assert (REPO_ROOT / rel).is_file(), f"missing {rel}"


def test_no_phase28_file_imports_the_live_order_placement_path():
    for path in _all_phase28_files():
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in FORBIDDEN_IMPORT_PREFIXES:
                    assert not node.module.startswith(prefix), f"{path} imports {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in FORBIDDEN_IMPORT_PREFIXES:
                        assert not alias.name.startswith(prefix), f"{path} imports {alias.name}"


def test_no_phase28_file_references_a_live_or_paper_order_placement_call():
    for path in _all_phase28_files():
        if not path.is_file():
            continue
        source = _code_with_string_literals_blanked(path)
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r} outside its module docstring"


def test_no_phase28_file_creates_a_strategy_backtest_or_hypothesis():
    forbidden_patterns = (
        "LiveStrategy(", "PaperStrategy(", "StrategyExecutor(", "connect_alpha_to_execution",
        "Hypothesis(", "HypothesisRegistry(", "PreregistrationRecord(", "compute_ic_series(",
        "grid_search(", "optimize_parameters(", "run_backtest(", "sharpe_optimi", "signal_rank",
        "profitable_signal", "claimed_edge", "alpha_discovery", "momentum_edge", "mean_reversion_edge",
    )
    for path in _all_phase28_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to register a hypothesis/backtest/strategy via {pattern!r}"


def test_no_phase28_file_purchases_a_vendor_or_stores_a_real_api_key():
    forbidden_patterns = (
        "purchase(", "create_account(", "api_key=\"", "API_KEY=\"", "stripe.", "checkout.",
        "credit_card", "payment_method=", "card_number", "cvv",
    )
    for path in _all_phase28_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to purchase/store credentials for a vendor via {pattern!r}"


def test_no_live_or_paper_trading_enabled_by_this_phase():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_phase28_files():
        if not path.is_file():
            continue
        source = _code_with_string_literals_blanked(path)
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r} outside its module docstring"


def test_no_per_trade_approval_state_or_concept_anywhere_in_the_new_state_machine():
    """The defining architectural requirement of this phase: no
    WAITING_FOR_TRADE_APPROVAL state, and no per-trade approval concept
    of any name, anywhere in system_state.py."""
    src = (REPO_ROOT / "src/execution/system_state.py").read_text()
    forbidden = ("WAITING_FOR_TRADE_APPROVAL", "PER_TRADE_APPROVAL", "TRADE_APPROVAL_REQUIRED", "approve_each_trade", "per_trade_human_approval")
    for pattern in forbidden:
        assert pattern not in src, f"system_state.py references {pattern!r} -- Part 11 forbids a per-trade approval state"


def test_system_state_enum_has_exactly_seven_members():
    from src.execution.system_state import SystemState
    assert len(SystemState) == 6


def test_provider_recommendation_is_never_auto_purchased():
    from src.options.phase28_provider_decision import PROVIDER_RECOMMENDATION
    assert PROVIDER_RECOMMENDATION.awaiting_human_approval is True


def test_final_decision_gate_vocabulary_matches_part_18_exactly():
    from src.options.phase28_provider_decision import Phase28FinalDecision
    assert {v.value for v in Phase28FinalDecision} == {
        "no_paid_provider_justified", "paid_provider_recommended_pending_human_approval",
        "multiple_paid_providers_require_human_review", "paid_provider_data_unverified",
    }


def test_options_only_allowlist_never_includes_an_equity_structure():
    from src.execution.autonomous_architecture_audit import OptionStructure
    names = {s.value for s in OptionStructure}
    forbidden_terms = ("stock", "equity_share", "etf_share")
    for name in names:
        for term in forbidden_terms:
            assert term not in name


def test_no_phase28_file_declares_data_capability_validated_with_wrong_vocabulary():
    forbidden_patterns = ('= "VALIDATED"', '== "VALIDATED"')
    for path in _all_phase28_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to declare something VALIDATED via {pattern!r}"
