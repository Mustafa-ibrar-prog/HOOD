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

One exception to "always marks fill_reconciled=True": a get_fill_status()
result of status="unknown" is NOT an authoritative determination (it
means either the status lookup itself failed, or the exchange returned
a state this system doesn't recognize) — reconcile_order() deliberately
leaves `fill_reconciled` False in that case, so the SAME pending order
remains eligible for a later retry (a subsequent reconcile_pending_orders()
sweep, or a manual re-run) instead of being permanently given up on
without ever learning its real fate. No position is ever opened for an
"unknown" result either way.

STALE-ENTRY SAFETY NET (added after a live incident — order D0EEB7H1AZ7J
submitted, immediately read back "unknown," then adopted FILLED by a
later sweep; separately, an even OLDER unresolved entry for the same
market resolved FILLED near that market's close, reopening a position
right after its own evidence-driven exit had just closed it):
reconcile_pending_orders() has no time bound on how long a "submitted,
not yet fill_reconciled" order may keep being retried — the only gate
was `fill_reconciled` itself, with nothing checking whether the order's
own originally-intended decision window (its market's close_time, or
this system's own expiry window on the pending record) was still
current. A fill discovered well after either has passed no longer
reflects a currently-relevant strategy decision.

Per explicit requirement: a REAL fill is never suppressed or pretended
away — the exchange says the shares exist, so record_fill() ALWAYS
still runs. What changes is visibility: reconcile_order() now checks
staleness (market already closed, or past the pending record's own
expires_at) BEFORE recording a genuine fill, and when stale, logs a
distinct `stale_entry_fill_adopted` decision entry carrying exactly
why, so this is never silent. The resulting OpenPosition's own
close_time (unchanged, straight from the order) is what then lets
exit_manager.py's own market-closed skip (see its module docstring)
keep a stale-adopted position out of the dynamic-exit cascade entirely
— settle_resolved_positions() (which already runs every cycle) is the
correct, exchange-aware path for a position whose market has ended,
never a fresh SELL attempt into a market that's no longer open.

Separately, reconcile_pending_orders()'s sweep now only ever reconciles
BUY (entry) pending orders — a SELL (exit) pending order is exclusively
exit_manager.py's own responsibility (its idempotency is
OpenPosition.exit_pending_order_id, not PendingLiveOrder.fill_reconciled
— record_exit_fill() never marks the underlying pending record
reconciled at all). Before this fix, a live SELL order that reached the
exchange and sat unresolved for even one cycle was ALSO visible to this
generic sweep and would have been reconciled through record_fill() —
the BUY-shaped position-creation path — fabricating a bogus "new
entry" position out of what was actually an exit fill. No shipped
behavior relied on this (every existing exit test drives
exit_manager.py's functions directly, never through this sweep), but
it is a real, latent gap this fix closes while already here.
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
    entry_context: dict | None = None,
) -> OpenPosition | None:
    """The ONLY place a FillResult becomes an OpenPosition. Shared by
    reconcile_order() below (real fills, discovered via a fresh exchange
    lookup) and engine.py's paper-mode path (a simulated fill has no
    exchange order to reconcile, but must open a position through this
    exact same idempotent, state-updating path — never a second,
    parallel way to create one). Returns the created OpenPosition, or
    None if `fill` isn't a fill (per FillResult.is_fill) or a position
    for this `client_order_id` already existed (add_if_absent's
    idempotency guard).

    `entry_context` (see positions.OpenPosition and trade_learning.py,
    TASK 2) is whatever same-cycle entry evidence the caller actually
    has available -- None (the default) for every existing call site
    that doesn't pass it, so this stays fully backward compatible."""
    if not fill.is_fill:
        return None
    position = OpenPosition(
        condition_id=order.condition_id, token_id=order.token_id, outcome=order.outcome,
        requested_size_usd=order.size_usd, filled_shares=fill.filled_shares, avg_fill_price=fill.avg_fill_price,
        order_id=fill.order_id, client_order_id=client_order_id, status=fill.status,
        opened_at=now, close_time=order.close_time, entry_context=entry_context,
        single_book_market=order.single_book_market,
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
    entry_context: dict | None = None,
) -> FillResult | None:
    """Idempotent: safe to call for the same `pending` any number of
    times, including across a restart (every check here is against
    persisted state, not in-memory flags). Returns the FillResult it
    found, or None if there was genuinely nothing to reconcile yet
    (no exchange_order_id — the order never reached the exchange — or
    already reconciled).

    `entry_context` (see record_fill/trade_learning.py, TASK 2): only
    engine.py's SAME-CYCLE submit-then-reconcile call site has this to
    pass (the entry decision that just happened); reconcile_pending_orders()'s
    restart-safety sweep (a DIFFERENT, later cycle than the one that
    submitted the order) never has it and passes None — never
    fabricated after the fact. Either way, `stale_entry_fill` is
    always set from what THIS call itself determines, regardless of
    what the caller passed."""
    now = now or datetime.now(timezone.utc)

    if pending.fill_reconciled:
        return None  # already handled — the primary idempotency guard

    if pending.exchange_order_id is None:
        return None  # nothing was ever submitted to the exchange for this pending order

    fill = client.get_fill_status(pending.exchange_order_id)

    if fill.is_fill:
        is_stale = _log_if_stale_entry_fill(pending, fill, now=now, decision_logger=decision_logger)
        merged_context = {**(entry_context or {}), "stale_entry_fill": is_stale}
        record_fill(
            fill, pending.order, pending.id,
            position_store=position_store, state_store=state_store, decision_logger=decision_logger, now=now,
            entry_context=merged_context,
        )
    elif fill.status == "unknown":
        # NOT an authoritative determination -- either the status
        # lookup call itself failed (fill.raw["lookup_error"], a
        # transport/auth problem that says nothing about the order's
        # real state) or the exchange returned a state this system
        # doesn't recognize (fill.raw["state"]). Logged, but
        # deliberately NOT marked fill_reconciled: a communication
        # failure may be transient (a later sweep/manual re-run can
        # succeed), and an unrecognized state may become interpretable
        # once the code is updated -- permanently giving up on either
        # without ever learning the truth is exactly the "unknown fill"
        # risk this must never create. No position is opened here
        # either way -- see FillResult.is_fill/models.py's module
        # docstring on "unknown" always being treated like "not filled."
        #
        # `fill.raw` (the lookup_error, or the raw exchange state) is
        # included verbatim -- a live incident showed the OLD version
        # of this log entry discarding exactly that information via
        # _fill_to_dict(), making "why did this read unknown"
        # unanswerable from the stored decision log after the fact.
        decision_logger.log_decision(
            kind="order_status_unknown",
            reason=f"Order {pending.exchange_order_id} on {pending.order.condition_id}: status unknown, "
                   "no position opened, NOT marked reconciled -- re-checkable later",
            evidence={"fill": _fill_to_dict(fill), "raw": dict(fill.raw)},
        )
        return fill
    else:
        # A genuine terminal non-fill (rejected/cancelled/expired) or a
        # resting state -- an authoritative answer, safe to mark done.
        # "resting" is logged distinctly since a FOK/FAK order should
        # never actually end up there; it may still warrant a human look.
        decision_logger.log_decision(
            kind="order_not_filled",
            reason=f"Order {pending.exchange_order_id} on {pending.order.condition_id}: {fill.status}, no position opened",
            evidence={"fill": _fill_to_dict(fill), "raw": dict(fill.raw)},
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
        # BUY (entry) orders only -- see this module's own docstring on
        # the SELL-misreconciliation gap this closes. A SELL (exit)
        # pending order is exclusively exit_manager.py's own
        # responsibility (reconcile_exit_fill(), gated by
        # OpenPosition.exit_pending_order_id); reconcile_order() below
        # is the BUY-shaped position-creation path and must never run
        # against one.
        if pending.order.side != "BUY":
            continue
        reconcile_order(
            pending, client=client, pending_store=pending_store, position_store=position_store,
            state_store=state_store, decision_logger=decision_logger, now=now,
        )
        reconciled += 1
    return reconciled


def _log_if_stale_entry_fill(
    pending: PendingLiveOrder, fill: FillResult, *, now: datetime, decision_logger: PolymarketDecisionLogger,
) -> bool:
    """See module docstring's STALE-ENTRY SAFETY NET section. Never
    blocks or alters the fill itself -- record_fill() always still
    runs regardless of what this finds; this only makes a stale
    adoption visible in the decision log rather than silent. Returns
    True iff this fill was stale -- reconcile_order() uses this to tag
    the resulting position's entry_context (see trade_learning.py,
    TASK 2) so a stale-adopted entry is never silently learned from as
    an ordinary strategy prediction."""
    close_time = pending.order.close_time
    if close_time.tzinfo is None:
        close_time = close_time.replace(tzinfo=timezone.utc)
    expires_at = pending.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    created_at = pending.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    market_closed = now >= close_time
    past_expiry = now > expires_at
    if not (market_closed or past_expiry):
        return False  # the common, healthy case -- resolved while still current; nothing to flag

    age_seconds = (now - created_at).total_seconds()
    reasons = []
    if market_closed:
        reasons.append(f"past the market's close_time ({close_time.isoformat()})")
    if past_expiry:
        reasons.append(f"past its own expiry ({expires_at.isoformat()})")
    decision_logger.log_decision(
        kind="stale_entry_fill_adopted",
        reason=(
            f"Order {pending.exchange_order_id} on {pending.order.condition_id} ({pending.order.outcome}): "
            f"a genuine fill resolved {age_seconds:.0f}s after submission, {' and '.join(reasons)} -- "
            "adopting the real fill into the position ledger (a genuine fill is never ignored), but this "
            "entry is STALE: it no longer reflects a currently-relevant strategy decision."
        ),
        evidence={
            "pending_order_id": pending.id, "exchange_order_id": pending.exchange_order_id,
            "condition_id": pending.order.condition_id, "outcome": pending.order.outcome,
            "market_closed": market_closed, "past_expiry": past_expiry,
            "close_time": close_time.isoformat(), "expires_at": expires_at.isoformat(),
            "created_at": created_at.isoformat(), "now": now.isoformat(), "age_seconds": age_seconds,
            "fill": _fill_to_dict(fill),
        },
    )
    return True


def _fill_to_dict(fill: FillResult) -> dict:
    return {
        "order_id": fill.order_id, "status": fill.status, "requested_shares": fill.requested_shares,
        "filled_shares": fill.filled_shares, "avg_fill_price": fill.avg_fill_price,
    }
