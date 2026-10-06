"""The ONLY path from "an order was submitted" to "the position ledger
reflects what actually happened." Both of this package's two order
paths funnel through `reconcile_order()`:

  1. Same-cycle auto-execute (POLYMARKET_LIVE_AUTO_EXECUTE=true): the
     order gets an exchange_order_id the instant gateway.submit_order()
     returns, so engine.run_cycle() can reconcile it immediately.
  2. Pending-approval (the default): gateway.submit_order() only
     creates a PendingLiveOrder; a real order doesn't exist yet. Some
     LATER call to LivePolymarketGateway.confirm_and_place() — possibly
     in a different process invocation, possibly after a restart —
     actually places it. That call's caller is responsible for also
     calling reconcile_order() with the returned pending order, but
     nothing enforces that at the time, which is exactly the gap Task 5
     describes. reconcile_pending_orders() closes it: a sweep over
     every PendingLiveOrder that was placed but not yet reconciled,
     safe to call from anywhere, at any time, including a bot restart
     that lost all in-memory state.

Idempotency (Task 5's explicit requirement): reconcile_order() checks
`pending.fill_reconciled` first and no-ops if already True, AND
position_store.add_if_absent() independently refuses to create a
second position for the same client_order_id even if some caller
managed to skip that check. Two independent guards, on purpose — the
same "deliberately overlapping" philosophy gateway.py and
execution/gateway.py already use for safety gates.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.polymarket.client import PolymarketClient
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import FillResult, OrderRequest, PendingLiveOrder
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.state import DailyPnlStateStore


def record_fill(
    fill: FillResult,
    order: OrderRequest,
    client_order_id: str,
    *,
    position_store: PolymarketPositionStore,
    state_store: DailyPnlStateStore,
    decision_logger: PolymarketDecisionLogger,
    now: datetime,
) -> OpenPosition | None:
    """The ONLY place a FillResult becomes an OpenPosition. Shared by
    reconcile_order() below (real fills, discovered via a fresh exchange
    lookup) and engine.py's paper-mode path (a simulated fill has no
    exchange order to reconcile, but must open a position through this
    exact same idempotent, state-updating path — never a second,
    parallel way to create one). Returns the created OpenPosition, or
    None if `fill` isn't a fill (per FillResult.is_fill) or a position
    for this `client_order_id` already existed (add_if_absent's
    idempotency guard)."""
    if not fill.is_fill:
        return None
    position = OpenPosition(
        condition_id=order.condition_id, token_id=order.token_id, outcome=order.outcome,
        requested_size_usd=order.size_usd, filled_shares=fill.filled_shares, avg_fill_price=fill.avg_fill_price,
        order_id=fill.order_id, client_order_id=client_order_id, status=fill.status,
        opened_at=now, close_time=order.close_time,
    )
    created = position_store.add_if_absent(position)  # the secondary idempotency guard
    if not created:
        return None
    state = state_store.load(today=now.date())
    state.trades_opened += 1
    state.open_position_count += 1
    state_store.save(state)
    decision_logger.log_decision(
        kind="position_opened",
        reason=(
            f"{position.outcome} on {position.condition_id}: requested ${position.requested_size_usd:.2f}, "
            f"filled {position.filled_shares:.4f} shares @ ${position.avg_fill_price:.4f} "
            f"({'partial' if fill.status == 'partially_filled' else 'full'} fill)"
        ),
        evidence={"position": position.to_dict(), "fill": _fill_to_dict(fill)},
    )
    return position


def reconcile_order(
    pending: PendingLiveOrder,
    *,
    client: PolymarketClient,
    pending_store: PolymarketPendingOrderStore,
    position_store: PolymarketPositionStore,
    state_store: DailyPnlStateStore,
    decision_logger: PolymarketDecisionLogger,
    now: datetime | None = None,
) -> FillResult | None:
    """Idempotent: safe to call for the same `pending` any number of
    times, including across a restart (every check here is against
    persisted state, not in-memory flags). Returns the FillResult it
    found, or None if there was genuinely nothing to reconcile yet
    (no exchange_order_id — the order never reached the exchange — or
    already reconciled)."""
    now = now or datetime.now(timezone.utc)

    if pending.fill_reconciled:
        return None  # already handled — the primary idempotency guard

    if pending.exchange_order_id is None:
        return None  # nothing was ever submitted to the exchange for this pending order

    fill = client.get_fill_status(pending.exchange_order_id)

    if fill.is_fill:
        record_fill(
            fill, pending.order, pending.id,
            position_store=position_store, state_store=state_store, decision_logger=decision_logger, now=now,
        )
    else:
        # Not a fill (rejected/cancelled/expired/resting/unknown) — no
        # position, but still mark reconciled so this pending order is
        # never re-checked forever. "resting"/"unknown" are logged
        # distinctly from genuine terminal non-fills, since they may
        # warrant a human look (a FOK/FAK order should never actually
        # end up "resting").
        decision_logger.log_decision(
            kind="order_not_filled",
            reason=f"Order {pending.exchange_order_id} on {pending.order.condition_id}: {fill.status}, no position opened",
            evidence={"fill": _fill_to_dict(fill)},
        )

    updated = pending.with_status(pending.status, fill_reconciled=True)
    pending_store.update(updated)
    return fill


def reconcile_pending_orders(
    *,
    client: PolymarketClient,
    pending_store: PolymarketPendingOrderStore,
    position_store: PolymarketPositionStore,
    state_store: DailyPnlStateStore,
    decision_logger: PolymarketDecisionLogger,
    now: datetime | None = None,
) -> int:
    """The restart-safety sweep (Task 5): reconciles every persisted
    pending order that has an exchange_order_id but hasn't been
    reconciled yet, regardless of which process or cycle created it.
    Call this at the start of every run_cycle() and it is also safe to
    call standalone (e.g. a one-off `python -m` invocation) after a
    crash or restart — reconcile_order()'s own idempotency makes
    repeated sweeps harmless.

    Returns the number of pending orders reconciled (fill checked; not
    necessarily the number that turned into positions)."""
    now = now or datetime.now(timezone.utc)
    reconciled = 0
    for pending in pending_store.load():
        if pending.fill_reconciled or pending.exchange_order_id is None:
            continue
        reconcile_order(
            pending, client=client, pending_store=pending_store, position_store=position_store,
            state_store=state_store, decision_logger=decision_logger, now=now,
        )
        reconciled += 1
    return reconciled


def _fill_to_dict(fill: FillResult) -> dict:
    return {
        "order_id": fill.order_id, "status": fill.status, "requested_shares": fill.requested_shares,
        "filled_shares": fill.filled_shares, "avg_fill_price": fill.avg_fill_price,
    }
