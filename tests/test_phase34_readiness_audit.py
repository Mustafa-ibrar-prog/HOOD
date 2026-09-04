"""Phase 34 — architectural/safety-gap regression guards.

Phase 34 is a READINESS AUDIT, not an implementation phase: nothing in
this file changes any production behavior. Each test here converts one
of this phase's real, verified findings (documented in
`docs/phase34_readiness_audit.md`) into a structural regression guard,
so a future phase cannot silently claim a gap is closed without this
test noticing, and cannot silently reopen a boundary this phase found
intact without this test catching it either.

Every test is a PASS today — each one documents CURRENT, VERIFIED
behavior (a real gap, or a real guarantee), never a fix. Where a test
documents a gap, its own assertion is written so that CLOSING the gap
in a future phase would make the test FAIL, prompting an intentional
update to both the code and this file together (never a silent drift).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


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


# --- Finding: the Phase 28 SystemState machine is real but unwired --------------


def test_system_state_module_still_declares_itself_design_only():
    source = (REPO_ROOT / "src/execution/system_state.py").read_text()
    assert "DESIGN ONLY" in source
    assert "nothing here is wired into" in source


def test_system_state_not_imported_by_gateway_settings_or_orchestrator():
    """Locks in Phase 34's headline finding: the 7-state authorization
    machine (RESEARCH -> ... -> LIVE_AUTONOMOUS_TRADING, EMERGENCY_STOP)
    is never consulted by the actual live gate. If a future phase wires
    it in, this test's assertion flips and must be updated deliberately
    -- it should never happen silently."""
    for rel in ("src/execution/gateway.py", "src/config/settings.py", "src/orchestrator.py"):
        imports = _imports(REPO_ROOT / rel)
        assert not any("system_state" in name for name in imports), f"{rel} now imports system_state -- update this test AND docs/phase34_readiness_audit.md"


# --- Finding: preflight.py (buying-power/account eligibility) is real but never called per-cycle --


def test_preflight_not_called_from_orchestrator_or_gateway():
    for rel in ("src/orchestrator.py", "src/execution/gateway.py"):
        imports = _imports(REPO_ROOT / rel)
        assert not any("preflight" in name for name in imports), f"{rel} now imports preflight -- update this test AND docs/phase34_readiness_audit.md"


# --- Finding: FEATURE ENGINE and opportunity_score.py are real but disconnected from the live path --


def test_features_package_not_imported_by_live_path():
    live_path_files = (
        "src/orchestrator.py", "src/strategy/momentum_breakout.py", "src/strategy/base.py",
        "src/strategy/scanner.py", "src/risk/manager.py", "src/position_manager/evaluator.py",
        "src/position_manager/monitor.py", "src/execution/gateway.py",
    )
    for rel in live_path_files:
        imports = _imports(REPO_ROOT / rel)
        assert not any(name == "src.features" or name.startswith("src.features.") for name in imports), (
            f"{rel} now imports src.features -- the live/research feature-computation boundary "
            f"described in docs/phase34_readiness_audit.md has changed; update both together"
        )


def test_opportunity_score_not_imported_by_live_path():
    live_path_files = (
        "src/orchestrator.py", "src/strategy/momentum_breakout.py", "src/strategy/scanner.py",
        "src/risk/manager.py",
    )
    for rel in live_path_files:
        imports = _imports(REPO_ROOT / rel)
        assert not any("opportunity_score" in name for name in imports), f"{rel} now imports opportunity_score -- update this test AND the report"


# --- Finding: no strategy in the live scanner was ever promoted from research/hypothesis IDs --


def test_no_research_hypothesis_id_referenced_in_live_execution_path():
    """P22/P31/P32/P33 hypothesis IDs must never appear in the live
    decision/execution path -- confirms no research finding was quietly
    promoted into production."""
    hypothesis_prefixes = ("P22-OPT", "P31-OPT", "P32-BKT", "P33-REPL")
    live_path_files = (
        "src/orchestrator.py", "src/strategy/momentum_breakout.py", "src/strategy/base.py",
        "src/strategy/scanner.py", "src/execution/gateway.py", "src/execution/orders.py",
        "src/risk/manager.py",
    )
    for rel in live_path_files:
        source = (REPO_ROOT / rel).read_text()
        for prefix in hypothesis_prefixes:
            assert prefix not in source, f"{rel} references {prefix} -- a research hypothesis must never be promoted into the live path without a fresh, explicit decision"


# --- Finding: only one concrete Strategy exists, and it was never statistically validated --


def test_exactly_one_concrete_strategy_class_exists_today():
    """Documents the current state (one live-wired strategy,
    MomentumBreakoutStrategy) so a second strategy silently appearing in
    the live scanner is caught and prompts a deliberate update to the
    readiness report's Strategy Status section."""
    strategy_dir = REPO_ROOT / "src/strategy"
    concrete_subclasses = []
    for path in strategy_dir.glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                (isinstance(b, ast.Name) and b.id == "Strategy") for b in node.bases
            ):
                concrete_subclasses.append(f"{path.name}:{node.name}")
    assert concrete_subclasses == ["momentum_breakout.py:MomentumBreakoutStrategy"]


