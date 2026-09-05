"""Phase 37 Final Safety Check (Part 25): Live Options Research Recorder
ONLY -- no live order, no paper order, no strategy deployed, no paid
provider, live authorization remains OFF, emergency stop remains ACTIVE,
MomentumBreakout remains NOT_READY, and the recorder contains NO
order-submission capability.

Same AST-based string/comment-blanking technique established in Phase
28-36's safety tests.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "src/research_recorder"

FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order",
    "submit_order", "cancel_order", "cancel_equity_order", "cancel_option_order", "cancel_crypto_order",
    "modify_order", "confirm_and_place", "review_option_order", "review_equity_order",
    "simulate_paper_order", "simulate_paper_exit",
)


def _all_package_files():
    return sorted(PACKAGE_DIR.rglob("*.py"))


def _string_literal_spans(path: Path) -> list[tuple[int, int, int, int]]:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    return [
        (n.lineno, n.col_offset, n.end_lineno, n.end_col_offset)
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and hasattr(n, "end_col_offset")
    ]


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


def test_no_file_calls_a_live_or_paper_order_function():
    for path in _all_package_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        for call in FORBIDDEN_CALLS:
            assert f"{call}(" not in source, f"{path} appears to call {call!r} outside a string/comment"


def test_no_file_enables_live_or_paper_trading():
    forbidden_patterns = ("live_trading_confirmed=True", "live_auto_execute=True", "trading_mode=\"live\"", "trading_mode='live'")
    for path in _all_package_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to enable live/paper trading via {pattern!r}"


def test_no_file_marks_a_strategy_validated_or_records_human_authorization():
    for path in _all_package_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        assert "StrategyStatus.VALIDATED" not in source
        assert "StrategyStatus.LIVE_AUTHORIZED" not in source
        assert ".mark_validated(" not in source
        assert "record_human_authorized_transition(" not in source
        assert "record_code_transition(" not in source


def test_no_file_clears_or_activates_the_emergency_stop():
    for path in _all_package_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        assert ".clear(" not in source
        assert ".activate(" not in source


def test_no_file_purchases_or_activates_a_paid_provider():
    forbidden_patterns = ("purchase(", "create_account(", "stripe.", "checkout.", "ORATS_API_KEY = \"", "ORATS_API_KEY='")
    for path in _all_package_files():
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to purchase/activate a paid provider via {pattern!r}"


# --- MomentumBreakoutStrategy remains NOT_READY --------------------------------------------------


def test_momentum_breakout_still_not_ready_in_the_default_registry():
    from src.production.registry import StrategyStatus, build_default_registry

    registry = build_default_registry()
    entry = registry.get("MOMENTUM_BREAKOUT_EXISTING_V1", "1.0")
    assert entry.status == StrategyStatus.NOT_READY
    assert registry.production_eligible_strategies() == ()


def test_research_signal_module_never_registers_or_promotes_the_strategy():
    source = _code_with_string_literals_and_comments_blanked(PACKAGE_DIR / "research_signal.py")
    assert "StrategyRegistry" not in source
    assert "ValidationArtifact" not in source


# --- Live authorization OFF / emergency stop ACTIVE ----------------------------------------------


def test_emergency_stop_defaults_active_with_no_record(tmp_path):
    from src.execution.emergency_stop import EmergencyStopStore
    assert EmergencyStopStore(tmp_path / "missing.json").is_stopped() is True


def test_no_system_state_record_means_unauthorized(tmp_path):
    from src.execution.system_state import SystemStateAuditLog, is_live_trading_authorized
    log = SystemStateAuditLog(tmp_path / "missing.jsonl")
    assert is_live_trading_authorized(log) is False


def test_current_env_still_paper_and_unconfirmed():
    from src.config.settings import Settings
    settings = Settings.from_env(env={})
    assert settings.trading_mode == "paper"
    assert settings.live_trading_confirmed is False
    assert settings.live_auto_execute is False


# --- The recorder contains NO order-submission capability ----------------------------------------


def test_recorder_stores_have_no_write_methods_beyond_append():
    """Every store class exposes only `append`-shaped mutation methods --
    none of them can construct or emit an order."""
    import src.research_recorder.storage as storage_module

    for name in ("RawObservationStore", "NormalizedUnderlyingStore", "NormalizedOptionStore", "ResearchSignalStore", "CycleLogStore"):
        cls = getattr(storage_module, name)
        public_methods = [m for m in dir(cls) if not m.startswith("_")]
        for method in public_methods:
            assert "order" not in method.lower(), f"{name}.{method} looks order-related"


def test_orchestrator_does_not_import_the_research_recorder():
    """Phase 37, like Phase 36, connects nothing into the live cycle --
    orchestrator.py must not import this package."""
    source = (REPO_ROOT / "src/orchestrator.py").read_text()
    assert "research_recorder" not in source
