"""Phase 30 Final Safety Check (Part 16/17): infrastructure only -- no
new alpha hypothesis/strategy/backtest/profitability optimization (Part
10), no purchase/payment/credential, no live or paper order placement,
no autonomous live trading started, and the autonomous-architecture/
OPTIONS_ONLY guarantees remain exactly as Phase 28/29 left them.

Same AST-based string/comment-blanking technique established in Phase 28
and reused in Phase 29 -- this phase's modules legitimately DISCUSS real
mechanisms (e.g. "never calls place_option_order") in docstrings/
comments, so forbidden-pattern checks scan real code structure only.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE30_SRC_MODULES = [
    "src/options/research_dataset.py",
    "src/options/research_features.py",
    "src/options/contract_selection.py",
    "src/options/research_opportunity_score.py",
    "src/options/affordability.py",
    "src/options/execution_realism_pricing.py",
    "src/options/research_position_view.py",
    "src/options/research_risk_engine.py",
    "src/options/research_events.py",
    "src/options/free_dataset_limitations.py",
    "src/options/live_research_bridge.py",
    "src/options/paper_trading_simulation.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order", "submit_order",
    "cancel_equity_order", "cancel_option_order", "review_option_order", "review_equity_order",
)


def _all_phase30_files():
    return [REPO_ROOT / rel for rel in PHASE30_SRC_MODULES]


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


def test_phase30_files_exist():
    for rel in PHASE30_SRC_MODULES:
        assert (REPO_ROOT / rel).is_file(), f"missing {rel}"


def test_no_phase30_file_imports_the_live_order_placement_path():
    for path in _all_phase30_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in FORBIDDEN_IMPORT_PREFIXES:
                    assert not node.module.startswith(prefix), f"{path} imports {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in FORBIDDEN_IMPORT_PREFIXES:
                        assert not alias.name.startswith(prefix), f"{path} imports {alias.name}"


def test_no_phase30_file_calls_a_live_or_paper_order_placement_function():
    for path in _all_phase30_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        for call in FORBIDDEN_CALLS:
            assert f"{call}(" not in source, f"{path} appears to call {call!r} outside a string/comment"


def test_no_phase30_file_registers_a_new_alpha_hypothesis_or_backtest():
    """Part 10's explicit instruction: infrastructure only, no new alpha
    family/hypothesis this phase."""
    forbidden_patterns = (
        "LiveStrategy(", "PaperStrategy(", "StrategyExecutor(", "connect_alpha_to_execution",
        "Hypothesis(", "HypothesisRegistry(", "PreregistrationRecord(", "compute_ic_series(",
        "grid_search(", "optimize_parameters(", "run_backtest(", "sharpe_optimi", "signal_rank",
        "profitable_signal", "claimed_edge", "alpha_discovery", "p&l_optimization", "pnl_optimization",
    )
    for path in _all_phase30_files():
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to register a hypothesis/backtest/strategy via {pattern!r}"


def test_no_phase30_file_purchases_a_vendor_or_hardcodes_a_credential():
    forbidden_patterns = (
        "purchase(", "create_account(", "stripe.", "checkout.", "credit_card", "payment_method=",
        "card_number", "cvv", 'ORATS_API_KEY = "', "ORATS_API_KEY='",
    )
    for path in _all_phase30_files():
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to purchase/hardcode a credential via {pattern!r}"


def test_no_live_or_paper_trading_enabled_by_this_phase():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_phase30_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r} outside a string/comment"


def test_no_phase30_file_records_a_human_authorized_system_state_transition():
    """Only a real human, through the real system, may ever authorize a
    transition into HUMAN_LIVE_AUTHORIZATION or LIVE_AUTONOMOUS_TRADING --
    no Phase 30 module should even attempt to call that function."""
    for path in _all_phase30_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        assert "record_human_authorized_transition(" not in source, f"{path} calls record_human_authorized_transition"


def test_no_phase30_file_fabricates_a_historical_field():
    forbidden_patterns = (
        "fabricated_bid", "fabricated_ask", "fabricated_oi", "fabricated_iv", "fabricated_greeks",
        "assumed_historical_bid", "assumed_historical_ask", "synthetic_historical_quote",
        "reconstructed_and_presented_as_observed",
    )
    for path in _all_phase30_files():
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate a historical field via {pattern!r}"


def test_synthetic_fixtures_never_imported_by_src_modules():
    for path in _all_phase30_files():
        source = path.read_text()
        assert "phase30_fixtures" not in source, f"{path} imports the test-only fixture module"
        assert "tests.phase30_fixtures" not in source


def test_no_new_orats_purchase_or_activation_this_phase():
    """This phase must not reactivate/purchase ORATS -- the final state
    from Phase 29 remains ORATS_ACTIVATION_PENDING_HUMAN, unmodified."""
    from src.options.orats_activation_state import CURRENT_STATE, ORATSActivationState
    assert CURRENT_STATE == ORATSActivationState.ORATS_ACTIVATION_PENDING_HUMAN
    for path in _all_phase30_files():
        source = path.read_text()
        assert "ORATS_ACTIVATION_PENDING_HUMAN" not in source or "orats_activation_state" not in source


def test_null_scoring_method_is_the_only_scoring_method_registered():
    import src.options.research_opportunity_score as mod
    subclasses = [
        v for v in vars(mod).values()
        if isinstance(v, type) and issubclass(v, mod.ScoringMethod) and v is not mod.ScoringMethod
    ]
    assert subclasses == [mod.NullScoringMethod]
