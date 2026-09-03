"""Phase 18, Part 22/10 — the explicit options-only execution
restriction test: 'BUY AAPL 100 SHARES' (or any non-options-shaped
order) must be rejected."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.execution.asset_class_restriction import ASSET_CLASS_RESTRICTION, NonOptionsOrderRejected, assert_options_only
from src.execution.orders import OrderLeg, OrderRequest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_asset_class_restriction_is_options_only():
    assert ASSET_CLASS_RESTRICTION == "OPTIONS_ONLY"


def test_valid_options_order_passes():
    order = OrderRequest(account_number="acct1", legs=(OrderLeg(option_id="real-option-id", side="buy", position_effect="open"),), quantity="1", price="3.53")
    assert_options_only(order)  # must not raise


def test_multi_leg_options_order_passes():
    order = OrderRequest(
        account_number="acct1",
        legs=(OrderLeg(option_id="leg-a", side="buy", position_effect="open"), OrderLeg(option_id="leg-b", side="sell", position_effect="open")),
        quantity="1", price="1.73",
    )
    assert_options_only(order)


def test_empty_option_id_leg_rejected():
    """The closest this codebase's shape can get to 'BUY AAPL 100
    SHARES' -- a leg with no real option_id -- must be rejected."""
    order = OrderRequest(account_number="acct1", legs=(OrderLeg(option_id="", side="buy", position_effect="open"),), quantity="100", price="230.00")
    with pytest.raises(NonOptionsOrderRejected):
        assert_options_only(order)


def test_order_with_no_legs_rejected_by_orderrequest_itself():
    """OrderRequest.__post_init__ already refuses a legless order before
    assert_options_only ever runs -- an even stronger guarantee than
    assert_options_only's own defensive check (which exists for the case
    where a caller somehow got a legs=() instance past construction)."""
    with pytest.raises(ValueError):
        OrderRequest(account_number="acct1", legs=(), quantity="1", price="1.00")


def test_order_leg_has_no_shares_or_equity_symbol_field():
    """Structural proof: OrderLeg cannot represent an equity order at
    all -- it has no field an equity order would need."""
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(OrderLeg)}
    assert "shares" not in field_names
    assert "equity_symbol" not in field_names
    assert "symbol" not in field_names
    assert "option_id" in field_names


def test_place_equity_order_never_called_anywhere_in_src():
    """Repository-wide static guarantee: place_equity_order/
    review_equity_order/cancel_equity_order are never actually invoked
    anywhere in src/ (the only mention is a docstring in
    src/market/hood_client.py explaining their deliberate absence)."""
    forbidden_calls = ("place_equity_order(", "review_equity_order(", "cancel_equity_order(")
    hood_client = REPO_ROOT / "src" / "market" / "hood_client.py"
    for path in (REPO_ROOT / "src").rglob("*.py"):
        source = path.read_text()
        for call in forbidden_calls:
            if call in source:
                # hood_client.py's own docstring NAMES these (without the trailing "(") to document
                # their absence -- but even there, the call form "xxx(" must never appear.
                assert path == hood_client, f"{path} appears to call {call!r}"


def test_no_equity_order_placement_function_defined_anywhere_in_execution():
    """AST-level guarantee: no function named like an equity order
    placer is DEFINED anywhere in src/execution/."""
    forbidden_prefixes = ("place_equity", "submit_equity", "buy_shares", "sell_shares")
    for path in (REPO_ROOT / "src" / "execution").glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for prefix in forbidden_prefixes:
                    assert not node.name.startswith(prefix), f"{path} defines {node.name} -- looks like an equity order placer"
