"""The event-driven backtest engine (Phase 3).

ARCHITECTURAL BOUNDARY (section 27): this module NEVER imports from
src.execution, src.market.hood_provider, or src.live_bridge, and calls no
HOOD MCP tool, directly or indirectly. It consumes only already-loaded
src.data.bar.Bar objects and produces only in-memory results — there is no
code path from here to a real or even a paper order. BACKTEST EXECUTION,
PAPER EXECUTION (src.execution.gateway.PaperExecutionGateway), and LIVE
EXECUTION (src.execution.gateway.LiveExecutionGateway) are three
completely separate object graphs that share no code.

THE EVENT QUEUE'S ACTUAL JOB: merging N symbols' independently-loaded bar
series into one correctly-interleaved global chronological order is the
one thing a flat nested loop cannot do correctly — that's what
events.EventQueue is for, and it's genuinely used for it below. Once a
MarketEvent is popped, everything it triggers (feature computation, a
strategy signal, sizing, risk review, order creation, a fill, a portfolio
update) is processed SYNCHRONOUSLY, in a fixed, deterministic order,
within the single call that handles that one MarketEvent — not re-queued.
This sidesteps a genuinely hard sub-problem (mixing "already known"
historical data events with "not yet due" future order-fill events in one
priority queue and getting the tie-breaking exactly right) while still
delivering everything sections 1-2 actually ask for: strict chronological
processing, no future bar ever influencing an earlier decision, and a
fully deterministic replay. Every event type (Signal/Order/Fill/
PortfolioUpdate) is still a real, immutable, timestamped object, appended
to `event_log` in the exact order produced — which, because the outer loop
is itself strictly chronological, is itself always in strict chronological
order.

THE LOOK-AHEAD BOUNDARY WITHIN ONE BAR'S PROCESSING (see _on_market_event):
  1. Append the bar to that symbol's history — now it "exists".
  2. Fill any order that was scheduled to execute AT this bar (from a
     signal generated on an EARLIER bar — see ExecutionModel).
  3. Compute this bar's features from the causal history (Phase 2's
     FeatureEngine, windowed to the largest configured feature lookback
     for performance — mathematically identical to using the unbounded
     history, since every feature is itself a bounded rolling window).
  4. Call the strategy — it sees only history up to and including this
     bar, never beyond.
  5. If it returns a Signal: size it, risk-review it, and (if approved)
     schedule an order for a FUTURE bar (delay_bars >= 1, enforced by
     ExecutionModel) — never this one.
  6. Mark the portfolio to market using this bar's close (now reflecting
     step 2's fill, if any) and append one EquityPoint.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

from src.backtesting.events import EventQueue, FillEvent, MarketEvent, OrderEvent, SignalEvent
from src.backtesting.execution_models import ExecutionModel, SlippageModel, SpreadModel, TransactionCostModel, apply_slippage, spread_adjusted_price
from src.backtesting.interfaces import BacktestConfig
from src.backtesting.journal import BacktestTrade, BacktestTradeJournal
from src.backtesting.metrics import BenchmarkComparison, PerformanceMetrics, compute_performance_metrics
from src.backtesting.portfolio import EquityPoint, Portfolio, PortfolioError
from src.backtesting.risk_adapter import BacktestRiskAdapter
from src.backtesting.sizing import PositionSizer
from src.backtesting.strategy import BacktestStrategy, Signal
from src.data.bar import Bar
from src.features.engine import FeatureEngine


@dataclass(frozen=True)
class BacktestResult:
    config: BacktestConfig
    trades: tuple[BacktestTrade, ...]
    equity_curve: tuple[EquityPoint, ...]
    event_log: tuple[Any, ...]
    metrics: PerformanceMetrics
    starting_cash: float
    ending_cash: float
    ending_equity: float
    benchmark_curve: tuple[EquityPoint, ...] | None = None


class BacktestEngine:
    def __init__(
        self,
        *,
        config: BacktestConfig,
        bars_by_symbol: Mapping[str, Sequence[Bar]],
        strategy: BacktestStrategy,
        feature_engine: FeatureEngine,
        execution_model: ExecutionModel,
        slippage_model: SlippageModel,
        cost_model: TransactionCostModel,
        spread_model: SpreadModel,
        position_sizer: PositionSizer,
        risk_adapter: BacktestRiskAdapter,
        trade_journal: BacktestTradeJournal | None = None,
        volatility_feature_name: str | None = None,
        allow_negative_cash: bool = False,
    ):
        self._config = config
        self._bars_by_symbol = {sym: list(bars) for sym, bars in bars_by_symbol.items()}
        self._strategy = strategy
        self._feature_engine = feature_engine
        self._execution_model = execution_model
        self._slippage_model = slippage_model
        self._cost_model = cost_model
        self._spread_model = spread_model
        self._position_sizer = position_sizer
        self._risk_adapter = risk_adapter
        self._trade_journal = trade_journal
        self._volatility_feature_name = volatility_feature_name

        self._portfolio = Portfolio(config.initial_capital_usd, allow_negative_cash=allow_negative_cash)
        self._history: dict[str, list[Bar]] = {sym: [] for sym in self._bars_by_symbol}
        self._last_price: dict[str, float] = {}
        self._pending_orders: dict[tuple[str, Any], list[OrderEvent]] = {}
        self._event_log: list[Any] = []
        self._trades: list[BacktestTrade] = []

        manifest = feature_engine.manifest()
        self._feature_window = max((f["lookback"] for f in manifest), default=0) + 2

        # Per-symbol risk bookkeeping the live RiskManager's checks need.
        # Intentionally NOT reusing src.risk.store.DailyRiskState/
        # RiskStateStore — those are file-persistence-oriented for a
        # stateless-per-cycle live process; this engine already holds all
        # state in memory for the whole run, a different and correctly
        # scoped design, not an oversight.
        self._current_day: date | None = None
        self._trades_opened_today = 0
        self._daily_realized_pnl = 0.0
        self._last_exit_time: dict[str, Any] = {}
        self._last_position_size_usd: dict[str, float] = {}
        self._last_trade_was_loss: dict[str, bool] = {}
        self._entry_timestamp: dict[str, Any] = {}
        self._entry_reason: dict[str, str] = {}
        self._entry_fees: dict[str, float] = {}
        self._entry_slippage: dict[str, float] = {}

    def run(self) -> BacktestResult:
        queue = EventQueue()
        for symbol in sorted(self._bars_by_symbol):
            for bar in self._bars_by_symbol[symbol]:
                queue.push(MarketEvent(timestamp=bar.timestamp, symbol=symbol, bar=bar))

        while queue:
            event = queue.pop()
            if isinstance(event, MarketEvent):
                self._on_market_event(event)

        self._force_close_all_positions()
        metrics = compute_performance_metrics(
            equity_curve=self._portfolio.equity_curve, trades=self._trades, starting_cash=self._config.initial_capital_usd
        )
        ending_equity = self._portfolio.equity_curve[-1].equity if self._portfolio.equity_curve else self._config.initial_capital_usd
        return BacktestResult(
            config=self._config,
            trades=tuple(self._trades),
            equity_curve=tuple(self._portfolio.equity_curve),
            event_log=tuple(self._event_log),
            metrics=metrics,
            starting_cash=self._config.initial_capital_usd,
            ending_cash=self._portfolio.cash,
            ending_equity=ending_equity,
        )

    # --- per-bar processing --------------------------------------------------------------

    def _on_market_event(self, event: MarketEvent) -> None:
        symbol, bar = event.symbol, event.bar
        self._roll_day_if_needed(bar.timestamp.date())

        self._history[symbol].append(bar)
        self._last_price[symbol] = bar.close

        self._fill_pending_orders(symbol, bar)

        windowed_history = self._history[symbol][-self._feature_window :] if self._feature_window else self._history[symbol]
        frame = self._feature_engine.compute(windowed_history)
        features_row = {name: frame.columns[name][-1] for name in frame.feature_names}

        signal = self._strategy.on_bar(self._history[symbol], features_row)
        if signal is not None:
            self._handle_signal(symbol, bar, signal, features_row)

        prices_for_valuation = {sym: price for sym, price in self._last_price.items() if sym in self._portfolio.positions}
        self._portfolio.mark_to_market(prices=prices_for_valuation, timestamp=bar.timestamp)

    def _roll_day_if_needed(self, today: date) -> None:
        if self._current_day != today:
            self._current_day = today
            self._trades_opened_today = 0
            self._daily_realized_pnl = 0.0

    # --- signal -> sized target -> risk review -> scheduled order ------------------------

    def _handle_signal(self, symbol: str, bar: Bar, signal: Signal, features_row: Mapping[str, float | None]) -> None:
        signal_event = SignalEvent(
            timestamp=bar.timestamp, symbol=symbol, direction=signal.direction, strength=signal.strength,
            strategy_name=self._strategy.name, reason=signal.reason,
        )
        self._event_log.append(signal_event)

        current_qty = self._portfolio.position_quantity(symbol)
        if signal.direction == "FLAT":
            desired_qty = 0
        else:
            volatility = features_row.get(self._volatility_feature_name) if self._volatility_feature_name else None
            desired_qty = self._position_sizer.target_quantity(
                signal_strength=signal.strength,
                reference_price=bar.close,
                available_cash=self._portfolio.cash,
                portfolio_equity=self._portfolio.equity_curve[-1].equity if self._portfolio.equity_curve else self._config.initial_capital_usd,
                volatility=volatility,
            )

        delta = desired_qty - current_qty
        if delta == 0:
            return
        side = "buy" if delta > 0 else "sell"
        requested_quantity = abs(delta)

        if side == "sell":
            # Reducing/closing risk is never blocked by risk controls — same
            # principle as src.risk.manager.RiskManager.evaluate_exit_conditions
            # ("exiting is risk-reducing, never gated"), applied consistently here.
            self._schedule_order(
                symbol=symbol, bar=bar, side="sell", quantity=requested_quantity,
                strategy_reason=signal.reason, risk_decision="APPROVED", risk_reason="Exits are never risk-blocked",
            )
            return

        review = self._risk_adapter.review(
            symbol=symbol,
            proposed_quantity=requested_quantity,
            reference_price=bar.close,
            bid=None,
            ask=None,
            volume=bar.volume,
            open_interest=None,
            trades_opened_today=self._trades_opened_today,
            daily_pnl_usd=self._daily_realized_pnl,
            open_symbols=list(self._portfolio.positions.keys()),
            last_exit_time=self._last_exit_time.get(symbol),
            now=bar.timestamp,
            last_position_size_usd=self._last_position_size_usd.get(symbol),
            last_trade_was_loss=self._last_trade_was_loss.get(symbol, False),
        )

        if review.decision == "REJECTED":
            order_id = f"ORD-{uuid.uuid4().hex[:10]}"
            order_event = OrderEvent(
                order_id=order_id, timestamp=bar.timestamp, generated_at_timestamp=bar.timestamp, symbol=symbol,
                side="buy", quantity=requested_quantity, order_type="market", limit_price=None,
                strategy_name=self._strategy.name, reason=signal.reason,
                risk_decision="REJECTED", risk_reason=review.reason,
            )
            self._event_log.append(order_event)
            self._event_log.append(
                FillEvent(
                    order_id=order_id, fill_id=f"FILL-{uuid.uuid4().hex[:10]}", timestamp=bar.timestamp, symbol=symbol,
                    side="buy", quantity=requested_quantity, order_type="market", requested_price=bar.close,
                    execution_price=bar.close, slippage_amount=0.0, fees=0.0, spread_source="n/a",
                    status="rejected", reason=review.reason,
                )
            )
            return

        self._schedule_order(
            symbol=symbol, bar=bar, side="buy", quantity=review.approved_quantity,
            strategy_reason=signal.reason, risk_decision=review.decision, risk_reason=review.reason,
        )

    def _schedule_order(self, *, symbol: str, bar: Bar, side: str, quantity: int, strategy_reason: str, risk_decision: str, risk_reason: str) -> None:
        all_bars = self._bars_by_symbol[symbol]
        current_index = len(self._history[symbol]) - 1
        fill_index = current_index + self._execution_model.delay_bars()

        order_id = f"ORD-{uuid.uuid4().hex[:10]}"
        if fill_index >= len(all_bars):
            self._event_log.append(
                OrderEvent(
                    order_id=order_id, timestamp=bar.timestamp, generated_at_timestamp=bar.timestamp, symbol=symbol,
                    side=side, quantity=quantity, order_type="market", limit_price=None,
                    strategy_name=self._strategy.name, reason=strategy_reason,
                    risk_decision=risk_decision, risk_reason=risk_reason,
                )
            )
            self._event_log.append(
                FillEvent(
                    order_id=order_id, fill_id=f"FILL-{uuid.uuid4().hex[:10]}", timestamp=bar.timestamp, symbol=symbol,
                    side=side, quantity=quantity, order_type="market", requested_price=bar.close,
                    execution_price=bar.close, slippage_amount=0.0, fees=0.0, spread_source="n/a",
                    status="rejected", reason="no future bar available to execute against — end of dataset",
                )
            )
            return

        fill_bar = all_bars[fill_index]
        order_event = OrderEvent(
            order_id=order_id, timestamp=fill_bar.timestamp, generated_at_timestamp=bar.timestamp, symbol=symbol,
            side=side, quantity=quantity, order_type="market", limit_price=None,
            strategy_name=self._strategy.name, reason=strategy_reason,
            risk_decision=risk_decision, risk_reason=risk_reason,
        )
        self._event_log.append(order_event)
        self._pending_orders.setdefault((symbol, fill_bar.timestamp), []).append(order_event)

    # --- fill simulation -------------------------------------------------------------------

    def _fill_pending_orders(self, symbol: str, bar: Bar) -> None:
        orders = self._pending_orders.pop((symbol, bar.timestamp), [])
        for order in orders:
            self._fill_order(order, bar)

    def _fill_order(self, order: OrderEvent, fill_bar: Bar) -> None:
        reference_price = self._execution_model.reference_price(fill_bar)
        execution_price, spread_source = spread_adjusted_price(self._spread_model, reference_price=reference_price, side=order.side, bar=fill_bar)
        execution_price = apply_slippage(self._slippage_model, reference_price=execution_price, side=order.side, quantity=order.quantity, bar=fill_bar)
        fees = self._cost_model.compute_fees(side=order.side, quantity=order.quantity, execution_price=execution_price)
        slippage_amount = (execution_price - reference_price) if order.side == "buy" else (reference_price - execution_price)

        status = "filled"
        reason = ""
        try:
            if order.side == "buy":
                self._portfolio.apply_buy_fill(symbol=order.symbol, quantity=order.quantity, execution_price=execution_price, fees=fees)
                self._trades_opened_today += 1
                proposed_size_usd = order.quantity * execution_price
                self._last_position_size_usd[order.symbol] = proposed_size_usd
                if order.symbol not in self._entry_timestamp:
                    self._entry_timestamp[order.symbol] = fill_bar.timestamp
                    self._entry_reason[order.symbol] = order.reason
                    self._entry_fees[order.symbol] = 0.0
                    self._entry_slippage[order.symbol] = 0.0
                self._entry_fees[order.symbol] = self._entry_fees.get(order.symbol, 0.0) + fees
                self._entry_slippage[order.symbol] = self._entry_slippage.get(order.symbol, 0.0) + slippage_amount
            else:
                entry_price = self._portfolio.positions[order.symbol].avg_entry_price if order.symbol in self._portfolio.positions else execution_price
                realized_pnl = self._portfolio.apply_sell_fill(symbol=order.symbol, quantity=order.quantity, execution_price=execution_price, fees=fees)
                self._daily_realized_pnl += realized_pnl
                self._last_exit_time[order.symbol] = fill_bar.timestamp
                self._last_trade_was_loss[order.symbol] = realized_pnl < 0

                if order.symbol not in self._portfolio.positions:  # fully closed
                    self._record_closed_trade(
                        symbol=order.symbol, quantity=order.quantity, entry_price=entry_price,
                        exit_price=execution_price, exit_reason=order.reason, risk_decision=order.risk_decision,
                        exit_fees=fees, exit_slippage=slippage_amount,
                    )
        except PortfolioError as exc:
            status = "rejected"
            reason = str(exc)

        self._event_log.append(
            FillEvent(
                order_id=order.order_id, fill_id=f"FILL-{uuid.uuid4().hex[:10]}", timestamp=fill_bar.timestamp, symbol=order.symbol,
                side=order.side, quantity=order.quantity, order_type=order.order_type, requested_price=reference_price,
                execution_price=execution_price, slippage_amount=slippage_amount, fees=fees,
                spread_source=spread_source, status=status, reason=reason,
            )
        )

    def _record_closed_trade(
        self, *, symbol: str, quantity: int, entry_price: float, exit_price: float, exit_reason: str,
        risk_decision: str, exit_fees: float = 0.0, exit_slippage: float = 0.0,
    ) -> None:
        exit_ts = self._last_exit_time[symbol]
        entry_ts = self._entry_timestamp.pop(symbol, None)
        if entry_ts is None:
            # Defensive only — every position in this engine originates
            # from a buy fill, which always records an entry_timestamp
            # first. Falls back to a zero-duration trade rather than
            # crashing if that invariant is ever violated by a future change.
            entry_ts = exit_ts
        entry_reason = self._entry_reason.pop(symbol, "")
        # total_fees/total_slippage must cover the FULL round trip — the
        # entry fill(s)' accumulated fees/slippage PLUS this exit fill's
        # own, which the caller passes in explicitly (a real bug, fixed:
        # these used to silently drop the exit leg's fees/slippage).
        total_fees = self._entry_fees.pop(symbol, 0.0) + exit_fees
        total_slippage = self._entry_slippage.pop(symbol, 0.0) + exit_slippage

        gross_pnl = (exit_price - entry_price) * quantity
        net_pnl = gross_pnl - total_fees
        holding_minutes = (exit_ts - entry_ts).total_seconds() / 60

        trade = BacktestTrade(
            trade_id=f"TR-{uuid.uuid4().hex[:10]}",
            backtest_id=self._config.backtest_id,
            strategy=self._strategy.name,
            symbol=symbol,
            entry_timestamp=entry_ts,
            entry_price=entry_price,
            exit_timestamp=exit_ts,
            exit_price=exit_price,
            quantity=quantity,
            gross_pnl=gross_pnl,
            fees=total_fees,
            slippage=total_slippage,
            net_pnl=net_pnl,
            holding_period_minutes=holding_minutes,
            entry_reason=entry_reason,
            exit_reason=exit_reason,
            risk_decision=risk_decision,
        )
        self._trades.append(trade)
        if self._trade_journal is not None:
            self._trade_journal.record_trade(trade)

    def _force_close_all_positions(self) -> None:
        """End-of-period event (section 1's minimum event list): any
        position still open when the data runs out is closed at the last
        known price so P&L reporting is complete, not silently left
        open/unmarked. A no-op (no extra equity_curve point appended) when
        there is nothing to close — the last bar's own mark-to-market
        already reflects the correct final state in that case."""
        open_symbols = list(self._portfolio.positions.keys())
        if not open_symbols:
            return
        for symbol in open_symbols:
            price = self._last_price.get(symbol)
            if price is None:
                continue
            quantity = self._portfolio.position_quantity(symbol)
            entry_price = self._portfolio.positions[symbol].avg_entry_price
            fees = self._cost_model.compute_fees(side="sell", quantity=quantity, execution_price=price)
            timestamp = self._history[symbol][-1].timestamp if self._history[symbol] else None
            realized_pnl = self._portfolio.apply_sell_fill(symbol=symbol, quantity=quantity, execution_price=price, fees=fees)
            self._daily_realized_pnl += realized_pnl
            self._last_exit_time[symbol] = timestamp
            self._record_closed_trade(
                symbol=symbol, quantity=quantity, entry_price=entry_price, exit_price=price,
                exit_reason="end-of-period forced close", risk_decision="APPROVED",
                exit_fees=fees, exit_slippage=0.0,  # no slippage model applied on a forced close
            )
            self._event_log.append(
                FillEvent(
                    order_id="END-OF-PERIOD", fill_id=f"FILL-{uuid.uuid4().hex[:10]}", timestamp=timestamp, symbol=symbol,
                    side="sell", quantity=quantity, order_type="market", requested_price=price, execution_price=price,
                    slippage_amount=0.0, fees=fees, spread_source="n/a", status="filled", reason="end-of-period forced close",
                )
            )
        last_ts = max((h[-1].timestamp for h in self._history.values() if h), default=None)
        if last_ts is not None:
            prices = {sym: price for sym, price in self._last_price.items() if sym in self._portfolio.positions}
            self._portfolio.mark_to_market(prices=prices, timestamp=last_ts)
