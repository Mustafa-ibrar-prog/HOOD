"""Ties client/strategy/risk/gateway/state together into one cycle —
analogous to src/orchestrator.py's run_trading_cycle(), run repeatedly
by scripts/run_polymarket_bot.py's loop rather than per-cycle by an
external scheduler, since nothing here needs an agent to relay data
(client.py calls the real API directly).

PRODUCTION STRATEGY (as of this round): a PREDICTIVE strategy -- a
real BTC direction model (btc_direction_model.py) estimates P(UP)/
P(DOWN) for the CURRENT 15-minute contract from live BTC market data
(btc_features.py), and the entry decision comes from that model's
EDGE over what Polymarket currently charges to buy each side
(btc_model_entry_signal.py), never from which side Polymarket itself
currently favors. THIS REPLACES THE OLD FAVORED-SIDE STRATEGY ENTIRELY:
simple_entry_signal.py (direction = whichever side has the higher
Polymarket-implied probability), its minimum-edge filter
(simple_min_entry_edge -- a gap between the two Polymarket sides, not
a model's edge over the market) and its persistence filter
(simple_entry_persistence_required) are all DELETED, not merely
unused -- that module, its settings, and MarketHistory's old
persistence-tracking fields no longer exist in this codebase. There is
exactly ONE authoritative production entry decision now; see
btc_model_entry_signal.assess_model_entry()'s own docstring for its
exact formula and hard gates (untrained model, insufficient feature
data, missing book data all fail closed to NO_TRADE).

take_profit.py (exit: a configurable +10% take-profit AND a
configurable -20% stop-loss, both settings-driven, never hard-coded)
is UNCHANGED by this round -- position management is infrastructure,
not strategy, and stays exactly as it was. Coinbase BTC intelligence
(btc_entry_signal.py/btc_intelligence.py -- the EARLIER, qualitative
evidence-cascade approach, never probabilistic and already dormant
since before this round), the settlement-reference divergence check
(reference_divergence.py), confidence scoring (entry_confidence.py),
and historical self-learning (trade_learning.py's adjustment
machinery) remain NOT CALLED from run_cycle() -- they stay in the
codebase, with their own tests, in case wanted again later, but none
of them influences a live entry or exit decision. trade_learning.
CompletedTradeStore is still used, but only for its RECORD-KEEPING
role (record_completed_trade at settlement/exit) -- never for its
historical-adjustment role, which this module never calls.

check_and_execute_dynamic_exits() (exit_manager.py, BTC-evidence-
based) and trailing_stop.check_and_execute_trailing_stops() (the
earlier +20% trailing-stop exit) are likewise no longer called --
take_profit.check_and_execute_take_profits() is the only exit logic
that runs, so a position opened by this strategy is never
independently sold by either earlier exit system too. Every open
position is actively managed: it exits automatically the instant
either the take-profit target or the stop-loss floor is reached,
never merely held to resolution by default."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.polymarket import reconciliation
from src.polymarket.btc_direction_model import BtcDirectionModel
from src.polymarket.btc_features import compute_btc_features, resolve_price_to_beat
from src.polymarket.btc_market_data import BtcPriceHistoryStore, compute_feed_status
from src.polymarket.btc_model_entry_signal import assess_model_entry
from src.polymarket.client import NoActiveMarketError, PolymarketClient
from src.polymarket.entry_guard import check_entry_retry_guard
from src.polymarket.gateway import ExecutionGateway
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import BinaryMarket, OrderRequest
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import PolymarketPositionStore
from src.polymarket.risk import PolymarketRiskManager
from src.polymarket.settings import PolymarketSettings
from src.polymarket.single_book import is_single_book_market, to_no_perspective
from src.polymarket.state import DailyPnlStateStore
from src.polymarket.strategy import BtcMomentumStrategy
from src.polymarket.take_profit import check_and_execute_take_profits
from src.polymarket.trade_learning import CompletedTradeStore, STRATEGY_ID_BTC_PREDICTIVE_MODEL, record_completed_trade


@dataclass
class CycleReport:
    ran: bool
    skipped_reason: str | None = None
    market_question: str | None = None
    entered: bool = False
    settled_count: int = 0
    reconciled_count: int = 0
    exits_submitted: int = 0


@dataclass
class MarketHistory:
    """In-memory only, by design: a restart losing a few minutes of this
    particular market's own price history is an acceptable cost, far
    cheaper than adding another file-backed store for data that's only
    ever useful within one 15-minute window. Harmless bookkeeping --
    nothing in the production path reads history.mids any more (the
    predictive model reads btc_price_store's own BTC bar history
    instead, keyed by real timestamp, not by this per-market list) --
    kept purely in case a future strategy wants a per-market Polymarket
    mid-price trail again. An EARLIER round's entry-persistence tracker
    lived here too; it was deleted along with simple_entry_signal.py
    (see engine.py's module docstring) rather than kept as dead code."""

    condition_id: str | None = None
    mids: list[float] = field(default_factory=list)

    def observe(self, market: BinaryMarket) -> list[float]:
        if market.condition_id != self.condition_id:
            self.condition_id = market.condition_id
            self.mids = []
        if market.yes_mid is not None:
            self.mids.append(market.yes_mid)
        return list(self.mids)


def settle_resolved_positions(
    *, client: PolymarketClient, position_store: PolymarketPositionStore,
    state_store: DailyPnlStateStore, decision_logger: PolymarketDecisionLogger, now: datetime | None = None,
    trade_store: CompletedTradeStore | None = None,
) -> int:
    now = now or datetime.now(timezone.utc)
    settled = 0
    for position in position_store.load():
        close_time = position.close_time if position.close_time.tzinfo else position.close_time.replace(tzinfo=timezone.utc)
        if now < close_time:
            continue
        winner = client.get_resolution(position.condition_id)
        if winner is None:
            continue  # resolved-by-clock but not yet reflected by the API; try again next cycle

        won = winner == position.outcome
        cost = position.filled_size_usd  # actual cost paid, from the verified fill — not the requested size
        pnl = (position.filled_shares - cost) if won else -cost
        decision_logger.log_decision(
            kind="position_settled",
            reason=f"{position.outcome} on {position.condition_id} {'WON' if won else 'LOST'}: pnl=${pnl:.2f}",
            evidence={"position": position.to_dict(), "winner": winner, "pnl_usd": pnl},
        )
        state = state_store.load(today=now.date())
        state.realized_pnl_usd += pnl
        state.open_position_count = max(0, state.open_position_count - 1)
        state.last_exit_time = now.isoformat()
        state_store.save(state)
        # Resolution pays exactly $1/share if won, $0 if lost -- a real,
        # known exit price, never a guess (see TASK 2's "never fabricate").
        record_completed_trade(
            trade_store, position, exit_timestamp=now, exit_price=(1.0 if won else 0.0),
            exit_reason="SETTLEMENT", fees_usd=0.0, realized_pnl_usd=pnl,
        )
        position_store.remove(position.condition_id)
        settled += 1
    return settled


def run_cycle(
    *,
    settings: PolymarketSettings,
    client: PolymarketClient,
    strategy: BtcMomentumStrategy,  # kept for call-site/signature compatibility -- no longer consulted for the live entry decision, see below
    risk_manager: PolymarketRiskManager,
    gateway: ExecutionGateway,
    decision_logger: PolymarketDecisionLogger,
    state_store: DailyPnlStateStore,
    position_store: PolymarketPositionStore,
    pending_store: PolymarketPendingOrderStore,
    history: MarketHistory,
    btc_price_store: BtcPriceHistoryStore,
    model: BtcDirectionModel,
    btc_feed_source: str = "manual",
    trade_store: CompletedTradeStore | None = None,
    reference_price_store: BtcPriceHistoryStore | None = None,
    reference_feed_source: str = "manual",
    now: datetime | None = None,
) -> CycleReport:
    now = now or datetime.now(timezone.utc)

    # Task 5: sweep for any order placed in a PRIOR cycle (or a prior
    # process, if the bot restarted) that reached the exchange but was
    # never reconciled — e.g. confirm_and_place() was called from a
    # separate approval step after run_cycle() already returned. Always
    # runs first, before this cycle proposes anything new, so the
    # position/state ledger a new trade's risk checks read from (open
    # position count, daily P&L) reflects reality.
    #
    # A DELAYED entry (one that sat UNKNOWN across earlier cycles) can
    # resolve FILLED right here, creating a position THIS call -- a
    # live incident showed that position then getting immediately
    # exited by the dynamic-exit pass a few lines below, in the SAME
    # cycle, on fresh evidence that had nothing to do with the stale
    # thesis the entry was originally made under. An ordinary brand-new
    # entry never has this problem (it's created further down in this
    # same function, AFTER the dynamic-exit pass already ran) -- so the
    # fix is just giving a delayed adoption the same one-cycle grace an
    # ordinary entry already gets for free: snapshot which
    # client_order_ids exist before this sweep, diff against after, and
    # tell check_and_execute_dynamic_exits() to defer evaluating exactly
    # those (see exit_manager.py's module docstring, DELAYED-ENTRY GRACE).
    client_order_ids_before_reconcile = {p.client_order_id for p in position_store.load()}
    reconciled = reconciliation.reconcile_pending_orders(
        client=client, pending_store=pending_store, position_store=position_store,
        state_store=state_store, decision_logger=decision_logger, now=now,
    )
    newly_adopted_client_order_ids = frozenset(
        p.client_order_id for p in position_store.load() if p.client_order_id not in client_order_ids_before_reconcile
    )

    settled = settle_resolved_positions(
        client=client, position_store=position_store, state_store=state_store, decision_logger=decision_logger, now=now,
        trade_store=trade_store,
    )

    # Configurable take-profit/stop-loss exit check (see take_profit.py) -- the
    # ONLY production exit logic as of this round. Deliberately placed
    # AFTER settlement (a position that already resolved this cycle is
    # gone, nothing to exit-check) and BEFORE any new-entry evaluation
    # below, so the open-position count a new trade's risk checks read
    # reflects any exit that just closed. Never touches MAX_BET_SIZE/
    # MAX_DAILY_LOSS/MAX_SPREAD/ORDER_BOOK_LIQUIDITY/ENTRY_CUTOFF or
    # anything below this point.
    exits_submitted = check_and_execute_take_profits(
        client=client, settings=settings, gateway=gateway, position_store=position_store,
        pending_store=pending_store, state_store=state_store, decision_logger=decision_logger,
        trade_store=trade_store, skip_client_order_ids=newly_adopted_client_order_ids, now=now,
    )

    try:
        market = client.find_active_btc_market(now=now)
    except NoActiveMarketError as exc:
        decision_logger.log_decision(kind="no_trade", reason=str(exc))
        return CycleReport(
            ran=True, skipped_reason=str(exc), settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    # history.observe() still runs every cycle -- harmless bookkeeping,
    # kept for whatever future use (nothing in the production path
    # reads history.mids any more -- see module docstring).
    history.observe(market)

    # The now-aware computation, NEVER BinaryMarket.seconds_to_close
    # (which reads real wall-clock time and would make this
    # non-deterministic under a test's fixed `now`) -- used for both
    # logging and the model's own time_remaining feature. There is no
    # "too early to evaluate" gate: the model is evaluated every cycle
    # across the FULL 15-minute market, not only its final minutes.
    close_time = market.close_time if market.close_time.tzinfo else market.close_time.replace(tzinfo=timezone.utc)
    seconds_remaining = (close_time - now).total_seconds()

    # --- FETCH THE REAL UP(YES)/DOWN(NO) ORDER BOOKS (see
    # single_book.py) -- UNCHANGED infrastructure from earlier rounds.
    # On a genuinely TWO-book venue (international Polymarket), YES's
    # and NO's own real, independent order books are both fetched. On
    # a SINGLE-book venue (Polymarket US -- detected structurally via
    # token_id_yes == token_id_no, never a venue name or setting),
    # there is only ONE real book to fetch: fetching "NO's own book" a
    # second time would return the exact same data under a different
    # name and misread it as a second, independent price (the
    # original pricing bug this fixes -- identical YES_ASK/NO_ASK
    # readings in the logs). single_book.to_no_perspective() derives
    # NO's own economically-correct view of that SAME one real book
    # instead -- never a second fetch.
    single_book_market = is_single_book_market(market)
    try:
        yes_order_book = client.get_order_book(market.token_id_yes)
        no_order_book = to_no_perspective(yes_order_book) if single_book_market else client.get_order_book(market.token_id_no)
    except Exception as exc:  # noqa: BLE001 - a book-fetch failure (rate limit or otherwise) must never crash the bot or be treated as tradeable
        decision_logger.log_decision(
            kind="no_trade",
            reason=(
                f"Could not fetch YES/NO order books on {market.condition_id} after retries: "
                f"{type(exc).__name__}: {exc} -- sitting this cycle out"
            ),
            evidence={"condition_id": market.condition_id, "error_type": type(exc).__name__, "error": str(exc)},
        )
        return CycleReport(
            ran=True, market_question=market.question, settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    # --- THE PREDICTIVE ENTRY DECISION (see btc_features.py/
    # btc_direction_model.py/btc_model_entry_signal.py's own
    # docstrings for the full formula and hard gates) -- the ONLY
    # production entry logic as of this round. price_to_beat is a
    # PROXY anchored to market.window_start (real metadata from the
    # event's own confirmed slug schedule), never Polymarket's own
    # order book and never hardcoded -- see btc_features.
    # resolve_price_to_beat()'s own docstring for exactly why.
    #
    # STALENESS: reuses the EXISTING compute_feed_status() gate
    # (btc_market_data.py, already proven under btc_intelligence.py/
    # btc_entry_signal.py) rather than a second, independently-written
    # check -- a feed that built real history and then went silent
    # (provider outage) must degrade to "no usable bars," never keep
    # feeding an increasingly-stale price into a confident-looking
    # prediction.
    btc_bars = btc_price_store.get_bars(interval_seconds=60, now=now)
    feed_status = compute_feed_status(btc_bars, max_bar_age_seconds=settings.btc_max_bar_age_seconds, source=btc_feed_source, now=now)
    fresh_bars = btc_bars if feed_status.status == "FRESH" else []
    price_to_beat = (
        resolve_price_to_beat(bars=fresh_bars, raw_samples=btc_price_store.load(), window_start=market.window_start)
        if market.window_start is not None else None
    )
    features = compute_btc_features(fresh_bars, at=now, price_to_beat=price_to_beat, close_time=close_time)
    prediction = model.predict(features)

    decision_logger.log_decision(
        kind="btc_model_prediction",
        reason=(
            f"BTC_PRICE={features.current_price} PRICE_TO_BEAT={features.price_to_beat} "
            f"DISTANCE_TO_BEAT={features.distance_from_price_to_beat} TIME_REMAINING={seconds_remaining:.0f} "
            f"MODEL_UP_PROBABILITY={prediction.predicted_up_probability:.4f} "
            f"MODEL_DOWN_PROBABILITY={prediction.predicted_down_probability:.4f} "
            f"MODEL_IS_TRAINED={prediction.is_trained} BAR_COUNT={features.bar_count} "
            f"BTC_FEED_STATUS={feed_status.status}"
        ),
        evidence={
            "condition_id": market.condition_id, **features.to_log_fields(), **prediction.to_log_fields(),
            "has_minimum_feature_data": features.has_minimum_data, "bar_count": features.bar_count,
            "btc_feed_status": feed_status.status, "btc_feed_source": feed_status.source,
            "btc_bar_age_seconds": feed_status.bar_age_seconds,
        },
    )

    signal = assess_model_entry(
        prediction=prediction, up_order_book=yes_order_book, down_order_book=no_order_book,
        has_minimum_feature_data=features.has_minimum_data, min_model_edge=settings.model_min_edge,
        fee_pct=settings.model_fee_pct, slippage_pct=settings.model_slippage_pct,
    )
    decision_logger.log_decision(
        kind="btc_model_entry_signal",
        reason=(
            f"MARKET_UP_PROBABILITY={signal.market_up_probability} MARKET_DOWN_PROBABILITY={signal.market_down_probability} "
            f"UP_EDGE={signal.up_edge} DOWN_EDGE={signal.down_edge} SELECTED_OUTCOME={signal.outcome} "
            f"EXECUTABLE_ENTRY_PRICE={signal.executable_entry_price} DECISION={signal.decision} REASON={signal.reason}"
        ),
        evidence={"condition_id": market.condition_id, "single_book_market": single_book_market, **signal.to_log_fields()},
    )

    if signal.outcome is None:
        decision_logger.log_decision(
            kind="no_trade", reason=signal.reason,
            evidence={
                "question": market.question, "rejection_reason": "no_model_edge",
                "remaining_seconds": seconds_remaining, **signal.to_log_fields(),
            },
        )
        return CycleReport(
            ran=True, market_question=market.question, settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    outcome = signal.outcome
    token_id = market.token_id_for(outcome)
    # The SAME order book already fetched above for this outcome --
    # never re-fetched, never inferred from the other side. best_ask is
    # guaranteed not-None here: assess_model_entry only ever returns a
    # non-None outcome when that side's own real ask was available and
    # its net edge cleared the configured minimum.
    order_book = yes_order_book if outcome == "YES" else no_order_book

    # Hard ceiling the exchange will not cross, anchored to the REAL
    # best ask plus a small configured slippage allowance. Clamped
    # below 1.0 — OrderRequest requires max_price < 1.0. Keeps the
    # existing aggressive LIMIT + FOK execution model — never an
    # unrestricted market order.
    max_price = round(min(order_book.best_ask * (1 + settings.max_price_slippage_pct), 0.99), 4)
    size_usd = settings.simple_entry_size_usd  # fixed $20 (minimum == maximum), validated at load time

    state = state_store.load(today=now.date())
    decision = risk_manager.evaluate_new_trade(
        size_usd=size_usd, market=market, state=state, order_book=order_book, side="BUY", max_price=max_price, now=now,
    )
    if not decision.allowed:
        decision_logger.log_risk_block(decision, context="new_trade")
        return CycleReport(
            ran=True, market_question=market.question, settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    # Idempotency/retry guard (see entry_guard.py) — unchanged: a live
    # incident showed auto-execute repeatedly resubmitting a live BUY
    # for the exact same market/outcome every cycle after an unknown/
    # rejected result. Never touches reconciliation's own unknown-fill
    # handling — it only decides whether a NEW submission may happen
    # yet for this exact (condition_id, outcome).
    retry_decision = check_entry_retry_guard(
        pending_store, position_store, condition_id=market.condition_id, outcome=outcome,
        candidate_max_price=max_price, cooldown_seconds=settings.entry_retry_cooldown_seconds,
        min_price_change=settings.entry_retry_min_price_change, now=now,
    )
    if retry_decision.blocked:
        decision_logger.log_decision(
            kind="entry_retry_blocked", reason=retry_decision.reason,
            evidence={
                "condition_id": market.condition_id, "outcome": outcome,
                "candidate_max_price": max_price, "blocking_pending_order_id": retry_decision.blocking_pending_order_id,
            },
        )
        return CycleReport(
            ran=True, market_question=market.question, settled_count=settled, reconciled_count=reconciled,
            exits_submitted=exits_submitted,
        )

    entry_liquidity_usd = order_book.executable_liquidity_usd(side="BUY", max_price=max_price)
    decision_logger.log_decision(
        kind="entry_allowed",
        reason=(
            f"SELECTED_OUTCOME={outcome} MODEL_UP_PROBABILITY={prediction.predicted_up_probability:.4f} "
            f"MODEL_DOWN_PROBABILITY={prediction.predicted_down_probability:.4f} "
            f"UP_EDGE={signal.up_edge} DOWN_EDGE={signal.down_edge} "
            f"EXECUTABLE_ENTRY_PRICE={signal.executable_entry_price} SIZE=${size_usd:.2f} "
            f"REMAINING_SECONDS={seconds_remaining:.0f} ENTRY_DECISION=ALLOW"
        ),
        evidence={
            "condition_id": market.condition_id, "selected_outcome": outcome,
            **prediction.to_log_fields(), **signal.to_log_fields(),
            "actual_allowed_size_usd": size_usd, "remaining_seconds": seconds_remaining,
            "entry_price": order_book.best_ask, "spread": market.yes_spread_pct, "liquidity": entry_liquidity_usd,
            "decision": "ALLOW",
        },
    )

    # Snapshot of exactly what this cycle's own predictive pipeline
    # computed -- attached to the resulting OpenPosition (see
    # positions.py) so trade_learning.py's RECORD-KEEPING (never its
    # historical-adjustment machinery, which this module never calls)
    # can still journal this decision, whatever is actually available.
    entry_context = {
        "strategy_id": STRATEGY_ID_BTC_PREDICTIVE_MODEL,
        "market_question": market.question,
        "model_up_probability_at_entry": prediction.predicted_up_probability,
        "model_down_probability_at_entry": prediction.predicted_down_probability,
        "model_version_at_entry": prediction.model_version,
        "model_data_source_at_entry": prediction.data_source,
        "btc_price_at_entry": features.current_price,
        "price_to_beat_at_entry": features.price_to_beat,
        "market_up_probability_at_entry": signal.market_up_probability,
        "market_down_probability_at_entry": signal.market_down_probability,
        "up_edge_at_entry": signal.up_edge,
        "down_edge_at_entry": signal.down_edge,
        "executable_entry_price_at_entry": signal.executable_entry_price,
        "polymarket_yes_bid": market.yes_bid,
        "polymarket_yes_ask": market.yes_ask,
        "entry_spread": market.yes_spread_pct,
        "entry_liquidity_usd": entry_liquidity_usd,
        "seconds_remaining_at_entry": seconds_remaining,
    }

    order = OrderRequest(
        condition_id=market.condition_id, token_id=token_id, outcome=outcome, side="BUY",
        size_usd=size_usd, max_price=max_price, close_time=market.close_time,
        reason=(
            f"btc_model_entry: model P({outcome})={prediction.predicted_up_probability if outcome == 'YES' else prediction.predicted_down_probability:.4f} "
            f"net edge {signal.up_edge if outcome == 'YES' else signal.down_edge:.4f}"
        ),
        order_type=settings.default_order_type, single_book_market=single_book_market,
    )
    result = gateway.submit_order(order)

    entered = False
    if result.status == "simulated_fill":
        # Paper mode: gateway.py already built the synthetic FillResult
        # directly (nothing to reconcile for a simulation — see
        # gateway.py's docstring), but it must still become a position
        # through the exact same idempotent path reconciliation.py uses
        # for real fills, never a second, parallel way to create one.
        assert result.fill_result is not None
        position = reconciliation.record_fill(
            result.fill_result, order, result.fill_result.order_id,
            position_store=position_store, state_store=state_store, decision_logger=decision_logger, now=now,
            entry_context=entry_context,
        )
        entered = position is not None
    elif result.status == "submitted":
        # live_auto_execute=True: the order already reached the exchange
        # this cycle. Reconcile it immediately rather than waiting for
        # the next cycle's sweep, so this cycle's own report reflects
        # what actually happened, not just what was submitted.
        pending_order_id = result.extra.get("pending_order_id") if result.extra else None
        pending = pending_store.get(pending_order_id) if pending_order_id else None
        if pending is not None:
            fill = reconciliation.reconcile_order(
                pending, client=client, pending_store=pending_store, position_store=position_store,
                state_store=state_store, decision_logger=decision_logger, now=now,
                entry_context=entry_context,
            )
            entered = bool(fill and fill.is_fill)
            reconciled += 1
    # result.status == "awaiting_approval": nothing to reconcile yet — a
    # separate confirm_and_place() call (or a later
    # reconcile_pending_orders() sweep, including after a restart) picks
    # this up once a human approves it and it actually reaches the
    # exchange. result.status == "rejected"/"failed": gateway.py already
    # marked the pending order fill_reconciled=True (nothing to
    # reconcile — the exchange never accepted it, or it never reached
    # the exchange at all).

    return CycleReport(
        ran=True, market_question=market.question, entered=entered,
        settled_count=settled, reconciled_count=reconciled, exits_submitted=exits_submitted,
    )
