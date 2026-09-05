"""The execution layer's safety boundary.

THIS IS THE ONLY MODULE IN THE CODEBASE THAT MAY EVER CALL A HOOD ORDER
TOOL. Two gateways exist:

  - PaperExecutionGateway: the only one that runs unattended. Never calls
    an order tool. Always safe.

  - LiveExecutionGateway: real order placement. Its submit_order() NEVER
    calls place_option_order directly from its own body — it always
    creates a PendingLiveOrder and persists it first, so there is a full
    audit trail no matter what happens next. What happens next depends on
    settings.live_auto_execute:

      - False (the default): submit_order() stops there and returns
        status="pending_approval". A separate, later call to
        confirm_and_place() — with an explicit `approved_by` — is required
        to actually place it. Nothing here enforces WHO or WHAT triggers
        that call (this codebase can't verify a human clicked "yes"); that
        is an operational/runbook convention, not a code-level guarantee.
      - True: if a LiveOrderPlacer was also injected at construction,
        submit_order() immediately places the order with no separate
        approval step — RiskManager and PositionEvaluator's deterministic
        checks (already run by the caller before submit_order was ever
        reached) are the only gate. `approved_by` is recorded as
        "system:auto_execute" in that case, so the audit log always shows
        plainly whether a given order went through a human step or not.

    Either way, `_place_pending()` is the ONLY method in this entire
    codebase that calls place_option_order — both submit_order()'s
    auto-execute path and confirm_and_place() funnel through it, so there
    is exactly one implementation of "what actually happens when a live
    order is placed" (see that method for the full behavior).

Independent guarantees enforced here, on purpose overlapping so a bug in
one doesn't silently remove the others:

  1. get_execution_gateway() only returns a *working paper* gateway by
     default. Getting a live-capable gateway requires the caller to
     explicitly pass a PendingOrderStore — there is no implicit default.

  2. LiveExecutionGateway itself refuses to even construct unless BOTH
     settings.is_live AND settings.live_trading_confirmed are true — two
     independent switches, so a single misconfiguration can't enable it.

  3. confirm_and_place() re-checks both of those switches again at call
     time (not just at construction time), re-validates the pending
     order's status and expiry, and only ever acts on the exact
     pending_order_id passed in.

  4. Every step (proposed, approved, rejected, expired, placed, failed) is
     written to the decision/audit log — see logging/decision_logger.py.

  5. Even with live_auto_execute=True, nothing in this codebase can call
     an MCP tool (see live_client.py's docstring) — a LiveOrderPlacer only
     ever exists because something outside this Python process bridged
     one in. In practice, on this platform, that means submit_order()
     degrades to the same pending-approval behavior as
     live_auto_execute=False during a normal run_trading_cycle() call; see
     README.md for what "auto-execute" means operationally here.

Phase 35, Parts N-P added THREE MORE independent, overlapping guards,
all enforced inside `_place_pending()` — the single method both
submit_order()'s auto-execute path and confirm_and_place() already
funnel through — so nothing can reach a real broker call by skipping
them:

  6. `assert_options_only(order)` (src/execution/asset_class_restriction.py,
     Phase 18) is now actually CALLED here, not just defined. Structurally
     redundant with OrderLeg.option_id being required (see that module's
     docstring), but Part N asked for this boundary to be explicit and
     enforced at the gateway itself, not merely true by construction
     elsewhere.

  7. `EmergencyStopStore.is_stopped()` (src/execution/emergency_stop.py,
     Part P) — a real, file-backed, restart-surviving kill switch,
     defaulting to STOPPED. Checked immediately before every broker call.
     Cannot be bypassed by live_auto_execute=True (checked regardless of
     that flag) or by strategy code (strategies never see this store).

  8. `is_live_trading_authorized(system_state_audit_log)`
     (src/execution/system_state.py, Part O) — true only when the
     persisted system state is exactly LIVE_AUTONOMOUS_TRADING. RESEARCH,
     VALIDATED_STRATEGY, HUMAN_LIVE_AUTHORIZATION, LIVE_PAUSED,
     EMERGENCY_STOP, and "no record at all" are all unauthorized.

Both new stores are constructor arguments with no permissive default:
omitting either (passing None) is treated as the safe/blocked answer
("no configured stop store" behaves as "stopped"; "no configured audit
log" behaves as "not authorized") — there is no way to construct a
gateway that skips these checks by simply not wiring the stores.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.execution.asset_class_restriction import assert_options_only
from src.execution.emergency_stop import EmergencyStopStore
from src.execution.live_positions import LiveBotPositionsStore
from src.execution.orders import LiveFill, OrderRequest, OrderResult, SimulatedFill
from src.execution.pending import PendingLiveOrder, PendingOrderStore
from src.execution.system_state import SystemStateAuditLog, is_live_trading_authorized

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.execution.live_client import LiveOrderPlacer
    from src.logging.decision_logger import DecisionLogger


class LiveTradingDisabledError(RuntimeError):
    """Raised whenever anything attempts to route a real order while the
    system is not both configured AND implemented for that specific step."""


class PendingOrderNotActionableError(RuntimeError):
    """Raised by confirm_and_place()/reject_pending() when the referenced
    pending order doesn't exist, was already decided, or has expired."""


