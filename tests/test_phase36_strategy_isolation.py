"""Phase 36, Part 3 — architectural tests proving the strategy/execution
boundary. A strategy must have NO direct access to: Robinhood order
placement, broker credentials, execution gateway submission, the live
authorization store, or the emergency-stop store.

Same AST-import-scan technique established across Phase 28-35's safety
tests (`_imports`, reused verbatim from tests/test_phase34_readiness_audit.py).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_MODULE_PREFIXES = (
    "src.execution.gateway",
    "src.execution.live_client",
    "src.market.hood_client",
    "src.execution.system_state",
    "src.execution.emergency_stop",
)

STRATEGY_FACING_MODULES = [
    "src/production/decision.py",
    "src/production/strategy_interface.py",
    "src/production/snapshot.py",
    "src/production/momentum_breakout_adapter.py",
]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
    return names


def test_no_strategy_facing_module_imports_a_forbidden_execution_module():
    for rel in STRATEGY_FACING_MODULES:
        imports = _imports(REPO_ROOT / rel)
        for name in imports:
            for prefix in FORBIDDEN_MODULE_PREFIXES:
                assert not name.startswith(prefix), f"{rel} imports {name} (forbidden prefix {prefix})"


def test_production_strategy_abc_has_no_execution_capability():
    from src.production.strategy_interface import ProductionStrategy
    for forbidden in ("submit_order", "place_order", "place_option_order", "cancel_order", "confirm_and_place"):
        assert not hasattr(ProductionStrategy, forbidden)


def test_momentum_breakout_adapter_has_no_execution_capability():
    from src.production.momentum_breakout_adapter import MomentumBreakoutProductionAdapter
    for forbidden in ("submit_order", "place_order", "place_option_order", "cancel_order", "confirm_and_place"):
        assert not hasattr(MomentumBreakoutProductionAdapter, forbidden)


def test_strategy_decision_carries_no_broker_reference():
    """A StrategyDecision's fields are all plain data (str/int/float/date/
    datetime/Mapping) -- never an ExecutionGateway, LiveOrderPlacer, or
    store reference."""
    import dataclasses

    from src.production.decision import StrategyDecision
    for f in dataclasses.fields(StrategyDecision):
        assert "Gateway" not in str(f.type) and "Placer" not in str(f.type) and "Store" not in str(f.type)


def test_pipeline_module_never_imports_gateway_or_live_client_at_module_level():
    """pipeline.py DOES perform one, single, deliberately-local (inside
    the function body, not at module level) READ-ONLY import of
    is_live_trading_authorized for the Authorization status check (Part
    16) -- verified separately below. It must never import
    src.execution.gateway or src.execution.live_client at all, at any
    level, since those are what could actually place an order."""
    path = REPO_ROOT / "src/production/pipeline.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("src.execution.gateway"), "pipeline.py imports src.execution.gateway"
            assert not node.module.startswith("src.execution.live_client"), "pipeline.py imports src.execution.live_client"


def test_pipeline_module_never_calls_submit_order_or_place_option_order():
    source = (REPO_ROOT / "src/production/pipeline.py").read_text()
    assert "submit_order(" not in source
    assert "place_option_order(" not in source
    assert "confirm_and_place(" not in source


def test_risk_handoff_never_calls_submit_order_or_place_option_order():
    source = (REPO_ROOT / "src/production/risk_handoff.py").read_text()
    assert "submit_order(" not in source
    assert "place_option_order(" not in source
    assert ".clear(" not in source  # never touches the emergency-stop store


def test_ranking_never_imports_a_signal_or_indicator_module():
    """Part 13: ranking must never become an undeclared second strategy."""
    imports = _imports(REPO_ROOT / "src/production/ranking.py")
    for name in imports:
        assert not name.startswith("src.market.indicators")
        assert not name.startswith("src.strategy.evidence")


def test_place_option_order_still_called_from_exactly_one_place_including_phase36():
    """Reconfirms Phase 35's invariant after adding an entire new package
    -- place_option_order( as an executable call must still appear in
    exactly one file in all of src/."""
    import re

    def_pattern = re.compile(r"\bdef\s+\w*place_option_order\s*\(")

    def _blanked(path: Path) -> str:
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines(keepends=True)
        spans = [
            (n.lineno, n.col_offset, n.end_lineno, n.end_col_offset)
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and hasattr(n, "end_col_offset")
        ]
        for lineno, col, end_lineno, end_col in spans:
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

    call_sites = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        source = _blanked(path)
        for line in source.splitlines():
            if "place_option_order(" in line and not def_pattern.search(line):
                call_sites.append(path)
                break
    assert call_sites == [REPO_ROOT / "src/execution/gateway.py"], call_sites
