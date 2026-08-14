"""End-to-end proof that HoodMarketDataProvider's output flows correctly
into the existing (unchanged) PositionEvaluator/RiskManager/PositionMonitor
pipeline, and that no order-placement tool is anywhere in that path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.execution.gateway import PaperExecutionGateway
from src.logging.decision_logger import DecisionLogger
from src.market.hood_provider import HoodMarketDataProvider
from src.position_manager.evaluator import PositionEvaluator
from src.position_manager.monitor import PositionMonitor
from src.risk.manager import RiskManager
from src.strategy.decision import Decision
from tests.conftest import make_position
from tests.test_hood_provider import OPTION_ID, UNDERLYING, _happy_client


def test_full_monitor_cycle_uses_real_provider_and_never_touches_order_tools(paper_settings, risk_limits, tmp_path):
    now = datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)  # Tuesday, regular hours
    client = _happy_client(now)
    provider = HoodMarketDataProvider(client, paper_settings)
    decision_logger = DecisionLogger(path=tmp_path / "decisions.jsonl", also_console=False)
    gateway = PaperExecutionGateway(paper_settings, decision_logger)

    monitor = PositionMonitor(
        settings=paper_settings,
        market_data=provider,
        evaluator=PositionEvaluator(),
        risk_manager=RiskManager(risk_limits),
        decision_logger=decision_logger,
        execution_gateway=gateway,
        account_number=paper_settings.account_number,
    )

    position = make_position(
        symbol=UNDERLYING,
        option_id=OPTION_ID,
        entry_price=0.95,
        expiration=(now + timedelta(days=30)).date(),
    )

    result = monitor.run_once(position, now=now)

    assert result.decision_result.decision in {Decision.HOLD, Decision.EXIT, Decision.TARGET_EXIT, Decision.STOP_EXIT}
    assert paper_settings.is_paper is True

    # The client backing the provider only exposes read-only market-data
    # methods — there is no order-placement call it could even make.
    order_related = {"place_option_order", "review_option_order", "cancel_option_order"}
    assert order_related.isdisjoint(set(client.calls))
    assert order_related.isdisjoint({m for m in dir(client) if not m.startswith("_")})

    # Every decision this cycle produced was logged (HOLD included).
    records = decision_logger.read_all()
    assert any(r["kind"] == "decision" for r in records)


def test_stale_snapshot_from_real_provider_still_yields_safe_hold(paper_settings, risk_limits, tmp_path):
    """PositionMonitor.run_once() passes its `now` straight through as the
    provider's fetch time (see monitor.py). Simulating a cycle that runs
    late — `now` several minutes behind the real wall clock — means the
    resulting snapshot's data_age_seconds (measured against the real clock)
    exceeds the configured staleness limit, and the unchanged RiskManager
    check must still catch it exactly as it did before this change."""
    stale_now = datetime.now(timezone.utc) - timedelta(minutes=5)  # > 90s default stale limit

    client = _happy_client(stale_now)
    provider = HoodMarketDataProvider(client, paper_settings)
    decision_logger = DecisionLogger(path=tmp_path / "decisions.jsonl", also_console=False)
    gateway = PaperExecutionGateway(paper_settings, decision_logger)

    monitor = PositionMonitor(
        settings=paper_settings,
        market_data=provider,
        evaluator=PositionEvaluator(),
        risk_manager=RiskManager(risk_limits),
        decision_logger=decision_logger,
        execution_gateway=gateway,
        account_number=paper_settings.account_number,
    )
    position = make_position(symbol=UNDERLYING, option_id=OPTION_ID)

    result = monitor.run_once(position, now=stale_now)

    assert result.decision_result.decision is Decision.HOLD
    assert "stale" in result.decision_result.reason.lower() or "unreliable" in result.decision_result.reason.lower()
