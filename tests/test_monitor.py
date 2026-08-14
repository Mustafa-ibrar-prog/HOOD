from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.execution.gateway import PaperExecutionGateway
from src.logging.decision_logger import DecisionLogger
from src.market.data_provider import MarketDataProvider, NotConfiguredMarketDataProvider
from src.market.models import OptionQuote
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

    def get_underlying_snapshot(self, symbol, now=None):
        raise NotImplementedError("not needed by these tests")

    def get_option_expirations(self, underlying_symbol):
        raise NotImplementedError("not needed by these tests")

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


def test_is_within_monitoring_window_converts_utc_to_market_timezone(paper_settings):
    """Regression test for a real bug caught during live verification:
    datetime.now(timezone.utc) — the natural default — must be converted
    to ET before comparing against ET boundary times, not compared
    directly. 2026-08-14 16:32 UTC is 12:32 EDT: within hours."""
    utc_now = datetime(2026, 8, 14, 16, 32, tzinfo=timezone.utc)
    assert is_within_monitoring_window(utc_now, paper_settings) is True


def test_is_within_monitoring_window_utc_after_local_close_is_false(paper_settings):
    # 2026-08-14 21:00 UTC = 17:00 EDT — after the 16:00 close.
    utc_now = datetime(2026, 8, 14, 21, 0, tzinfo=timezone.utc)
    assert is_within_monitoring_window(utc_now, paper_settings) is False


def test_is_within_monitoring_window_utc_before_local_open_is_false(paper_settings):
    # 2026-08-14 12:00 UTC = 08:00 EDT — before the 09:30 open.
    utc_now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    assert is_within_monitoring_window(utc_now, paper_settings) is False


def test_run_once_holds_when_no_data_provider_implemented(paper_settings, risk_limits, decision_logger, gateway):
    monitor = PositionMonitor(
        settings=paper_settings,
        market_data=NotConfiguredMarketDataProvider(),
        evaluator=PositionEvaluator(),
        risk_manager=RiskManager(risk_limits),
        decision_logger=decision_logger,
        execution_gateway=gateway,
        account_number=paper_settings.account_number,
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
        account_number=paper_settings.account_number,
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
        account_number=paper_settings.account_number,
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
        account_number=paper_settings.account_number,
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
        account_number=paper_settings.account_number,
    )
    monitor.run_once(make_position(), now=datetime.now(timezone.utc))
    assert calls == []


def test_run_once_submits_a_simulated_closing_order_on_stop_exit(paper_settings, risk_limits, decision_logger, gateway):
    """A STOP_EXIT decision must actually route a sell-to-close order
    through the (paper-only) execution gateway, not just log the intent."""
    position = make_position(entry_price=0.95, stop_loss_usd=15.0)
    # mid = (0.30+0.35)/2 = 0.325 -> pnl = (0.325-0.95)*100 = -62.5, well past the $15 stop
    losing_snapshot = make_market_snapshot(
        option=OptionQuote(
            instrument_id=position.option_id,
            bid_price=0.30,
            ask_price=0.35,
            last_trade_price=0.32,
            previous_close=0.90,
            volume=500,
            open_interest=1000,
            as_of=datetime.now(timezone.utc),
        )
    )
    monitor = PositionMonitor(
        settings=paper_settings,
        market_data=_FakeFreshDataProvider(losing_snapshot),
        evaluator=PositionEvaluator(),
        risk_manager=RiskManager(risk_limits),
        decision_logger=decision_logger,
        execution_gateway=gateway,
        account_number=paper_settings.account_number,
    )

    result = monitor.run_once(position, now=datetime.now(timezone.utc))

    assert result.decision_result.decision is Decision.STOP_EXIT
    assert result.acted is True
    assert result.order_result is not None
    assert result.order_result.status == "simulated_fill"
    assert result.order_result.request.legs[0].side == "sell"
    assert result.order_result.request.legs[0].position_effect == "close"
    assert result.order_result.request.legs[0].option_id == position.option_id
    # The order was simulated, never placed for real:
    assert paper_settings.is_paper is True

    # And it was logged as a simulated order, not just as a decision:
    records = decision_logger.read_all()
    assert any(r["kind"] == "simulated_order" for r in records)


def test_run_once_never_submits_an_order_on_hold(paper_settings, risk_limits, decision_logger, gateway):
    calls = []
    original_submit = gateway.submit_order
    gateway.submit_order = lambda order: calls.append(order) or original_submit(order)

    # Entry just above cost, ambiguous/neutral evidence -> expect HOLD.
    position = make_position(entry_price=0.95)
    neutral_snapshot = make_market_snapshot(
        option=OptionQuote(
            instrument_id=position.option_id,
            bid_price=0.97,
            ask_price=1.01,
            last_trade_price=0.99,
            previous_close=0.90,
            volume=500,
            open_interest=1000,
            as_of=datetime.now(timezone.utc),
        ),
        rsi=55.0,
        rsi_prev=None,
        macd_histogram=None,
        ema_fast=None,
        ema_slow=None,
        volume_ratio=1.0,
    )
    monitor = PositionMonitor(
        settings=paper_settings,
        market_data=_FakeFreshDataProvider(neutral_snapshot),
        evaluator=PositionEvaluator(),
        risk_manager=RiskManager(risk_limits),
        decision_logger=decision_logger,
        execution_gateway=gateway,
        account_number=paper_settings.account_number,
    )

    result = monitor.run_once(position, now=datetime.now(timezone.utc))

    assert result.decision_result.decision is Decision.HOLD
    assert result.acted is False
    assert result.order_result is None
    assert calls == []


def test_run_once_with_simulate_exit_false_decides_but_never_submits_an_order(
    paper_settings, risk_limits, decision_logger, gateway
):
    """Positions synced read-only from the real Robinhood account (see
    hood_sync.py) must still be evaluated and logged, but never get a
    simulated paper order — this system doesn't own their lifecycle."""
    position = make_position(entry_price=0.95, stop_loss_usd=15.0)
    losing_snapshot = make_market_snapshot(
        option=OptionQuote(
            instrument_id=position.option_id,
            bid_price=0.30,
            ask_price=0.35,
            last_trade_price=0.32,
            previous_close=0.90,
            volume=500,
            open_interest=1000,
            as_of=datetime.now(timezone.utc),
        )
    )
    calls = []
    original_submit = gateway.submit_order
    gateway.submit_order = lambda order: calls.append(order) or original_submit(order)

    monitor = PositionMonitor(
        settings=paper_settings,
        market_data=_FakeFreshDataProvider(losing_snapshot),
        evaluator=PositionEvaluator(),
        risk_manager=RiskManager(risk_limits),
        decision_logger=decision_logger,
        execution_gateway=gateway,
        account_number=paper_settings.account_number,
    )

    result = monitor.run_once(position, now=datetime.now(timezone.utc), simulate_exit=False)

    assert result.decision_result.decision is Decision.STOP_EXIT  # still decided...
    assert result.acted is False  # ...but never acted on
    assert result.order_result is None
    assert calls == []  # the gateway was never touched
    records = decision_logger.read_all()
    assert any(r["kind"] == "decision" and r["decision"] == "STOP_EXIT" for r in records)  # still logged
    assert not any(r["kind"] == "simulated_order" for r in records)