def assert_paper_mode(settings: "Settings") -> None:
    """Belt-and-braces guard for paper-only call sites. Call this at the
    top of any function that must never run outside paper mode, even if the
    caller believes it already checked."""
    if not settings.is_paper:
        raise LiveTradingDisabledError(
            f"TRADING_MODE={settings.trading_mode!r} — refusing to proceed. "
            "This code path only ever operates in paper mode."
        )


class ExecutionGateway(ABC):
    @abstractmethod
    def submit_order(self, order: OrderRequest) -> OrderResult:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, account_number: str, order_id: str) -> OrderResult:
        raise NotImplementedError


class PaperExecutionGateway(ExecutionGateway):
    """Simulates a fill at the caller-supplied limit price and writes it to
    the decision/audit log. Never calls place_option_order,
    review_option_order, or cancel_option_order."""

    def __init__(self, settings: "Settings", decision_logger: "DecisionLogger"):
        self._settings = settings
        self._decision_logger = decision_logger

    def submit_order(self, order: OrderRequest) -> OrderResult:
        assert_paper_mode(self._settings)

        # Paper fills use the caller-supplied limit price when given
        # (matching what a limit order would target); otherwise there's no
        # quote to simulate against here, so the caller must supply price.
        if order.price is None:
            result = OrderResult(status="rejected", request=order, error="No price to simulate a fill against")
            self._decision_logger.log_simulated_order(order, result)
            return result

        fill = SimulatedFill(
            fill_price=float(order.price),
            filled_at=datetime.now(timezone.utc),
            quote_bid=float(order.price),
            quote_ask=float(order.price),
        )
        result = OrderResult(status="simulated_fill", request=order, simulated_fill=fill)
        self._decision_logger.log_simulated_order(order, result)
        return result

    def cancel_order(self, account_number: str, order_id: str) -> OrderResult:
        assert_paper_mode(self._settings)
        self._decision_logger.log_simulated_cancel(account_number=account_number, order_id=order_id)
        return OrderResult(
            status="simulated_fill",
            request=OrderRequest(
                account_number=account_number,
                legs=(_placeholder_leg(),),
                quantity="0",
                price="0",
                reason=f"paper-cancel {order_id}",
            ),
            extra={"cancelled_order_id": order_id},
        )


def _placeholder_leg():
    from src.execution.orders import OrderLeg

    # OrderRequest requires >=1 leg; a cancel has no real leg, so this is a
    # clearly-marked placeholder purely to satisfy the audit-log shape.
    return OrderLeg(option_id="n/a", side="sell", position_effect="close")


