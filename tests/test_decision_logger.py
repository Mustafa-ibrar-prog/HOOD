from __future__ import annotations

import json

import pytest

from src.execution.orders import OrderLeg, OrderRequest, OrderResult, SimulatedFill
from src.logging.decision_logger import DecisionLogger
from src.strategy.decision import Decision
from datetime import datetime, timezone


@pytest.fixture
def logger(tmp_path) -> DecisionLogger:
    return DecisionLogger(path=tmp_path / "decisions.jsonl", also_console=False)


def test_log_decision_writes_one_jsonl_record(logger):
    logger.log_decision(
        symbol="AAPL",
        option_id="opt-1",
        decision=Decision.HOLD,
        reason="momentum stable",
        confidence=0.6,
        evidence={"pnl_usd": 5.0},
    )
    records = logger.read_all()
    assert len(records) == 1
    record = records[0]
    assert record["symbol"] == "AAPL"
    assert record["decision"] == "HOLD"
    assert record["reason"] == "momentum stable"
    assert record["evidence"]["pnl_usd"] == 5.0
    assert "timestamp" in record


@pytest.mark.parametrize("decision", list(Decision))
def test_every_decision_type_is_loggable(logger, decision):
    logger.log_decision(
        symbol="AAPL",
        option_id="opt-1",
        decision=decision,
        reason=f"test for {decision.value}",
        confidence=0.5,
    )
    records = logger.read_all()
    assert records[-1]["decision"] == decision.value


def test_log_decision_is_written_immediately_not_buffered(logger, tmp_path):
    logger.log_decision(symbol="AAPL", option_id=None, decision=Decision.NO_TRADE, reason="no setups", confidence=1.0)
    # Read the raw file directly (not through the logger) to confirm the
    # write actually reached disk without needing a flush/close from the caller.
    raw = (tmp_path / "decisions.jsonl").read_text()
    assert json.loads(raw.strip())["decision"] == "NO_TRADE"


def test_log_risk_block_records_blocking_reasons(logger):
    logger.log_risk_block(
        context="new_trade",
        symbol="AAPL",
        attempted_decision=Decision.BUY,
        blocking_reasons=("Daily trade limit reached (4/4)",),
    )
    records = logger.read_all()
    assert records[0]["kind"] == "risk_block"
    assert "Daily trade limit reached" in records[0]["blocking_reasons"][0]


def test_log_simulated_order_records_order_and_result(logger):
    order = OrderRequest(
        account_number="ACC1",
        legs=(OrderLeg(option_id="opt-1", side="sell", position_effect="close"),),
        quantity="1",
        price="1.05",
        reason="TARGET_EXIT",
    )
    result = OrderResult(
        status="simulated_fill",
        request=order,
        simulated_fill=SimulatedFill(fill_price=1.05, filled_at=datetime.now(timezone.utc), quote_bid=1.03, quote_ask=1.07),
    )
    logger.log_simulated_order(order, result)
    records = logger.read_all()
    assert records[0]["kind"] == "simulated_order"
    assert records[0]["order"]["account_number"] == "ACC1"
    assert records[0]["result"]["status"] == "simulated_fill"


def test_read_all_returns_empty_list_when_no_log_yet(tmp_path):
    logger = DecisionLogger(path=tmp_path / "nonexistent.jsonl", also_console=False)
    assert logger.read_all() == []


def test_multiple_decisions_append_in_order(logger):
    logger.log_decision(symbol="AAPL", option_id="opt-1", decision=Decision.HOLD, reason="r1", confidence=0.5)
    logger.log_decision(symbol="AAPL", option_id="opt-1", decision=Decision.EXIT, reason="r2", confidence=0.9)
    records = logger.read_all()
    assert [r["decision"] for r in records] == ["HOLD", "EXIT"]
