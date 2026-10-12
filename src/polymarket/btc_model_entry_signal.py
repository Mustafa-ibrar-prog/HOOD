"""THE ONLY production entry-direction logic as of this round,
replacing simple_entry_signal.py entirely (deleted -- see engine.py's
module docstring for the full list of what this replaces and why).

OLD RULE (REMOVED): "whichever Polymarket side currently has the
higher implied probability" -- that is following the market, not
predicting BTC, and is gone from the entry decision completely. There
is exactly ONE authoritative production entry decision now; this
module is it.

NEW RULE: compare the BTC direction MODEL's own probability (see
btc_direction_model.py) against what Polymarket currently charges to
buy each side (the real executable ASK, never the mid -- using the ask
already prices in HALF the bid/ask spread as a real execution cost,
rather than the model-vs-market comparison pretending it could trade
at the fairer mid). The trade decision comes from the MODEL's EDGE
over that real cost, net of fees and slippage, never from which side
happens to be favored:

    net_edge(side) = model_probability(side) - executable_ask(side)
                     - fee_pct - slippage_pct

Only the side (if either) whose net_edge clears the configured
minimum (settings.model_min_edge) is eligible; if both somehow clear
it (only possible when the model's own UP+DOWN probabilities and the
market's own ask+ask don't sum cleanly to ~1, which can happen since
they come from two independent sources), the LARGER net edge wins --
never both, never a coin flip between them.

HARD GATES (all independent of the configured minimum edge):
  - The model must be TRAINED (BtcDirectionModel.is_trained) -- an
    untrained model's flat 50/50 output must never be compared against
    anything and mistaken for a real prediction.
  - The feature vector must have enough history
    (BtcFeatureVector.has_minimum_data) -- missing price-to-beat,
    missing current BTC price, or not enough bar history for the
    longest return window is NO TRADE, never an imputed guess.
  - Both sides' own order books must be real and two-sided (a bid AND
    an ask) -- missing book data is NO TRADE, same as before.

EXECUTABLE ENTRY PRICE stays a separate concept from the probability/
edge calculation throughout, exactly as before this round: always the
real best_ask of whichever side is selected, never the model
probability and never the market's implied probability."""

from __future__ import annotations

from dataclasses import dataclass

from src.polymarket.btc_direction_model import BtcDirectionPrediction
from src.polymarket.models import OrderBookSnapshot

OUTCOME_UP = "YES"  # Polymarket's own UP outcome label -- see models.py/OrderRequest.outcome
OUTCOME_DOWN = "NO"


@dataclass(frozen=True)
class ModelEntrySignal:
    """The full, inspectable answer -- always attaches every value
    that went into the decision (even on a NO-TRADE result) for full
    auditability in the decision log. Field names match this round's
    required log vocabulary: MARKET_UP_PROBABILITY,
    MARKET_DOWN_PROBABILITY, UP_ASK, DOWN_ASK, UP_EDGE, DOWN_EDGE,
    SELECTED_OUTCOME, EXECUTABLE_ENTRY_PRICE, DECISION, REASON
    (BTC_PRICE/PRICE_TO_BEAT/DISTANCE_TO_BEAT/TIME_REMAINING/
    MODEL_UP_PROBABILITY/MODEL_DOWN_PROBABILITY come from the
    prediction/features objects themselves -- see their own
    to_log_fields()). UP_ASK/DOWN_ASK are logged on EVERY outcome,
    including NO_TRADE -- the per-side executable ask is what makes a
    NO_TRADE decision's REASON auditable after the fact (e.g. "edge too
    small"), not just the eventual trade's own EXECUTABLE_ENTRY_PRICE."""

    outcome: str | None  # "YES" (UP) | "NO" (DOWN) | None -- SELECTED_OUTCOME
    decision: str  # "TRADE" | "NO_TRADE"
    reason: str
    market_up_probability: float | None
    market_down_probability: float | None
    up_ask: float | None
    down_ask: float | None
    up_edge: float | None  # net of fee/slippage -- None only when market_up_probability is unavailable
    down_edge: float | None
    executable_entry_price: float | None

    @property
    def has_candidate(self) -> bool:
        return self.outcome is not None

    def to_log_fields(self) -> dict[str, float | str | None]:
        return {
            "MARKET_UP_PROBABILITY": self.market_up_probability, "MARKET_DOWN_PROBABILITY": self.market_down_probability,
            "UP_ASK": self.up_ask, "DOWN_ASK": self.down_ask,
            "UP_EDGE": self.up_edge, "DOWN_EDGE": self.down_edge, "SELECTED_OUTCOME": self.outcome,
            "EXECUTABLE_ENTRY_PRICE": self.executable_entry_price, "DECISION": self.decision, "REASON": self.reason,
        }