class LiveExecutionGateway(ExecutionGateway):
    """Live order placement, gated on explicit per-trade human approval.
    See the module docstring above for the full design — this class is the
    enforcement point for it.
    """

    def __init__(
        self,
        settings: "Settings",
        decision_logger: "DecisionLogger",
        pending_store: PendingOrderStore,
        bot_positions_store: LiveBotPositionsStore | None = None,
        live_order_placer: "LiveOrderPlacer | None" = None,
        emergency_stop_store: EmergencyStopStore | None = None,
        system_state_audit_log: SystemStateAuditLog | None = None,
    ) -> None:
        if not settings.is_live:
            raise LiveTradingDisabledError(
                f"TRADING_MODE={settings.trading_mode!r} — LiveExecutionGateway must not be "
                "constructed outside TRADING_MODE=live."
            )
        if not settings.live_trading_confirmed:
            raise LiveTradingDisabledError(
                "LIVE_TRADING_CONFIRMED is not true — refusing to construct a live execution "
                "gateway. This is a deliberate second switch, independent of TRADING_MODE, "
                "that a human must set explicitly before this class will even instantiate."
            )
        self._settings = settings
        self._decision_logger = decision_logger
        self._pending_store = pending_store
        self._bot_positions_store = bot_positions_store
        # Only relevant when settings.live_auto_execute is True — see
        # submit_order(). On this platform nothing can call an MCP tool
        # from inside a plain Python call stack (see live_client.py's
        # docstring), so in practice this is only ever populated by a
        # caller sophisticated enough to bridge that gap; when it's None,
        # auto-execute has nothing to act through and submit_order()
        # degrades to the same pending-approval behavior as
        # live_auto_execute=False.
        self._live_order_placer = live_order_placer
        # Phase 35, Parts N-P — see the module docstring's guards 6-8.
        # Deliberately NOT defaulted to a permissive stand-in: None is
        # carried through as-is and treated as the blocked answer at
        # check time in _place_pending, so there is no way to construct
        # a gateway that silently skips these checks.
        self._emergency_stop_store = emergency_stop_store
        self._system_state_audit_log = system_state_audit_log

    def submit_order(self, order: OrderRequest) -> OrderResult:
        """NEVER calls place_option_order directly from this method's own
        body. Always creates a PendingLiveOrder and persists it first, so
        there is a full audit trail regardless of what happens next:

          - settings.live_auto_execute is False (the default), OR no
            LiveOrderPlacer was injected at construction: stop here and
            return status="pending_approval". A separate, later call to
            confirm_and_place() is required to actually place it — see
            that method's docstring for who/what is allowed to make that
            call.
          - settings.live_auto_execute is True AND a LiveOrderPlacer was
            injected: immediately place it via the same code path
            confirm_and_place() uses, with no conversational approval
            step — RiskManager/PositionEvaluator's deterministic checks
            (already run by the caller before submit_order was ever
            reached) are the only gate. `approved_by` is recorded as
            "system:auto_execute" so the audit log always shows plainly
            whether a given order went through a human or not.
        """
        pending = PendingLiveOrder.new(
            order=order,
            expiry_minutes=self._settings.pending_order_expiry_minutes,
            decision_context={"reason": order.reason},
        )
        self._pending_store.add(pending)
        self._decision_logger.log_pending_live_order(pending)

        if self._settings.live_auto_execute and self._live_order_placer is not None:
            return self._place_pending(pending, self._live_order_placer, approved_by="system:auto_execute")

        return OrderResult(
            status="pending_approval",
            request=order,
            extra={"pending_order_id": pending.id, "expires_at": pending.expires_at.isoformat()},
        )

    def cancel_order(self, account_number: str, order_id: str) -> OrderResult:
        # Deliberately not implemented, even though this class otherwise
        # supports live placement: cancellation of an already-placed real
        # order was not part of what was asked for, and adding it casually
        # here would be exactly the kind of scope creep this codebase's
        # existing safety posture warns against. Build it deliberately,
        # with the same review-then-approve pattern, if it's ever needed.
        raise LiveTradingDisabledError(
            "Live order cancellation is not implemented. cancel_option_order must never be "
            "called automatically by this codebase; cancelling a live order today has to be "
            "an explicit, human-directed action taken outside this gateway."
        )

    def confirm_and_place(
        self,
        pending_order_id: str,
        live_order_placer: "LiveOrderPlacer",
        *,
        approved_by: str,
        now: datetime | None = None,
    ) -> OrderResult:
        """The path to place_option_order for an order that stopped at
        pending_approval (settings.live_auto_execute is False, or True but
        with no LiveOrderPlacer available at cycle time — see
        submit_order()). Must only be called after that specific pending
        order has been explicitly approved — `approved_by` is recorded
        verbatim in the pending-order record and the audit log, and must
        identify who/what actually approved it (never a generic
        placeholder; "system:auto_execute" is reserved for
        submit_order()'s own immediate-placement path, not for this one).
        """
        if not self._settings.is_live or not self._settings.live_trading_confirmed:
            raise LiveTradingDisabledError(
                "TRADING_MODE=live and LIVE_TRADING_CONFIRMED=true are both required to place "
                "a live order, and were re-checked here (not just at construction time)."
            )
        now = now or datetime.now(timezone.utc)

        pending = self._pending_store.get(pending_order_id)
        if pending is None:
            raise PendingOrderNotActionableError(f"No pending order {pending_order_id!r} found")
        if now >= pending.expires_at and pending.status == "awaiting_approval":
            expired = pending.with_status("expired", decided_at=now, decided_by="system:expiry")
            self._pending_store.update(expired)
            self._decision_logger.log_pending_live_order(expired)
            pending = expired
        if pending.status != "awaiting_approval":
            raise PendingOrderNotActionableError(
                f"Pending order {pending_order_id!r} is {pending.status!r}, not "
                "awaiting_approval — refusing to place it. Each pending order can only be "
                "confirmed once, and an expired one needs a fresh cycle to re-propose it "
                "against current data."
            )

        return self._place_pending(pending, live_order_placer, approved_by=approved_by, now=now)

    def _assert_execution_permitted(
        self, order: OrderRequest, *, now: datetime, pending: PendingLiveOrder, approved_by: str,
    ) -> None:
        """Phase 35, Parts N-P's guards 6-8 (see module docstring),
        enforced unconditionally right before every broker call. A
        blocked attempt is recorded exactly like a placer-raised
        failure — status="failed" on the pending order, logged, then
        re-raised — never silently swallowed."""
        try:
            assert_options_only(order)
            if self._emergency_stop_store is None or self._emergency_stop_store.is_stopped():
                raise LiveTradingDisabledError(
                    "Emergency stop is active (or no emergency-stop store was configured for "
                    "this gateway) -- refusing to place a live order. See "
                    "src/execution/emergency_stop.py."
                )
            if self._system_state_audit_log is None or not is_live_trading_authorized(self._system_state_audit_log):
                current = (
                    self._system_state_audit_log.current_state()
                    if self._system_state_audit_log is not None else None
                )
                raise LiveTradingDisabledError(
                    f"System is not authorized for live autonomous trading (current state: "
                    f"{current}) -- refusing to place a live order. See "
                    "src/execution/system_state.py."
                )
        except Exception as exc:  # noqa: BLE001 - record the block in the audit trail, then re-raise
            failed = pending.with_status("failed", decided_at=now, decided_by=approved_by, error=str(exc))
            self._pending_store.update(failed)
            self._decision_logger.log_pending_live_order(failed)
            raise

    def _place_pending(
        self,
        pending: PendingLiveOrder,
        live_order_placer: "LiveOrderPlacer",
        *,
        approved_by: str,
        now: datetime | None = None,
    ) -> OrderResult:
        """The ONLY place in this entire codebase that calls
        place_option_order. Both submit_order()'s auto-execute path and
        confirm_and_place() funnel through here after their own
        pre-checks, so there is exactly one implementation of "what
        actually happens when we place a live order" to audit and test.

        Phase 35, Parts N-P: this is also where guards 6-8 from the
        module docstring are enforced — immediately before the broker
        call, unconditionally, regardless of live_auto_execute or which
        caller reached here. A blocked attempt is recorded to the
        pending-order store/audit log exactly like any other failure
        (status="failed"), never silently swallowed."""
        now = now or datetime.now(timezone.utc)
        order = pending.order
        self._assert_execution_permitted(order, now=now, pending=pending, approved_by=approved_by)
        ref_id = order.ref_id or new_ref_id()
        try:
            raw = live_order_placer.place_option_order(
                account_number=order.account_number,
                legs=[leg.to_dict() for leg in order.legs],
                quantity=order.quantity,
                type=order.type,
                price=order.price,
                stop_price=order.stop_price,
                time_in_force=order.time_in_force,
                market_hours=order.market_hours,
                ref_id=ref_id,
            )
        except Exception as exc:  # noqa: BLE001 - record the failure in the audit trail, then re-raise
            failed = pending.with_status("failed", decided_at=now, decided_by=approved_by, error=str(exc))
            self._pending_store.update(failed)
            self._decision_logger.log_pending_live_order(failed)
            raise

        fill = LiveFill(
            order_id=raw.get("id") or raw.get("order_id"),
            state=raw.get("state"),
            filled_at=now,
            raw=raw,
        )
        result = OrderResult(status="placed", request=order, live_fill=fill)
        placed = pending.with_status("placed", decided_at=now, decided_by=approved_by)
        self._pending_store.update(placed)
        self._decision_logger.log_live_order_placed(placed, result)

        if self._bot_positions_store is not None:
            # Provenance bookkeeping (see live_positions.py): only track
            # entries so future cycles know this system may propose exits
            # for the resulting position; a close doesn't need tracking
            # added, just removed once the position is actually gone.
            for leg in order.legs:
                if leg.position_effect == "open":
                    self._bot_positions_store.add(leg.option_id)
                elif leg.position_effect == "close":
                    self._bot_positions_store.remove(leg.option_id)

        return result

    def reject_pending(
        self,
        pending_order_id: str,
        *,
        reason: str,
        rejected_by: str,
        now: datetime | None = None,
    ) -> PendingLiveOrder:
        now = now or datetime.now(timezone.utc)
        pending = self._pending_store.get(pending_order_id)
        if pending is None:
            raise PendingOrderNotActionableError(f"No pending order {pending_order_id!r} found")
        if pending.status != "awaiting_approval":
            raise PendingOrderNotActionableError(
                f"Pending order {pending_order_id!r} is {pending.status!r}, not awaiting_approval "
                "— nothing to reject."
            )
        rejected = pending.with_status("rejected", decided_at=now, decided_by=rejected_by, error=reason)
        self._pending_store.update(rejected)
        self._decision_logger.log_pending_live_order(rejected)
        return rejected


