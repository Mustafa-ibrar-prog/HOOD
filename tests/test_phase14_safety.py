"""Phase 14 Final Safety Check: this phase STOPPED at the data-capability
audit (MICROSTRUCTURE_DATA_INSUFFICIENT) — no P14-MICRO-* hypothesis
family was created, no features were built, no discovery analysis ran, no
gate transitions were recorded. These tests verify that stop was genuine:
no live/paper orders, no modification of any prior-phase hypothesis, and
critically, no fabricated bid/ask/spread/order-flow/order-book data
anywhere in the Phase 14 surface.

Mirrors tests/test_phase8_safety.py through test_phase13_safety.py's
pattern, scoped down to what an audit-only phase actually touches.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PHASE14_SCRIPTS = sorted((REPO_ROOT / "scripts").glob("phase14_*.py"))
FORBIDDEN_IMPORT_PREFIXES = ("src.execution", "src.orchestrator")
FORBIDDEN_CALLS = ("place_equity_order", "place_option_order", "place_crypto_order", "submit_order", "cancel_equity_order", "cancel_option_order")


def test_phase14_has_no_hypothesis_family_or_discovery_script():
    """This phase stopped at the audit stage (Part 4/25) — there must be
    no step1 (preregistration) or step2 (discovery campaign) script, since
    no hypothesis was ever registered."""
    names = {p.name for p in PHASE14_SCRIPTS}
    assert not any("preregister" in n for n in names)
    assert not any("discovery_campaign" in n for n in names)


def test_no_phase14_script_imports_the_live_execution_or_orchestrator_path():
    for path in PHASE14_SCRIPTS:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in FORBIDDEN_IMPORT_PREFIXES:
                    assert not node.module.startswith(prefix), f"{path} imports {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in FORBIDDEN_IMPORT_PREFIXES:
                        assert not alias.name.startswith(prefix), f"{path} imports {alias.name}"


def test_no_phase14_script_references_a_live_order_placement_call():
    for path in PHASE14_SCRIPTS:
        source = path.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in source, f"{path} references {call!r}"


def test_no_phase14_script_functionally_touches_mr002_or_any_prior_phase_hypothesis():
    prior_ids = (
        ("MR-002", "P7-VOLANOM-A", "P7-VOLANOM-A-DEV1", "P9-VOLCLUST-A")
        + tuple(f"P10-VP-{i:03d}" for i in range(1, 11))
        + tuple(f"P11-VCE-{i:03d}" for i in range(1, 7))
        + tuple(f"P12-CSRS-{i:03d}" for i in range(1, 11))
        + tuple(f"P13-OID-{i:03d}" for i in range(1, 9))
    )
    forbidden_patterns = tuple(f'"{hid}"' for hid in prior_ids) + tuple(f"'{hid}'" for hid in prior_ids)
    for path in PHASE14_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} references a prior-phase hypothesis id via {pattern!r}"


def test_no_phase14_script_fabricates_microstructure_data():
    """The core safety property of an audit-only phase: no code path
    computes/estimates/synthesizes a bid, ask, spread, order-imbalance, or
    signed-volume VALUE from OHLCV. This deliberately does NOT forbid
    merely discussing/naming these concepts (the audit script's whole job
    is to explain why they are absent) — only concrete fabrication
    signatures: assigning a spread/bid/ask-shaped variable from an OHLCV
    expression."""
    forbidden_patterns = (
        "estimated_spread", "synthetic_spread", "implied_spread", "fake_bid", "fake_ask",
        "spread = high", "spread=high", "spread = (high", "bid = close", "ask = close",
        "bid=close", "ask=close", "bid_price = close", "ask_price = close",
    )
    for path in PHASE14_SCRIPTS:
        source = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, f"{path} appears to construct microstructure data via {pattern!r}"


def test_no_phase14_script_constructs_more_than_one_historical_data_store():
    """No adjusted/unadjusted (or otherwise dual-source) price mixing:
    each Phase 14 script touches at most one HistoricalDataStore."""
    for path in PHASE14_SCRIPTS:
        source = path.read_text()
        assert source.count("HistoricalDataStore(") <= 1, f"{path} constructs more than one HistoricalDataStore"


def test_no_phase14_script_touches_development_validation_or_final_holdout_data():
    for path in PHASE14_SCRIPTS:
        source = path.read_text()
        assert "PartitionLifecycleStage.VALIDATION" not in source
        assert "PartitionLifecycleStage.FINAL_HOLDOUT" not in source
        assert "PartitionLifecycleStage.DEVELOPMENT" not in source


def test_no_phase14_script_writes_to_the_discovery_development_gate():
    """No hypothesis was preregistered or classified this phase — there
    should be no gate_store.transition(...) call anywhere in Phase 14."""
    for path in PHASE14_SCRIPTS:
        source = path.read_text()
        assert "gate_store.transition(" not in source
        assert "DiscoveryDevelopmentGateStore(" not in source
