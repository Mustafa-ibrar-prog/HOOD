"""Orchestrates a single position-monitoring evaluation cycle.

Deliberately NOT a scheduler. There is no `while True: sleep(300)` here and
there should never be one — that would be a fake 5-minute timer running
inside a request/response agent process, which can't reliably fire on a
wall-clock cadence anyway. Instead:

  - `run_once()` performs exactly one evaluate-and-log cycle for one open
    position, right now.
  - `is_within_monitoring_window()` tells an external scheduler (a cron
    job, a Routine/trigger, a supervised process — see README.md) whether
    now is a sensible time to call run_once() at all.

The real ~5-minute cadence during market hours is an operational concern
for whatever invokes this code, not something this module fakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.config.constants import TRADING_WEEKDAYS
from src.config.settings import Settings
from src.execution.gateway import ExecutionGateway
from src.logging.decision_logger import DecisionLogger
from src.market.data_provider import MarketDataProvider
from src.market.errors import MarketDataError
from src.position_manager.evaluator import PositionEvaluator, PositionSnapshot
from src.position_manager.models import OpenPosition
from src.risk.manager import RiskManager
from src.strategy.decision import POSITION_MONITOR_DECISIONS, Decision, DecisionResult


def is_within_monitoring_window(now: datetime, settings: Settings) -> bool:
    """True if `now` (expected in the market's local time) falls on a
    trading weekday and within regular market hours. Pure/testable — no
    dependency on wall-clock time."""
    if now.weekday() not in TRADING_WEEKDAYS:
        return False
    return settings.market_open_time <= now.time() <= settings.market_close_time


@dataclass
class MonitorResult:
    decision_result: DecisionResult
    acted: bool  # True if an exit-type decision was routed to the execution gateway


class PositionMonitor:
    def __init__(
        self,
        *,
        settings: Settings,
        market_data: MarketDataProvider,
        evaluator: PositionEvaluator,
        risk_manager: RiskManager,
        decision_logger: DecisionLogger,
        execution_gateway: ExecutionGateway,
    ):
        self._settings = settings
        self._market_data = market_data
        self._evaluator = evaluator
        self._risk_manager = risk_manager
        self._decision_logger = decision_logger
        self._execution_gateway = execution_gateway

    def run_once(self, position: OpenPosition, now: datetime) -> MonitorResult:
        """Evaluate one open position exactly once: fetch data, score
        evidence, decide, log — always — and, only for exit-type decisions,
        hand the *intent* to the execution gateway (which itself refuses to
        do anything but simulate while TRADING_MODE=paper)."""

        try:
            snapshot_market = self._market_data.get_market_snapshot(position.option_id, position.symbol, now=now)
        except (NotImplementedError, MarketDataError) as exc:
            # NotImplementedError: no provider wired up at all (e.g. the
            # NotConfiguredMarketDataProvider default). MarketDataError: a
            # real provider was wired up and a fetch was attempted, but
            # critical data (a quote) was unavailable, invalid, or the tool
            # call itself failed. Either way: hold, don't act blind.
            result = DecisionResult(
                decision=Decision.HOLD,
                reason=f"No market data available this cycle ({exc}); holding rather than acting blind",
                confidence=0.0,
                evidence={},
            )
            self._decision_logger.log_decision(
                symbol=position.symbol,
                option_id=position.option_id,
                decision=result.decision,
                reason=result.reason,
                confidence=result.confidence,
                evidence=result.evidence,
            )
            return MonitorResult(decision_result=result, acted=False)

        risk_check = self._risk_manager.evaluate_exit_conditions(
            data_age_seconds=snapshot_market.data_age_seconds,
            bid=snapshot_market.option.bid_price,
            ask=snapshot_market.option.ask_price,
        )
        if not risk_check.allowed:
            result = DecisionResult(
                decision=Decision.HOLD,
                reason=f"Market data unreliable this cycle: {'; '.join(risk_check.blocking_reasons)}",
                confidence=0.0,
                evidence={"risk_checks": risk_check.results},
            )
            self._decision_logger.log_decision(
                symbol=position.symbol,
                option_id=position.option_id,
                decision=result.decision,
                reason=result.reason,
                confidence=result.confidence,
                evidence=result.evidence,
                risk_checks=risk_check.results,
            )
            return MonitorResult(decision_result=result, acted=False)

        position_snapshot = PositionSnapshot(
            position=position,
            option_price=snapshot_market.option.mid_price,
            momentum=_build_momentum_evidence(position, snapshot_market),
            minutes_to_expiration=position.minutes_to_expiration(now),
        )
        result = self._evaluator.evaluate(position_snapshot)

        if result.decision not in POSITION_MONITOR_DECISIONS:
            raise ValueError(f"PositionEvaluator returned {result.decision}, which the monitor cannot act on")

        self._decision_logger.log_decision(
            symbol=position.symbol,
            option_id=position.option_id,
            decision=result.decision,
            reason=result.reason,
            confidence=result.confidence,
            evidence=result.evidence,
            pnl_usd=result.evidence.get("pnl_usd"),
            risk_checks=risk_check.results,
        )

        acted = False
        if result.decision in (Decision.EXIT, Decision.TARGET_EXIT, Decision.STOP_EXIT):
            # Routing to the gateway is intentionally NOT implemented beyond
            # logging the intent here — building the real close-order path
            # (sizing the closing leg, choosing a limit price, calling the
            # paper gateway) is future work. See README "still needs to be
            # built" section. This keeps run_once() honest about what it
            # does today: decide and log, not execute.
            acted = False

        return MonitorResult(decision_result=result, acted=acted)


def _build_momentum_evidence(position: OpenPosition, snapshot):
    from src.strategy.evidence import MomentumEvidence
    from src.market.indicators import detect_breakout_continuation, detect_failed_breakout, higher_highs_lower_highs

    higher_highs, lower_highs = higher_highs_lower_highs(list(snapshot.underlying_bars))
    breakout = detect_breakout_continuation(list(snapshot.underlying_bars))
    failed_breakout = detect_failed_breakout(list(snapshot.underlying_bars))

    return MomentumEvidence(
        thesis_direction=position.thesis.direction,
        rsi=snapshot.rsi,
        rsi_prev=snapshot.rsi_prev,
        macd_histogram=snapshot.macd_histogram,
        macd_histogram_prev=snapshot.macd_histogram_prev,
        ema_fast=snapshot.ema_fast,
        ema_slow=snapshot.ema_slow,
        higher_highs=higher_highs,
        lower_highs=lower_highs,
        breakout_continuation=breakout,
        failed_breakout=failed_breakout,
        reversal_signal=False,  # future work: derive from candlestick/structure analysis
        volume_ratio=snapshot.volume_ratio,
    )
