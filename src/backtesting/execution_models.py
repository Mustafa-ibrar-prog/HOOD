"""Configurable execution, slippage, transaction-cost, and spread models
(Phase 3, sections 4-7).

None of these call Robinhood or any live tool — they are pure functions of
already-known historical bar data, used only to simulate what a fill would
plausibly have looked like.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping

from src.data.bar import Bar

# ==============================================================================
# EXECUTION MODEL (section 4) — WHEN a signal is allowed to become a fill.
# ==============================================================================


class ExecutionModel(ABC):
    """Decides which bar an order generated from bar T is allowed to fill
    against, and which price field of that bar to use as the pre-slippage
    reference price.

    THE LOOK-AHEAD BOUNDARY, stated explicitly: a signal computed from bar
    T's close (the bar is "closed" — every field on it is known) becomes an
    order at timestamp T. That order is NEVER eligible to fill using bar
    T's own price — only a LATER bar's price, per `delay_bars`. The engine
    enforces this by construction (see engine.py's order-scheduling logic
    and events.py's EventQueue, which physically refuses an out-of-order
    push) — this class only decides how many bars later, and which price
    field of that later bar.
    """

    @abstractmethod
    def delay_bars(self) -> int:
        """How many bars after the signal bar the order becomes eligible
        to fill. Must be >= 1 — 0 would mean "fill on the same bar the
        signal was computed from," which is look-ahead bias by definition
        (the bar's close wasn't known until the bar closed) and this base
        class refuses to allow it; see NextBarExecutionModel's default."""
        raise NotImplementedError

    @abstractmethod
    def reference_price(self, fill_bar: Bar) -> float:
        """The pre-slippage reference price from the bar the order fills
        against."""
        raise NotImplementedError


class NextBarExecutionModel(ExecutionModel):
    """The default, look-ahead-safe execution model: an order generated
    from bar T fills `delay_bars` bars later (default 1 — the very next
    bar), at that bar's `price_field` (default "open" — the first price
    actually observable on that later bar, not its close, which isn't
    known until the bar itself finishes)."""

    def __init__(self, price_field: str = "open", delay_bars: int = 1):
        if delay_bars < 1:
            raise ValueError(
                "delay_bars must be >= 1 — filling on the same bar a signal was computed from is look-ahead bias"
            )
        if price_field not in ("open", "close", "high", "low"):
            raise ValueError("price_field must be one of: open, close, high, low")
        self._price_field = price_field
        self._delay_bars = delay_bars

    def delay_bars(self) -> int:
        return self._delay_bars

    def reference_price(self, fill_bar: Bar) -> float:
        return getattr(fill_bar, self._price_field)


# ==============================================================================
# SLIPPAGE MODEL (section 5)
# ==============================================================================


class SlippageModel(ABC):
    @abstractmethod
    def slippage_amount(self, *, reference_price: float, side: str, quantity: int, bar: Bar) -> float:
        """Returns a POSITIVE amount (price units) representing how much
        worse than the reference price the fill is. The caller applies the
        sign (buy = pay more, sell = receive less) — see apply_slippage()."""
        raise NotImplementedError


def apply_slippage(model: SlippageModel, *, reference_price: float, side: str, quantity: int, bar: Bar) -> float:
    """execution_price = reference_price + slippage (buy) or
    reference_price - slippage (sell) — the exact formula specified for
    this phase."""
    amount = model.slippage_amount(reference_price=reference_price, side=side, quantity=quantity, bar=bar)
    if amount < 0:
        raise ValueError(f"{type(model).__name__} returned a negative slippage amount ({amount}) — must be >= 0")
    return reference_price + amount if side == "buy" else reference_price - amount


class ZeroSlippage(SlippageModel):
    """Explicit, not a default — a backtest must opt into zero slippage,
    never fall into it silently (per this phase's instruction)."""

    def slippage_amount(self, *, reference_price: float, side: str, quantity: int, bar: Bar) -> float:
        return 0.0


class FixedPercentSlippage(SlippageModel):
    def __init__(self, pct: float):
        if pct < 0:
            raise ValueError("pct must be >= 0")
        self._pct = pct

    def slippage_amount(self, *, reference_price: float, side: str, quantity: int, bar: Bar) -> float:
        return reference_price * self._pct


