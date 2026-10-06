"""The execution layer's safety boundary — mirrors
src/execution/gateway.py's design exactly, adapted for one real
difference: on Robinhood, nothing in this Python process can call an
MCP order tool (only the orchestrating agent can), so LiveOrderPlacer
there is injected by something bridging that gap per-call. Polymarket
has no such constraint — client.py's PolymarketClient makes real HTTP
calls directly (via py-clob-client), so IT is the live order placer,
running unattended in scripts/run_polymarket_bot.py's loop with no
agent in the loop. That is exactly why every guard below matters more
here, not less: there is no human-in-the-loop agent turn to catch a
mistake before it reaches the network.

THIS IS THE ONLY MODULE THAT MAY EVER CALL PolymarketOrderPlacer.place_order.

  - PaperPolymarketGateway: the only one safe to run unattended without
    live_trading_confirmed. Never calls place_order. Always a simulated
    fill at the requested price, logged like a real one.

  - LivePolymarketGateway: real order placement. submit_order() NEVER
    calls place_order directly from its own body — it always creates a
    PendingLiveOrder and persists it first, so there is a full audit
    trail no matter what happens next. What happens next depends on
    settings.live_auto_execute (default False): stop at pending_approval
    and require a separate confirm_and_place() call, or (True) place
    immediately once the risk gate clears, recorded as approved_by=
    "system:auto_execute" either way so the log always shows whether a
    human step happened.

Independent, deliberately overlapping guards (a bug in one must not
silently remove another):
  1. get_execution_gateway() only returns a *working paper* gateway by
     default — a live-capable one requires explicitly passing a
     PolymarketPendingOrderStore.
  2. LivePolymarketGateway refuses to even construct unless BOTH
     settings.is_live AND settings.live_trading_confirmed are true.
  3. confirm_and_place() re-checks both again at call time, re-validates
     the pending order's status and expiry, and only ever acts on the
     exact pending_order_id passed in.
  4. EmergencyStopStore.is_stopped() (src/execution/emergency_stop.py —
     reused as-is; it's generic) — a real, file-backed kill switch,
     defaulting to STOPPED, checked immediately before every real call,
     unbypassable by live_auto_execute or by strategy code (strategy.py
     never sees this store).
  5. Every step (pending, approved, rejected, expired, placed, failed)
     is written to the decision/audit log.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Protocol

from src.execution.emergency_stop import EmergencyStopStore
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import OrderRequest, OrderResult, PendingLiveOrder
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.settings import PolymarketSettings


class LiveTradingDisabledError(RuntimeError):
    pass


class PendingOrderNotActionableError(RuntimeError):
    pass


def assert_paper_mode(settings: PolymarketSettings) -> None:
    if not settings.is_paper:
        raise LiveTradingDisabledError(
            f"POLYMARKET_TRADING_MODE={settings.trading_mode!r} — refusing to proceed. "
            "This code path only ever operates in paper mode."
        )


class PolymarketOrderPlacer(Protocol):
    """Implemented by client.py's PolymarketClient. Kept as a Protocol,
    same as live_client.py's LiveOrderPlacer, so gateway.py's tests can
    inject a fake instead of a real network client."""

    def place_order(self, order: OrderRequest) -> dict[str, Any]: ...


class ExecutionGateway(ABC):
    @abstractmethod
    def submit_order(self, order: OrderRequest) -> OrderResult:
        raise NotImplementedError


class PaperPolymarketGateway(ExecutionGateway):
    """Simulates a fill at the caller-supplied limit price. Never calls
    PolymarketOrderPlacer.place_order."""

    def __init__(self, settings: PolymarketSettings, decision_logger: PolymarketDecisionLogger):
        self._settings = settings
        self._decision_logger = decision_logger

    def submit_order(self, order: OrderRequest) -> OrderResult:
        assert_paper_mode(self._settings)
        result = OrderResult(
            status="simulated_fill", request=order,
            filled_price=order.price, filled_at=datetime.now(timezone.utc),
        )
        self._decision_logger.log_simulated_order(result)
        return result


class LivePolymarketGateway(ExecutionGateway):
    def __init__(
        self,
        settings: PolymarketSettings,
        decision_logger: PolymarketDecisionLogger,
        pending_store: PolymarketPendingOrderStore,
        order_placer: PolymarketOrderPlacer | None = None,
        emergency_stop_store: EmergencyStopStore | None = None,
    ) -> None:
        if not settings.is_live:
            raise LiveTradingDisabledError(
                f"POLYMARKET_TRADING_MODE={settings.trading_mode!r} — LivePolymarketGateway must "
                "not be constructed outside POLYMARKET_TRADING_MODE=live."
            )
        if not settings.live_trading_confirmed:
            raise LiveTradingDisabledError(
                "POLYMARKET_LIVE_TRADING_CONFIRMED is not true — refusing to construct a live "
                "execution gateway. This is a deliberate second switch, independent of "
                "POLYMARKET_TRADING_MODE, that a human must set explicitly."
            )
        self._settings = settings
        self._decision_logger = decision_logger
        self._pending_store = pending_store
        self._order_placer = order_placer
        # Deliberately NOT defaulted to a permissive stand-in — None is
        # treated as the blocked answer at check time, same as
        # execution/gateway.py's guard 7.
        self._emergency_stop_store = emergency_stop_store

    def submit_order(self, order: OrderRequest) -> OrderResult:
        pending = PendingLiveOrder.new(order=order, expiry_seconds=self._settings.poll_interval_seconds * 6)
        self._pending_store.add(pending)
        self._decision_logger.log_pending_order(pending)

        if self._settings.live_auto_execute and self._order_placer is not None:
            return self._place_pending(pending, self._order_placer, approved_by="system:auto_execute")

        return OrderResult(
            status="awaiting_approval", request=order,
            extra={"pending_order_id": pending.id, "expires_at": pending.expires_at.isoformat()},
        )

    def confirm_and_place(
        self, pending_order_id: str, order_placer: PolymarketOrderPlacer, *, approved_by: str, now: datetime | None = None,
    ) -> OrderResult:
        if not self._settings.is_live or not self._settings.live_trading_confirmed:
            raise LiveTradingDisabledError(
                "POLYMARKET_TRADING_MODE=live and POLYMARKET_LIVE_TRADING_CONFIRMED=true are both "
                "required to place a live order, and were re-checked here (not just at construction time)."
            )
        now = now or datetime.now(timezone.utc)
        pending = self._pending_store.get(pending_order_id)
        if pending is None:
            raise PendingOrderNotActionableError(f"No pending order {pending_order_id!r} found")
        if now >= pending.expires_at and pending.status == "awaiting_approval":
            expired = pending.with_status("expired", decided_at=now, decided_by="system:expiry")
            self._pending_store.update(expired)
            self._decision_logger.log_pending_order(expired)
            pending = expired
        if pending.status != "awaiting_approval":
            raise PendingOrderNotActionableError(
                f"Pending order {pending_order_id!r} is {pending.status!r}, not awaiting_approval — "
                "refusing to place it. A 15-minute market moves fast; an expired pending order "
                "needs a fresh cycle to re-propose it against current data, not a stale approval."
            )
        return self._place_pending(pending, order_placer, approved_by=approved_by, now=now)

    def _place_pending(
        self, pending: PendingLiveOrder, order_placer: PolymarketOrderPlacer, *, approved_by: str, now: datetime | None = None,
    ) -> OrderResult:
        now = now or datetime.now(timezone.utc)
        order = pending.order
        if self._emergency_stop_store is None or self._emergency_stop_store.is_stopped():
            exc = LiveTradingDisabledError(
                "Emergency stop is active (or no emergency-stop store was configured) — "
                "refusing to place a live order. See src/execution/emergency_stop.py."
            )
            failed = pending.with_status("failed", decided_at=now, decided_by=approved_by, error=str(exc))
            self._pending_store.update(failed)
            self._decision_logger.log_pending_order(failed)
            raise exc

        try:
            raw = order_placer.place_order(order)
        except Exception as exc:  # noqa: BLE001 - record the failure in the audit trail, then re-raise
            failed = pending.with_status("failed", decided_at=now, decided_by=approved_by, error=str(exc))
            self._pending_store.update(failed)
            self._decision_logger.log_pending_order(failed)
            raise

        result = OrderResult(status="placed", request=order, filled_at=now, raw=raw)
        placed = pending.with_status("placed", decided_at=now, decided_by=approved_by)
        self._pending_store.update(placed)
        self._decision_logger.log_live_order_placed(placed, result)
        return result

    def reject_pending(self, pending_order_id: str, *, reason: str, rejected_by: str, now: datetime | None = None) -> PendingLiveOrder:
        now = now or datetime.now(timezone.utc)
        pending = self._pending_store.get(pending_order_id)
        if pending is None:
            raise PendingOrderNotActionableError(f"No pending order {pending_order_id!r} found")
        if pending.status != "awaiting_approval":
            raise PendingOrderNotActionableError(f"Pending order {pending_order_id!r} is {pending.status!r}, not awaiting_approval — nothing to reject.")
        rejected = pending.with_status("rejected", decided_at=now, decided_by=rejected_by, error=reason)
        self._pending_store.update(rejected)
        self._decision_logger.log_pending_order(rejected)
        return rejected


def get_execution_gateway(
    settings: PolymarketSettings,
    decision_logger: PolymarketDecisionLogger,
    pending_store: PolymarketPendingOrderStore | None = None,
    order_placer: PolymarketOrderPlacer | None = None,
    emergency_stop_store: EmergencyStopStore | None = None,
) -> ExecutionGateway:
    if settings.is_paper:
        return PaperPolymarketGateway(settings, decision_logger)
    if pending_store is None:
        raise LiveTradingDisabledError(
            "POLYMARKET_TRADING_MODE=live requires an explicit PolymarketPendingOrderStore — "
            "there is no implicit default, so a caller can't accidentally obtain a live-capable gateway."
        )
    return LivePolymarketGateway(settings, decision_logger, pending_store, order_placer, emergency_stop_store=emergency_stop_store)
