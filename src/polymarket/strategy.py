"""Signal for the Polymarket BTC 15-minute system.

Deliberately single-asset (bitcoin) and deliberately simple: a v1
starting point to tune once you can see it trade against real markets,
not a validated edge. Unlike src/strategy/momentum_breakout.py (which
reads RSI/MACD/EMA computed from real OHLCV bars over a 180-minute
lookback), a 15-minute binary market gives almost no history to compute
indicators like that FROM — by the time a market opens, there is no
"this market's own price action" to look back over yet. So this reads
momentum in the market's own implied probability (the YES mid-price)
since the window opened: if YES has been climbing since open, bet YES
continues (the crowd's updating belief, not a reversal bet); if it's
been falling, bet NO. Near a 50/50 coin-flip with no clear direction
yet, or without enough samples to trust a direction, it proposes
nothing — same "don't guess on insufficient evidence" posture as
src/strategy/evidence.py's evaluate_momentum.

SUPERSEDED AS THE LIVE ENTRY TRIGGER: engine.run_cycle() no longer
calls BtcMomentumStrategy.evaluate() to decide entry direction — a
Polymarket price move, by itself, must never create an entry (a live
requirement: this strategy's own basis, a YES-mid move since market
open, is exactly the thing that could never distinguish "real BTC
move" from "the crowd re-pricing on no new information"). See
btc_entry_signal.py: Coinbase BTC evidence, run through the SAME
scoring pipeline exit_manager.py's dynamic-exit decision already uses,
is now the primary entry-direction signal; Polymarket's own quote is
consulted only afterward, for execution confirmation (spread/
liquidity/price sanity), never for direction. This class and its tests
are kept — unused by the live path, but still valid, still pure, still
useful for backtesting or future reference — rather than deleted
outright.

This is pure logic (no network calls), so it's fully unit-testable
without Polymarket API access, unlike client.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.polymarket.models import BinaryMarket, SetupCandidate, TradeThesis


@dataclass(frozen=True)
class MomentumConfig:
    # Minimum number of price samples since market open before this will
    # propose anything at all — avoids reacting to the first noisy tick.
    min_samples: int = 3
    # Minimum move in YES mid-price (in probability points, e.g. 0.04 =
    # 4 cents) since the earliest sample before calling it a real
    # direction rather than noise.
    min_move: float = 0.04
    # Price itself can't be nearer to a coin-flip than this when
    # entering — buying at 0.50 risks the whole premise being "there is
    # no edge yet," regardless of recent direction.
    min_distance_from_mid: float = 0.03
    # Size scales with conviction between these two bounds (USD),
    # clamped by settings.max_bet_usd by the risk manager regardless.
    min_size_usd: float = 2.0
    max_size_usd: float = 5.0


class BtcMomentumStrategy:
    name = "btc-15min-momentum-continuation"

    def __init__(self, config: MomentumConfig | None = None):
        self.config = config or MomentumConfig()

    def evaluate(self, market: BinaryMarket, recent_mids: list[float]) -> SetupCandidate | None:
        """recent_mids: YES mid-price samples since this market opened,
        oldest first, each from a previous poll of the same market (see
        engine.py — it owns the buffer, this function only reads it)."""
        samples = [m for m in recent_mids if m is not None]
        if len(samples) < self.config.min_samples:
            return None

        current = market.yes_mid
        if current is None:
            return None

        move = current - samples[0]
        if abs(move) < self.config.min_move:
            return None
        if abs(current - 0.5) < self.config.min_distance_from_mid:
            return None

        outcome = "YES" if move > 0 else "NO"
        conviction = min(1.0, abs(move) / (self.config.min_move * 3))
        size_usd = self.config.min_size_usd + conviction * (self.config.max_size_usd - self.config.min_size_usd)

        if outcome == "YES":
            if market.yes_ask is None:
                return None
            entry_price = market.yes_ask
        else:
            if market.yes_bid is None:
                return None
            entry_price = round(1 - market.yes_bid, 4)  # buying NO at (1 - YES bid)

        thesis = TradeThesis(
            outcome=outcome,
            catalyst=f"YES mid moved {move:+.3f} over {len(samples)} samples since market open ({samples[0]:.3f} -> {current:.3f})",
            confidence=round(conviction, 3),
        )
        return SetupCandidate(market=market, thesis=thesis, suggested_entry_price=entry_price, suggested_size_usd=round(size_usd, 2))
