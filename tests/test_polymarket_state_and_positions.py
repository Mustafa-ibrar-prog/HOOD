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
        condition_id="c1", token_id="tok", outcome="YES", entry_price=0.5,
        size_usd=5.0, shares=10.0, opened_at=now, close_time=now + timedelta(minutes=10),
    )
    defaults.update(overrides)
    return OpenPosition(**defaults)


def test_position_store_add_and_remove(tmp_path):
    store = PolymarketPositionStore(tmp_path / "positions.json")
    assert store.load() == []
    position = _position()
    store.add(position)
    assert store.load() == [position]
    store.remove(position.condition_id)
    assert store.load() == []


def test_position_round_trips_through_json(tmp_path):
    store = PolymarketPositionStore(tmp_path / "positions.json")
    position = _position(condition_id="c2")
    store.add(position)
    reloaded = store.load()[0]
    assert reloaded.condition_id == position.condition_id
    assert reloaded.entry_price == position.entry_price
    assert reloaded.close_time == position.close_time
