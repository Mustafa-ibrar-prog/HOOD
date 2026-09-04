"""Phase 29 Final Safety Check (Part 14/17): ORATS adapter, ingestion,
and certification only -- no purchase, no payment info, no paid
subscription, no stored API key, no order placement, no alpha
hypothesis, no strategy, no backtest, no signal/parameter/P&L/Sharpe
optimization, and -- reconfirmed, not weakened -- no per-trade
human-approval requirement anywhere in the (unmodified) system-state
design.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE29_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase29_*.py"))
PHASE29_SRC_MODULES = [
    "src/options/orats_config.py",
    "src/options/orats_field_provenance.py",
    "src/options/orats_schema_mapping.py",
    "src/options/orats_client.py",
    "src/options/orats_ingest.py",
    "src/options/orats_execution_certification.py",
    "src/options/orats_iv_greeks_certification.py",
    "src/options/orats_lifecycle_pit.py",
    "src/options/orats_corporate_actions.py",
    "src/options/orats_certification_score.py",
    "src/options/orats_activation_state.py",
    "src/options/orats_coverage_report.py",
]
FORBIDDEN_IMPORT_PREFIXES = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order", "submit_order",
    "cancel_equity_order", "cancel_option_order", "review_option_order", "review_equity_order",
)


def _all_phase29_files():
    return [REPO_ROOT / rel for rel in PHASE29_SRC_MODULES] + list(PHASE29_SCRIPTS)


def _string_literal_spans(path: Path) -> list[tuple[int, int, int, int]]:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and hasattr(node, "end_col_offset"):
            spans.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset))
    return spans


def _code_with_string_literals_and_comments_blanked(path: Path) -> str:
    """Same technique Phase 28's safety test established: this phase's
    modules legitimately DISCUSS real API field/call names in
    docstrings and comments (e.g. the real `place_option_order` tool
    name is never called here, only mentioned in prose explaining why
    it never is) -- so forbidden-pattern checks scan real code
    structure only, never string/comment content."""
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


def test_phase29_files_exist():
    for rel in PHASE29_SRC_MODULES:
        assert (REPO_ROOT / rel).is_file(), f"missing {rel}"


def test_no_phase29_file_imports_the_live_order_placement_path():
    for path in _all_phase29_files():
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


def test_no_phase29_file_calls_a_live_or_paper_order_placement_function():
    for path in _all_phase29_files():
        if not path.is_file():
            continue
        source = _code_with_string_literals_and_comments_blanked(path)
        for call in FORBIDDEN_CALLS:
            assert f"{call}(" not in source, f"{path} appears to call {call!r} outside a string/comment"


def test_no_phase29_file_creates_a_strategy_backtest_or_hypothesis():
    forbidden_patterns = (
        "LiveStrategy(", "PaperStrategy(", "StrategyExecutor(", "connect_alpha_to_execution",
        "Hypothesis(", "HypothesisRegistry(", "PreregistrationRecord(", "compute_ic_series(",
        "grid_search(", "optimize_parameters(", "run_backtest(", "sharpe_optimi", "signal_rank",
        "profitable_signal", "claimed_edge", "alpha_discovery", "p&l_optimization", "pnl_optimization",
    )
    for path in _all_phase29_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to register a hypothesis/backtest/strategy via {pattern!r}"


def test_no_phase29_file_purchases_a_vendor_or_hardcodes_a_credential():
    """No literal-looking real API key anywhere -- and no purchase/
    payment call of any kind."""
    forbidden_patterns = (
        "purchase(", "create_account(", "stripe.", "checkout.", "credit_card", "payment_method=",
        "card_number", "cvv", 'ORATS_API_KEY = "', "ORATS_API_KEY='",
    )
    for path in _all_phase29_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to purchase/hardcode a credential via {pattern!r}"


def test_no_env_file_or_committed_secret_holds_a_real_looking_orats_key():
    """A real API key is long, high-entropy, and never a placeholder
    like 'test'/'fake'/'sk_fake...' -- this test just confirms no .env
    or settings file in the repo defines ORATS_API_KEY at all (the only
    safe state for a repo that must never commit a credential)."""
    for candidate in (REPO_ROOT / ".env", REPO_ROOT / ".env.example"):
        if candidate.is_file():
            assert "ORATS_API_KEY=" not in candidate.read_text() or "ORATS_API_KEY=\n" in candidate.read_text() or "ORATS_API_KEY=\"\"" in candidate.read_text()


def test_no_live_or_paper_trading_enabled_by_this_phase():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_phase29_files():
        if not path.is_file():
            continue
        source = _code_with_string_literals_and_comments_blanked(path)
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r} outside a string/comment"


def test_no_phase29_file_fabricates_a_historical_field():
    forbidden_patterns = (
        "fabricated_bid", "fabricated_ask", "fabricated_oi", "fabricated_iv", "fabricated_greeks",
        "assumed_historical_bid", "assumed_historical_ask", "synthetic_historical_quote",
        "reconstructed_and_presented_as_observed",
    )
    for path in _all_phase29_files():
        if not path.is_file():
            continue
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to fabricate a historical field via {pattern!r}"


def test_synthetic_fixtures_never_imported_by_src_modules():
    """Part 4-style discipline (Phase 27): SYNTHETIC_TEST_DATA lives
    only in tests/, never imported by any src/ module."""
    for path in [REPO_ROOT / rel for rel in PHASE29_SRC_MODULES]:
        if not path.is_file():
            continue
        source = path.read_text()
        assert "orats_fixtures" not in source, f"{path} imports the test-only fixture module"
        assert "tests.orats_fixtures" not in source


def test_no_real_orats_response_is_ever_claimed_this_phase():
    """No src/ module may hardcode actually_returned_by_provider=True --
    that must only ever be set by a caller with a REAL response, and no
    caller in this phase's own src/ code has one."""
    for path in [REPO_ROOT / rel for rel in PHASE29_SRC_MODULES]:
        if not path.is_file():
            continue
        source = path.read_text()
        assert "actually_returned_by_provider=True" not in source


def test_system_state_machine_unchanged_no_per_trade_approval():
    """Phase 29 does not modify Phase 28's system_state.py -- re-
    confirmed here, not merely assumed."""
    from src.execution.system_state import SystemState
    assert len(SystemState) == 7
    names = {s.name for s in SystemState}
    assert "WAITING_FOR_TRADE_APPROVAL" not in names
    assert not any("PER_TRADE" in n or "TRADE_APPROVAL" in n for n in names)


def test_autonomous_architecture_pipeline_still_fifteen_stages_all_ready_or_partial():
    from src.execution.autonomous_architecture_audit import PIPELINE_READINESS, ReadinessStatus
    assert len(PIPELINE_READINESS) == 15
    assert all(a.status != ReadinessStatus.MISSING for a in PIPELINE_READINESS)


def test_options_only_structural_enforcement_still_holds():
    src = (REPO_ROOT / "src/execution/orders.py").read_text()
    assert "class OrderLeg" in src
    assert "option_id: str" in src


def test_orats_activation_state_is_pending_human_not_active():
    from src.options.orats_activation_state import CURRENT_STATE, ORATSActivationState
    assert CURRENT_STATE == ORATSActivationState.ORATS_ACTIVATION_PENDING_HUMAN
