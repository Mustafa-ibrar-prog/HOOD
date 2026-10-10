"""Self-learning from the bot's OWN completed trades (TASK 2).

This is NEVER a second trading strategy, and the bot NEVER rewrites its
own source code. Coinbase BTC evidence (btc_entry_signal.py) remains
the PRIMARY, sole source of DIRECTION. entry_confidence.py's base
confidence remains the PRIMARY driver of whether/how much to risk.
This module only computes a SECONDARY, BOUNDED adjustment to that base
confidence, from this exact bot's own trade history, grouped into
coarse "setups" (build_setup_key below).

Hard guarantees (never violated by any function here):
  - A historical adjustment can never CREATE a direction -- it is only
    ever applied to an already-directional, already-approved base
    confidence (see apply_historical_adjustment: base_confidence == 0
    always stays 0, no matter what the adjustment is).
  - It can never reverse bullish to bearish -- direction is a separate
    field entirely untouched by this module; only the scalar confidence
    number is adjusted.
  - It can never override neutral or stale BTC evidence -- neutral
    direction already forces base_confidence to 0 upstream
    (entry_confidence.compute_base_confidence), which this module leaves
    at 0 for the same reason as above.
  - It can never bypass risk.py -- the final, adjusted confidence still
    only ever proposes a bucketed size via entry_confidence's own
    recommended_size_usd()/confidence_bucket(), which engine.py still
    runs through risk_manager.evaluate_new_trade() exactly as before.
  - A tiny sample can never swing behavior -- compute_historical_adjustment
    shrinks the raw win-rate signal toward 0 below learning_min_sample_size,
    and the result is always clamped to [learning_min_adjustment,
    learning_max_adjustment] (default -10..+10) regardless of sample size.

Execution/reconciliation problems (a stale, delayed-adopted entry fill
-- see reconciliation.py's STALE-ENTRY SAFETY NET) are classified
separately from the strategy's own win/loss record (classify_outcome)
and EXCLUDED from win-rate/expectancy statistics entirely (2E: "Do not
teach the strategy that every losing P&L event means its prediction
was wrong") -- they are still persisted (never discarded -- "whatever
is actually available, never fabricated"), just not counted as a
strategy prediction.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.polymarket.positions import OpenPosition

STRATEGY_ID_COINBASE_MOMENTUM = "COINBASE_MOMENTUM"  # retained for completed trades recorded before this round
STRATEGY_ID_SIMPLE_PRICE_THRESHOLD = "SIMPLE_PRICE_THRESHOLD"  # the ONLY production strategy_id as of this round

# --- Outcome classification (2E) --------------------------------------------
OUTCOME_NORMAL_WIN = "NORMAL_WIN"
OUTCOME_STRATEGY_LOSS = "STRATEGY_LOSS"
OUTCOME_EXECUTION_LOSS = "EXECUTION_LOSS"
OUTCOME_STALE_ORDER_EVENT = "STALE_ORDER_EVENT"
OUTCOME_API_RECONCILIATION_EVENT = "API_RECONCILIATION_EVENT"
OUTCOME_OTHER_NON_STRATEGY_EVENT = "OTHER_NON_STRATEGY_EVENT"

# Only these two classifications represent a genuine strategy
# prediction outcome -- every other classification is excluded from
# win-rate/expectancy statistics (see compute_setup_stats).
_STRATEGY_OUTCOME_CLASSIFICATIONS = frozenset({OUTCOME_NORMAL_WIN, OUTCOME_STRATEGY_LOSS})


def classify_outcome(
    *, realized_pnl_usd: float, stale_entry: bool = False, execution_failure: bool = False,
    reconciliation_event: bool = False,
) -> str:
    """Pure classification -- never infers an execution/reconciliation
    problem from the P&L number itself (that would be exactly the
    "every loss was a wrong prediction" mistake 2E forbids); the three
    non-strategy flags must be passed in from what ACTUALLY happened
    (e.g. OpenPosition.entry_context["stale_entry_fill"])."""
    if stale_entry:
        return OUTCOME_STALE_ORDER_EVENT
    if execution_failure:
        return OUTCOME_EXECUTION_LOSS
    if reconciliation_event:
        return OUTCOME_API_RECONCILIATION_EVENT
    return OUTCOME_NORMAL_WIN if realized_pnl_usd > 0 else OUTCOME_STRATEGY_LOSS


# --- Completed trade record (2A) --------------------------------------------

@dataclass(frozen=True)
class CompletedTrade:
    """One finished position, entry through exit. Every field is
    "whatever was actually available at the time" -- optional fields
    are None when this bot's own pipeline never computed/observed that
    value (e.g. a delayed-adopted stale entry has no same-cycle BTC
    evidence to attach -- see engine.py), never a fabricated guess."""

    strategy_id: str
    condition_id: str
    outcome: str  # "YES" or "NO"
    entry_timestamp: datetime
    exit_timestamp: datetime
    size_usd: float  # requested_size_usd, actually filled at entry
    entry_fill_price: float
    exit_price: float
    exit_reason: str  # "SETTLEMENT" | "DYNAMIC_EXIT"
    fees_usd: float
    realized_pnl_usd: float
    win: bool
    outcome_classification: str  # one of the OUTCOME_* constants above
    market_question: str | None = None
    seconds_remaining_at_entry: float | None = None
    btc_price_at_entry: float | None = None
    btc_direction: str | None = None
    btc_edge_score: float | None = None
    momentum_state: str | None = None
    fired_signal_count: int | None = None
    fired_signals: tuple[str, ...] | None = None  # RSI/MACD/EMA/trend evidence, where available -- see btc_intelligence.py
    coinbase_feed_status: str | None = None
    polymarket_yes_bid: float | None = None
    polymarket_yes_ask: float | None = None
    entry_spread: float | None = None
    entry_liquidity_usd: float | None = None
    base_confidence: int | None = None
    confidence_bucket: str | None = None
    final_confidence: int | None = None
    historical_adjustment: float | None = None
    exit_btc_state: str | None = None
    exit_btc_evidence_score: float | None = None
    stale_entry: bool = False
    # Settlement-aligned reference feed (see reference_divergence.py).
    # Always None today -- no licensed reference feed is wired in yet
    # (see that module's docstring) -- but once one is, these populate
    # automatically via entry_context with zero further changes here.
    reference_direction_at_entry: str | None = None
    reference_divergence_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["entry_timestamp"] = self.entry_timestamp.isoformat()
        d["exit_timestamp"] = self.exit_timestamp.isoformat()
        d["fired_signals"] = list(self.fired_signals) if self.fired_signals is not None else None
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompletedTrade":
        fired_signals = data.get("fired_signals")
        return cls(
            strategy_id=data["strategy_id"], condition_id=data["condition_id"], outcome=data["outcome"],
            entry_timestamp=datetime.fromisoformat(data["entry_timestamp"]),
            exit_timestamp=datetime.fromisoformat(data["exit_timestamp"]),
            size_usd=float(data["size_usd"]), entry_fill_price=float(data["entry_fill_price"]),
            exit_price=float(data["exit_price"]), exit_reason=data["exit_reason"],
            fees_usd=float(data["fees_usd"]), realized_pnl_usd=float(data["realized_pnl_usd"]),
            win=bool(data["win"]), outcome_classification=data["outcome_classification"],
            market_question=data.get("market_question"),
            seconds_remaining_at_entry=data.get("seconds_remaining_at_entry"),
            btc_price_at_entry=data.get("btc_price_at_entry"), btc_direction=data.get("btc_direction"),
            btc_edge_score=data.get("btc_edge_score"), momentum_state=data.get("momentum_state"),
            fired_signal_count=data.get("fired_signal_count"),
            fired_signals=tuple(fired_signals) if fired_signals is not None else None,
            coinbase_feed_status=data.get("coinbase_feed_status"),
            polymarket_yes_bid=data.get("polymarket_yes_bid"), polymarket_yes_ask=data.get("polymarket_yes_ask"),
            entry_spread=data.get("entry_spread"), entry_liquidity_usd=data.get("entry_liquidity_usd"),
            base_confidence=data.get("base_confidence"), confidence_bucket=data.get("confidence_bucket"),
            final_confidence=data.get("final_confidence"), historical_adjustment=data.get("historical_adjustment"),
            exit_btc_state=data.get("exit_btc_state"), exit_btc_evidence_score=data.get("exit_btc_evidence_score"),
            stale_entry=bool(data.get("stale_entry", False)),
            reference_direction_at_entry=data.get("reference_direction_at_entry"),
            reference_divergence_status=data.get("reference_divergence_status"),
        )


class CompletedTradeStoreError(RuntimeError):
    pass


class CompletedTradeStore:
    """Same file-backed, restart-safe JSON convention as every other
    store in this package (positions.py/pending.py/state.py) -- an
    append-only ledger, never rewritten or pruned by this module."""

    def __init__(self, path: Path):
        self._path = path

    def load(self) -> list[CompletedTrade]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        try:
            return [CompletedTrade.from_dict(row) for row in json.loads(raw)]
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise CompletedTradeStoreError(f"Completed-trade journal is corrupted or unreadable: {exc}") from exc

    def append(self, trade: CompletedTrade) -> None:
        trades = self.load()
        trades.append(trade)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps([t.to_dict() for t in trades], indent=2, sort_keys=True))


# --- Setup matching (2B) ----------------------------------------------------

def _bucket_entry_price(entry_fill_price: float) -> str:
    return f"{round(entry_fill_price / 0.05) * 0.05:.2f}"


def _bucket_seconds_remaining(seconds_remaining: float | None) -> str:
    if seconds_remaining is None:
        return "unknown"
    return str(int(round(seconds_remaining / 180.0) * 180))


def build_setup_key(
    *, btc_direction: str | None, momentum_state: str | None, fired_signal_count: int | None,
    entry_fill_price: float, seconds_remaining_at_entry: float | None,
) -> str:
    """A deterministic, coarse bucketing of exactly the features 2B
    names: BTC direction, momentum state, fired signal count, entry
    price (nearest $0.05), and seconds remaining at entry (nearest
    3-minute bucket) -- never a continuous/high-cardinality key, which
    would starve every setup of a usable sample size."""
    return "|".join([
        f"dir={btc_direction or 'unknown'}",
        f"state={momentum_state or 'unknown'}",
        f"signals={fired_signal_count if fired_signal_count is not None else 'unknown'}",
        f"price={_bucket_entry_price(entry_fill_price)}",
        f"secs={_bucket_seconds_remaining(seconds_remaining_at_entry)}",
    ])


@dataclass(frozen=True)
class SetupStats:
    setup_key: str
    sample_count: int  # strategy-attributable trades only (NORMAL_WIN/STRATEGY_LOSS) -- see module docstring
    wins: int
    losses: int
    excluded_non_strategy_count: int  # STALE_ORDER_EVENT/EXECUTION_LOSS/etc. for this setup -- never counted above
    win_rate: float | None  # None when sample_count == 0 -- never fabricated as 0.0
    avg_win_usd: float | None
    avg_loss_usd: float | None
    expectancy_usd: float | None  # win_rate*avg_win + (1-win_rate)*avg_loss (avg_loss is negative)
    total_pnl_usd: float


def compute_setup_stats(trades: list[CompletedTrade], setup_key: str) -> SetupStats:
    matching = [
        t for t in trades
        if build_setup_key(
            btc_direction=t.btc_direction, momentum_state=t.momentum_state,
            fired_signal_count=t.fired_signal_count, entry_fill_price=t.entry_fill_price,
            seconds_remaining_at_entry=t.seconds_remaining_at_entry,
        ) == setup_key
    ]
    strategy_trades = [t for t in matching if t.outcome_classification in _STRATEGY_OUTCOME_CLASSIFICATIONS]
    excluded_count = len(matching) - len(strategy_trades)

    wins = [t for t in strategy_trades if t.outcome_classification == OUTCOME_NORMAL_WIN]
    losses = [t for t in strategy_trades if t.outcome_classification == OUTCOME_STRATEGY_LOSS]
    sample_count = len(strategy_trades)

    win_rate = (len(wins) / sample_count) if sample_count else None
    avg_win = (sum(t.realized_pnl_usd for t in wins) / len(wins)) if wins else None
    avg_loss = (sum(t.realized_pnl_usd for t in losses) / len(losses)) if losses else None
    expectancy = None
    if sample_count and win_rate is not None:
        expectancy = win_rate * (avg_win or 0.0) + (1 - win_rate) * (avg_loss or 0.0)
    total_pnl = sum(t.realized_pnl_usd for t in strategy_trades)

    return SetupStats(
        setup_key=setup_key, sample_count=sample_count, wins=len(wins), losses=len(losses),
        excluded_non_strategy_count=excluded_count, win_rate=win_rate, avg_win_usd=avg_win,
        avg_loss_usd=avg_loss, expectancy_usd=expectancy, total_pnl_usd=total_pnl,
    )


# --- Historical adjustment (2C/2D) ------------------------------------------

@dataclass(frozen=True)
class HistoricalAdjustment:
    adjustment: float
    reason: str


def compute_historical_adjustment(
    stats: SetupStats, *, min_sample_size: int, min_adjustment: float, max_adjustment: float,
) -> HistoricalAdjustment:
    """Shrinkage toward 0 below `min_sample_size` (anti-overfitting,
    2C: "do not let one or two trades change behavior") -- a win rate
    centered at 50% maps linearly to the full [min_adjustment,
    max_adjustment] range at a FULL sample, scaled down by
    `sample_count / min_sample_size` (capped at 1.0) below it. A
    sample of 0 always yields exactly 0.0 (nothing learned yet)."""
    if stats.sample_count == 0 or stats.win_rate is None:
        return HistoricalAdjustment(0.0, f"no historical sample yet for setup {stats.setup_key!r}")

    weight = min(1.0, stats.sample_count / min_sample_size)
    centered = stats.win_rate - 0.5  # -0.5..+0.5
    raw = centered * 2.0 * max(abs(min_adjustment), abs(max_adjustment))
    adjustment = raw * weight
    adjustment = max(min_adjustment, min(max_adjustment, adjustment))
    reason = (
        f"setup {stats.setup_key!r}: n={stats.sample_count} (min={min_sample_size}), "
        f"win_rate={stats.win_rate:.1%}, weight={weight:.2f} -> adjustment={adjustment:+.1f}"
    )
    return HistoricalAdjustment(adjustment, reason)


def apply_historical_adjustment(base_confidence: int, adjustment: float) -> int:
    """NEVER applied to a zero (NO_TRADE / neutral-direction) base --
    see module docstring's hard guarantees. Otherwise clamped to
    [0, 100], same as entry_confidence.compute_base_confidence."""
    if base_confidence <= 0:
        return 0
    return max(0, min(100, round(base_confidence + adjustment)))


# --- Persisting a completed trade (2A) --------------------------------------

def record_completed_trade(
    trade_store: CompletedTradeStore | None,
    position: OpenPosition,
    *,
    exit_timestamp: datetime,
    exit_price: float,
    exit_reason: str,
    fees_usd: float,
    realized_pnl_usd: float,
    exit_btc_state: str | None = None,
    exit_btc_evidence_score: float | None = None,
) -> CompletedTrade | None:
    """The ONE place a fully-closed OpenPosition becomes a
    CompletedTrade -- called from engine.settle_resolved_positions()
    (exit_reason="SETTLEMENT") and exit_manager.record_exit_fill()
    (exit_reason="DYNAMIC_EXIT") alike, so both lifecycle endings feed
    the SAME learning pipeline rather than two independently-tracked
    ones. A no-op (returns None) whenever `trade_store` is None --
    every existing call site that doesn't pass one stays exactly as it
    was before TASK 2."""
    if trade_store is None:
        return None

    entry_context = position.entry_context or {}
    stale_entry = bool(entry_context.get("stale_entry_fill", False))
    win = realized_pnl_usd > 0
    classification = classify_outcome(realized_pnl_usd=realized_pnl_usd, stale_entry=stale_entry)

    opened_at = position.opened_at if position.opened_at.tzinfo else position.opened_at
    trade = CompletedTrade(
        strategy_id=entry_context.get("strategy_id", STRATEGY_ID_COINBASE_MOMENTUM),
        condition_id=position.condition_id, outcome=position.outcome,
        entry_timestamp=opened_at, exit_timestamp=exit_timestamp,
        # filled_size_usd (actual dollar cost of what's being closed NOW,
        # filled_shares * avg_fill_price), never requested_size_usd --
        # the latter never shrinks on a partial exit, so it would
        # overstate the size of a final closing slice after an earlier
        # partial fill (a rare case, but never fabricated here).
        size_usd=position.filled_size_usd, entry_fill_price=position.avg_fill_price,
        exit_price=exit_price, exit_reason=exit_reason, fees_usd=fees_usd,
        realized_pnl_usd=realized_pnl_usd, win=win, outcome_classification=classification,
        market_question=entry_context.get("market_question"),
        seconds_remaining_at_entry=entry_context.get("seconds_remaining_at_entry"),
        btc_price_at_entry=entry_context.get("btc_price_at_entry"),
        btc_direction=entry_context.get("btc_direction"), btc_edge_score=entry_context.get("btc_edge_points"),
        momentum_state=entry_context.get("momentum_state"),
        fired_signal_count=entry_context.get("fired_signal_count"),
        fired_signals=tuple(entry_context["fired_signals"]) if entry_context.get("fired_signals") else None,
        coinbase_feed_status=entry_context.get("coinbase_feed_status"),
        polymarket_yes_bid=entry_context.get("polymarket_yes_bid"), polymarket_yes_ask=entry_context.get("polymarket_yes_ask"),
        entry_spread=entry_context.get("entry_spread"), entry_liquidity_usd=entry_context.get("entry_liquidity_usd"),
        base_confidence=entry_context.get("base_confidence"), confidence_bucket=entry_context.get("confidence_bucket"),
        final_confidence=entry_context.get("final_confidence"), historical_adjustment=entry_context.get("historical_adjustment"),
        exit_btc_state=exit_btc_state, exit_btc_evidence_score=exit_btc_evidence_score, stale_entry=stale_entry,
        reference_direction_at_entry=entry_context.get("reference_direction_at_entry"),
        reference_divergence_status=entry_context.get("reference_divergence_status"),
    )
    trade_store.append(trade)
    return trade


# --- Loss replay/analysis utility --------------------------------------
# For each losing completed trade, determines as much as can actually
# be read off the stored record about WHY it lost -- never a guess,
# never fabricated data for a field this bot never captured. Built for
# the reference-data architecture investigation: whether losses are
# primarily (A) incorrect BTC direction, (B) Coinbase/reference-feed
# divergence, (C) poor timing, (D) a poor Polymarket entry price,
# (E) an execution/reconciliation problem, or (F) exit logic.
#
# (B) is ALWAYS reported as "cannot be determined" today: no
# historical reference-feed data exists yet for any trade (see
# reference_divergence.py's module docstring -- no legitimate free/
# live Chainlink Data Streams access exists), so inventing a verdict
# here would be exactly the kind of fabrication this whole feature
# must never do. A trade's own `reference_direction_at_entry` (see
# record_completed_trade/engine.py's entry_context) becomes available
# automatically, with zero further code changes here, the moment a
# licensed reference feed is actually wired in and starts recording it.

CAUSE_BTC_DIRECTION = "A_btc_direction"
CAUSE_REFERENCE_DIVERGENCE_UNKNOWN = "B_reference_divergence_unknown"
CAUSE_REFERENCE_DIVERGENCE = "B_reference_divergence"
CAUSE_TIMING = "C_timing"
CAUSE_ENTRY_PRICE = "D_entry_price"
CAUSE_EXECUTION_RECONCILIATION = "E_execution_reconciliation"
CAUSE_EXIT_LOGIC = "F_exit_logic"

DEFAULT_TIMING_THRESHOLD_SECONDS = 120.0
DEFAULT_SPREAD_THRESHOLD = 0.05


@dataclass(frozen=True)
class LossAnalysis:
    condition_id: str
    exit_timestamp: datetime
    realized_pnl_usd: float
    outcome_classification: str
    btc_direction: str | None
    coinbase_price_at_entry: float | None  # btc_price_at_entry -- Coinbase, the only feed with real historical data today
    reference_direction_at_entry: str | None  # None on every trade until a licensed reference feed exists (see above)
    seconds_remaining_at_entry: float | None
    polymarket_yes_bid: float | None
    polymarket_yes_ask: float | None
    entry_fill_price: float
    exit_price: float
    exit_reason: str
    likely_causes: tuple[str, ...]  # subset of the CAUSE_* constants above


def analyze_losing_trades(
    trades: list[CompletedTrade], *,
    timing_threshold_seconds: float = DEFAULT_TIMING_THRESHOLD_SECONDS,
    spread_threshold: float = DEFAULT_SPREAD_THRESHOLD,
) -> list[LossAnalysis]:
    """Pure function over already-persisted trades -- no I/O, no live
    data, fully deterministic and testable. A non-strategy loss
    (EXECUTION_LOSS/API_RECONCILIATION_EVENT/STALE_ORDER_EVENT) is
    flagged with ONLY cause E -- exactly 2E's own rule that an
    execution/reconciliation problem must never be read as "the
    strategy's BTC-direction call was wrong," so it is never also
    tagged A/B/C/D/F."""
    results = []
    for t in trades:
        if t.realized_pnl_usd >= 0:
            continue
        causes: list[str] = []
        if t.outcome_classification in (OUTCOME_EXECUTION_LOSS, OUTCOME_API_RECONCILIATION_EVENT, OUTCOME_STALE_ORDER_EVENT):
            causes.append(CAUSE_EXECUTION_RECONCILIATION)
        else:
            if t.outcome_classification == OUTCOME_STRATEGY_LOSS:
                causes.append(CAUSE_BTC_DIRECTION)
            # Only ever a real verdict when this trade actually recorded
            # a reference-feed reading (reference_divergence_status ==
            # "DIVERGENCE") -- on every trade today, this is None (no
            # licensed reference feed exists yet -- see
            # reference_divergence.py's module docstring), so this is
            # reported as "cannot be determined," never fabricated.
            if t.reference_divergence_status == "DIVERGENCE":
                causes.append(CAUSE_REFERENCE_DIVERGENCE)
            elif t.reference_divergence_status is None:
                causes.append(CAUSE_REFERENCE_DIVERGENCE_UNKNOWN)
            if t.seconds_remaining_at_entry is not None and t.seconds_remaining_at_entry < timing_threshold_seconds:
                causes.append(CAUSE_TIMING)
            if t.entry_spread is not None and t.entry_spread > spread_threshold:
                causes.append(CAUSE_ENTRY_PRICE)
            if t.exit_reason == "DYNAMIC_EXIT":
                causes.append(CAUSE_EXIT_LOGIC)
        results.append(LossAnalysis(
            condition_id=t.condition_id, exit_timestamp=t.exit_timestamp, realized_pnl_usd=t.realized_pnl_usd,
            outcome_classification=t.outcome_classification, btc_direction=t.btc_direction,
            coinbase_price_at_entry=t.btc_price_at_entry,
            reference_direction_at_entry=t.reference_direction_at_entry,  # None until a reference feed exists -- never fabricated
            seconds_remaining_at_entry=t.seconds_remaining_at_entry,
            polymarket_yes_bid=t.polymarket_yes_bid, polymarket_yes_ask=t.polymarket_yes_ask,
            entry_fill_price=t.entry_fill_price, exit_price=t.exit_price, exit_reason=t.exit_reason,
            likely_causes=tuple(causes),
        ))
    return results


def summarize_loss_causes(analyses: list[LossAnalysis]) -> dict[str, int]:
    """How many losing trades each cause appears in -- a trade with
    multiple plausible contributing causes counts once toward each,
    so these counts need not sum to len(analyses)."""
    counts: dict[str, int] = {}
    for analysis in analyses:
        for cause in analysis.likely_causes:
            counts[cause] = counts.get(cause, 0) + 1
    return counts