class BasisPointSlippage(SlippageModel):
    def __init__(self, bps: float):
        if bps < 0:
            raise ValueError("bps must be >= 0")
        self._bps = bps

    def slippage_amount(self, *, reference_price: float, side: str, quantity: int, bar: Bar) -> float:
        return reference_price * (self._bps / 10_000)


class VolatilityAdjustedSlippage(SlippageModel):
    """base_bps applies always; an additional component scales with the
    bar's own (high-low)/close range as a simple, causal (uses only this
    bar's own already-known OHLC) volatility proxy — wider bars imply a
    less certain fill price."""

    def __init__(self, base_bps: float = 5.0, range_multiplier: float = 0.5):
        if base_bps < 0 or range_multiplier < 0:
            raise ValueError("base_bps and range_multiplier must be >= 0")
        self._base_bps = base_bps
        self._range_multiplier = range_multiplier

    def slippage_amount(self, *, reference_price: float, side: str, quantity: int, bar: Bar) -> float:
        range_pct = (bar.high - bar.low) / bar.close if bar.close > 0 else 0.0
        pct = self._base_bps / 10_000 + self._range_multiplier * range_pct
        return reference_price * pct


class PerSymbolSlippage(SlippageModel):
    """Applies a different SlippageModel per symbol (or asset class, if
    the caller keys the mapping that way), falling back to `default` for
    anything not listed — the "configurable by symbol/asset class" part of
    this phase's requirement."""

    def __init__(self, by_symbol: Mapping[str, SlippageModel], default: SlippageModel):
        self._by_symbol = dict(by_symbol)
        self._default = default

    def slippage_amount(self, *, reference_price: float, side: str, quantity: int, bar: Bar) -> float:
        model = self._by_symbol.get(bar.symbol, self._default)
        return model.slippage_amount(reference_price=reference_price, side=side, quantity=quantity, bar=bar)


class SizeAwareSlippage(SlippageModel):
    """Scales a `base` model's slippage up when the order is large relative
    to the bar's own volume (a rough participation-rate proxy — "the
    configurable by order size" part of this phase's requirement). No
    effect (multiplier == 1.0) when volume is zero/unknown, since there is
    nothing sound to scale against."""

    def __init__(self, base: SlippageModel, *, participation_multiplier: float = 2.0):
        if participation_multiplier < 0:
            raise ValueError("participation_multiplier must be >= 0")
        self._base = base
        self._participation_multiplier = participation_multiplier

    def slippage_amount(self, *, reference_price: float, side: str, quantity: int, bar: Bar) -> float:
        base_amount = self._base.slippage_amount(reference_price=reference_price, side=side, quantity=quantity, bar=bar)
        if bar.volume <= 0:
            return base_amount
        participation = quantity / bar.volume
        return base_amount * (1.0 + self._participation_multiplier * participation)


# ==============================================================================
# TRANSACTION COST MODEL (section 6)
# ==============================================================================


class TransactionCostModel(ABC):
    @abstractmethod
    def compute_fees(self, *, side: str, quantity: int, execution_price: float) -> float:
        """Returns a non-negative dollar fee for one fill."""
        raise NotImplementedError


class ZeroCostModel(TransactionCostModel):
    def compute_fees(self, *, side: str, quantity: int, execution_price: float) -> float:
        return 0.0


class PerShareCommission(TransactionCostModel):
    def __init__(self, commission_per_share: float, minimum: float = 0.0):
        if commission_per_share < 0 or minimum < 0:
            raise ValueError("commission_per_share and minimum must both be >= 0")
        self._per_share = commission_per_share
        self._minimum = minimum

    def compute_fees(self, *, side: str, quantity: int, execution_price: float) -> float:
        return max(self._minimum, quantity * self._per_share)


class PercentOfNotionalCommission(TransactionCostModel):
    def __init__(self, pct: float, minimum: float = 0.0):
        if pct < 0 or minimum < 0:
            raise ValueError("pct and minimum must both be >= 0")
        self._pct = pct
        self._minimum = minimum

    def compute_fees(self, *, side: str, quantity: int, execution_price: float) -> float:
        return max(self._minimum, quantity * execution_price * self._pct)


