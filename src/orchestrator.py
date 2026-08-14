"""The trading-cycle orchestrator:

  MARKET SCAN → FIND SETUP → PAPER ENTRY → MONITOR EVERY ~5 MINUTES →
  HOLD / EARLY EXIT / TARGET EXIT / STOP → LOG EVERYTHING →
  SYNC WITH ROBINHOOD

`run_trading_cycle()` performs exactly ONE cycle. There is no scheduler in
this module or anywhere else in this codebase — see
position_manager/monitor.py's module docstring for why a code-level
`while True: sleep(300)` doesn't belong here. The real ~5-minute cadence
during market hours is achieved by an external, real scheduling mechanism
invoking this function repeatedly (see the project's operational docs /
README.md for what that is in this deployment).

TRADING_MODE stays paper end-to-end. Every "entry" and "exit" performed
here is a simulated fill from PaperExecutionGateway (see
src/execution/gateway.py, which physically refuses to do anything else
while TRADING_MODE=paper). Nothing in this module calls
place_option_order, review_option_order, or cancel_option_order.

One cycle, in order:
  1. SYNC WITH ROBINHOOD (read-only): pull the account's real open option
     positions via hood_sync.py. These are monitored (decided, logged)
     but never paper-order-simulated — this system doesn't own their
     lifecycle (see PositionMonitor.run_once(simulate_exit=False)).
  2. MONITOR this system's own paper positions (from PaperPositionStore):
     HOLD / EARLY EXIT / TARGET EXIT / STOP, each a real evaluator call
     against real (or supplementary-degraded) market data. An exit-type
     decision routes a simulated sell-to-close order and removes the
     position from the paper ledger.
  3. MARKET SCAN → FIND SETUP, only if risk controls allow a new trade
     this cycle (daily trade count, cutoff time) — MomentumBreakoutStrategy
     proposes candidates; RiskManager.evaluate_new_trade re-validates each
     one against fresh data before any paper entry, exactly the same gate
     a real trade would have to pass.
  4. LOG EVERYTHING happens throughout, not as a separate step — every
     HOLD/EXIT/TARGET_EXIT/STOP_EXIT/NO_TRADE and every simulated order is
     written to the decision/audit log as it happens (see
     logging/decision_logger.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config.settings import Settings
from src.execution.gateway import ExecutionGateway, get_execution_gateway, new_ref_id
from src.execution.orders import OrderLeg, OrderRequest
from src.logging.decision_logger import DecisionLogger
from src.market.data_provider import MarketDataProvider
from src.market.errors import MarketDataError
from src.market.hood_client import HoodToolClient
from src.market.models import PriceBar
from src.position_manager.evaluator import PositionEvaluator
from src.position_manager.hood_sync import sync_open_positions_from_hood
from src.position_manager.models import OpenPosition
from src.position_manager.monitor import MonitorResult, PositionMonitor, is_within_monitoring_window
from src.position_manager.store import PaperPositionStore
from src.risk.manager import RiskDecision, RiskManager
from src.risk.models import RiskLimits
from src.risk.store import DailyRiskState, RiskStateStore
from src.strategy.base import SetupCandidate
from src.strategy.decision import EXIT_DECISIONS, Decision
from src.strategy.momentum_breakout import MomentumBreakoutStrategy
from src.strategy.scanner import StrategyScanner


@dataclass
class CycleReport:
    """What happened in one run_trading_cycle() call — the return value a
    caller (or the human operating this system) inspects to know whether
    anything actually ran, and what it did."""

    ran: bool
    skipped_reason: str | None = None
    monitored_paper_count: int = 0
    monitored_real_count: int = 0
    exits: list[str] = field(default_factory=list)  # option_ids exited (paper) this cycle
    new_entries: list[str] = field(default_factory=list)  # option_ids entered (paper) this cycle
    scan_candidate_count: int = 0
    real_positions_synced: int = 0
    errors: list[str] = field(default_factory=list)


def run_trading_cycle(
    *,
    settings: Settings,
    market_data: MarketDataProvider,
    hood_client: HoodToolClient,
    now: datetime | None = None,
) -> CycleReport:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    # Localize ONCE here rather than at each call site: several downstream
    # checks compare `now`'s wall-clock time-of-day against local-market-
    # time boundary values (RiskManager.check_cutoff_time via
    # evaluate_new_trade; OpenPosition.minutes_to_expiration's 4pm-local
    # close) without doing that conversion themselves — they're written to
    # take `now` already in local terms. Passing a raw UTC `now` through
    # them silently compares the wrong clock (caught live: it made the
    # entry cutoff fire ~4 hours early). Localizing here, once, fixes every
    # one of those call sites without touching risk/manager.py or
    # position_manager's evaluator/models — see is_within_monitoring_window
    # for the same fix applied there.
    now = now.astimezone(ZoneInfo(settings.market_timezone))

    if not is_within_monitoring_window(now, settings):
        return CycleReport(ran=False, skipped_reason="outside regular market hours")

    if not settings.account_number:
        return CycleReport(
            ran=False,
            skipped_reason="no account_number configured (set ROBINHOOD_ACCOUNT_NUMBER)",
        )

    decision_logger = DecisionLogger(path=settings.decision_log_file, app_log_file=settings.app_log_file)
    # get_execution_gateway refuses outright unless TRADING_MODE=paper —
    # this is the same hard stop the rest of the codebase relies on.
    execution_gateway = get_execution_gateway(settings, decision_logger)
    risk_manager = RiskManager(RiskLimits.from_settings(settings))
    risk_store = RiskStateStore(Path(settings.risk_state_file))
    risk_state = risk_store.load(today=now.date())
    paper_store = PaperPositionStore(Path(settings.paper_positions_file))

    report = CycleReport(ran=True)

    # --- 1. SYNC WITH ROBINHOOD (read-only) -----------------------------------------
    real_positions: list[OpenPosition] = []
    try:
        sync_result = sync_open_positions_from_hood(hood_client, settings.account_number, settings)
        real_positions = list(sync_result.positions)
        report.real_positions_synced = len(real_positions)
    except Exception as exc:  # noqa: BLE001 - a sync failure must not abort the whole cycle
        report.errors.append(f"position sync failed: {exc}")

    monitor = PositionMonitor(
        settings=settings,
        market_data=market_data,
        evaluator=PositionEvaluator(),
        risk_manager=risk_manager,
        decision_logger=decision_logger,
        execution_gateway=execution_gateway,
        account_number=settings.account_number,
    )

    # --- 2. MONITOR this system's own paper positions -------------------------------
    paper_positions = paper_store.load()
    for position in paper_positions:
        report.monitored_paper_count += 1
        try:
            result = monitor.run_once(position, now=now)
        except MarketDataError as exc:
            report.errors.append(f"monitor failed for paper position {position.option_id}: {exc}")
            continue
        if result.decision_result.decision in EXIT_DECISIONS and result.acted:
            risk_state.record_exit(position.symbol, now, realized_pnl_usd=_realized_pnl(position, result))
            paper_store.remove_position(position.option_id)
            report.exits.append(position.option_id)

    # Real positions: decide and log only — this system did not open them
    # and never simulates a paper order for them (simulate_exit=False).
    for position in real_positions:
        report.monitored_real_count += 1
        try:
            monitor.run_once(position, now=now, simulate_exit=False)
        except MarketDataError as exc:
            report.errors.append(f"monitor failed for real position {position.option_id}: {exc}")

    # --- 3. MARKET SCAN → FIND SETUP → PAPER ENTRY -----------------------------------
    scan_universe_label = ",".join(settings.scan_universe) or "(empty universe)"
    trade_count_check = risk_manager.check_trade_count(risk_state.trades_opened)
    cutoff_check = risk_manager.check_cutoff_time(now)
    if trade_count_check.passed and cutoff_check.passed and settings.max_new_entries_per_cycle > 0:
        scanner = StrategyScanner([MomentumBreakoutStrategy()])
        scan_result = scanner.scan_for_setups(market_data, settings.scan_universe)
        report.scan_candidate_count = len(scan_result.candidates)
        decision_logger.log_decision(
            symbol=scan_universe_label,
            option_id=None,
            decision=scan_result.decision.decision,
            reason=scan_result.decision.reason,
            confidence=scan_result.decision.confidence,
            evidence=scan_result.decision.evidence,
        )

        # Both this system's own paper positions AND the user's real ones
        # count for duplicate-position / cooldown protection — no reason
        # to paper-buy something already held for real.
        currently_open = list(paper_store.load()) + real_positions
        entries_this_cycle = 0

        for candidate in scan_result.candidates:
            if entries_this_cycle >= settings.max_new_entries_per_cycle:
                break

            risk_decision = _evaluate_candidate(risk_manager, candidate, risk_state, currently_open, now, market_data)
            if risk_decision is None:
                report.errors.append(f"could not fetch fresh data to re-validate candidate {candidate.option_id}")
                continue
            if not risk_decision.allowed:
                decision_logger.log_risk_block(
                    context="new_trade",
                    symbol=candidate.underlying_symbol,
                    attempted_decision=Decision.BUY,
                    blocking_reasons=risk_decision.blocking_reasons,
                )
                continue

            new_position = _open_paper_position(candidate, settings, execution_gateway, now)
            if new_position is None:
                continue

            paper_store.add_position(new_position)
            risk_state.record_trade_opened(new_position.size_usd)
            entries_this_cycle += 1
            report.new_entries.append(new_position.option_id)
            currently_open = currently_open + [new_position]
    else:
        skip_reasons = [c.message for c in (trade_count_check, cutoff_check) if not c.passed]
        if settings.max_new_entries_per_cycle <= 0:
            skip_reasons.append("MAX_NEW_ENTRIES_PER_CYCLE is 0")
        decision_logger.log_decision(
            symbol=scan_universe_label,
            option_id=None,
            decision=Decision.NO_TRADE,
            reason=f"Scan skipped this cycle: {'; '.join(skip_reasons)}",
            confidence=1.0,
            evidence={},
        )

    risk_store.save(risk_state)
    return report


def _realized_pnl(position: OpenPosition, result: MonitorResult) -> float:
    """Prefer the actual simulated-fill price (what the paper close order
    would have filled at) over the evaluator's evidence pnl (computed from
    the option's mid price) — the fill is the more accurate "what really
    happened" number."""
    if result.order_result is not None and result.order_result.simulated_fill is not None:
        fill_price = result.order_result.simulated_fill.fill_price
        return round((fill_price - position.entry_price) * position.quantity * position.contract_multiplier, 2)
    return float(result.decision_result.evidence.get("pnl_usd", 0.0))