def assess_model_entry(
    *,
    prediction: BtcDirectionPrediction,
    up_order_book: OrderBookSnapshot | None,
    down_order_book: OrderBookSnapshot | None,
    has_minimum_feature_data: bool,
    min_model_edge: float,
    fee_pct: float = 0.0,
    slippage_pct: float = 0.0,
) -> ModelEntrySignal:
    """Pure and deterministic. `up_order_book`/`down_order_book` are
    the real UP(YES)/DOWN(NO) books for THIS outcome (a genuinely
    separate book on international Polymarket, or -- on a single-book
    venue -- single_book.to_no_perspective()'s derivation of the one
    real book; this function never derives one from the other itself,
    same contract simple_entry_signal.py's no_order_book parameter
    used to have)."""
    if not prediction.is_trained:
        return ModelEntrySignal(
            outcome=None, decision="NO_TRADE", reason="model is untrained (no real weights loaded) -- never trading on a 50/50 placeholder",
            market_up_probability=None, market_down_probability=None, up_ask=None, down_ask=None,
            up_edge=None, down_edge=None, executable_entry_price=None,
        )
    if not has_minimum_feature_data:
        return ModelEntrySignal(
            outcome=None, decision="NO_TRADE",
            reason="insufficient BTC feature data (missing price-to-beat, current price, or bar history) -- no prediction to act on",
            market_up_probability=None, market_down_probability=None, up_ask=None, down_ask=None,
            up_edge=None, down_edge=None, executable_entry_price=None,
        )

    up_ask = up_order_book.best_ask if up_order_book is not None else None
    up_bid = up_order_book.best_bid if up_order_book is not None else None
    down_ask = down_order_book.best_ask if down_order_book is not None else None
    down_bid = down_order_book.best_bid if down_order_book is not None else None

    market_up_probability = ((up_bid + up_ask) / 2.0) if (up_bid is not None and up_ask is not None) else None
    market_down_probability = ((down_bid + down_ask) / 2.0) if (down_bid is not None and down_ask is not None) else None

    if market_up_probability is None or market_down_probability is None:
        return ModelEntrySignal(
            outcome=None, decision="NO_TRADE", reason="no two-sided Polymarket quote available yet on one or both sides -- nothing to compare the model against",
            market_up_probability=market_up_probability, market_down_probability=market_down_probability,
            up_ask=up_ask, down_ask=down_ask, up_edge=None, down_edge=None, executable_entry_price=None,
        )

    cost = fee_pct + slippage_pct
    up_edge = prediction.predicted_up_probability - up_ask - cost
    down_edge = prediction.predicted_down_probability - down_ask - cost

    up_qualifies = up_edge >= min_model_edge
    down_qualifies = down_edge >= min_model_edge

    if not up_qualifies and not down_qualifies:
        return ModelEntrySignal(
            outcome=None, decision="NO_TRADE",
            reason=(
                f"model edge too small after execution costs (UP_EDGE={up_edge:.4f}, DOWN_EDGE={down_edge:.4f}, "
                f"minimum required {min_model_edge:.4f}) -- a tiny theoretical edge that disappears after "
                "spread/fees/slippage is no trade"
            ),
            market_up_probability=market_up_probability, market_down_probability=market_down_probability,
            up_ask=up_ask, down_ask=down_ask, up_edge=up_edge, down_edge=down_edge, executable_entry_price=None,
        )

    if up_qualifies and (not down_qualifies or up_edge >= down_edge):
        return ModelEntrySignal(
            outcome=OUTCOME_UP, decision="TRADE",
            reason=(
                f"model P(UP)={prediction.predicted_up_probability:.4f} vs market ask {up_ask:.4f} "
                f"(mid {market_up_probability:.4f}) -- net edge {up_edge:.4f} clears the minimum {min_model_edge:.4f}"
            ),
            market_up_probability=market_up_probability, market_down_probability=market_down_probability,
            up_ask=up_ask, down_ask=down_ask, up_edge=up_edge, down_edge=down_edge, executable_entry_price=up_ask,
        )
    return ModelEntrySignal(
        outcome=OUTCOME_DOWN, decision="TRADE",
        reason=(
            f"model P(DOWN)={prediction.predicted_down_probability:.4f} vs market ask {down_ask:.4f} "
            f"(mid {market_down_probability:.4f}) -- net edge {down_edge:.4f} clears the minimum {min_model_edge:.4f}"
        ),
        market_up_probability=market_up_probability, market_down_probability=market_down_probability,
        up_ask=up_ask, down_ask=down_ask, up_edge=up_edge, down_edge=down_edge, executable_entry_price=down_ask,
    )
