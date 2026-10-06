"""Data shapes for the Polymarket BTC 15-minute system. No options concepts
(strikes, expirations, Greeks) — a Polymarket binary market is one
question ("Will BTC be up at <close_time>?") with exactly two
complementary ERC-1155 tokens (YES, NO) that always sum to $1.00 at
resolution, traded on a central limit order book priced in USDC."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

_ORDER_STATUSES = frozenset({"awaiting_approval", "approved", "rejected", "expired", "placed", "failed", "simulated_fill"})
_SIDES = frozenset({"BUY", "SELL"})
_OUTCOMES = frozenset({"YES", "NO"})


@dataclass(frozen=True)
class BinaryMarket:
    """One Polymarket binary market snapshot. token_id_yes/token_id_no are
    the two ERC-1155 token ids this market's order book trades — every
    order references one of them, never a strike or expiration."""

    condition_id: str
    question: str
    token_id_yes: str
    token_id_no: str
    close_time: datetime
    fetched_at: datetime
    # Best bid/ask for the YES token, in dollars (0.00-1.00). NO's
    # price is implied as (1 - YES), not separately quoted here — see
    # client.py's docstring on why only YES is tracked.
    yes_bid: float | None = None
    yes_ask: float | None = None

    @property
    def data_age_seconds(self) -> float:
        now = datetime.now(timezone.utc)
        fetched = self.fetched_at if self.fetched_at.tzinfo else self.fetched_at.replace(tzinfo=timezone.utc)
        return (now - fetched).total_seconds()

    @property
    def seconds_to_close(self) -> float:
        now = datetime.now(timezone.utc)
        close = self.close_time if self.close_time.tzinfo else self.close_time.replace(tzinfo=timezone.utc)
        return (close - now).total_seconds()

    @property
    def yes_mid(self) -> float | None:
        if self.yes_bid is None or self.yes_ask is None:
            return None
        return round((self.yes_bid + self.yes_ask) / 2, 4)

    @property
    def yes_spread_pct(self) -> float | None:
        mid = self.yes_mid
        if mid is None or mid <= 0 or self.yes_bid is None or self.yes_ask is None:
            return None
        return round((self.yes_ask - self.yes_bid) / mid, 4)

    def token_id_for(self, outcome: str) -> str:
        if outcome not in _OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(_OUTCOMES)}, got {outcome!r}")
        return self.token_id_yes if outcome == "YES" else self.token_id_no


@dataclass(frozen=True)
class TradeThesis:
    """Mirrors src/strategy/decision.py's TradeThesis in spirit (record
    exactly why, not just what), adapted for a binary outcome instead of
    an option contract."""

    outcome: str  # "YES" or "NO"
    catalyst: str
    confidence: float  # 0.0-1.0, strategy's own calibration — not a guarantee

    def __post_init__(self) -> None:
        if self.outcome not in _OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(_OUTCOMES)}, got {self.outcome!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")


@dataclass(frozen=True)
class SetupCandidate:
    """What strategy.py proposes — analogous to
    src/strategy/base.py's SetupCandidate, but for one binary market."""

    market: BinaryMarket
    thesis: TradeThesis
    suggested_entry_price: float  # dollars per share, the ask (YES) or (1 - bid) (NO) being bought
    suggested_size_usd: float


@dataclass(frozen=True)
class OrderRequest:
    """Mirrors src/execution/orders.py's OrderRequest, adapted: a side
    (BUY/SELL) and outcome (YES/NO) instead of option legs."""

    token_id: str
    outcome: str
    side: str
    price: float  # limit price, dollars per share (0.00-1.00)
    size_usd: float
    reason: str
    ref_id: str | None = None

    def __post_init__(self) -> None:
        if self.outcome not in _OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(_OUTCOMES)}, got {self.outcome!r}")
        if self.side not in _SIDES:
            raise ValueError(f"side must be one of {sorted(_SIDES)}, got {self.side!r}")
        if not 0.0 < self.price < 1.0:
            raise ValueError("price must be between 0.0 and 1.0 (exclusive) — Polymarket shares never trade at or past the bounds")
        if self.size_usd <= 0:
            raise ValueError("size_usd must be > 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_id": self.token_id, "outcome": self.outcome, "side": self.side,
            "price": self.price, "size_usd": self.size_usd, "reason": self.reason, "ref_id": self.ref_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OrderRequest":
        return cls(
            token_id=data["token_id"], outcome=data["outcome"], side=data["side"],
            price=float(data["price"]), size_usd=float(data["size_usd"]),
            reason=data.get("reason", ""), ref_id=data.get("ref_id"),
        )


@dataclass(frozen=True)
class OrderResult:
    status: str  # one of _ORDER_STATUSES
    request: OrderRequest
    filled_price: float | None = None
    filled_at: datetime | None = None
    raw: Mapping[str, Any] | None = None
    error: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PendingLiveOrder:
    """Mirrors src/execution/pending.py's PendingLiveOrder exactly in
    spirit — a real order is NEVER placed by the method that creates
    this record; only confirm_and_place() (or auto-execute, if enabled)
    can transition it to "placed"."""

    id: str
    order: OrderRequest
    status: str
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in _ORDER_STATUSES:
            raise ValueError(f"status must be one of {sorted(_ORDER_STATUSES)}, got {self.status!r}")

    @classmethod
    def new(cls, *, order: OrderRequest, expiry_seconds: int, now: datetime | None = None) -> "PendingLiveOrder":
        now = now or datetime.now(timezone.utc)
        return cls(
            id=str(uuid.uuid4()), order=order, status="awaiting_approval",
            created_at=now, expires_at=now + timedelta(seconds=expiry_seconds),
        )

    def with_status(self, status: str, *, decided_at: datetime | None = None, decided_by: str | None = None, error: str | None = None) -> "PendingLiveOrder":
        return replace(
            self, status=status,
            decided_at=decided_at if decided_at is not None else self.decided_at,
            decided_by=decided_by if decided_by is not None else self.decided_by,
            error=error if error is not None else self.error,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "order": self.order.to_dict(), "status": self.status,
            "created_at": self.created_at.isoformat(), "expires_at": self.expires_at.isoformat(),
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decided_by": self.decided_by, "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PendingLiveOrder":
        return cls(
            id=data["id"], order=OrderRequest.from_dict(data["order"]), status=data["status"],
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            decided_at=datetime.fromisoformat(data["decided_at"]) if data.get("decided_at") else None,
            decided_by=data.get("decided_by"), error=data.get("error"),
        )
