"""Orchestrates a single position-monitoring evaluation cycle.

Deliberately NOT a scheduler. There is no `while True: sleep(300)` here and
there should never be one — that would be a fake 5-minute timer running
inside a request/response agent process, which can't reliably fire on a
wall-clock cadence anyway. Instead:

  - `run_once()` performs exactly one evaluate-and-log cycle for one open
    position, right now — and, for an EXIT/TARGET_EXIT/STOP_EXIT decision,
    routes a sell-to-close order through the (paper-only) execution
    gateway. See src/execution/gateway.py: that gateway physically cannot
    place a real order while TRADING_MODE=paper, so this is always a
    simulated fill, never a live one.
  - `is_within_monitoring_window()` tells an external scheduler (a cron
    job, a Routine/trigger, a supervised process — see README.md) whether
    now is a sensible time to call run_once() at all.

The real ~5-minute cadence during market hours is an operational concern
for whatever invokes this code, not something this module fakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config.constants import TRADING_WEEKDAYS
from src.config.settings import Settings
from src.execution.gateway import ExecutionGateway, new_ref_id
from src.execution.orders import OrderLeg, OrderRequest, OrderResult
from src.logging.decision_logger import DecisionLogger
from src.market.data_provider import MarketDataProvider
from src.market.errors import MarketDataError
from src.market.models import MarketSnapshot
from src.position_manager.evaluator import PositionEvaluator, PositionSnapshot
from src.position_manager.models import OpenPosition
from src.risk.manager import RiskManager
from src.strategy.decision import EXIT_DECISIONS, POSITION_MONITOR_DECISIONS, Decision, DecisionResult


def is_within_monitoring_window(now: datetime, settings: Settings) -> bool:
    """True if `now` falls on a trading weekday and within regular market
    hours, in the configured market timezone (Settings.market_timezone).

    `now` may be either:
      - naive (no tzinfo): assumed to already BE local market time, used
        as-is. This matches how this codebase's own tests construct `now`
        directly as e.g. datetime(2026, 8, 14, 11, 0).
      - timezone-aware (e.g. datetime.now(timezone.utc), which is what
        run_trading_cycle defaults to): converted to the configured market
        timezone first. A UTC `now` is NOT treated as already-local — that
        was a real bug caught during live verification (comparing a raw
        UTC clock against ET boundary times silently produces the wrong
        answer most of the year, since US markets are never UTC-aligned).
    """
    if now.tzinfo is not None:
        now = now.astimezone(ZoneInfo(settings.market_timezone))
    if now.weekday() not in TRADING_WEEKDAYS:
        return False
    return settings.market_open_time <= now.time() <= settings.market_close_time


@dataclass
class MonitorResult:
    decision_result: DecisionResult
    acted: bool  # True if an exit-type decision resulted in a simulated fill
    order_result: OrderResult | None = None  # set when `acted` is True


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
        account_number: str,
    ):
        self._settings = settings
        self._market_data = market_data
        self._evaluator = evaluator
        self._risk_manager = risk_manager
        self._decision_logger = decision_logger
        self._execution_gateway = execution_gateway
        self._account_number = account_number

    def run_once(self, position: OpenPosition, now: datetime, *, simulate_exit: bool = True) -> MonitorResult:
        """Evaluate one open position exactly once: fetch data, score
        evidence, decide, log — always — and, only for exit-type decisions,
        hand the *intent* to the execution gateway (which itself refuses to
        do anything but simulate while TRADING_MODE=paper).

        `simulate_exit=False` decides and logs only, without submitting a
        simulated closing order — for positions this system is watching
        but did not itself open (e.g. synced read-only from the real
        Robinhood account via hood_sync.py). Even with simulate_exit=True
        the order is never real (see PaperExecutionGateway), but skipping
        it here keeps the paper order-audit log limited to trades this
        system's own paper-entry/exit lifecycle actually owns."""

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
        order_result = None
        if result.decision in EXIT_DECISIONS and simulate_exit:
            close_order = _build_closing_order(position, snapshot_market, result, self._account_number)
            order_result = self._execution_gateway.submit_order(close_order)
            # submit_order already writes its own audit-log entry (see
            # PaperExecutionGateway) — nothing further to log here.
            acted = order_result.status == "simulated_fill"

        return MonitorResult(decision_result=result, acted=acted, order_result=order_result)


def _build_closing_order(
    position: OpenPosition, snapshot: MarketSnapshot, result: DecisionResult, account_number: str
) -> OrderRequest:
    """A long call/put is always closed with a sell. Priced at the current
    bid — a marketable sell-to-close limit, the realistic fill assumption
    for a paper simulation (never sent to a real order tool; see
    src/execution/gateway.py)."""
    leg = OrderLeg(option_id=position.option_id, side="sell", position_effect="close", ratio_quantity=1)
    return OrderRequest(
        account_number=account_number,
        legs=(leg,),
        quantity=str(position.quantity),
        type="limit",
        price=f"{snapshot.option.bid_price:.2f}",
        time_in_force="gfd",
        market_hours="regular_hours",
        ref_id=new_ref_id(),
        reason=f"{result.decision.value}: {result.reason}",
    )


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
