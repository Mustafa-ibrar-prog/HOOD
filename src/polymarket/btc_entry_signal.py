"""Coinbase BTC intelligence as the PRIMARY entry-direction signal for
the Polymarket BTC Up/Down 15m system — replacing strategy.py's old
BtcMomentumStrategy (Polymarket YES-mid price movement) as the live
entry trigger. See strategy.py's own module docstring for why that
approach is no longer used to decide direction, and this module's for
what replaced it.

ARCHITECTURE (unchanged from the rest of this package's philosophy):

    COINBASE BTC -> directional thesis        (this module)
    POLYMARKET   -> execution quality          (engine.py, risk.py — unchanged)
    RISK ENGINE  -> final permission           (risk.py, entry_guard.py — unchanged)
    ORDER EXECUTION -> actual trade            (gateway.py — unchanged)

A Polymarket price move, by itself, must NEVER create an entry — this
module never reads a BinaryMarket's yes_bid/yes_ask/yes_mid or any
Polymarket order book at all; its ONLY input is real BTC OHLC bars
(btc_market_data.py, fed from Coinbase — see btc_coinbase_source.py).

REUSE, NOT A SECOND SCORING ENGINE: every actual indicator computation
here is the EXACT SAME, completely unmodified pipeline exit_manager.py
already uses for the dynamic-exit decision —
btc_intelligence.build_btc_momentum_evidence() (RSI/MACD/EMA/structure/
breakout/reversal) feeding src/strategy/evidence.py's evaluate_momentum()
(the single scoring engine in this codebase, reused unmodified), plus
btc_intelligence.wrap_btc_signals() for uniform Signal auditability and
btc_market_data.compute_feed_status() for the identical staleness gate
exit_manager.py already relies on. Nothing here invents a new
threshold, a new indicator, or a new staleness rule.

THE ONE GENUINELY NEW PIECE: evaluate_momentum's WEAKENING/STRENGTHENING/
REVERSING states are only ever meaningful RELATIVE TO an already-stated
thesis_direction — there is no "is BTC bullish right now" scorer
anywhere in this codebase that doesn't presuppose a direction, because
the exit side always already knows its position's outcome. Entry has
no outcome yet; that is exactly what this module must decide. The fix
is not a new scorer — it's running the EXISTING one TWICE per cycle
(once framed bullish, once framed bearish) and asking "which framing,
if either, does the CURRENT evidence actually confirm" — see
assess_btc_entry_direction()'s own docstring for the precise rule.

Entry and exit now consume the SAME authoritative BTC evidence
pipeline; they just ask it two different, deliberately separate
questions (see exit_manager.py's own module docstring, unchanged):

    ENTRY: "Does current BTC evidence justify opening a YES/NO position?"
    EXIT:  "Does current BTC evidence materially invalidate the position
            this system is already holding?"

Entry is never gated on P&L (there is no position yet to have P&L
against) and exit's own P&L-independent philosophy is completely
untouched by this module — nothing here imports or calls anything
from exit_manager.py, and nothing in exit_manager.py was changed to
support this.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from src.market.models import PriceBar
from src.polymarket.btc_intelligence import (
    DEFAULT_MAX_BAR_AGE_SECONDS,
    BtcMarketAssessment,
    build_btc_momentum_evidence,
    wrap_btc_signals,
)
from src.polymarket.btc_market_data import BtcFeedStatus, compute_feed_status
from src.polymarket.models import BinaryMarket, SetupCandidate, TradeThesis
from src.strategy.evidence import MomentumState, evaluate_momentum

# Same default/mechanism as exit_manager.DEFAULT_MIN_WEAKENING_SIGNALS_FOR_EXIT
# (itself reused verbatim from the proven options-side EvaluatorConfig) --
# a materiality gate on the fired-signal COUNT, not an independently
# invented entry-specific threshold. "A single weak indicator should
# not automatically trigger a trade" (entry's own requirement) is the
# exact same guarantee evaluate_momentum/exit_manager.py already give;
# this just applies that SAME gate on the entry side.
DEFAULT_MIN_STRENGTHENING_SIGNALS_FOR_ENTRY = 2

_NEUTRAL_REASON_CODES = frozenset({"insufficient_btc_evidence", "conflicting_btc_evidence", "neutral_btc_evidence"})


@dataclass(frozen=True)
class BtcDirectionalAssessment:
    """The full, inspectable answer to "which way, if any, does
    CURRENT Coinbase BTC evidence point" — independent of any
    Polymarket data. Both framings are always attached (even when
    direction is "neutral") for full auditability/structured logging —
    see engine.py's btc_entry_signal decision log entry.

    `direction` is "bullish" (candidate YES), "bearish" (candidate
    NO), or "neutral" (NO ENTRY — covers insufficient/stale data,
    genuinely mixed/ambiguous evidence, AND a both-sides-STRENGTHENING
    conflict, which is never resolved by guessing)."""

    direction: str  # "bullish" | "bearish" | "neutral"
    reason: str
    neutral_reason_code: str | None  # one of _NEUTRAL_REASON_CODES, or None when direction != "neutral"
    bullish_assessment: BtcMarketAssessment
    bearish_assessment: BtcMarketAssessment
    bullish_edge_points: float  # strengthening_score - weakening_score, framed bullish (same formula as exit_manager.EdgeAssessment.btc_points)
    bearish_edge_points: float  # same, framed bearish
    bullish_entry_worthy: bool
    bearish_entry_worthy: bool
    feed_status: BtcFeedStatus

    @property
    def outcome(self) -> str | None:
        if self.direction == "bullish":
            return "YES"
        if self.direction == "bearish":
            return "NO"
        return None

    @property
    def selected_assessment(self) -> BtcMarketAssessment | None:
        if self.direction == "bullish":
            return self.bullish_assessment
        if self.direction == "bearish":
            return self.bearish_assessment
        return None

    @property
    def edge_points(self) -> float:
        if self.direction == "bullish":
            return self.bullish_edge_points
        if self.direction == "bearish":
            return self.bearish_edge_points
        return 0.0

    @property
    def fired_signal_count(self) -> int:
        selected = self.selected_assessment
        return selected.signal_count if selected is not None else 0

    @property
    def momentum_state(self) -> MomentumState | None:
        selected = self.selected_assessment
        return selected.state if selected is not None else None


def classify_btc_direction(
    *,
    bullish_assessment: BtcMarketAssessment,
    bearish_assessment: BtcMarketAssessment,
    bullish_edge_points: float,
    bearish_edge_points: float,
    bullish_worthy: bool,
    bearish_worthy: bool,
) -> tuple[str, str | None, str]:
    """The pure decision table behind assess_btc_entry_direction()'s
    "which framing wins, if either" call — pulled out as its own
    function specifically so the rare BOTH-worthy (internally
    conflicting) branch can be exercised directly in tests without
    needing to hand-construct real BTC bars that happen to make both
    framings read STRENGTHENING simultaneously (the two framings' own
    detector pairs are near-complementary by construction, so that
    case is naturally rare in realistic price action — never meaning
    it can't happen, which is exactly why it must still be handled,
    not asserted-away).

    Returns (direction, neutral_reason_code, reason) — see
    BtcDirectionalAssessment's own field docstrings."""
    if bullish_worthy and bearish_worthy:
        return (
            "neutral", "conflicting_btc_evidence",
            f"Both bullish and bearish BTC framings read STRENGTHENING simultaneously "
            f"(bullish edge_points={bullish_edge_points:+.0f}, bearish edge_points={bearish_edge_points:+.0f}) "
            "-- internally conflicting, refusing to guess a direction",
        )
    if bullish_worthy:
        return (
            "bullish", None,
            f"BTC evidence materially confirms a bullish thesis (STRENGTHENING, "
            f"edge_points={bullish_edge_points:+.0f}, {bullish_assessment.signal_count} fired signal(s))",
        )
    if bearish_worthy:
        return (
            "bearish", None,
            f"BTC evidence materially confirms a bearish thesis (STRENGTHENING, "
            f"edge_points={bearish_edge_points:+.0f}, {bearish_assessment.signal_count} fired signal(s))",
        )
    if bullish_assessment.state is MomentumState.INSUFFICIENT_DATA:
        return (
            "neutral", "insufficient_btc_evidence",
            "Insufficient or stale BTC market evidence this cycle -- holding rather than guessing a direction",
        )
    return (
        "neutral", "neutral_btc_evidence",
        f"BTC evidence does not materially confirm either direction (bullish={bullish_assessment.state.value}, "
        f"bearish={bearish_assessment.state.value}) -- no entry",
    )