def _evaluate_candidate(
    risk_manager: RiskManager,
    candidate: SetupCandidate,
    risk_state: DailyRiskState,
    open_positions: list[OpenPosition],
    now: datetime,
    market_data: MarketDataProvider,
) -> RiskDecision | None:
    """Re-validates a scanner candidate against FRESH data immediately
    before considering a paper entry — the scanner's own snapshot may be a
    moment old by the time risk-gating runs. Returns None (not a
    RiskDecision) if fresh data can't be fetched at all."""
    try:
        snapshot = market_data.get_market_snapshot(candidate.option_id, candidate.underlying_symbol, now=now)
    except MarketDataError:
        return None

    proposed_size_usd = candidate.suggested_entry_price * candidate.suggested_quantity * 100
    return risk_manager.evaluate_new_trade(
        candidate_symbol=candidate.underlying_symbol,
        candidate_option_id=candidate.option_id,
        proposed_size_usd=proposed_size_usd,
        trades_opened_today=risk_state.trades_opened,
        daily_pnl_usd=risk_state.daily_pnl_usd,
        open_positions=open_positions,
        last_exit_time=risk_state.last_exit_time(candidate.underlying_symbol),
        data_age_seconds=snapshot.data_age_seconds,
        bid=snapshot.option.bid_price,
        ask=snapshot.option.ask_price,
        volume=snapshot.option.volume,
        open_interest=snapshot.option.open_interest,
        underlying_move_pct=_underlying_move_pct(snapshot.underlying_bars),
        now=now,
        last_position_size_usd=risk_state.last_position_size_usd,
        last_trade_was_loss=risk_state.last_trade_was_loss,
    )


