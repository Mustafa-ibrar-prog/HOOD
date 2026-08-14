from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.execution.gateway import PaperExecutionGateway
from src.logging.decision_logger import DecisionLogger
from src.market.data_provider import MarketDataProvider, NotConfiguredMarketDataProvider
from src.position_manager.evaluator import PositionEvaluator
from src.position_manager.monitor import PositionMonitor, is_within_monitoring_window
from src.risk.manager import RiskManager
from src.strategy.decision import Decision, DecisionResult
from tests.conftest import make_market_snapshot, make_position


class _FakeFreshDataProvider(MarketDataProvider):
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def get_market_snapshot(self, option_id, underlying_symbol, now=None):
        return self._snapshot

    def get_option_chain_candidates(self, underlying_symbol, **filters):
        return []


class _AlwaysBuyEvaluator(PositionEvaluator):
    def evaluate(self, snapshot):
        return DecisionResult(decision=Decision.BUY, reason="bad evaluator", confidence=1.0)


@pytest.fixture
def decision_logger(tmp_path) -> DecisionLogger:
    return DecisionLogger(path=tmp_path / "decisions.jsonl", also_console=False)


@pytest.fixture
def gateway(paper_settings, decision_logger):
    return PaperExecutionGateway(paper_settings, decision_logger)


def test_is_within_monitoring_window_true_during_regular_hours(paper_settings):
    # Friday, Aug 14 2026, 11:00 — a weekday within 09:30-16:00
    now = datetime(2026, 8, 14, 11, 0)
    assert is_within_monitoring_window(now, paper_settings) is True


def test_is_within_monitoring_window_false_on_saturday(paper_settings):
    now = datetime(2026, 8, 15, 11, 0)  # Saturday
    assert is_within_monitoring_window(now, paper_settings) is False


def test_is_within_monitoring_window_false_before_open(paper_settings):
    now = datetime(2026, 8, 14, 8, 0)  # before 09:30
    assert is_within_monitoring_window(now, paper_settings) is False


def test_is_within_monitoring_window_false_after_close(paper_settings):
    now = datetime(2026, 8, 14, 17, 0)  # after 16:00
    assert is_within_monitoring_window(now, paper_settings) is False


def test_run_once_holds_when_no_data_provider_implemented(paper_settings, risk_limits, decision_logger, gateway):
    monitor = PositionMonitor(
        settings=paper_settings,
        market_data=NotConfiguredMarketDataProvider(),
        evaluator=PositionEvaluator(),
        risk_manager=RiskManager(risk_limits),
        decision_logger=decision_logger,
        execution_gateway=gateway,
    )
    position = make_position()
    result = monitor.run_once(position, now=datetime.now(timezone.utc))
    assert result.decision_result.decision is Decision.HOLD
    assert result.acted is False
    assert decision_logger.read_all()  # something was logged


def test_run_once_holds_on_stale_market_data(paper_settings, risk_limits, decision_logger, gateway):
    stale_snapshot = make_market_snapshot(fetched_at=datetime.now(timezone.utc) - timedelta(minutes=10))
    monitor = PositionMonitor(
        settings=paper_settings,
        market_data=_FakeFreshDataProvider(stale_snapshot),
        evaluator=PositionEvaluator(),
        risk_manager=RiskManager(risk_limits),
        decision_logger=decision_logger,
        execution_gateway=gateway,
    )
    position = make_position()
    result = monitor.run_once(position, now=datetime.now(timezone.utc))
    assert result.decision_result.decision is Decision.HOLD
    assert "stale" in result.decision_result.reason.lower() or "unreliable" in result.decision_result.reason.lower()


def test_run_once_evaluates_and_logs_with_fresh_data(paper_settings, risk_limits, decision_logger, gateway):
    fresh_snapshot = make_market_snapshot(fetched_at=datetime.now(timezone.utc))
    monitor = PositionMonitor(
        settings=paper_settings,
        market_data=_FakeFreshDataProvider(fresh_snapshot),
        evaluator=PositionEvaluator(),
        risk_manager=RiskManager(risk_limits),
        decision_logger=decision_logger,
        execution_gateway=gateway,
    )
    position = make_position()
    result = monitor.run_once(position, now=datetime.now(timezone.utc))
    assert result.decision_result.decision in {Decision.HOLD, Decision.EXIT, Decision.TARGET_EXIT, Decision.STOP_EXIT}
    records = decision_logger.read_all()
    assert records[-1]["kind"] == "decision"


def test_run_once_rejects_an_evaluator_that_returns_a_non_monitor_decision(
    paper_settings, risk_limits, decision_logger, gateway
):
    fresh_snapshot = make_market_snapshot(fetched_at=datetime.now(timezone.utc))
    monitor = PositionMonitor(
        settings=paper_settings,
        market_data=_FakeFreshDataProvider(fresh_snapshot),
        evaluator=_AlwaysBuyEvaluator(),
        risk_manager=RiskManager(risk_limits),
        decision_logger=decision_logger,
        execution_gateway=gateway,
    )
    with pytest.raises(ValueError):
        monitor.run_once(make_position(), now=datetime.now(timezone.utc))


def test_run_once_never_calls_the_execution_gateway_for_a_hold(paper_settings, risk_limits, decision_logger, gateway):
    calls = []
    original_submit = gateway.submit_order
    gateway.submit_order = lambda order: calls.append(order) or original_submit(order)

    stale_snapshot = make_market_snapshot(fetched_at=datetime.now(timezone.utc))
    monitor = PositionMonitor(
        settings=paper_settings,
        market_data=_FakeFreshDataProvider(stale_snapshot),
        evaluator=PositionEvaluator(),
        risk_manager=RiskManager(risk_limits),
        decision_logger=decision_logger,
        execution_gateway=gateway,
    )
    monitor.run_once(make_position(), now=datetime.now(timezone.utc))
    assert calls == []