def assess_btc_entry_direction(
    bars: Sequence[PriceBar],
    *,
    now: datetime | None = None,
    max_bar_age_seconds: float = DEFAULT_MAX_BAR_AGE_SECONDS,
    feed_source: str = "manual",
    min_strengthening_signals: int = DEFAULT_MIN_STRENGTHENING_SIGNALS_FOR_ENTRY,
    **evidence_kwargs,
) -> BtcDirectionalAssessment:
    """The single entry point engine.py's run_cycle() calls once per
    cycle, BEFORE any Polymarket order book is ever fetched for a new
    entry — see module docstring.

    STALENESS/INSUFFICIENCY: delegates entirely to the exact same
    gates assess_btc_market() already uses — compute_feed_status()
    (bars only ever reach the scorer when the feed is FRESH; a STALE
    or UNAVAILABLE feed is silently treated as zero bars) and
    evaluate_momentum's own `available_field_count() < 3 ->
    INSUFFICIENT_DATA` gate. No separate staleness or insufficiency
    rule is introduced here — a dead/thin feed on either framing simply
    never reads STRENGTHENING, which is already enough to produce
    direction="neutral" below.

    DIRECTION RULE: a framing is "entry-worthy" only when ALL of:
      1. its MomentumState is STRENGTHENING (the evidence CONFIRMS
         that framing's thesis, not merely fails to oppose it);
      2. its edge_points (strengthening_score - weakening_score) is
         positive — net evidence actually favors it;
      3. its fired-signal count clears min_strengthening_signals — a
         single soft signal is never enough (see this module's own
         constant docstring).
    Exactly one framing entry-worthy -> that is the direction. Neither
    -> "neutral" (insufficient or genuinely non-directional evidence).
    BOTH -> "neutral" too (internally conflicting; never guessed)."""
    now = now or datetime.now(timezone.utc)
    bars = list(bars)
    feed_status = compute_feed_status(bars, max_bar_age_seconds=max_bar_age_seconds, source=feed_source, now=now)
    usable_bars = bars if feed_status.status == "FRESH" else []
    signal_time = usable_bars[-1].start_time if usable_bars else now

    def _framing(thesis_direction: str) -> tuple[BtcMarketAssessment, float, bool]:
        evidence = build_btc_momentum_evidence(usable_bars, thesis_direction=thesis_direction, **evidence_kwargs)
        momentum = evaluate_momentum(evidence)
        assessment = BtcMarketAssessment(
            state=momentum.state, evidence_score=momentum.weakening_score - momentum.strengthening_score,
            btc_assessment=momentum, signals=wrap_btc_signals(evidence, at=signal_time), feed_status=feed_status,
        )
        edge_points = -assessment.evidence_score  # strengthening - weakening; same formula as exit_manager.EdgeAssessment.btc_points
        worthy = (
            assessment.state is MomentumState.STRENGTHENING
            and edge_points > 0
            and assessment.signal_count >= min_strengthening_signals
        )
        return assessment, edge_points, worthy

    bullish_assessment, bullish_edge_points, bullish_worthy = _framing("bullish")
    bearish_assessment, bearish_edge_points, bearish_worthy = _framing("bearish")

    direction, code, reason = classify_btc_direction(
        bullish_assessment=bullish_assessment, bearish_assessment=bearish_assessment,
        bullish_edge_points=bullish_edge_points, bearish_edge_points=bearish_edge_points,
        bullish_worthy=bullish_worthy, bearish_worthy=bearish_worthy,
    )

    return BtcDirectionalAssessment(
        direction=direction, reason=reason, neutral_reason_code=code,
        bullish_assessment=bullish_assessment, bearish_assessment=bearish_assessment,
        bullish_edge_points=bullish_edge_points, bearish_edge_points=bearish_edge_points,
        bullish_entry_worthy=bullish_worthy, bearish_entry_worthy=bearish_worthy, feed_status=feed_status,
    )


