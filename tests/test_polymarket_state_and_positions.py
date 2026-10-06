from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.state import DailyPnlState, DailyPnlStateStore, PolymarketRiskStateError


def test_daily_state_defaults_fresh_when_no_file(tmp_path):
    store = DailyPnlStateStore(tmp_path / "pnl.json")
    state = store.load(today=date(2026, 1, 1))
    assert state.trades_opened == 0
    assert state.realized_pnl_usd == 0.0


def test_daily_state_resets_on_a_new_day(tmp_path):
    path = tmp_path / "pnl.json"
    store = DailyPnlStateStore(path)
    yesterday = date(2026, 1, 1)
    state = store.load(today=yesterday)
    state.realized_pnl_usd = -15.0
    state.trades_opened = 3
    store.save(state)

    today = date(2026, 1, 2)
    fresh = store.load(today=today)
    assert fresh.trades_opened == 0
    assert fresh.realized_pnl_usd == 0.0
    assert fresh.trade_date == today


def test_daily_state_persists_within_the_same_day(tmp_path):
    path = tmp_path / "pnl.json"
    store = DailyPnlStateStore(path)
    today = date(2026, 1, 1)
    state = store.load(today=today)
    state.trades_opened = 2
    store.save(state)

    reloaded = store.load(today=today)
    assert reloaded.trades_opened == 2


def test_corrupted_state_file_fails_closed(tmp_path):
    path = tmp_path / "pnl.json"
    path.write_text("not json")
    store = DailyPnlStateStore(path)
    with pytest.raises(PolymarketRiskStateError):
        store.load(today=date(2026, 1, 1))


def _position(**overrides) -> OpenPosition:
    now = datetime.now(timezone.utc)
    defaults = dict(
        condition_id="c1", token_id="tok", outcome="YES", requested_size_usd=5.0,
        filled_shares=10.0, avg_fill_price=0.5, order_id="order-1", client_order_id="client-1",
        status="filled", opened_at=now, close_time=now + timedelta(minutes=10),
    )
    defaults.update(overrides)
    return OpenPosition(**defaults)


def test_filled_size_usd_reflects_actual_fill():
    position = _position(filled_shares=10.0, avg_fill_price=0.5)
    assert position.filled_size_usd == pytest.approx(5.0)


def test_position_store_add_if_absent_and_remove(tmp_path):
    store = PolymarketPositionStore(tmp_path / "positions.json")
    assert store.load() == []
    position = _position()
    assert store.add_if_absent(position) is True
    assert store.load() == [position]
    store.remove(position.condition_id)
    assert store.load() == []


def test_position_round_trips_through_json(tmp_path):
    store = PolymarketPositionStore(tmp_path / "positions.json")
    position = _position(condition_id="c2")
    store.add_if_absent(position)
    reloaded = store.load()[0]
    assert reloaded.condition_id == position.condition_id
    assert reloaded.avg_fill_price == position.avg_fill_price
    assert reloaded.filled_shares == position.filled_shares
    assert reloaded.client_order_id == position.client_order_id
    assert reloaded.close_time == position.close_time


# --- Idempotency (Task 5's explicit requirement) ------------------------------

def test_exists_reflects_client_order_id_membership(tmp_path):
    store = PolymarketPositionStore(tmp_path / "positions.json")
    position = _position(client_order_id="dup-1")
    assert store.exists("dup-1") is False
    store.add_if_absent(position)
    assert store.exists("dup-1") is True


def test_add_if_absent_refuses_a_second_position_for_the_same_client_order_id(tmp_path):
    store = PolymarketPositionStore(tmp_path / "positions.json")
    first = _position(client_order_id="dup-1", condition_id="c1")
    second = _position(client_order_id="dup-1", condition_id="c1")  # same order, reconciled twice
    assert store.add_if_absent(first) is True
    assert store.add_if_absent(second) is False
    assert len(store.load()) == 1


def test_add_if_absent_is_idempotent_across_a_fresh_store_instance(tmp_path):
    """Simulates a process restart: a brand-new PolymarketPositionStore
    object pointed at the same file must still refuse the duplicate,
    since the guard is based on the persisted file, not in-memory state."""
    path = tmp_path / "positions.json"
    position = _position(client_order_id="dup-1")
    assert PolymarketPositionStore(path).add_if_absent(position) is True
    assert PolymarketPositionStore(path).add_if_absent(position) is False
    assert len(PolymarketPositionStore(path).load()) == 1
