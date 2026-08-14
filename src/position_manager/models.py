"""The open-position record the position manager evaluates every cycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Mapping

from src.config.constants import CONTRACT_MULTIPLIER
from src.strategy.decision import TradeThesis


@dataclass(frozen=True)
class OpenPosition:
    symbol: str  # underlying ticker
    option_id: str  # instrument UUID
    option_description: str  # e.g. "AAPL 2026-09-18 C 230"
    side: str  # "long_call" | "long_put"
    quantity: int
    entry_price: float  # premium per contract, at entry
    entry_time: datetime
    thesis: TradeThesis
    profit_target_usd: float
    stop_loss_usd: float
    expiration: date
    contract_multiplier: int = CONTRACT_MULTIPLIER

    def __post_init__(self) -> None:
        if self.side not in {"long_call", "long_put"}:
            raise ValueError("side must be 'long_call' or 'long_put'")
        if self.quantity <= 0:
            raise ValueError("quantity must be > 0")
        if self.entry_price <= 0:
            raise ValueError("entry_price must be > 0")
        if self.profit_target_usd <= 0:
            raise ValueError("profit_target_usd must be > 0")
        if self.stop_loss_usd <= 0:
            raise ValueError("stop_loss_usd must be > 0 (expressed as a positive max-loss amount)")

    @property
    def size_usd(self) -> float:
        """Capital committed at entry."""
        return self.entry_price * self.quantity * self.contract_multiplier

    def unrealized_pnl_usd(self, current_price: float) -> float:
        # Rounded to the cent: this is a currency figure feeding threshold
        # comparisons (profit target, stop loss), and raw binary-float
        # arithmetic on prices like 1.15 - 0.95 can land a fraction of a
        # cent off exact, which would wrongly miss an exact-target/stop hit.
        return round((current_price - self.entry_price) * self.quantity * self.contract_multiplier, 2)

    def unrealized_pnl_pct(self, current_price: float) -> float:
        if self.entry_price == 0:
            return 0.0
        return (current_price - self.entry_price) / self.entry_price

    def minutes_to_expiration(self, now: datetime, market_close: time = time(16, 0)) -> float:
        """Minutes remaining until the contract's expiration-day market
        close. Assumes `now` and the returned value share the same
        (naive-local or otherwise consistent) time reference as `market_close`
        — callers should pass `now` in the same timezone convention used
        elsewhere (see Settings.market_timezone)."""
        expiration_dt = datetime.combine(self.expiration, market_close, tzinfo=now.tzinfo)
        return (expiration_dt - now).total_seconds() / 60

    def to_dict(self) -> dict[str, Any]:
        """For persistence — see position_manager/store.py (the paper
        position ledger)."""
        return {
            "symbol": self.symbol,
            "option_id": self.option_id,
            "option_description": self.option_description,
            "side": self.side,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat(),
            "thesis": self.thesis.to_dict(),
            "profit_target_usd": self.profit_target_usd,
            "stop_loss_usd": self.stop_loss_usd,
            "expiration": self.expiration.isoformat(),
            "contract_multiplier": self.contract_multiplier,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OpenPosition":
        entry_time = datetime.fromisoformat(data["entry_time"])
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
        return cls(
            symbol=data["symbol"],
            option_id=data["option_id"],
            option_description=data["option_description"],
            side=data["side"],
            quantity=int(data["quantity"]),
            entry_price=float(data["entry_price"]),
            entry_time=entry_time,
            thesis=TradeThesis.from_dict(data["thesis"]),
            profit_target_usd=float(data["profit_target_usd"]),
            stop_loss_usd=float(data["stop_loss_usd"]),
            expiration=date.fromisoformat(data["expiration"]),
            contract_multiplier=int(data.get("contract_multiplier", CONTRACT_MULTIPLIER)),
        )
