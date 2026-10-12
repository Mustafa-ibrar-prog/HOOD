"""Evidence-gated exit for an open Polymarket US position — the first
EARLY-exit path in this codebase alongside hold-to-resolution
settlement (engine.settle_resolved_positions), which remains the
fallback whenever a position's thesis never weakens AND its soft
profit target is never reached before its market closes. Nothing here
alters settlement, risk.py's entry checks, max_bet/max_daily_loss/
max_spread/liquidity thresholds, entry_cutoff, or the existing BUY
path in any way.

EXPECTED-VALUE REDESIGN (v2): P&L does NOT independently trigger an
exit. The old version gated the decision on gross_pnl_pct (profitable
+ weakening -> exit; target reached -> exit unless strengthening); a
position sitting exactly at -50% and one sitting at +50% could reach
opposite conclusions purely because of that gate, even when the real
BTC evidence was identical. That is backwards: a losing position whose
underlying evidence is still genuinely strong should be HELD (the loss
is already priced in and the edge hasn't gone away), and a profitable
position whose evidence has materially deteriorated should be EXITED
(the edge is gone; the current gain is beside the point).

evaluate_dynamic_exit() now decides purely from compute_edge_assessment()
(below), which combines TWO evidence sources but deliberately does
NOT blend them into one undifferentiated score:

  - BTC momentum (RSI, MACD histogram, EMA fast/slow, higher-highs/
    lower-highs structure, breakout continuation, failed breakout,
    reversal) stays the AUTHORITATIVE, continuous signal: btc_points
    is evaluate_momentum's own weakening_score - strengthening_score
    (negated), reusing its exact, already-calibrated per-condition
    point weights and its "a single soft signal is never enough"
    materiality filter (the WEAKENING_THRESHOLD/REVERSING_THRESHOLD a
    MomentumState is already built from). An earlier version of this
    redesign instead re-derived a signal-by-signal direction straight
    from each raw indicator (e.g. "RSI above or below 50") and let
    every signal vote equally regardless of whether evaluate_momentum
    itself considered it material — that reintroduced exactly the
    single-weak-signal false-exit problem this module exists to
    prevent (an RSI reading of 49 is not "the thesis has reversed"),
    caught by this module's own replay tests
    (tests/test_polymarket_dynamic_exit_replay.py). So the BTC side
    reuses evaluate_momentum's verdict directly rather than re-scoring
    its inputs from scratch.
  - Polymarket's own order-book microstructure (imbalance, spread,
    price momentum, trade flow — see
    btc_intelligence.assess_polymarket_microstructure) is used as
    CORROBORATION/VETO on an already-material BTC read, never as an
    independent trigger — exactly the role btc_intelligence.py's own
    module docstring already assigns it ("BTC evidence... stays
    authoritative; Polymarket's own odds are a DERIVATIVE of that
    thesis... not treated as an independent vote on it"); this
    redesign is what finally makes that documented intent actually
    affect the exit decision, rather than only being logged.

The cascade, in order:
  1. INSUFFICIENT_DATA (not enough real BTC evidence fed in yet, or a
     stale/dead feed — see btc_market_data.py) -> HOLD. Never guessed.
     This is a hard safety rule, independent of the edge score below.
  2. Otherwise, compute the EdgeAssessment. EXIT only when BTC
     evidence has materially turned against the thesis (btc_points
     negative, state is WEAKENING/REVERSING, fired-signal count
     clears config.min_weakening_signals_for_exit — the exact
     mechanism the pre-v2 cascade already used, just no longer gated
     by P&L/target) AND Polymarket's order-book flow does not clearly
     contradict that read. Otherwise -> HOLD — including the
     ambiguous case (BTC evidence itself net favorable or merely
     STABLE), which deliberately defaults to holding rather than
     guessing a direction.
  3. gross_pnl_pct, target_price, and seconds remaining are still
     computed and carried on ExitDecision/logged — CONTEXT for a human
     or LLM reviewing the decision, never a branch condition.
compute_target_price() itself is unchanged.

TWO DIFFERENT STEPS, NOT A CONTRADICTION — decision vs. recording:
  - WHETHER to exit now folds in the GROSS move (profit_target_pct
    against avg_fill_price) and BTC evidence, checked against REAL,
    currently-executable BID liquidity — never the ask or the
    midpoint, since this system can only SELL into a resting bid, not
    cross its own spread. The SELL order, when one is submitted, always
    prices at the REAL current best bid (not a fixed target) — we are
    reacting to current evidence/price, not waiting for a specific
    better number.
  - the REALIZED P&L this module records once an exit actually fills
    (record_exit_fill) is always NET of both entry and exit fees
    whenever the exchange reports them (FillResult.fee_usd) — never an
    assumption that a gross price move alone made the trade profitable.

IDEMPOTENCY — the same two-independent-guards philosophy
reconciliation.py already established for entries, applied to exits:
  1. OpenPosition.exit_pending_order_id is the PRIMARY guard: set the
     instant an exit order is submitted (submit_dynamic_exit), checked
     before any new exit is ever proposed
     (evaluate_dynamic_exit/check_and_execute_dynamic_exits). Persisted
     on disk — restart-safe by construction, not an in-memory flag.
  2. PolymarketPendingOrderStore's own per-id semantics are the
     secondary guard on the live side (same store entries already use).
  An exit fill status of "unknown" leaves exit_pending_order_id SET —
  never cleared, never assumed filled — so a later sweep
  (reconcile_exit_fill) retries the SAME lookup instead of ever
  proposing a second, duplicate exit for the same position.

RETRY/COOLDOWN GUARD (see exit_retry_guard.py): the idempotency guard
above only ever blocks while an exit is IN FLIGHT or of UNKNOWN
status. A live incident showed what happens once an exit instead
resolves to an authoritative, no-fill TERMINAL outcome
(expired/rejected/failed): exit_pending_order_id was cleared
immediately, with no cooldown and no check that the evidence had
changed, so the very next cycle just resubmitted another exit on the
SAME still-exit-worthy evidence — observed live as
"EXIT -> UNKNOWN -> EXPIRED -> EXIT -> UNKNOWN -> EXPIRED -> EXIT" on
loop, never actually reducing the position's exposure.
evaluate_dynamic_exit() now consults check_exit_retry_guard() (see
that module for the full mechanism) once it has already decided
current evidence is exit-worthy on its own — a RATE LIMIT on retrying
a recently-failed attempt, requiring either a cooldown or materially
changed evidence, never a reason by itself to hold a position whose
evidence still supports exiting.

DELAYED-ENTRY GRACE (see check_and_execute_dynamic_exits'
`skip_client_order_ids`): an ordinary brand-new entry structurally
never gets evaluated for a dynamic exit on the SAME cycle it opens —
engine.run_cycle() calls check_and_execute_dynamic_exits() BEFORE the
entry path even runs, so a position created this cycle by a fresh BUY
isn't in position_store yet when the exit pass reads it. A DELAYED
entry breaks that symmetry: an order submitted cycles earlier that sat
UNKNOWN finally reconciles FILLED via reconcile_pending_orders()'s
sweep, which runs at the very TOP of run_cycle() — BEFORE the exit
pass — so the newly-adopted position WAS already visible to this same
cycle's dynamic-exit check, with zero cycles of grace. A live incident
showed exactly this: an old, stale-thesis entry filled, and the SAME
cycle's fresh evidence immediately exited it, net of fees, for no
benefit. `skip_client_order_ids` restores the same one-cycle grace
delayed adoptions were missing — see engine.py's run_cycle(), which
computes it as "whatever reconcile_pending_orders() just created this
call" and passes it straight through. It is a one-cycle deferral only:
next cycle, with nothing special persisted and no exception carved
out, the position is evaluated completely normally — a genuinely bad
newly-opened position is still caught exactly one poll interval later,
never permanently shielded.

That one-cycle grace fixed the SAME-cycle case, but a live incident
showed a second, independent gap it does not touch: a pending entry
order can sit unresolved for far longer than one cycle — long enough
that its OWN market closes before the exchange ever gives an
authoritative fill answer. reconciliation.py's STALE-ENTRY SAFETY NET
(see its own module docstring) still adopts a genuine late fill like
this (a real fill is never pretended away) but flags it distinctly as
stale. The MARKET-CLOSED SKIP below is this module's own half of that
same fix: a position whose close_time has already passed — stale-
adopted or not, the check is general — is skipped entirely here,
deferring 100% to settle_resolved_positions() (already run earlier in
run_cycle(), before this function). Attempting a fresh SELL into a
market that is no longer open for trading is never correct, regardless
of current BTC evidence; this is a position-eligibility PRE-CHECK, the
same category as the exit_pending_order_id/no-live-bid checks already
in evaluate_dynamic_exit() — it never alters the evidence cascade
itself, and an exit ALREADY in flight when the market closes is still
reconciled (never abandoned) before this skip is even reached.

MASTER SWITCH: settings.dynamic_exit_enabled (POLYMARKET_DYNAMIC_EXIT_ENABLED,
default False) — while False, check_and_execute_dynamic_exits() is a
complete no-op: it never even evaluates a position, in PAPER or LIVE
mode. The entire feature ships inert until explicitly turned on.

LIVE SUBMISSION, EMERGENCY STOP: an automatic exit that reaches the
exchange in live mode goes through the EXACT SAME
LivePolymarketGateway.confirm_and_place() -> _submit_pending() path
entries use, so it inherits that method's independent, pre-existing
emergency-stop check for free — there is no separate emergency-stop
check in this module, by design, so the two paths can never drift
apart. settings.auto_exit_enabled (default False) is a SEPARATE,
exit-specific switch, independent of settings.live_auto_execute (the
entry-only flag — left untouched, never enabled by this module): it
only ever decides whether a LIVE exit this cascade approved is
immediately confirmed and placed, or stops at awaiting_approval for a
human to confirm (scripts/confirm_pending_order.py and
scripts/confirm_polymarket_order.py already handle this generically,
regardless of the underlying order's side). PAPER mode is unaffected
by auto_exit_enabled either way — gateway.submit_order() already
returns a synthetic, immediate fill in paper mode regardless, exactly
like an entry, and (also exactly like an entry) is never blocked by
emergency stop — paper mode never touches real money or the real
order placer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from src.polymarket.btc_intelligence import BtcMarketAssessment, assess_btc_market, thesis_direction_for_outcome
from src.polymarket.exit_retry_guard import check_exit_retry_guard
from src.polymarket.gateway import ExecutionGateway, LivePolymarketGateway, LiveTradingDisabledError, PolymarketOrderPlacer
from src.polymarket.logger import PolymarketDecisionLogger
from src.polymarket.models import FillResult, OrderBookSnapshot, OrderRequest, OrderResult
from src.polymarket.pending import PolymarketPendingOrderStore
from src.polymarket.positions import OpenPosition, PolymarketPositionStore
from src.polymarket.settings import PolymarketSettings
from src.polymarket.state import DailyPnlStateStore
from src.polymarket.trade_learning import CompletedTradeStore, record_completed_trade
from src.strategy.evidence import MomentumState

# Same default as src/position_manager/evaluator.py's
# EvaluatorConfig.min_weakening_signals_for_exit — reused verbatim
# (not independently re-tuned) so a barely-WEAKENING read (few
# corroborating signals) doesn't trigger an early exit on a
# technicality, exactly like the proven options-side cascade.
DEFAULT_MIN_WEAKENING_SIGNALS_FOR_EXIT = 2


def compute_target_price(avg_fill_price: float, profit_target_pct: float) -> float:
    """The GROSS soft-target reference price for a LONG/YES position:
    avg_fill_price * (1 + profit_target_pct) — e.g. $0.36 * 1.20 ≈
    $0.432 with the default 0.20 target. Deliberately based on the
    position's own ACTUAL average fill price (never the requested
    order size or a suggested entry price) — see OpenPosition's
    docstring: avg_fill_price already is that verified figure.

    This is a REFERENCE point for evaluate_dynamic_exit()'s cascade,
    not a sell trigger by itself — see module docstring.

    Rounded to 4 decimal places, matching models.OrderBookSnapshot's
    own mid/spread_pct convention — precise enough to compare against
    a real bid price, far from the floating-point noise of the raw
    multiplication (0.36 * 1.2 == 0.43200000000000005 in IEEE 754)."""
    return round(avg_fill_price * (1.0 + profit_target_pct), 4)


@dataclass(frozen=True)
class DynamicExitConfig:
    """Tunable thresholds for the evidence-gated exit cascade —
    modeled directly on EvaluatorConfig (src/position_manager/
    evaluator.py).

    min_weakening_signals_for_exit: the minimum number of
    evaluate_momentum's own NAMED fired conditions (its
    MomentumAssessment.signals — "trend_flip", "reversal_signal", and
    so on) required before evaluate_dynamic_exit will treat a
    WEAKENING/REVERSING BTC read as material enough to exit on. Same
    name/default/value/mechanism as the pre-v2 cascade (and as the
    options side's own EvaluatorConfig.min_weakening_signals_for_exit)
    — reused verbatim, not re-tuned; only the P&L/profit-target gating
    around it was removed."""

    min_weakening_signals_for_exit: int = DEFAULT_MIN_WEAKENING_SIGNALS_FOR_EXIT


@dataclass(frozen=True)
class EdgeAssessment:
    """The continuous read of whether the latest real evidence —
    BTC momentum AND Polymarket microstructure — currently supports or
    opposes the position's own thesis direction
    (thesis_direction_for_outcome(position.outcome)).

    This is the expected-value core of v2's exit decision: it answers
    "does the evidence still favor this position winning," entirely
    independent of entry price, current P&L, or any soft profit
    target — see evaluate_dynamic_exit and the module docstring.

    Two evidence sources, kept deliberately SEPARATE rather than
    blended into one score, because they are not comparable units and
    not equally reliable:

    btc_points = -btc_assessment.evidence_score (evaluate_momentum's
    own weakening_score - strengthening_score, negated so positive
    means net SUPPORTING and negative means net OPPOSING). This reuses
    evaluate_momentum's exact, already-calibrated per-condition point
    weights (trend_flip=2, reversal_signal=3, momentum_exhaustion=2,
    ...) and its "a single soft signal is never enough" materiality
    filter (WEAKENING_THRESHOLD/REVERSING_THRESHOLD) — nothing here
    re-derives or re-weights that scoring. btc_fired_signal_count is
    evaluate_momentum's own count of NAMED fired conditions (its
    MomentumAssessment.signals), the SAME quantity the pre-v2 cascade
    gated on.

    microstructure_net/_supporting/_opposing are a confidence-weighted
    signed tally of ONLY the Polymarket order-book signals
    (btc_intelligence.assess_polymarket_microstructure's imbalance/
    spread/price-momentum/trade-flow — identified by their
    "polymarket_" source prefix), using their own already-assigned
    confidence (0.3-0.6) as-is. BTC evidence is deliberately
    authoritative for DIRECTION (see btc_intelligence.py's own module
    docstring: "Polymarket's own odds are a DERIVATIVE of that
    thesis... not treated as an independent vote on it") — raw
    per-indicator BTC signals (a bare rsi>50 crossing, say) are noisy
    enough on their own that letting them vote directly, signal-for-
    signal, alongside Polymarket's order-book reads produced exactly
    the kind of single-weak-signal false exit this redesign is
    supposed to prevent (caught by this module's own replay tests).
    Microstructure's role here is corroboration/veto on an
    already-material BTC read (see evaluate_dynamic_exit), not an
    independent trigger — the real use case this was built for is
    noticing persistent order-book buying pressure that contradicts a
    marginal BTC weakening read, not manufacturing an exit from thin
    order-book noise alone."""

    thesis_direction: str
    btc_points: float
    btc_fired_signal_count: int
    microstructure_net: float
    microstructure_supporting: tuple[str, ...]
    microstructure_opposing: tuple[str, ...]


def compute_edge_assessment(btc_assessment: BtcMarketAssessment, *, thesis_direction: str) -> EdgeAssessment:
    """See EdgeAssessment's own docstring for the full reasoning behind
    keeping BTC-momentum and Polymarket-microstructure evidence
    separate rather than blended into one score."""
    opposite = "bearish" if thesis_direction == "bullish" else "bullish"
    micro_net = 0.0
    micro_supporting: list[str] = []
    micro_opposing: list[str] = []
    for signal in btc_assessment.signals:
        if not signal.source.startswith("polymarket_"):
            continue
        if signal.direction == thesis_direction:
            micro_net += signal.confidence
            micro_supporting.append(signal.source)
        elif signal.direction == opposite:
            micro_net -= signal.confidence
            micro_opposing.append(signal.source)
        # "neutral" (e.g. the bid/ask spread signal) contributes to
        # neither tally -- an uninformative reading is never evidence
        # either way.
    return EdgeAssessment(
        thesis_direction=thesis_direction,
        btc_points=-btc_assessment.evidence_score,
        btc_fired_signal_count=len(btc_assessment.btc_assessment.signals),
        microstructure_net=round(micro_net, 6),
        microstructure_supporting=tuple(micro_supporting),
        microstructure_opposing=tuple(micro_opposing),
    )


@dataclass(frozen=True)
class ExitDecision:
    """The full, inspectable answer to "should this position exit right
    now," independent of whether anything is actually submitted —
    evaluate_dynamic_exit() is pure and side-effect free; only
    submit_dynamic_exit() (called separately, only when `eligible`)
    ever touches the network or the position ledger.

    `btc_assessment` is always attached (even when not eligible) so
    the full evidence trail — every Signal, source/timestamp/value/
    direction/confidence — is available to whatever explains the
    decision (see btc_intelligence.py).

    `gross_pnl_pct` and `target_price` are CONTEXT ONLY in v2 — see
    the module docstring's EXPECTED-VALUE REDESIGN section. They are
    always computed and logged (useful for a human or LLM reviewing
    the decision, and for scripts that print them), but
    evaluate_dynamic_exit never branches on either.

    `edge_btc_points` is EdgeAssessment.btc_points at the time of this
    decision — None whenever it was never computed (the
    exit_pending_order_id/no-bid/INSUFFICIENT_DATA guards all return
    before it exists). submit_dynamic_exit() persists it on the
    position the instant a new exit is submitted, so exit_retry_guard.py
    has it available later to judge whether evidence has materially
    changed since a recently-failed attempt — see that module."""

    position: OpenPosition
    eligible: bool
    reason: str
    target_price: float  # context only -- the soft profit-target reference price (compute_target_price)
    best_bid: float | None  # the REAL live best bid -- also the price a submitted exit order would use
    executable_shares_at_target: float
    gross_pnl_pct: float | None  # context only -- never a branch condition, see module docstring
    btc_assessment: BtcMarketAssessment | None
    edge_btc_points: float | None = None


def evaluate_dynamic_exit(
    position: OpenPosition,
    order_book: OrderBookSnapshot,
    btc_assessment: BtcMarketAssessment,
    *,
    profit_target_pct: float,
    config: DynamicExitConfig | None = None,
    exit_retry_cooldown_seconds: float = 0.0,
    exit_retry_min_evidence_change: float = 0.0,
    now: datetime | None = None,
) -> ExitDecision:
    """Pure decision logic — see module docstring's EXPECTED-VALUE
    REDESIGN section for the full reasoning. Checklist, in order:
      1. no exit already pending for this position (idempotency guard);
      2. a real live bid must exist at all (can't sell into nothing);
      3. INSUFFICIENT_DATA BTC evidence -> HOLD, never guess (hard
         safety, independent of everything below);
      4. compute_edge_assessment() against the position's own thesis
         direction -- EXIT only when BTC evidence has MATERIALLY
         turned against the thesis (btc_points negative, state is
         WEAKENING/REVERSING, and the fired-signal count clears
         config.min_weakening_signals_for_exit -- the exact mechanism
         the pre-v2 cascade used, just no longer gated by P&L/target),
         AND Polymarket's own order-book microstructure does not
         clearly contradict that read; otherwise HOLD. gross_pnl_pct/
         target_price are computed for context/logging only and never
         participate in this decision;
      5. (only once exit is decided exit-worthy) check_exit_retry_guard
         (see exit_retry_guard.py) -- a RECENTLY-FAILED attempt (an
         authoritative, no-fill terminal outcome) on this exact
         position rate-limits an immediate retry unless the cooldown
         has elapsed or the evidence has materially changed. A
         position with no such prior failure is never affected by this
         step at all;
      6. (only once exit clears the retry guard too) enough REAL
         executable bid liquidity, AT OR ABOVE the current best bid,
         to sell the position's entire filled_shares.
    `exit_retry_cooldown_seconds`/`exit_retry_min_evidence_change`
    default to 0.0 (no rate-limiting at all) so existing callers that
    never pass them keep their original behavior exactly; engine.py's
    production call site passes settings.exit_retry_cooldown_seconds/
    settings.exit_retry_min_evidence_change explicitly.
    Any failure returns `eligible=False` with a human-readable reason;
    nothing here ever submits an order."""
    config = config or DynamicExitConfig()
    now = now or datetime.now(timezone.utc)
    target_price = compute_target_price(position.avg_fill_price, profit_target_pct)
    best_bid = order_book.best_bid

    if position.exit_pending_order_id is not None:
        return ExitDecision(
            position=position, eligible=False,
            reason=f"An exit order ({position.exit_pending_order_id}) is already pending for this position",
            target_price=target_price, best_bid=best_bid, executable_shares_at_target=0.0,
            gross_pnl_pct=None, btc_assessment=btc_assessment,
        )

    if best_bid is None:
        return ExitDecision(
            position=position, eligible=False, reason="No live bid available -- cannot sell",
            target_price=target_price, best_bid=None, executable_shares_at_target=0.0,
            gross_pnl_pct=None, btc_assessment=btc_assessment,
        )

    # CONTEXT ONLY from here on -- see EdgeAssessment/module docstring.
    # Never used in the branching below.
    gross_pnl_pct = (best_bid - position.avg_fill_price) / position.avg_fill_price
    state = btc_assessment.state

    def _decision(eligible: bool, reason: str, executable: float = 0.0, edge_btc_points: float | None = None) -> ExitDecision:
        return ExitDecision(
            position=position, eligible=eligible, reason=reason, target_price=target_price, best_bid=best_bid,
            executable_shares_at_target=executable, gross_pnl_pct=gross_pnl_pct, btc_assessment=btc_assessment,
            edge_btc_points=edge_btc_points,
        )

    # --- Hard safety: insufficient/stale BTC evidence -> HOLD, never guess -
    if state is MomentumState.INSUFFICIENT_DATA:
        return _decision(False, "Insufficient BTC market evidence this cycle -- holding rather than guessing")

    # --- Continuous evidence/expected-value edge ----------------------------
    thesis_direction = thesis_direction_for_outcome(position.outcome)
    edge = compute_edge_assessment(btc_assessment, thesis_direction=thesis_direction)

    btc_opposes_materially = (
        edge.btc_points < 0
        and state in (MomentumState.WEAKENING, MomentumState.REVERSING)
        and edge.btc_fired_signal_count >= config.min_weakening_signals_for_exit
    )
    microstructure_contradicts = (
        edge.microstructure_net > 0
        and len(edge.microstructure_supporting) > len(edge.microstructure_opposing)
    )
    exit_worthy = btc_opposes_materially and not microstructure_contradicts

    if not exit_worthy:
        if btc_opposes_materially:  # only reachable when microstructure vetoed it
            return _decision(
                False,
                f"BTC evidence opposes the thesis ({state.value.lower()}, btc_points={edge.btc_points:+.0f}) but "
                f"Polymarket order-book flow contradicts it (microstructure_net={edge.microstructure_net:+.2f}, "
                f"{', '.join(edge.microstructure_supporting)}); holding regardless of pnl={gross_pnl_pct:+.1%}",
                edge_btc_points=edge.btc_points,
            )
        return _decision(
            False,
            f"BTC evidence still favors or is neutral on the thesis ({state.value.lower()}, "
            f"btc_points={edge.btc_points:+.0f}); holding regardless of pnl={gross_pnl_pct:+.1%} -- "
            "P&L is context, not a trigger",
            edge_btc_points=edge.btc_points,
        )

    # --- Retry/cooldown guard (see exit_retry_guard.py) -- only reached
    # once evidence is ALREADY exit-worthy on its own; rate-limits a
    # resubmission after a recently-failed attempt, never a reason by
    # itself to hold a position whose evidence still supports exiting.
    retry_decision = check_exit_retry_guard(
        position, candidate_btc_points=edge.btc_points, cooldown_seconds=exit_retry_cooldown_seconds,
        min_evidence_change=exit_retry_min_evidence_change, now=now,
    )
    if retry_decision.blocked:
        return _decision(False, retry_decision.reason, edge_btc_points=edge.btc_points)

    exit_reason = (
        f"BTC evidence has materially turned against the thesis ({state.value.lower()}, "
        f"btc_points={edge.btc_points:+.0f}, {edge.btc_fired_signal_count} fired signal(s)); exiting now "
        f"regardless of pnl={gross_pnl_pct:+.1%}"
    )

    # --- Liquidity check against the REAL price the order would use --------
    available = order_book.executable_shares(side="SELL", min_price=best_bid)
    if available < position.filled_shares:
        return _decision(
            False,
            f"Insufficient executable bid liquidity at/above {best_bid}: "
            f"{available} available shares < {position.filled_shares} needed",
            edge_btc_points=edge.btc_points,
        )

    return ExitDecision(
        position=position, eligible=True, reason=exit_reason, target_price=target_price, best_bid=best_bid,
        executable_shares_at_target=available, gross_pnl_pct=gross_pnl_pct, btc_assessment=btc_assessment,
        edge_btc_points=edge.btc_points,
    )


def _fill_to_dict(fill: FillResult) -> dict:
    return {
        "order_id": fill.order_id, "status": fill.status, "requested_shares": fill.requested_shares,
        "filled_shares": fill.filled_shares, "avg_fill_price": fill.avg_fill_price, "fee_usd": fill.fee_usd,
    }


def record_exit_fill(
    fill: FillResult,
    position: OpenPosition,
    *,
    position_store: PolymarketPositionStore,
    state_store: DailyPnlStateStore,
    decision_logger: PolymarketDecisionLogger,
    now: datetime,
    trade_store: CompletedTradeStore | None = None,
    exit_btc_state: str | None = None,
    exit_btc_evidence_score: float | None = None,
) -> OpenPosition | None:
    """The ONLY place an exit FillResult mutates the position ledger —
    the exit-side counterpart to reconciliation.record_fill(). Always
    re-reads the CURRENT persisted position by client_order_id first
    (never trusts the possibly-stale `position` argument for anything
    but its identity key), so this is safe to call more than once for
    the same fill: a second call finds the position already
    gone/updated and no-ops.

    `trade_store`/`exit_btc_state`/`exit_btc_evidence_score` (see
    trade_learning.py, TASK 2): only used on a FULL close, where this
    is genuinely the end of this trade's lifecycle; None by default so
    every existing call site stays exactly as it was before TASK 2.

    Returns the updated (still-open, partially-closed) OpenPosition, or
    None if the position is now fully closed or there was nothing to
    do."""
    current = position_store.get(position.client_order_id)
    if current is None:
        return None  # already fully closed by an earlier call -- nothing to do

    if fill.status == "unknown":
        # NOT an authoritative determination -- requirement: "if exit
        # status is unknown, STOP and retry reconciliation later; never
        # assume an exit filled." exit_pending_order_id is left exactly
        # as it is, so a later sweep (reconcile_exit_fill) re-checks the
        # SAME exit rather than this position ever being offered a
        # second, duplicate one.
        decision_logger.log_decision(
            kind="exit_status_unknown",
            reason=f"Exit order {fill.order_id} for {current.condition_id}: status unknown, "
                   "position left unchanged, NOT reconciled -- re-checkable later",
            evidence={"position": current.to_dict(), "fill": _fill_to_dict(fill)},
        )
        return current

    if not fill.is_fill:
        # A genuine terminal non-fill (rejected/cancelled/expired), or a
        # resting state that should never actually happen for an
        # IOC/FOK exit -- authoritative and safe to clear: free to
        # retry a fresh exit, nothing about the position itself
        # changed. THIS is exit_retry_guard.py's own trigger: record
        # last_exit_attempt_at/last_exit_attempt_edge_points (from
        # whatever evidence this now-failed attempt was submitted
        # under) so the NEXT proposed exit is rate-limited by cooldown/
        # evidence-change rather than resubmitted immediately and
        # unconditionally -- the exact live incident this closes
        # (EXIT -> UNKNOWN -> EXPIRED -> EXIT, repeating with zero
        # cooldown).
        cleared = replace(
            current, exit_pending_order_id=None, pending_exit_edge_points=None,
            last_exit_attempt_at=now, last_exit_attempt_edge_points=current.pending_exit_edge_points,
        )
        position_store.update(cleared)
        decision_logger.log_decision(
            kind="exit_not_filled",
            reason=f"Exit order {fill.order_id} for {current.condition_id}: {fill.status}, position unchanged",
            evidence={"position": current.to_dict(), "fill": _fill_to_dict(fill)},
        )
        return cleared

    # A real (full or partial) fill. Reconcile EXACTLY how much of the
    # position this exit closed -- never assume full (requirement:
    # "reconcile the partial fill correctly and leave only the
    # remaining quantity open").
    closed_shares = fill.filled_shares
    remaining_shares = max(0.0, round(current.filled_shares - closed_shares, 8))
    exit_fee = fill.fee_usd or 0.0
    entry_fee_for_closed = (
        current.entry_fee_usd * (closed_shares / current.filled_shares) if current.filled_shares else 0.0
    )
    # NET realized P&L on the closed slice only -- proceeds at the
    # ACTUAL average exit price, minus the matching slice of the
    # original entry cost, minus BOTH entry and exit fees whenever the
    # exchange actually reported them. Never inferred from the gross
    # 20% price move alone (requirement: "Do not call a trade
    # profitable merely because gross price increased 20%").
    proceeds = closed_shares * fill.avg_fill_price
    entry_cost_for_closed = closed_shares * current.avg_fill_price
    realized_pnl = proceeds - entry_cost_for_closed - entry_fee_for_closed - exit_fee

    state = state_store.load(today=now.date())
    state.realized_pnl_usd += realized_pnl
    fully_closed = remaining_shares <= 1e-6
    if fully_closed:
        state.open_position_count = max(0, state.open_position_count - 1)
        state.last_exit_time = now.isoformat()
    state_store.save(state)

    decision_logger.log_decision(
        kind="profit_target_exit_filled",
        reason=(
            f"{current.outcome} on {current.condition_id}: exit "
            f"{'FULLY' if fully_closed else 'PARTIALLY'} filled {closed_shares:.4f}/{current.filled_shares:.4f} "
            f"shares @ ${fill.avg_fill_price:.4f}, realized_pnl=${realized_pnl:.4f} "
            f"(entry_fee=${entry_fee_for_closed:.4f}, exit_fee=${exit_fee:.4f})"
        ),
        evidence={
            "position": current.to_dict(), "fill": _fill_to_dict(fill), "realized_pnl_usd": realized_pnl,
            "entry_fee_usd": entry_fee_for_closed, "exit_fee_usd": exit_fee,
        },
    )

    if fully_closed:
        record_completed_trade(
            trade_store, current, exit_timestamp=now, exit_price=fill.avg_fill_price,
            exit_reason="DYNAMIC_EXIT", fees_usd=entry_fee_for_closed + exit_fee, realized_pnl_usd=realized_pnl,
            exit_btc_state=exit_btc_state, exit_btc_evidence_score=exit_btc_evidence_score,
        )
        position_store.remove(current.condition_id)
        return None

    # A real fill (even partial) succeeded -- any retry-guard history
    # from an earlier failed attempt is no longer relevant; the next
    # exit decision for the remaining shares starts with a clean slate.
    updated = replace(
        current, filled_shares=remaining_shares, exit_pending_order_id=None, pending_exit_edge_points=None,
        last_exit_attempt_at=None, last_exit_attempt_edge_points=None,
        entry_fee_usd=max(0.0, current.entry_fee_usd - entry_fee_for_closed),
    )
    position_store.update(updated)
    return updated


def reconcile_exit_fill(
    position: OpenPosition,
    *,
    client: Any,
    pending_store: PolymarketPendingOrderStore,
    position_store: PolymarketPositionStore,
    state_store: DailyPnlStateStore,
    decision_logger: PolymarketDecisionLogger,
    now: datetime | None = None,
    trade_store: CompletedTradeStore | None = None,
) -> OpenPosition | None:
    """The restart-safety sweep for a position whose exit_pending_order_id
    is already set — the exit-side counterpart to
    reconciliation.reconcile_pending_orders(). Safe to call any number
    of times, including across a process restart: every check here is
    against persisted state, never in-memory flags.

    No-ops (returns `position` unchanged) when there is genuinely
    nothing new to learn yet: a paper-mode fill is always reconciled
    synchronously by submit_profit_target_exit() the moment it happens,
    so exit_pending_order_id should never outlive that single call for
    paper mode; reaching here with no matching PendingLiveOrder (or one
    that hasn't reached the exchange yet, still awaiting a human
    confirm_and_place()) means there's nothing more this sweep can
    learn right now."""
    now = now or datetime.now(timezone.utc)
    if position.exit_pending_order_id is None:
        return position

    pending = pending_store.get(position.exit_pending_order_id)
    if pending is None or pending.exchange_order_id is None:
        return position

    fill = client.get_fill_status(pending.exchange_order_id)
    return record_exit_fill(
        fill, position, position_store=position_store, state_store=state_store, decision_logger=decision_logger, now=now,
        trade_store=trade_store,
    )


def submit_dynamic_exit(
    decision: ExitDecision,
    *,
    client: Any,
    gateway: ExecutionGateway,
    position_store: PolymarketPositionStore,
    state_store: DailyPnlStateStore,
    decision_logger: PolymarketDecisionLogger,
    settings: PolymarketSettings,
    order_placer: PolymarketOrderPlacer | None = None,
    now: datetime | None = None,
    trade_store: CompletedTradeStore | None = None,
) -> OrderResult:
    """Submits the exit order for an ELIGIBLE decision, marks the
    position's exit_pending_order_id BEFORE anything else can observe
    it (the idempotency guard), and — for every outcome this call can
    fully resolve synchronously (a paper-mode simulated fill, or a
    live order that reached the exchange this same call) — reconciles
    it immediately, exactly mirroring how engine.run_cycle() already
    handles the symmetric cases on the entry side.

    Prices the SELL at `decision.best_bid` — the REAL live price that
    made this decision eligible — never the soft target_price: we are
    reacting to current evidence/price, not demanding a specific
    better number the book may not actually have.

    Caller (check_and_execute_dynamic_exits) must have already
    verified `decision.eligible`; this does not re-check eligibility
    itself."""
    position = decision.position
    now = now or datetime.now(timezone.utc)
    assert decision.best_bid is not None  # guaranteed by evaluate_dynamic_exit's own eligibility checks
    quantity = int(round(position.filled_shares))
    order = OrderRequest(
        condition_id=position.condition_id, token_id=position.token_id, outcome=position.outcome, side="SELL",
        size_usd=round(quantity * decision.best_bid, 2), max_price=decision.best_bid,
        close_time=position.close_time, reason="dynamic_exit", order_type=settings.default_order_type,
        quantity=quantity, closes_client_order_id=position.client_order_id,
    )
    result = gateway.submit_order(order)

    pending_order_id = (result.extra or {}).get("pending_order_id")
    if pending_order_id is None and result.fill_result is not None:
        pending_order_id = result.fill_result.order_id  # paper mode's synthetic id -- same idempotency role

    # pending_exit_edge_points travels WITH exit_pending_order_id (see
    # exit_retry_guard.py/positions.py): the evidence that justified
    # THIS attempt, stashed so a later cycle -- or a restart -- can
    # still judge "has the evidence materially changed" if this attempt
    # ends up failing with no fill.
    position_store.update(replace(
        position, exit_pending_order_id=pending_order_id, pending_exit_edge_points=decision.edge_btc_points,
    ))
    decision_logger.log_decision(
        kind="dynamic_exit_submitted",
        reason=f"{position.outcome} on {position.condition_id}: {decision.reason}",
        evidence={
            "position": position.to_dict(), "order": order.to_dict(), "result_status": result.status,
            "gross_pnl_pct": decision.gross_pnl_pct,
            "btc_state": decision.btc_assessment.state.value if decision.btc_assessment else None,
            "btc_evidence_score": decision.btc_assessment.evidence_score if decision.btc_assessment else None,
            "signals": [s.to_dict() for s in decision.btc_assessment.signals] if decision.btc_assessment else [],
        },
    )

    if (
        result.status == "awaiting_approval" and settings.is_live and settings.auto_exit_enabled
        and order_placer is not None and isinstance(gateway, LivePolymarketGateway)
    ):
        try:
            result = gateway.confirm_and_place(pending_order_id, order_placer, approved_by="system:auto_exit", now=now)
        except LiveTradingDisabledError as exc:
            # Emergency stop (or a live/confirmed flag flip) blocked
            # this exit before it ever reached the exchange. The
            # underlying PendingLiveOrder is now a terminal "failed"
            # with no exchange_order_id -- nothing to reconcile -- so
            # this position must NOT stay permanently exit-blocked:
            # clear the guard so a later cycle can re-propose a fresh
            # exit once the block lifts. "Emergency stop blocks
            # automatic exits," not "...forever." Deliberately does NOT
            # set last_exit_attempt_at/exit_retry_guard cooldown -- this
            # is an OPERATIONAL block, not an evidence-based failure;
            # the attempt never even reached the exchange, so there is
            # nothing here for exit_retry_guard.py's "has the evidence
            # changed since the last FAILED attempt" question to apply to.
            refreshed = position_store.get(position.client_order_id)
            if refreshed is not None:
                position_store.update(replace(refreshed, exit_pending_order_id=None, pending_exit_edge_points=None))
            decision_logger.log_decision(
                kind="exit_blocked",
                reason=f"Automatic exit for {position.condition_id} blocked before reaching the exchange: {exc}",
                evidence={"position": position.to_dict()},
            )
            return OrderResult(status="failed", request=order, error=str(exc))

    exit_btc_state = decision.btc_assessment.state.value if decision.btc_assessment else None
    exit_btc_evidence_score = decision.btc_assessment.evidence_score if decision.btc_assessment else None
    if result.status == "simulated_fill":
        assert result.fill_result is not None
        record_exit_fill(
            result.fill_result, position, position_store=position_store, state_store=state_store,
            decision_logger=decision_logger, now=now, trade_store=trade_store,
            exit_btc_state=exit_btc_state, exit_btc_evidence_score=exit_btc_evidence_score,
        )
    elif result.status == "submitted":
        exchange_order_id = (result.extra or {}).get("exchange_order_id")
        if exchange_order_id:
            fill = client.get_fill_status(exchange_order_id)
            record_exit_fill(
                fill, position, position_store=position_store, state_store=state_store,
                decision_logger=decision_logger, now=now, trade_store=trade_store,
                exit_btc_state=exit_btc_state, exit_btc_evidence_score=exit_btc_evidence_score,
            )
    elif result.status in ("rejected", "failed"):
        # Terminal, no-fill, no-position-change outcomes with nothing
        # to wait on -- a gateway-level rejection discovered
        # synchronously (never reached the exchange, or was refused on
        # the spot). This IS the authoritative-failure case
        # exit_retry_guard.py rate-limits: free exit_pending_order_id
        # so a later cycle CAN retry, but record last_exit_attempt_at/
        # last_exit_attempt_edge_points first so that retry is subject
        # to the cooldown/evidence-change guard, not immediate and
        # unconditional -- see this module's own docstring on the
        # repeating EXIT -> UNKNOWN -> EXPIRED -> EXIT incident this
        # closes.
        refreshed = position_store.get(position.client_order_id)
        if refreshed is not None and refreshed.exit_pending_order_id == pending_order_id:
            position_store.update(replace(
                refreshed, exit_pending_order_id=None, pending_exit_edge_points=None,
                last_exit_attempt_at=now, last_exit_attempt_edge_points=refreshed.pending_exit_edge_points,
            ))
    # result.status == "awaiting_approval": exit_pending_order_id stays
    # set -- a human confirm_and_place() call (scripts/confirm_pending_order.py
    # or confirm_polymarket_order.py, both already side-agnostic), or a
    # later reconcile_exit_fill() sweep once one happens, picks this up.
    # Never assumed filled.

    return result


def check_and_execute_dynamic_exits(
    *,
    client: Any,
    settings: PolymarketSettings,
    gateway: ExecutionGateway,
    position_store: PolymarketPositionStore,
    pending_store: PolymarketPendingOrderStore,
    state_store: DailyPnlStateStore,
    decision_logger: PolymarketDecisionLogger,
    btc_price_store: Any,
    history: Any = None,
    config: DynamicExitConfig | None = None,
    btc_feed_source: str = "manual",
    skip_client_order_ids: frozenset[str] = frozenset(),
    now: datetime | None = None,
    trade_store: CompletedTradeStore | None = None,
) -> int:
    """One per-cycle pass over every open position — intended to be
    called from engine.run_cycle() right after settle_resolved_positions()
    and before any new-entry evaluation, exactly like that function's
    own reconciliation sweep.

    MASTER SWITCH: returns 0 immediately, without evaluating or
    touching any position, whenever settings.dynamic_exit_enabled is
    False (the default) — see module docstring.

    For each open position, otherwise:
      1. a position with an exit already pending is swept via
         reconcile_exit_fill() (restart-safe; never proposes a second
         exit while one is in flight or of unknown status);
      2. otherwise, a FRESH order book is fetched (never a cached/stale
         snapshot) plus the real BTC bars fed so far
         (btc_price_store.get_bars) and this market's own recent
         mid-price history (`history`, if its tracked condition_id
         matches this position's — duck-typed as `.condition_id`/
         `.mids` to avoid importing engine.MarketHistory here and
         creating a circular import; untyped/None is also accepted and
         degrades to no Polymarket-momentum signal, never a crash);
      3. assess_btc_market() builds the one structured assessment —
         rejecting the fetched bars as evidence (forcing
         INSUFFICIENT_DATA) if the newest one is older than
         settings.btc_max_bar_age_seconds (a dead feed must never keep
         deciding from stale data — see btc_market_data.py's module
         docstring) — and evaluate_dynamic_exit() decides eligibility
         against it;
      4. an eligible position gets exactly one exit order submitted via
         submit_dynamic_exit().

    Every cycle, for every open position, logs BTC_FEED_SOURCE/
    BTC_LAST_BAR_TIME/BTC_BAR_AGE_SECONDS/BTC_FEED_STATUS/
    BTC_EVIDENCE_STATE regardless of what else happens — a dead feed
    must be visible in the decision log, not silent.

    `btc_feed_source` is a plain label (e.g. "coinbase") for that log
    line, set by whatever constructed the DirectBtcQuoteSource actually
    feeding btc_price_store (see scripts/run_polymarket_bot.py) —
    "manual" (the default) when only the interim feed_btc_quote.py
    bridge is in use.

    `skip_client_order_ids` (see module docstring's DELAYED-ENTRY GRACE
    section): positions adopted into the ledger THIS SAME call to
    engine.run_cycle() via a delayed reconcile_pending_orders() sweep
    (an old entry order that sat UNKNOWN across earlier cycles finally
    resolving FILLED) are skipped entirely this one cycle — logged as
    `exit_check_deferred` — so a stale, already-superseded entry
    decision is never immediately reversed by this same cycle's fresh
    evidence. Empty by default (no-op for any caller that doesn't pass
    it, including every direct test call site); engine.py's production
    call site computes it from what reconcile_pending_orders() just
    created.

    Returns the number of exit orders submitted this call (0 is the
    overwhelmingly common case: most cycles, no position exits)."""
    if not settings.dynamic_exit_enabled:
        return 0

    now = now or datetime.now(timezone.utc)
    order_placer = client if settings.is_live else None
    submitted = 0

    for snapshot in position_store.load():
        # Re-fetch by client_order_id rather than trust this loop's own
        # snapshot — an earlier iteration (or a concurrent process)
        # could have already mutated or closed it (requirement:
        # "verify the position still exists").
        current = position_store.get(snapshot.client_order_id)
        if current is None:
            continue

        if current.client_order_id in skip_client_order_ids:
            decision_logger.log_decision(
                kind="exit_check_deferred",
                reason=(
                    f"{current.outcome} on {current.condition_id}: position was just adopted via a "
                    "delayed entry-order reconciliation THIS cycle -- deferring dynamic-exit evaluation "
                    "one cycle so a stale, already-superseded entry decision is never immediately "
                    "reversed by this same cycle's fresh evidence (see exit_manager.py's module docstring)"
                ),
                evidence={"position": current.to_dict()},
            )
            continue

        if current.exit_pending_order_id is not None:
            # Reconciling an exit ALREADY in flight always runs,
            # regardless of market close below -- we must still learn
            # its fate; this is never a NEW exit proposal.
            reconcile_exit_fill(
                current, client=client, pending_store=pending_store, position_store=position_store,
                state_store=state_store, decision_logger=decision_logger, now=now, trade_store=trade_store,
            )
            continue

        # MARKET-CLOSED SKIP (see module docstring's STALE-ENTRY /
        # MARKET-CLOSE section): a position whose own market has
        # already closed must never have a NEW exit order evaluated or
        # submitted here -- settle_resolved_positions() (already run
        # earlier this same cycle) is the correct, exchange-aware path
        # for a closed market; attempting to sell into one that's no
        # longer open for trading is never correct, regardless of what
        # current BTC evidence says. This is checked AFTER the
        # in-flight-exit reconcile above, never before it.
        close_time = current.close_time if current.close_time.tzinfo else current.close_time.replace(tzinfo=timezone.utc)
        if now >= close_time:
            decision_logger.log_decision(
                kind="exit_check_skipped_market_closed",
                reason=(
                    f"{current.outcome} on {current.condition_id}: this position's market already "
                    f"closed ({close_time.isoformat()}) -- deferring entirely to settlement, never "
                    "proposing a new exit on a closed market"
                ),
                evidence={"position": current.to_dict()},
            )
            continue

        try:
            order_book = client.get_order_book(current.token_id)
        except Exception as exc:  # noqa: BLE001 - a book-fetch failure must never be treated as "target reached"
            decision_logger.log_decision(
                kind="exit_check_failed",
                reason=f"Could not fetch order book for {current.condition_id}: {exc}",
                evidence={"position": current.to_dict()},
            )
            continue

        # Isolated from the order-book fetch above on purpose
        # (requirement: a BTC-feed failure must never affect normal
        # Polymarket functionality, and must never crash this bot) —
        # a corrupted real-bar file or any other btc_price_store
        # failure degrades to "no BTC bars this cycle" (bars=[]),
        # which assess_btc_market() already turns into
        # UNAVAILABLE/INSUFFICIENT_DATA correctly; it is never treated
        # as a reason to skip the position's order-book-based checks
        # entirely, the way an order-book fetch failure is.
        try:
            bars = btc_price_store.get_bars(interval_seconds=settings.btc_bar_interval_seconds, now=now)
        except Exception as exc:  # noqa: BLE001 - a BTC store failure must never crash the bot or block Polymarket logic
            decision_logger.log_decision(
                kind="btc_feed_read_failed",
                reason=f"Could not read BTC price history for {current.condition_id}: {exc}",
                evidence={"position": current.to_dict()},
            )
            bars = []
        recent_mids = (
            history.mids if history is not None and getattr(history, "condition_id", None) == current.condition_id
            else []
        )
        btc_assessment = assess_btc_market(
            bars, order_book, recent_mids, outcome=current.outcome, now=now,
            max_bar_age_seconds=settings.btc_max_bar_age_seconds, feed_source=btc_feed_source,
        )

        # Requirement: a dead BTC feed must be visible, not silent.
        # Logged every cycle, for every open position, regardless of
        # whether anything else happens this cycle.
        feed_status = btc_assessment.feed_status
        decision_logger.log_decision(
            kind="btc_feed_status",
            reason=(
                f"BTC_FEED_SOURCE={feed_status.source} BTC_LAST_BAR_TIME={feed_status.last_bar_time} "
                f"BTC_BAR_AGE_SECONDS={feed_status.bar_age_seconds} BTC_FEED_STATUS={feed_status.status} "
                f"BTC_EVIDENCE_STATE={btc_assessment.state.value}"
            ),
            evidence={
                "condition_id": current.condition_id,
                "BTC_FEED_SOURCE": feed_status.source,
                "BTC_LAST_BAR_TIME": feed_status.last_bar_time.isoformat() if feed_status.last_bar_time else None,
                "BTC_BAR_AGE_SECONDS": feed_status.bar_age_seconds,
                "BTC_FEED_STATUS": feed_status.status,
                "BTC_EVIDENCE_STATE": btc_assessment.state.value,
            },
        )

        decision = evaluate_dynamic_exit(
            current, order_book, btc_assessment, profit_target_pct=settings.profit_target_pct, config=config,
            exit_retry_cooldown_seconds=settings.exit_retry_cooldown_seconds,
            exit_retry_min_evidence_change=settings.exit_retry_min_evidence_change, now=now,
        )
        if not decision.eligible:
            continue

        submit_dynamic_exit(
            decision, client=client, gateway=gateway, position_store=position_store, state_store=state_store,
            decision_logger=decision_logger, settings=settings, order_placer=order_placer, now=now,
            trade_store=trade_store,
        )
        submitted += 1

    return submitted
