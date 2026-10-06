"""The execution layer's safety boundary — mirrors
src/execution/gateway.py's design, adapted for one real difference: on
Robinhood, nothing in this Python process can call an MCP order tool
(only the orchestrating agent can), so LiveOrderPlacer there is
injected by something bridging that gap per-call. Polymarket has no
such constraint — client.py's PolymarketClient makes real HTTP calls
directly, so IT is the live order placer, running unattended in
scripts/run_polymarket_bot.py's loop with no agent in the loop. That is
exactly why every guard below matters more here, not less: there is no
human-in-the-loop agent turn to catch a mistake before it reaches the
network.

Scope, deliberately narrow (Task 3): this module's job stops at
SUBMISSION. `_place_pending()` records exactly what the exchange said
about accepting the order (via PolymarketOrderPlacer.place_order() ->
SubmissionOutcome) and nothing more — it never calls get_fill_status,
never creates a position, never touches position_store or
state_store. Determining whether an accepted order actually FILLED,
and updating the position ledger accordingly, is reconciliation.py's
job alone, called by engine.py after submit_order()/confirm_and_place()
return. Keeping these separate is what makes "submitted" and "filled"
impossible to conflate by construction — see models.OrderResult's
docstring.

THIS IS THE ONLY MODULE THAT MAY EVER CALL PolymarketOrderPlacer.place_order.

  - PaperPolymarketGateway: the only one safe to run unattended without
    live_trading_confirmed. Never calls place_order. Returns a
    synthetic, clearly-labeled FillResult (status="filled") directly —
    paper mode has no submission/fill gap to begin with, since nothing
    real was ever submitted.

  - LivePolymarketGateway: real order submission. submit_order() NEVER
    calls place_order directly from its own body — it always creates a
    PendingLiveOrder and persists it first, so there is a full audit
    trail no matter what happens next. What happens next depends on
    settings.live_auto_execute (default False): stop at pending_approval
    and require a separate confirm_and_place() call, or (True) submit
    immediately once the risk gate clears, recorded as approved_by=
    "system:auto_execute" either way so the log always shows whether a
    human step happened. Either way, the returned OrderResult's
    fill_result is always None — engine.py must call
    reconciliation.reconcile_order() to find out what actually filled.

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
  5. Every step (pending, submitted, rejected, expired, failed) is
     written to the decision/audit log.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Protocol

from src.execution.emergency_stop import EmergencyStopStore
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import FillResult, OrderRequest, OrderResult, PendingLiveOrder, SubmissionOutcome
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

    def place_order(self, order: OrderRequest) -> SubmissionOutcome: ...


class ExecutionGateway(ABC):
    @abstractmethod
    def submit_order(self, order: OrderRequest) -> OrderResult:
        raise NotImplementedError


class PaperPolymarketGateway(ExecutionGateway):
    """Simulates a fill at the order's max_price. Never calls
    PolymarketOrderPlacer.place_order. The only gateway whose
    OrderResult carries a non-None fill_result directly — there is
    nothing to reconcile for a simulation."""

    def __init__(self, settings: PolymarketSettings, decision_logger: PolymarketDecisionLogger):
        self._settings = settings
        self._decision_logger = decision_logger

    def submit_order(self, order: OrderRequest) -> OrderResult:
        assert_paper_mode(self._settings)
        shares = round(order.size_usd / order.max_price, 6)
        fill = FillResult(
            order_id=f"paper:{uuid.uuid4()}", status="filled",
            requested_shares=shares, filled_shares=shares, avg_fill_price=order.max_price,
        )
        result = OrderResult(status="simulated_fill", request=order, fill_result=fill)
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
            return self._submit_pending(pending, self._order_placer, approved_by="system:auto_execute")

        return OrderResult(
            status="awaiting_approval", request=order,
            extra={"pending_order_id": pending.id, "expires_at": pending.expires_at.isoformat()},
        )

    def confirm_and_place(
        self, pending_order_id: str, order_placer: PolymarketOrderPlacer, *, approved_by: str, now: datetime | None = None,
    ) -> OrderResult:
        """Submits a pending order that stopped at awaiting_approval.
        IMPORTANT: this only submits — it does not reconcile. The
        caller must separately call reconciliation.reconcile_order()
        (or let the next reconcile_pending_orders() sweep pick it up)
        to find out whether it actually filled before assuming
        anything about a resulting position. See this module's
        docstring and Task 5."""
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
        return self._submit_pending(pending, order_placer, approved_by=approved_by, now=now)

    def _submit_pending(
        self, pending: PendingLiveOrder, order_placer: PolymarketOrderPlacer, *, approved_by: str, now: datetime | None = None,
    ) -> OrderResult:
        """The ONLY method in this codebase that calls
        PolymarketOrderPlacer.place_order. Records the SubmissionOutcome
        verbatim and nothing more — see module docstring for why fill
        determination is deliberately out of scope here."""
        now = now or datetime.now(timezone.utc)
        order = pending.order
        if self._emergency_stop_store is None or self._emergency_stop_store.is_stopped():
            exc = LiveTradingDisabledError(
                "Emergency stop is active (or no emergency-stop store was configured) — "
                "refusing to submit a live order. See src/execution/emergency_stop.py."
            )
            failed = pending.with_status("failed", decided_at=now, decided_by=approved_by, error=str(exc))
            self._pending_store.update(failed)
            self._decision_logger.log_pending_order(failed)
            raise exc

        try:
            outcome = order_placer.place_order(order)
        except Exception as exc:  # noqa: BLE001 - a transport/client exception that never reached an exchange decision
            failed = pending.with_status("failed", decided_at=now, decided_by=approved_by, error=str(exc))
            self._pending_store.update(failed)
            self._decision_logger.log_pending_order(failed)
            raise

        if not outcome.ok:
            # A clean rejection FROM the exchange (not an exception) — e.g.
            # fok_not_filled, not_enough_balance. No exchange_order_id, so
            # there is nothing for reconciliation to look up; this is
            # already a known-terminal, known-no-position outcome.
            rejected = pending.with_status(
                "rejected", decided_at=now, decided_by=approved_by,
                error=f"{outcome.error_code}: {outcome.error_message}", fill_reconciled=True,
            )
            self._pending_store.update(rejected)
            self._decision_logger.log_pending_order(rejected)
            return OrderResult(status="rejected", request=order, submission=outcome, error=rejected.error)

        submitted = pending.with_status(
            "submitted", decided_at=now, decided_by=approved_by, exchange_order_id=outcome.exchange_order_id,
        )
        self._pending_store.update(submitted)
        self._decision_logger.log_pending_order(submitted)
        return OrderResult(
            status="submitted", request=order, submission=outcome,
            extra={"pending_order_id": pending.id, "exchange_order_id": outcome.exchange_order_id},
        )

    def reject_pending(self, pending_order_id: str, *, reason: str, rejected_by: str, now: datetime | None = None) -> PendingLiveOrder:
        now = now or datetime.now(timezone.utc)
        pending = self._pending_store.get(pending_order_id)
        if pending is None:
            raise PendingOrderNotActionableError(f"No pending order {pending_order_id!r} found")
        if pending.status != "awaiting_approval":
            raise PendingOrderNotActionableError(f"Pending order {pending_order_id!r} is {pending.status!r}, not awaiting_approval — nothing to reject.")
        rejected = pending.with_status("rejected", decided_at=now, decided_by=rejected_by, error=reason, fill_reconciled=True)
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
