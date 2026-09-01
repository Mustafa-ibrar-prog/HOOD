"""A concrete, bullish-momentum-breakout scanning strategy.

Scope, deliberately: CALLS ONLY. market/indicators.py's structure
detectors (detect_breakout_continuation / detect_failed_breakout /
higher_highs_lower_highs) are asymmetric — they detect upside breaks above
resistance, not downside breaks below support. A mirrored bearish
("breakdown") detector and long-put setups are real, legitimate future
work; this strategy doesn't half-implement that to look more complete.

Per symbol in the scan universe:
  1. Fetch an UnderlyingSnapshot (equity quote + bars + local indicators) —
     no option contract chosen yet.
  2. Score it with strategy/evidence.py's evaluate_momentum(), assuming a
     bullish thesis — exactly the same scoring the position manager uses
     to judge an OPEN position's momentum. Scanning for a setup and
     monitoring one already held are the same underlying question ("is
     this move real"), just asked before vs. after entry.
  3. Require BOTH a confirmed breakout_continuation AND a STRENGTHENING
     assessment before treating the symbol as a candidate at all —
     scanning is inherently more conservative than holding: it should
     never chase an ambiguous setup the way holding a profitable position
     through mixed evidence might be justified.
  4. Resolve the nearest expiration within a configured DTE window (via
     get_option_expirations, so we never pull an underlying's entire
     chain — see market/data_provider.py), then the strike closest to the
     current price within that expiration.
  5. Re-fetch a real, contract-specific MarketSnapshot to price the
     contract and apply basic liquidity/spread sanity checks. This is a
     PRE-FILTER only — final gating remains RiskManager.evaluate_new_trade
     at entry time, unchanged.
  6. Build a SetupCandidate with a profit target/stop loss expressed as a
     percentage of the option premium (configurable), and a thesis
     recording exactly which evidence supported the call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Sequence

from src.market.data_provider import MarketDataProvider
from src.market.errors import MarketDataError
from src.market.indicators import bid_ask_spread_pct, is_liquid
from src.strategy.base import SetupCandidate, Strategy
from src.strategy.decision import TradeThesis
from src.strategy.evidence import MomentumEvidence, MomentumState, evaluate_momentum


@dataclass(frozen=True)
class MomentumBreakoutConfig:
    min_days_to_expiration: int = 7
    max_days_to_expiration: int = 45
    profit_target_pct: float = 0.50  # % gain on premium
    stop_loss_pct: float = 0.50  # % loss on premium
    max_spread_pct: float = 0.15  # pre-filter only; RiskManager enforces the real limit at entry
    min_volume: int = 10
    min_open_interest: int = 50


class MomentumBreakoutStrategy(Strategy):
    name = "momentum-breakout-calls"

    def __init__(self, config: MomentumBreakoutConfig | None = None, *, now: datetime | None = None):
        self.config = config or MomentumBreakoutConfig()
        # Injectable "current time" for expiration-window selection —
        # optional and backward compatible: omitting it preserves the
        # exact prior behavior (real wall clock). Fixes a real bug flagged
        # in the Phase 1 audit: _select_expiration() previously always
        # called datetime.now(timezone.utc) directly, unlike every other
        # time-dependent function in this codebase (run_trading_cycle,
        # is_within_monitoring_window, PositionMonitor.run_once all accept
        # `now`), which made this strategy's expiration window silently
        # drift out of sync with a cycle's own injected `now` — orchestrator.py
        # now passes its own `now` through here.
        self._now = now

    def _current_time(self) -> datetime:
        return self._now if self._now is not None else datetime.now(timezone.utc)

    def scan(self, market: MarketDataProvider, universe: Sequence[str]) -> list[SetupCandidate]:
        candidates: list[SetupCandidate] = []
        for symbol in universe:
            try:
                candidate = self._scan_symbol(market, symbol)
            except MarketDataError:
                continue  # missing/unavailable data for this symbol — skip it, don't guess
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _scan_symbol(self, market: MarketDataProvider, symbol: str) -> SetupCandidate | None:
        underlying = market.get_underlying_snapshot(symbol)

        if not underlying.breakout_continuation:
            return None  # hard gate: a confirmed breakout, not just "looks okay"

        evidence = MomentumEvidence(
            thesis_direction="bullish",
            rsi=underlying.rsi,
            rsi_prev=underlying.rsi_prev,
            macd_histogram=underlying.macd_histogram,
            macd_histogram_prev=underlying.macd_histogram_prev,
            ema_fast=underlying.ema_fast,
            ema_slow=underlying.ema_slow,
            higher_highs=underlying.higher_highs,
            lower_highs=underlying.lower_highs,
            breakout_continuation=underlying.breakout_continuation,
            failed_breakout=underlying.failed_breakout,
            reversal_signal=False,
            volume_ratio=underlying.volume_ratio,
        )
        assessment = evaluate_momentum(evidence)
        if assessment.state is not MomentumState.STRENGTHENING:
            return None  # scanning is conservative: ambiguous/weak evidence doesn't qualify

        contract = self._select_contract(market, symbol, underlying.quote.last_trade_price)
        if contract is None:
            return None
        option_id, expiration, strike = contract

        option_snapshot = market.get_market_snapshot(option_id, symbol)
        quote = option_snapshot.option

        if not is_liquid(quote.volume, quote.open_interest, self.config.min_volume, self.config.min_open_interest):
            return None
        if bid_ask_spread_pct(quote.bid_price, quote.ask_price) > self.config.max_spread_pct:
            return None

        entry_price = quote.ask_price  # a marketable buy-to-open limit
        if entry_price <= 0:
            return None

        profit_target_usd = round(entry_price * 100 * self.config.profit_target_pct, 2)
        stop_loss_usd = round(entry_price * 100 * self.config.stop_loss_pct, 2)

        thesis = TradeThesis(
            setup_name=self.name,
            direction="bullish",
            catalyst=(
                f"Confirmed breakout continuation on {symbol}; momentum evidence: "
                f"{', '.join(assessment.signals) if assessment.signals else 'trend/structure aligned'}"
            ),
            invalidation=(
                "Underlying closes back below the breakout level, or momentum evidence "
                "turns WEAKENING/REVERSING"
            ),
            profit_target_usd=profit_target_usd,
            stop_loss_usd=stop_loss_usd,
        )

        return SetupCandidate(
            underlying_symbol=symbol,
            option_id=option_id,
            option_description=f"{symbol} {expiration.isoformat()} C {strike}",
            side="long_call",
            thesis=thesis,
            suggested_entry_price=entry_price,
            suggested_quantity=1,
            profit_target_usd=profit_target_usd,
            stop_loss_usd=stop_loss_usd,
            expiration=expiration,
            score=float(assessment.strengthening_score),
            signals=assessment.signals,
        )

    def _select_contract(
        self, market: MarketDataProvider, symbol: str, underlying_price: float
    ) -> tuple[str, date, str] | None:
        expiration = self._select_expiration(market, symbol)
        if expiration is None:
            return None

        raw_candidates = market.get_option_chain_candidates(
            symbol,
            expiration_dates=expiration.isoformat(),
            type="call",
            state="active",
            tradability="tradable",
        )

        best: tuple[str, date, str] | None = None
        best_distance: float | None = None
        for raw in raw_candidates:
            option_id = raw.get("id")
            strike_raw = raw.get("strike_price")
            if not (option_id and strike_raw):
                continue
            try:
                strike = float(strike_raw)
            except (TypeError, ValueError):
                continue
            distance = abs(strike - underlying_price)
            if best_distance is None or distance < best_distance:
                best = (option_id, expiration, strike_raw)
                best_distance = distance

        return best

    def _select_expiration(self, market: MarketDataProvider, symbol: str) -> date | None:
        today = self._current_time().date()
        expirations = market.get_option_expirations(symbol)
        in_window = [
            exp for exp in expirations if self.config.min_days_to_expiration <= (exp - today).days <= self.config.max_days_to_expiration
        ]
        return min(in_window) if in_window else None
