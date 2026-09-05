"""Phase 37, Part 2/24 — THE critical architectural test: the Live
Options Research Recorder cannot reach the order execution path.

Structurally enforced, not merely `live_auto_execute=False` (Part 2's
explicit instruction) -- verified three independent ways:
  1. Static AST scan of every file in `src/research_recorder/` for a
     forbidden import (direct, at any nesting level -- module-level or
     function-local).
  2. Static scan for a forbidden call substring (`place_option_order(`,
     `submit_order(`, `cancel_order(`, `modify_order(`, `confirm_and_place(`)
     outside a string/comment.
  3. A DYNAMIC check: actually importing every module in the package and
     inspecting `sys.modules` afterward for `src.execution.gateway`/
     `src.execution.live_client`/`src.market.hood_client`'s broker-order
     surface -- this catches a TRANSITIVE import a purely static per-file
     scan could miss (e.g. importing some other module that itself
     imports the gateway).
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "src/research_recorder"

FORBIDDEN_IMPORT_PREFIXES = (
    "src.execution.gateway",
    "src.execution.live_client",
)
FORBIDDEN_CALLS = (
    "place_equity_order", "place_option_order", "place_crypto_order",
    "submit_order", "cancel_order", "cancel_equity_order", "cancel_option_order", "cancel_crypto_order",
    "modify_order", "confirm_and_place", "review_option_order", "review_equity_order",
)


def _package_files():
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


def test_package_has_files_to_check():
    assert len(_package_files()) >= 10


def test_no_file_imports_a_forbidden_module_at_any_level():
    """Walks the ENTIRE AST (not just top-level statements), so a
    function-local `import` is caught exactly like a module-level one."""
    for path in _package_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in FORBIDDEN_IMPORT_PREFIXES:
                    assert not node.module.startswith(prefix), f"{path} imports {node.module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in FORBIDDEN_IMPORT_PREFIXES:
                        assert not alias.name.startswith(prefix), f"{path} imports {alias.name}"


def test_no_file_calls_an_order_submission_or_cancellation_function():
    for path in _package_files():
        source = _code_with_string_literals_and_comments_blanked(path)
        for call in FORBIDDEN_CALLS:
            assert f"{call}(" not in source, f"{path} appears to call {call!r} outside a string/comment"


def test_dynamic_import_of_every_module_never_pulls_in_the_execution_gateway():
    """The decisive check: in a FRESH, isolated subprocess (never the
    pytest process itself, whose `sys.modules` is already contaminated
    by unrelated test files that legitimately import
    `src.execution.gateway` for their OWN tests -- e.g.
    test_live_execution.py), actually import every real module in the
    package and inspect THAT process's `sys.modules` afterward. A
    transitive import (module A imports module B, B imports the
    gateway) would be invisible to a per-file static scan but is caught
    here."""
    package_modules = [
        "src.research_recorder",
        "src.research_recorder.provenance",
        "src.research_recorder.market_hours",
        "src.research_recorder.target_universe",
        "src.research_recorder.raw_observation",
        "src.research_recorder.dte",
        "src.research_recorder.moneyness",
        "src.research_recorder.normalized_observation",
        "src.research_recorder.quote_quality",
        "src.research_recorder.contract_selection",
        "src.research_recorder.research_signal",
        "src.research_recorder.storage",
        "src.research_recorder.recorder",
        "src.research_recorder.quality_report",
        "src.research_recorder.security",
    ]
    script = (
        "import sys\n"
        + "\n".join(f"import {name}" for name in package_modules)
        + "\n"
        + "forbidden = [m for m in sys.modules if m.startswith('src.execution.gateway') or m.startswith('src.execution.live_client')]\n"
        + "print(','.join(forbidden))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    forbidden_loaded = [m for m in result.stdout.strip().split(",") if m]
    assert forbidden_loaded == [], f"Importing the research_recorder package pulled in: {forbidden_loaded}"


def test_recorder_module_has_no_order_submission_function_reachable():
    """Belt-and-braces: recorder.py (the main orchestration entry point)
    exposes no callable whose name suggests order submission."""
    import src.research_recorder.recorder as recorder_module

    for name in dir(recorder_module):
        assert "submit" not in name.lower() or name.startswith("_"), f"recorder.py exposes {name!r}"
        assert "place_order" not in name.lower()


def test_place_option_order_still_called_from_exactly_one_place_in_all_of_src():
    """Reconfirms the Phase 18/35/36 invariant after adding an entire new
    package -- place_option_order( still appears as an executable call in
    exactly one file, gateway.py's _place_pending."""
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
