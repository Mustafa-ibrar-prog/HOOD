"""Phase 35, Part D/E — the research adapter: a `ResearchStrategy` that
carries EACH matched option trade (`phase35_option_trade_matching.py`)
through the REAL, unmodified `PositionEvaluator` (`src.position_manager.
evaluator`) -- the SAME exit engine every live position (of any
strategy) goes through -- via the project's REAL, unmodified
`ResearchStrategyBacktestAdapter`/`BacktestEngine` (Part E's explicit
"do NOT introduce a special backtest engine"). Implementing the
`ResearchStrategy` ABC (rather than `BacktestStrategy` directly) also
means this adapter can run through `src.research.validation.
run_cost_sensitivity` unmodified for Part H's cost-stress sweep.

DESIGN: one "symbol" per matched trade attempt (its own short, sparse,
REAL Bar sequence built from that option contract's own observed
ask/bid/mid prices -- never a fabricated daily grid). Bar 0 is always
the entry (this "symbol"'s series only exists because a real, causal
entry signal already fired upstream -- see phase35_underlying_signal.py
-- so no further entry re-detection happens inside generate_signal).
Every bar after that calls the REAL `PositionEvaluator.evaluate()`,
exactly mirroring `position_manager/monitor.py::_build_momentum_evidence`'s
live pattern of recomputing momentum evidence FRESH from the
underlying's own bars at each evaluation
(`phase35_underlying_signal.compute_momentum_evidence_at`, reused, not
reimplemented).

`thesis_invalidated` is always False here -- NOT a simplification: the
real live monitor (`position_manager/monitor.py`'s own `PositionSnapshot`
construction) never sets it either; it has no other caller anywhere in
this codebase. This adapter is exact on that point, not approximate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Mapping, Sequence

from src.data.bar import Bar
from src.features.engine import FeatureEngine
from src.options.phase35_option_trade_matching import MatchedOptionTrade
from src.options.phase35_underlying_signal import compute_momentum_evidence_at
from src.position_manager.evaluator import PositionEvaluator, PositionSnapshot
from src.position_manager.models import OpenPosition
from src.research.strategy import ResearchSignal, ResearchStrategy, ResearchStrategySpec
from src.strategy.decision import EXIT_DECISIONS, TradeThesis
from src.strategy.evidence import MomentumEvidence

STRATEGY_ID = "MOMENTUM_BREAKOUT_EXISTING_V1"


@dataclass(frozen=True)
class TradeMetadata:
    underlying_symbol: str
    expiration: date
    entry_reason: str


def build_bars_for_matched_trade(trade: MatchedOptionTrade) -> list[Bar]:
    """One Bar per real observation of the matched contract (entry_row +
    management_rows), price = mid of real bid/ask when both are present,
    else whichever side is real and available. Irregular timestamps are
    fine -- src.backtesting is event-driven, not calendar-grid-driven."""
    rows = (trade.entry_row,) + trade.management_rows
    bars = []
    for r in rows:
        bid, ask = r.get("bid"), r.get("ask")
        if bid is not None and ask is not None:
            price = (bid + ask) / 2
        elif ask is not None:
            price = ask
        elif bid is not None:
            price = bid
        else:
            continue  # no real price at all for this row -- skip it, never fabricate one
        ts = r["timestamp"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        bars.append(Bar(timestamp=ts, symbol=trade.option_id, timeframe="day", open=price, high=price, low=price, close=price, volume=int(r.get("volume") or 0)))
    return bars


class MomentumBreakoutOptionResearchStrategy(ResearchStrategy):
    """Manages N independent matched trades (each its own "symbol"),
    entering once at bar 0 and exiting via the real PositionEvaluator
    thereafter. Needs no bar-window FeatureEngine features -- everything
    it needs is either already resolved at trade-matching time (entry
    price, expiration, strike) or recomputed causally per-bar from the
    underlying series (compute_momentum_evidence_at, reused unchanged)."""

    def __init__(
        self, trades_by_symbol: Mapping[str, MatchedOptionTrade],
        underlying_daily_series: Mapping[str, list[tuple[date, float]]],
        *, universe: tuple[str, ...] = (),
    ):
        self._trades = dict(trades_by_symbol)
        self._underlying_series = dict(underlying_daily_series)
        self._evaluator = PositionEvaluator()
        self._state: dict[str, dict] = {}
        self.spec = ResearchStrategySpec(
            strategy_id=STRATEGY_ID, name="MomentumBreakoutStrategy (existing, frozen)", version="1.0",
            hypothesis_id=STRATEGY_ID, universe=universe, timeframe="day",
            parameters={"see": "src.options.phase35_frozen_strategy_spec.MOMENTUM_BREAKOUT_EXISTING_V1"},
            holding_period_bars=0, prediction_horizon_bars=0, expected_regime="trending",
        )

    def feature_engine(self) -> FeatureEngine:
        return FeatureEngine([])

    def generate_signal(self, history: Sequence[Bar], features: Mapping[str, float | None]) -> ResearchSignal | None:
        """State machine, precisely accounting for NextBarExecutionModel's
        delay_bars=1 (the signal emitted from bar N fills at bar N+1's
        open -- see execution_models.py): a LONG signal is emitted at
        bar 0 ("PENDING" -> signaled); the FILL actually happens at bar 1,
        which the engine processes BEFORE calling generate_signal again
        for bar 1 (engine.py's own per-bar order: append -> fill pending
        orders -> compute features -> call strategy). So bar 1's own
        price genuinely IS this position's real fill/entry price (since
        every Bar this adapter builds has open==close, see
        build_bars_for_matched_trade) -- entry_price is recorded HERE, at
        bar 1, not at bar 0, and bar 1 itself is never asked to justify an
        exit (a position cannot be evaluated for exit before it has
        actually been entered) -- exit evaluation starts at bar 2 onward."""
        current = history[-1]
        symbol = current.symbol
        trade = self._trades[symbol]
        state = self._state.setdefault(symbol, {"phase": "PENDING", "entry_price": None, "peak_price": None})

        if state["phase"] == "PENDING":
            state["phase"] = "SIGNALED"
            return ResearchSignal(
                timestamp=current.timestamp, symbol=symbol, strategy_id=STRATEGY_ID, strategy_version="1.0",
                direction="LONG", signal_strength=1.0, target_position=None,
                feature_values={"entry_reason": None},
            )
        if state["phase"] == "SIGNALED":
            # This bar IS the real fill (see docstring) -- record it, do not yet evaluate exit.
            state["phase"] = "IN_POSITION"
            state["entry_price"] = current.close
            state["peak_price"] = current.close
            return None

        option_price = current.close
        state["peak_price"] = max(state["peak_price"], option_price)
        entry_price = state["entry_price"]

        thesis = TradeThesis(
            setup_name="momentum-breakout-calls", direction="bullish",
            catalyst=f"Confirmed breakout continuation on {trade.underlying_symbol} (Phase 35 daily-bar reinterpretation)",
            invalidation="Underlying closes back below the breakout level, or momentum evidence turns WEAKENING/REVERSING",
            profit_target_usd=round(entry_price * 100 * 0.50, 2), stop_loss_usd=round(entry_price * 100 * 0.50, 2),
        )
        position = OpenPosition(
            symbol=trade.underlying_symbol, option_id=symbol, option_description=f"{trade.underlying_symbol} {trade.expiration.isoformat()} C {trade.strike}",
            side="long_call", quantity=1, entry_price=entry_price,
            entry_time=datetime(trade.signal_date.year, trade.signal_date.month, trade.signal_date.day, tzinfo=timezone.utc),
            thesis=thesis, profit_target_usd=round(entry_price * 100 * 0.50, 2), stop_loss_usd=round(entry_price * 100 * 0.50, 2),
            expiration=trade.expiration,
        )

        current_date = current.timestamp.date()
        series = self._underlying_series.get(trade.underlying_symbol, [])
        momentum = compute_momentum_evidence_at(series, current_date) if current_date in [d for d, _ in series] else None
        if momentum is None:
            momentum = MomentumEvidence(thesis_direction="bullish")  # INSUFFICIENT_DATA -- never fabricated, see evaluate_momentum's own fail-safe

        minutes_to_expiration = (trade.expiration - current_date).days * 24 * 60  # coarse DTE-based proxy -- DATA_LIMITED, see module docstring

        snapshot = PositionSnapshot(
            position=position, option_price=option_price, momentum=momentum,
            minutes_to_expiration=float(minutes_to_expiration), peak_price=state["peak_price"],
        )
        decision = self._evaluator.evaluate(snapshot)
        if decision.decision in EXIT_DECISIONS:
            return ResearchSignal(
                timestamp=current.timestamp, symbol=symbol, strategy_id=STRATEGY_ID, strategy_version="1.0",
                direction="FLAT", signal_strength=1.0, target_position=None,
                feature_values={},
            )
        return None  # HOLD -- persist the current position, no new signal this bar
