"""Phase 30, Part 15/17 — paper-trading preparation interfaces."""

from __future__ import annotations

import dataclasses

import pytest

from src.options.paper_trading_simulation import (
    CommissionSchedule,
    PaperOrderRequest,
    PaperOrderStatus,
    PaperTradingLedger,
    reevaluate_pending_order,
    simulate_paper_exit,
    simulate_paper_order,
)
from src.options.research_dataset import build_research_observations
from tests.phase30_fixtures import synthetic_multi_bar_store, synthetic_store


def test_order_request_validates():
    with pytest.raises(ValueError):
        PaperOrderRequest(option_id="c1", side="hold", quantity=1)
    with pytest.raises(ValueError):
        PaperOrderRequest(option_id="c1", side="buy", quantity=0)


def test_simulated_fill_uses_real_ask():
    store = synthetic_store()
    rows = build_research_observations(store)
    req = PaperOrderRequest(option_id=rows[0].option_id, side="buy", quantity=2)
    fill = simulate_paper_order(req, rows[0])
    assert fill.status == PaperOrderStatus.FILLED
    assert fill.execution_price == rows[0].ask
    assert fill.filled_quantity == 2
    assert fill.order_simulation_event.status == "simulated_fill"


def test_rejected_order_when_no_ask_available():
    store = synthetic_store()
    rows = build_research_observations(store)
    poisoned = dataclasses.replace(rows[0], ask=None)
    req = PaperOrderRequest(option_id=poisoned.option_id, side="buy", quantity=1)
    fill = simulate_paper_order(req, poisoned)
    assert fill.status == PaperOrderStatus.REJECTED
    assert fill.execution_price is None
    assert fill.order_simulation_event.status == "execution_data_limited"


def test_commission_applied_per_contract_and_per_order():
    store = synthetic_store()
    rows = build_research_observations(store)
    req = PaperOrderRequest(option_id=rows[0].option_id, side="buy", quantity=3)
    schedule = CommissionSchedule(per_contract_usd=0.65, per_order_usd=1.0)
    fill = simulate_paper_order(req, rows[0], commission=schedule)
    assert fill.commission_usd == pytest.approx(1.0 + 0.65 * 3)


def test_slippage_assumption_shifts_execution_price():
    store = synthetic_store()
    rows = build_research_observations(store)
    req = PaperOrderRequest(option_id=rows[0].option_id, side="buy", quantity=1)
    fill = simulate_paper_order(req, rows[0], slippage_usd=0.03)
    assert fill.execution_price == rows[0].ask + 0.03
    assert fill.slippage_assumption_usd == 0.03


def test_partial_fill_when_liquidity_constrained():
    store = synthetic_multi_bar_store(n_bars=1)
    rows = build_research_observations(store)
    req = PaperOrderRequest(option_id=rows[0].option_id, side="buy", quantity=100)
    fill = simulate_paper_order(req, rows[0], max_fill_fraction_of_volume=0.5)
    max_expected = int(rows[0].volume * 0.5)
    assert fill.filled_quantity == max_expected
    assert fill.status in (PaperOrderStatus.PARTIALLY_FILLED, PaperOrderStatus.REJECTED)


def test_reevaluate_pending_order_uses_updated_row():
    store = synthetic_multi_bar_store(n_bars=3)
    rows = build_research_observations(store)
    req = PaperOrderRequest(option_id=rows[0].option_id, side="buy", quantity=1)
    fill = reevaluate_pending_order(req, rows[-1])
    assert fill.execution_price == rows[-1].ask
    assert fill.order_simulation_event.timestamp == rows[-1].observation_timestamp


def test_simulate_exit_realizes_pnl_on_a_long_close():
    store = synthetic_store()
    rows = build_research_observations(store)
    exit_result = simulate_paper_exit(
        option_id=rows[0].option_id, side_to_close="sell", quantity=1, entry_price=4.50, row=rows[0],
    )
    assert exit_result.status == PaperOrderStatus.FILLED
    assert exit_result.execution_price == rows[0].bid
    expected_pnl = (rows[0].bid - 4.50) * 1 * 100 - exit_result.commission_usd
    assert exit_result.realized_pnl == pytest.approx(expected_pnl)


def test_simulate_exit_rejected_when_no_bid():
    store = synthetic_store()
    rows = build_research_observations(store)
    poisoned = dataclasses.replace(rows[0], bid=None)
    exit_result = simulate_paper_exit(option_id=poisoned.option_id, side_to_close="sell", quantity=1, entry_price=4.5, row=poisoned)
    assert exit_result.status == PaperOrderStatus.REJECTED
    assert exit_result.realized_pnl is None


def test_ledger_tracks_fills_and_exits():
    store = synthetic_store()
    rows = build_research_observations(store)
    cid = rows[0].option_id
    ledger = PaperTradingLedger()

    req = PaperOrderRequest(option_id=cid, side="buy", quantity=2)
    fill = simulate_paper_order(req, rows[0])
    ledger.apply_fill(fill)
    assert ledger.position(cid).open_quantity == 2

    exit_result = simulate_paper_exit(option_id=cid, side_to_close="sell", quantity=2, entry_price=rows[0].ask, row=rows[0])
    ledger.apply_exit(exit_result)
    state = ledger.position(cid)
    assert state.open_quantity == 0
    assert state.exit_count == 1
    assert state.fill_count == 1


def test_ledger_never_updates_on_rejected_fill():
    store = synthetic_store()
    rows = build_research_observations(store)
    poisoned = dataclasses.replace(rows[0], ask=None)
    req = PaperOrderRequest(option_id=poisoned.option_id, side="buy", quantity=5)
    fill = simulate_paper_order(req, poisoned)
    ledger = PaperTradingLedger()
    ledger.apply_fill(fill)
    assert ledger.position(poisoned.option_id).open_quantity == 0


def test_unknown_position_returns_a_zeroed_state_not_a_crash():
    ledger = PaperTradingLedger()
    state = ledger.position("nonexistent")
    assert state.open_quantity == 0
    assert state.realized_pnl_usd == 0.0