class CompositeCostModel(TransactionCostModel):
    """Sums several cost components — e.g. a broker commission plus a
    regulatory sell-side fee. This is the generic abstraction the
    requirement asks for; ROBINHOOD_EQUITY_COST_MODEL below is one
    example broker-specific configuration built from it, not something
    hardcoded into the engine."""

    def __init__(self, components: list[TransactionCostModel]):
        self._components = list(components)

    def compute_fees(self, *, side: str, quantity: int, execution_price: float) -> float:
        return sum(c.compute_fees(side=side, quantity=quantity, execution_price=execution_price) for c in self._components)


class SellOnlyFee(TransactionCostModel):
    """A fee charged only on sells (e.g. a regulatory transaction fee) —
    zero on buys. Wrap in CompositeCostModel alongside a commission model
    to build a realistic broker profile."""

    def __init__(self, inner: TransactionCostModel):
        self._inner = inner

    def compute_fees(self, *, side: str, quantity: int, execution_price: float) -> float:
        if side != "sell":
            return 0.0
        return self._inner.compute_fees(side=side, quantity=quantity, execution_price=execution_price)


def robinhood_equity_cost_model() -> TransactionCostModel:
    """An EXAMPLE broker profile, not a hardcoded engine default — pass it
    explicitly to a BacktestConfig if you want it. Robinhood charges $0
    commission on equity trades; this models only the small regulatory
    fees (SEC/TAF-style, sell-side only) that a real Robinhood fill still
    carries. The exact current per-share/per-notional rates are NOT
    hardcoded here with false precision (this codebase's own convention is
    to never guess a real financial figure) — this returns a
    CompositeCostModel with $0 commission and a small illustrative
    sell-side fee; verify and replace SellOnlyFee's inner model with
    Robinhood's actual current published fee schedule before trusting
    absolute dollar P&L from a backtest using this profile."""
    return CompositeCostModel(
        [
            PerShareCommission(commission_per_share=0.0),  # Robinhood: $0 equity commission
            SellOnlyFee(PercentOfNotionalCommission(pct=0.0000278, minimum=0.01)),  # illustrative SEC-fee-scale placeholder — verify before trusting
        ]
    )


# ==============================================================================
# SPREAD MODEL (section 7)
# ==============================================================================


@dataclass(frozen=True)
class SpreadQuote:
    bid: float
    ask: float
    source: str  # "real_bid_ask" | "modeled_spread" — NEVER silently mislabeled


class SpreadModel(ABC):
    @abstractmethod
    def quote(self, *, reference_price: float, bar: Bar) -> SpreadQuote:
        raise NotImplementedError


class FixedPercentSpreadModel(SpreadModel):
    """MODELED spread — Bar (this codebase's historical OHLCV shape; see
    src/data/bar.py) carries no real bid/ask, so every equity backtest
    built purely from Bar series uses a modeled spread. This is labeled
    honestly (source="modeled_spread") everywhere it's used — never
    presented as real market microstructure data."""

    def __init__(self, spread_pct: float):
        if spread_pct < 0:
            raise ValueError("spread_pct must be >= 0")
        self._spread_pct = spread_pct

    def quote(self, *, reference_price: float, bar: Bar) -> SpreadQuote:
        half = reference_price * self._spread_pct / 2
        return SpreadQuote(bid=reference_price - half, ask=reference_price + half, source="modeled_spread")


class RealBidAskSpreadModel(SpreadModel):
    """For the (currently hypothetical) case where real bid/ask
    accompanies each bar — e.g. a future Quote-paired historical dataset.
    Falls back to a configured modeled spread, clearly re-labeled, if a
    given bar has no real quote attached."""

    def __init__(self, quotes_by_timestamp: Mapping, fallback: SpreadModel):
        self._quotes = dict(quotes_by_timestamp)
        self._fallback = fallback

    def quote(self, *, reference_price: float, bar: Bar) -> SpreadQuote:
        real = self._quotes.get(bar.timestamp)
        if real is not None and real.bid is not None and real.ask is not None:
            return SpreadQuote(bid=real.bid, ask=real.ask, source="real_bid_ask")
        return self._fallback.quote(reference_price=reference_price, bar=bar)


def spread_adjusted_price(spread_model: SpreadModel, *, reference_price: float, side: str, bar: Bar) -> tuple[float, str]:
    """BUY -> ask, SELL -> bid, per this phase's exact requirement. Returns
    (price, source)."""
    q = spread_model.quote(reference_price=reference_price, bar=bar)
    return (q.ask, q.source) if side == "buy" else (q.bid, q.source)
