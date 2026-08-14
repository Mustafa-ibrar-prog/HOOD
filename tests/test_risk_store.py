from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.risk.store import DailyRiskState, RiskStateError, RiskStateStore


def test_load_returns_fresh_state_when_no_file_exists(tmp_path):
    store = RiskStateStore(tmp_path / "risk_state.json")
    state = store.load(today=date(2026, 8, 14))
    assert state.trades_opened == 0
    assert state.daily_pnl_usd == 0.0


def test_save_and_load_round_trip(tmp_path):
    store = RiskStateStore(tmp_path / "risk_state.json")
    state = DailyRiskState(trade_date=date(2026, 8, 14))
    state.record_trade_opened(size_usd=100.0)
    state.record_exit("AAPL", datetime(2026, 8, 14, 11, 0, tzinfo=timezone.utc), realized_pnl_usd=-25.0)

    store.save(state)
    reloaded = store.load(today=date(2026, 8, 14))

    assert reloaded.trades_opened == 1
    assert reloaded.last_position_size_usd == 100.0
    assert reloaded.realized_pnl_usd == -25.0
    assert reloaded.last_trade_was_loss is True
    assert reloaded.last_exit_time("AAPL") is not None


def test_state_resets_automatically_on_new_day(tmp_path):
    store = RiskStateStore(tmp_path / "risk_state.json")
    state = DailyRiskState(trade_date=date(2026, 8, 14))
    state.record_trade_opened(size_usd=100.0)
    store.save(state)

    reloaded = store.load(today=date(2026, 8, 15))  # next day
    assert reloaded.trades_opened == 0
    assert reloaded.trade_date == date(2026, 8, 15)


def test_corrupted_state_file_fails_closed_instead_of_silently_resetting(tmp_path):
    path = tmp_path / "risk_state.json"
    path.write_text("{not valid json")
    store = RiskStateStore(path)
    with pytest.raises(RiskStateError):
        store.load(today=date(2026, 8, 14))


def test_empty_state_file_is_treated_as_no_state(tmp_path):
    path = tmp_path / "risk_state.json"
    path.write_text("")
    store = RiskStateStore(path)
    state = store.load(today=date(2026, 8, 14))
    assert state.trades_opened == 0
