"""Tests for the append-only "teaching moment" trade journal.

Covers: entry serialization round-trips, the deterministic lesson-template
branches, record_close's actual write behavior (including the derived
hold_minutes/pnl_pct math), and summary()'s aggregation. Explicitly does
NOT test any config-mutation behavior, because there isn't any — see the
module's own docstring.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.logging.trade_journal import TradeJournal, TradeJournalEntry, _derive_lesson
from src.strategy.decision import Decision, DecisionResult
from tests.conftest import make_position


def _result(decision: Decision, reason: str, **evidence) -> DecisionResult:
    return DecisionResult(decision=decision, reason=reason, confidence=0.8, evidence=evidence)


def test_entry_to_dict_from_dict_round_trip():
    entry = TradeJournalEntry(
        closed_at=datetime(2026, 8, 14, 15, 0, tzinfo=timezone.utc),
        trade_mode="paper",
        symbol="AAPL",
        option_id="11111111-1111-1111-1111-111111111111",
        option_description="AAPL 2026-09-18 C 230",
        side="long_call",
        setup_name="test-breakout",
        direction="bullish",
        catalyst="broke above 20-bar resistance on volume",
        entry_price=0.95,
        entry_time=datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc),
        exit_decision=Decision.TARGET_EXIT.value,
        exit_reason="Profit target reached",
        realized_pnl_usd=20.0,
        realized_pnl_pct=0.21,
        hold_minutes=300.0,
        momentum_state_at_exit="strengthening",
        momentum_signals_at_exit=("higher_highs", "rsi_rising"),
        lesson="Took the planned win.",
    )
    restored = TradeJournalEntry.from_dict(entry.to_dict())
    assert restored == entry


def test_from_dict_defaults_missing_optional_fields():
    data = {
        "closed_at": "2026-08-14T15:00:00+00:00",
        "trade_mode": "paper",
        "symbol": "AAPL",
        "option_id": "abc",
        "option_description": "AAPL 2026-09-18 C 230",
        "side": "long_call",
        "setup_name": "test-breakout",
        "direction": "bullish",
        "catalyst": "broke above resistance",
        "entry_price": 0.95,
        "entry_time": "2026-08-14T10:00:00+00:00",
        "exit_decision": "TARGET_EXIT",
        "exit_reason": "Profit target reached",
        "realized_pnl_usd": 20.0,
        "realized_pnl_pct": 0.21,
        "hold_minutes": 300.0,
        "momentum_state_at_exit": "strengthening",
    }
    entry = TradeJournalEntry.from_dict(data)
    assert entry.momentum_signals_at_exit == ()
    assert entry.lesson == ""


def test_derive_lesson_trailing_exit_win_vs_reversal():
    win = _derive_lesson(Decision.EXIT, "Trailing exit: price peaked at $1.05 ...", 5.0)
    assert "locked in a real gain" in win
    loss = _derive_lesson(Decision.EXIT, "Trailing exit: price peaked at $1.05 ...", -1.0)
    assert "reversed" in loss


def test_derive_lesson_stop_exit():
    lesson = _derive_lesson(Decision.STOP_EXIT, "Stop-loss breached", -15.0)
    assert "Hard stop" in lesson


def test_derive_lesson_target_exit():
    lesson = _derive_lesson(Decision.TARGET_EXIT, "Profit target reached", 20.0)
    assert "Profit target reached" in lesson


def test_derive_lesson_early_exit_profitable_vs_loss():
    profitable = _derive_lesson(Decision.EXIT, "Evidence shows the move has weakened", 5.0)
    assert "evidence-based exit path working as intended" in profitable
    losing = _derive_lesson(Decision.EXIT, "Evidence shows the move has weakened", -3.0)
    assert "cut before it could develop into a stop-out" in losing


def test_derive_lesson_generic_fallback():
    lesson = _derive_lesson(Decision.HOLD, "some unexpected reason", 0.0)
    assert "HOLD" in lesson
    assert "some unexpected reason" in lesson


def test_load_returns_empty_list_when_file_missing(tmp_path):
    journal = TradeJournal(tmp_path / "journal.jsonl")
    assert journal.load() == []


def test_record_close_writes_and_load_round_trips(tmp_path):
    journal = TradeJournal(tmp_path / "nested" / "journal.jsonl")
    position = make_position(entry_price=0.95, entry_time=datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc))
    result = _result(
        Decision.TARGET_EXIT,
        "Profit target reached",
        momentum_state="strengthening",
        momentum_signals=["higher_highs"],
    )
    now = datetime(2026, 8, 14, 15, 0, tzinfo=timezone.utc)

    entry = journal.record_close(
        position=position,
        result=result,
        exit_price=1.15,
        realized_pnl_usd=20.0,
        trade_mode="paper",
        now=now,
    )

    assert entry.hold_minutes == 300.0
    assert round(entry.realized_pnl_pct, 4) == round((1.15 - 0.95) / 0.95, 4)
    assert entry.momentum_state_at_exit == "strengthening"
    assert entry.momentum_signals_at_exit == ("higher_highs",)
    assert "Profit target reached" in entry.lesson

    loaded = journal.load()
    assert loaded == [entry]


def test_record_close_appends_multiple_entries(tmp_path):
    journal = TradeJournal(tmp_path / "journal.jsonl")
    position = make_position()
    now = datetime(2026, 8, 14, 15, 0, tzinfo=timezone.utc)

    journal.record_close(
        position=position,
        result=_result(Decision.TARGET_EXIT, "target"),
        exit_price=1.15,
        realized_pnl_usd=20.0,
        trade_mode="paper",
        now=now,
    )
    journal.record_close(
        position=position,
        result=_result(Decision.STOP_EXIT, "stop"),
        exit_price=0.50,
        realized_pnl_usd=-15.0,
        trade_mode="live",
        now=now,
    )

    loaded = journal.load()
    assert len(loaded) == 2
    assert loaded[0].trade_mode == "paper"
    assert loaded[1].trade_mode == "live"


def test_summary_empty(tmp_path):
    journal = TradeJournal(tmp_path / "journal.jsonl")
    assert journal.summary() == {"trade_count": 0}


def test_summary_aggregates_wins_losses_and_exit_types(tmp_path):
    journal = TradeJournal(tmp_path / "journal.jsonl")
    position = make_position()
    now = datetime(2026, 8, 14, 15, 0, tzinfo=timezone.utc)

    journal.record_close(
        position=position,
        result=_result(Decision.TARGET_EXIT, "target"),
        exit_price=1.15,
        realized_pnl_usd=20.0,
        trade_mode="paper",
        now=now,
    )
    journal.record_close(
        position=position,
        result=_result(Decision.STOP_EXIT, "stop"),
        exit_price=0.50,
        realized_pnl_usd=-15.0,
        trade_mode="paper",
        now=now,
    )
    journal.record_close(
        position=position,
        result=_result(Decision.EXIT, "Trailing exit: ..."),
        exit_price=1.02,
        realized_pnl_usd=7.0,
        trade_mode="paper",
        now=now,
    )

    summary = journal.summary()
    assert summary["trade_count"] == 3
    assert summary["win_count"] == 2
    assert summary["loss_count"] == 1
    assert round(summary["win_rate"], 4) == round(2 / 3, 4)
    assert summary["total_realized_pnl_usd"] == 12.0
    assert summary["exit_type_counts"] == {"TARGET_EXIT": 1, "STOP_EXIT": 1, "EXIT": 1}