def get_execution_gateway(
    settings: "Settings",
    decision_logger: "DecisionLogger",
    pending_store: PendingOrderStore | None = None,
    bot_positions_store: LiveBotPositionsStore | None = None,
    live_order_placer: "LiveOrderPlacer | None" = None,
    emergency_stop_store: EmergencyStopStore | None = None,
    system_state_audit_log: SystemStateAuditLog | None = None,
) -> ExecutionGateway:
    """The only supported way to obtain a gateway.

    TRADING_MODE=paper always returns PaperExecutionGateway, regardless of
    any other argument. TRADING_MODE=live requires the caller to explicitly
    pass a PendingOrderStore — there is no implicit default that would let
    a caller accidentally receive a live-capable gateway just by flipping
    TRADING_MODE without also wiring the rest of the live path deliberately.

    Phase 35, Parts N-P: `emergency_stop_store`/`system_state_audit_log` are
    threaded straight through to LiveExecutionGateway unchanged — omitting
    either here produces a gateway that will refuse every real placement
    attempt (see that class's docstring), never one that silently skips
    the check.
    """
    if settings.is_paper:
        return PaperExecutionGateway(settings, decision_logger)
    if pending_store is None:
        raise LiveTradingDisabledError(
            "TRADING_MODE=live requires an explicit PendingOrderStore to be passed to "
            "get_execution_gateway — there is no implicit default, so a caller can't "
            "accidentally obtain a live-capable gateway."
        )
    return LiveExecutionGateway(
        settings, decision_logger, pending_store, bot_positions_store, live_order_placer,
        emergency_stop_store=emergency_stop_store, system_state_audit_log=system_state_audit_log,
    )


def new_ref_id() -> str:
    return str(uuid.uuid4())
