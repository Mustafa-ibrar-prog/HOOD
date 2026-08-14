"""These tests exist to prove one thing above all else: this codebase
cannot place a real order while TRADING_MODE=paper, and cannot place one at
all yet regardless of TRADING_MODE, because live execution isn't built."""

from __future__ import annotations

import pytest

from src.execution.gateway import (
    LiveExecutionGateway,
    LiveTradingDisabledError,
    PaperExecutionGateway,
    assert_paper_mode,
    get_execution_gateway,
)
from src.execution.orders import OrderLeg, OrderRequest
from src.logging.decision_logger import DecisionLogger


@pytest.fixture
def decision_logger(tmp_path) -> DecisionLogger:
    return DecisionLogger(path=tmp_path / "decisions.jsonl", also_console=False)


@pytest.fixture
def sample_order() -> OrderRequest:
    return OrderRequest(
        account_number="ACC123",
        legs=(OrderLeg(option_id="opt-1", side="buy", position_effect="open"),),
        quantity="1",
        type="limit",
        price="1.05",
        reason="TARGET_EXIT",
    )


def test_get_execution_gateway_returns_paper_gateway_in_paper_mode(paper_settings, decision_logger):
    gateway = get_execution_gateway(paper_settings, decision_logger)
    assert isinstance(gateway, PaperExecutionGateway)


def test_get_execution_gateway_refuses_in_live_mode(live_settings, decision_logger):
    with pytest.raises(LiveTradingDisabledError):
        get_execution_gateway(live_settings, decision_logger)


def test_paper_gateway_never_raises_and_simulates_fill(paper_settings, decision_logger, sample_order):
    gateway = PaperExecutionGateway(paper_settings, decision_logger)
    result = gateway.submit_order(sample_order)
    assert result.status == "simulated_fill"
    assert result.simulated_fill is not None
    assert result.simulated_fill.fill_price == 1.05


def test_paper_gateway_logs_every_simulated_order(paper_settings, decision_logger, sample_order):
    gateway = PaperExecutionGateway(paper_settings, decision_logger)
    gateway.submit_order(sample_order)
    records = decision_logger.read_all()
    assert len(records) == 1
    assert records[0]["kind"] == "simulated_order"


def test_paper_gateway_refuses_if_settings_somehow_say_live(live_settings, decision_logger, sample_order):
    # Defense in depth: even if a caller manages to hand a "live" Settings
    # object to the paper gateway directly, it must still refuse.
    gateway = PaperExecutionGateway(live_settings, decision_logger)
    with pytest.raises(LiveTradingDisabledError):
        gateway.submit_order(sample_order)


def test_live_gateway_always_refuses_submit_regardless_of_mode(sample_order):
    gateway = LiveExecutionGateway()
    with pytest.raises(LiveTradingDisabledError):
        gateway.submit_order(sample_order)


def test_live_gateway_always_refuses_cancel():
    gateway = LiveExecutionGateway()
    with pytest.raises(LiveTradingDisabledError):
        gateway.cancel_order("ACC123", "order-1")


def test_assert_paper_mode_passes_in_paper(paper_settings):
    assert_paper_mode(paper_settings)  # must not raise


def test_assert_paper_mode_raises_in_live(live_settings):
    with pytest.raises(LiveTradingDisabledError):
        assert_paper_mode(live_settings)


def test_paper_gateway_cancel_never_raises(paper_settings, decision_logger):
    gateway = PaperExecutionGateway(paper_settings, decision_logger)
    result = gateway.cancel_order("ACC123", "order-1")
    assert result.status == "simulated_fill"
    records = decision_logger.read_all()
    assert any(r["kind"] == "simulated_cancel" for r in records)