def _underlying_move_pct(bars: tuple[PriceBar, ...]) -> float:
    """How far the underlying has already moved across the fetched
    lookback window — the "no chasing extended moves" risk check's input.
    0.0 (not extended) when there isn't enough history to judge, which is
    the conservative choice for a check whose job is to REJECT extension,
    not silently pass a candidate through on missing data."""
    if len(bars) < 2:
        return 0.0
    first, last = bars[0], bars[-1]
    if first.close == 0:
        return 0.0
    return (last.close - first.close) / first.close


def _open_paper_position(
    candidate: SetupCandidate, settings: Settings, execution_gateway: ExecutionGateway, now: datetime
) -> OpenPosition | None:
    leg = OrderLeg(option_id=candidate.option_id, side="buy", position_effect="open", ratio_quantity=1)
    order = OrderRequest(
        account_number=settings.account_number,
        legs=(leg,),
        quantity=str(candidate.suggested_quantity),
        type="limit",
        price=f"{candidate.suggested_entry_price:.2f}",
        time_in_force="gfd",
        market_hours="regular_hours",
        ref_id=new_ref_id(),
        reason=f"BUY: {candidate.thesis.catalyst}",
    )
    order_result = execution_gateway.submit_order(order)
    if order_result.status != "simulated_fill" or order_result.simulated_fill is None:
        return None

    return OpenPosition(
        symbol=candidate.underlying_symbol,
        option_id=candidate.option_id,
        option_description=candidate.option_description,
        side=candidate.side,
        quantity=candidate.suggested_quantity,
        entry_price=order_result.simulated_fill.fill_price,
        entry_time=now,
        thesis=candidate.thesis,
        profit_target_usd=candidate.profit_target_usd,
        stop_loss_usd=candidate.stop_loss_usd,
        expiration=candidate.expiration,
    )
