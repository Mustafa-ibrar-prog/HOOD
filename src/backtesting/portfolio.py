"""Position and cash accounting for the backtesting engine (Phase 3,
sections 8-10). Long-only today, deliberately — see Position's docstring
for why short selling is refused rather than silently half-implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


class PortfolioError(RuntimeError):
    """Raised on an impossible accounting state (overspending cash,
    overselling a position). Fails closed — same convention as every other
    store/ledger in this codebase — rather than silently clamping to
    something that hides a real bug in the caller."""


@dataclass
class Position:
    """A single long equity position. Short selling is explicitly OUT OF
    SCOPE for this phase (per the requirement: "if short selling is not
    currently supported, DO NOT silently implement it") — `quantity` is
    enforced to never go negative, and there is no sell-to-open path
    anywhere in this module. A future short-selling extension would add a
    parallel, explicitly-named path rather than silently overloading this
    one."""

    symbol: str
    quantity: int = 0
    avg_entry_price: float = 0.0

    def cost_basis(self) -> float:
        return self.quantity * self.avg_entry_price

    def market_value(self, price: float) -> float:
        return self.quantity * price

    def unrealized_pnl(self, price: float) -> float:
        return self.market_value(price) - self.cost_basis()


@dataclass(frozen=True)
class EquityPoint:
    """One row of the equity curve (Phase 3, section 16)."""

    timestamp: datetime
    equity: float
    cash: float
    positions_value: float
    gross_exposure: float  # sum of |market value| across positions (== positions_value, long-only)
    net_exposure: float  # signed sum of market value across positions (== positions_value, long-only)
    drawdown: float  # equity - peak_equity, always <= 0
    drawdown_pct: float  # drawdown / peak_equity, always <= 0
    open_position_count: int = 0
    position_weights: dict[str, float] = field(default_factory=dict)  # symbol -> market_value/equity, for concentration


class Portfolio:
    def __init__(self, starting_cash: float, *, allow_negative_cash: bool = False):
        if starting_cash < 0:
            raise ValueError("starting_cash must be >= 0")
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.allow_negative_cash = allow_negative_cash
        self.positions: dict[str, Position] = {}
        self.realized_pnl_total = 0.0
        self.peak_equity = starting_cash
        self.equity_curve: list[EquityPoint] = []

    def position_quantity(self, symbol: str) -> int:
        pos = self.positions.get(symbol)
        return pos.quantity if pos is not None else 0

    def apply_buy_fill(self, *, symbol: str, quantity: int, execution_price: float, fees: float) -> None:
        if quantity <= 0:
            raise PortfolioError(f"cannot buy a non-positive quantity ({quantity})")
        cost = quantity * execution_price + fees
        if not self.allow_negative_cash and cost > self.cash:
            raise PortfolioError(
                f"insufficient cash to buy {quantity} {symbol} @ {execution_price:.4f} "
                f"(+${fees:.2f} fees): needs ${cost:.2f}, have ${self.cash:.2f}"
            )
        pos = self.positions.get(symbol)
        if pos is None:
            self.positions[symbol] = Position(symbol=symbol, quantity=quantity, avg_entry_price=execution_price)
        else:
            new_quantity = pos.quantity + quantity
            # Weighted-average cost basis across the combined position.
            pos.avg_entry_price = (pos.cost_basis() + quantity * execution_price) / new_quantity
            pos.quantity = new_quantity
        self.cash -= cost

    def apply_sell_fill(self, *, symbol: str, quantity: int, execution_price: float, fees: float) -> float:
        """Returns the realized P&L of this specific sell (before fees are
        netted out of cash but AFTER fees are netted out of the returned
        P&L figure, matching how a real fill's net proceeds work)."""
        if quantity <= 0:
            raise PortfolioError(f"cannot sell a non-positive quantity ({quantity})")
        pos = self.positions.get(symbol)
        if pos is None or pos.quantity < quantity:
            held = pos.quantity if pos is not None else 0
            raise PortfolioError(f"cannot sell {quantity} {symbol}: only {held} held (selling more than owned)")

        gross_pnl = (execution_price - pos.avg_entry_price) * quantity
        realized_pnl = gross_pnl - fees
        proceeds = quantity * execution_price - fees

        pos.quantity -= quantity
        if pos.quantity == 0:
            del self.positions[symbol]

        self.cash += proceeds
        self.realized_pnl_total += realized_pnl
        return realized_pnl

    def mark_to_market(self, *, prices: dict[str, float], timestamp: datetime) -> EquityPoint:
        """Values every held position at `prices` (must be prices already
        known AT `timestamp` — the caller's responsibility not to pass a
        future price; see engine.py, which only ever calls this with the
        current bar's own close) and appends one EquityPoint. Never uses
        any price not explicitly supplied."""
        positions_value = 0.0
        market_values: dict[str, float] = {}
        for symbol, pos in self.positions.items():
            price = prices.get(symbol)
            if price is None:
                raise PortfolioError(f"mark_to_market: no price supplied for held position {symbol!r}")
            mv = pos.market_value(price)
            market_values[symbol] = mv
            positions_value += mv

        equity = self.cash + positions_value
        self.peak_equity = max(self.peak_equity, equity)
        drawdown = equity - self.peak_equity
        drawdown_pct = (drawdown / self.peak_equity) if self.peak_equity > 0 else 0.0
        weights = {sym: (mv / equity if equity > 0 else 0.0) for sym, mv in market_values.items()}

        point = EquityPoint(
            timestamp=timestamp,
            equity=equity,
            cash=self.cash,
            positions_value=positions_value,
            gross_exposure=positions_value,
            net_exposure=positions_value,
            drawdown=drawdown,
            drawdown_pct=drawdown_pct,
            open_position_count=len(self.positions),
            position_weights=weights,
        )
        self.equity_curve.append(point)
        return point
