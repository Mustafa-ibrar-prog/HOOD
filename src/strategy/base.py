"""Setup-scanning framework.

This defines the *shape* of a strategy and the candidates it produces. No
concrete strategy is implemented yet — that's future work once a real
MarketDataProvider is wired to the HOOD MCP tools (see
src/market/data_provider.py).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Sequence

from src.strategy.decision import TradeThesis

if TYPE_CHECKING:
    from src.market.data_provider import MarketDataProvider


@dataclass(frozen=True)
class SetupCandidate:
    """A potential new trade found by a Strategy during a scan.

    This is a proposal only. It still has to pass through the risk manager
    (position sizing, daily limits, spread/liquidity, cutoff time, ...)
    before it could ever become a BUY decision that reaches execution.
    """

    underlying_symbol: str
    option_id: str
    option_description: str
    side: str  # "long_call" or "long_put" — Level 2 single-leg only, for now
    thesis: TradeThesis
    suggested_entry_price: float
    suggested_quantity: int
    profit_target_usd: float
    stop_loss_usd: float
    expiration: date
    score: float  # higher = more attractive; strategy-defined scale
    signals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.side not in {"long_call", "long_put"}:
            raise ValueError("side must be 'long_call' or 'long_put'")
        if self.suggested_entry_price <= 0:
            raise ValueError("suggested_entry_price must be > 0")
        if self.suggested_quantity <= 0:
            raise ValueError("suggested_quantity must be > 0")


class Strategy(ABC):
    """Base class for a setup-scanning strategy.

    Implementations should be pure with respect to the MarketDataProvider
    they're given — no side effects, no direct MCP calls, no order
    placement. That keeps strategies unit-testable against a fake provider.
    """

    name: str = "unnamed-strategy"

    @abstractmethod
    def scan(self, market: "MarketDataProvider", universe: Sequence[str]) -> list[SetupCandidate]:
        """Return zero or more SetupCandidate proposals for the given
        universe of underlying symbols. Must not raise for "no setups
        found" — return an empty list instead.
        """
        raise NotImplementedError