def build_entry_candidate(
    market: BinaryMarket, assessment: BtcDirectionalAssessment, *, size_usd: float,
) -> SetupCandidate | None:
    """Maps a directional BtcDirectionalAssessment onto the CURRENT
    market — "bullish -> YES, bearish -> NO" — never the reverse, and
    never anything at all when `assessment.direction == "neutral"`.

    The ONLY Polymarket data this touches is the CURRENT market's own
    yes_bid/yes_ask, used purely to confirm a two-sided quote actually
    exists to buy the selected side at (mirrors
    strategy.BtcMomentumStrategy.evaluate's own same check) — never to
    decide WHICH side. Returns None, never a guessed price, when the
    needed side of the quote is missing.

    `size_usd` is the caller's own sizing decision (engine.py passes
    settings.max_bet_usd — see its own call site) — this function
    never computes or scales a size itself."""
    outcome = assessment.outcome
    if outcome is None:
        return None

    if outcome == "YES":
        if market.yes_ask is None:
            return None
        entry_price = market.yes_ask
    else:
        if market.yes_bid is None:
            return None
        entry_price = round(1 - market.yes_bid, 4)  # buying NO at (1 - YES bid)

    selected = assessment.selected_assessment
    assert selected is not None  # guaranteed whenever outcome is not None
    thesis = TradeThesis(
        outcome=outcome,
        catalyst=(
            f"Coinbase BTC evidence {assessment.direction} ({selected.state.value}, "
            f"edge_points={assessment.edge_points:+.0f}, {selected.signal_count} fired signal(s))"
        ),
        confidence=round(min(1.0, abs(assessment.edge_points) / 10.0), 3),  # presentational only -- never used for sizing/risk
    )
    return SetupCandidate(market=market, thesis=thesis, suggested_entry_price=entry_price, suggested_size_usd=size_usd)