# --- Finding: research/production import boundary (already covered by 12+ AST safety tests, re-asserted here as one final cross-cutting check) --


def test_no_research_or_options_module_imports_execution_or_orchestrator():
    """A final, cross-cutting re-assertion (Phase 34's own independent
    check) of what every test_phaseNN_safety.py already enforces
    per-phase: src/research/*.py and src/options/*.py must never import
    src.execution.gateway, src.execution.live_client, or src.orchestrator."""
    forbidden_prefixes = ("src.execution.gateway", "src.execution.live_client", "src.orchestrator")
    for directory in ("src/research", "src/options"):
        for path in (REPO_ROOT / directory).glob("*.py"):
            imports = _imports(path)
            for name in imports:
                for prefix in forbidden_prefixes:
                    assert not name.startswith(prefix), f"{path} imports {name}"


# --- Finding: a pending (awaiting-approval) live order is not visible to the duplicate-position check --


def test_check_duplicate_position_has_no_pending_order_parameter():
    """Documents a real gap this phase found: RiskManager.check_duplicate_position
    only ever sees FILLED open_positions, never PendingOrderStore's
    awaiting-approval records -- so two overlapping cycles could each
    propose a pending order for the same symbol before either is
    approved/rejected/expired. This test inspects the real method
    signature so it fails (prompting an update) the day this is fixed,
    rather than silently going stale."""
    import inspect

    from src.risk.manager import RiskManager

    sig = inspect.signature(RiskManager.check_duplicate_position)
    assert set(sig.parameters) == {"self", "candidate_symbol", "candidate_option_id", "open_positions"}


# --- Finding: OptionQuote has no Greeks/IV/size fields despite them being present in the live payload --


def test_option_quote_has_no_greeks_iv_or_size_fields():
    """Documents the live-data field gap: bid_size, ask_size,
    implied_volatility, delta, gamma, theta, vega, rho, break_even_price,
    and chance_of_profit are all confirmed present in the real live
    get_option_quotes payload (docs/options_architecture.md) but are not
    surfaced on the live-path OptionQuote model."""
    from dataclasses import fields

    from src.market.models import OptionQuote

    field_names = {f.name for f in fields(OptionQuote)}
    unavailable = {
        "bid_size", "ask_size", "implied_volatility", "delta", "gamma", "theta", "vega", "rho",
        "break_even_price", "chance_of_profit_long", "chance_of_profit_short",
    }
    assert field_names.isdisjoint(unavailable), (
        "OptionQuote now carries a field Phase 34 documented as unparsed -- update "
        "docs/phase34_readiness_audit.md's live data field audit to match"
    )


# --- Finding: position sizing is a flat USD cap, not equity/confidence/liquidity-aware --


def test_check_position_size_takes_only_a_flat_usd_amount():
    """Documents the position-sizing gap: the live sizing check has no
    parameter for account equity, confidence score, or liquidity --
    only a proposed dollar amount compared against a flat config cap."""
    import inspect

    from src.risk.manager import RiskManager

    sig = inspect.signature(RiskManager.check_position_size)
    assert set(sig.parameters) == {"self", "proposed_size_usd"}
