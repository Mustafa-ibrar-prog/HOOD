"""Data shapes for the Polymarket BTC 15-minute system. No options concepts
(strikes, expirations, Greeks) — a Polymarket binary market is one
question ("Will BTC be up at <close_time>?") with exactly two
complementary ERC-1155 tokens (YES, NO) that always sum to $1.00 at
resolution, traded on a central limit order book priced in USDC.

Deliberately independent of the `polymarket` SDK's own pydantic models
(``polymarket.models.clob.*``) — client.py converts real SDK responses
into these plain dataclasses at the boundary. That keeps everything
downstream of client.py (risk.py, strategy.py, gateway.py, engine.py,
and their tests) free of the SDK dependency, so pure-logic tests run
without it installed, and keeps this module the one place that defines
what "filled" actually means for this system.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

_SIDES = frozenset({"BUY", "SELL"})
_OUTCOMES = frozenset({"YES", "NO"})
_ORDER_TYPES = frozenset({"FOK", "FAK"})

# The ground truth for "what happened to an order," independent of
# whatever vocabulary the exchange's own API uses for a given response
# (client.py translates into this set — see client.py's
# _classify_fill_status). "unknown" is the fail-closed default: nothing
# downstream may treat "unknown" as a fill.
FillStatus = str  # one of _FILL_STATUSES, kept as `str` (not a strict Literal) so a
# genuinely novel exchange status can still be logged/stored instead of crashing.
_FILL_STATUSES = frozenset({
    "filled", "partially_filled", "resting", "cancelled", "rejected", "expired", "unknown",
})
# Statuses where filled_shares, if > 0, is trustworthy enough to open/grow a position.
FILLED_STATUSES = frozenset({"filled", "partially_filled"})

PENDING_STATUSES = frozenset({"awaiting_approval", "submitted", "rejected", "expired", "failed"})

_SIGNAL_DIRECTIONS = frozenset({"bullish", "bearish", "neutral"})


@dataclass(frozen=True)
class Signal:
    """One self-contained piece of market evidence — the uniform shape
    every input to the BTC/Polymarket intelligence engine (see
    btc_intelligence.py) is wrapped in before it's shown to a human or
    an LLM explaining the decision: where it came from, when it was
    observed, its raw value, which way it points, and how much weight
    it deserves. This is deliberately NOT the only internal
    representation signals are scored in — evaluate_momentum()
    (src/strategy/evidence.py) still does the actual STRENGTHENING/
    WEAKENING/REVERSING scoring from its own typed MomentumEvidence
    fields, reused unmodified — Signal exists for AUDITABILITY (so
    every signal that went into a decision can be listed, source and
    all) and for signals that fall outside evaluate_momentum's existing
    fields entirely (Polymarket's own order-book microstructure).

    `confidence` is 0.0-1.0, this signal's own weight/reliability — NOT
    a probability that BTC goes up. A signal with incomplete or stale
    backing data should carry a low confidence rather than being
    omitted silently.
    """

    source: str  # e.g. "btc_rsi", "btc_macd_histogram", "polymarket_order_book_imbalance"
    timestamp: datetime
    value: float | bool | None
    direction: str  # "bullish" | "bearish" | "neutral"
    confidence: float

    def __post_init__(self) -> None:
        if self.direction not in _SIGNAL_DIRECTIONS:
            raise ValueError(f"direction must be one of {sorted(_SIGNAL_DIRECTIONS)}, got {self.direction!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "timestamp": self.timestamp.isoformat(), "value": self.value,
            "direction": self.direction, "confidence": self.confidence,
        }


@dataclass(frozen=True)
class BookLevel:
    """One price level of an order book, in this system's own
    best-first convention (client.py normalizes the SDK's raw
    ascending-bids/descending-asks-with-best-at-[-1] shape into this)."""

    price: float
    size: float  # shares


@dataclass(frozen=True)
class OrderBookSnapshot:
    """One outcome token's own order book — NOT shared between YES and
    NO. Polymarket's CLOB books each ERC-1155 token independently (they
    stay near-complementary via arbitrage, but are never guaranteed to
    be exact mirrors), so a NO entry must check NO's own book, not
    `1 - YES`."""

    token_id: str
    bids: tuple[BookLevel, ...]  # best (highest) bid first
    asks: tuple[BookLevel, ...]  # best (lowest) ask first
    fetched_at: datetime
    # Optional market-statistics fields, populated ONLY on the US venue
    # from Polymarket US's own MarketBook.stats block (us_client.py's
    # get_order_book() already fetches this response for bids/asks —
    # these are additional fields from that SAME response, previously
    # parsed and discarded). None on the international venue (whose
    # book response has no equivalent block) or whenever the US venue's
    # own stats block is itself absent/empty — never fabricated.
    # last_trade_price/shares_traded are this system's one source for a
    # real (if coarse) executed-trade/activity signal — see
    # btc_intelligence.py's assess_polymarket_microstructure().
    last_trade_price: float | None = None
    shares_traded: float | None = None
    session_high: float | None = None
    session_low: float | None = None
    open_interest: float | None = None

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return round((self.best_bid + self.best_ask) / 2, 4)

    @property
    def spread_pct(self) -> float | None:
        m = self.mid
        if m is None or m <= 0 or self.best_bid is None or self.best_ask is None:
            return None
        return round((self.best_ask - self.best_bid) / m, 4)

    @property
    def data_age_seconds(self) -> float:
        now = datetime.now(timezone.utc)
        fetched = self.fetched_at if self.fetched_at.tzinfo else self.fetched_at.replace(tzinfo=timezone.utc)
        return (now - fetched).total_seconds()

    def executable_liquidity_usd(self, *, side: str, max_price: float | None = None) -> float:
        """Total USD notional resting on the side of the book a BUY of
        this token would consume (the asks), restricted to levels at or
        below `max_price` (a level priced above what we're willing to
        pay isn't liquidity we can actually use). `side` is the side of
        OUR order ("BUY"/"SELL") — a BUY consumes asks, a SELL consumes
        bids.

        This is the precise, executable definition behind
        POLYMARKET_MIN_ORDER_BOOK_LIQUIDITY_USD — see risk.py and
        .env.polymarket.example. An empty or one-sided book (the side we
        need has no levels) correctly returns 0.0, never raises.
        """
        if side not in _SIDES:
            raise ValueError(f"side must be one of {sorted(_SIDES)}, got {side!r}")
        levels = self.asks if side == "BUY" else self.bids
        total = 0.0
        for level in levels:
            if max_price is not None and level.price > max_price:
                continue
            total += level.price * level.size
        return total

    def executable_shares(self, *, side: str, min_price: float | None = None, max_price: float | None = None) -> float:
        """Total SHARE size resting on the side of the book an order of
        this type would consume, restricted to levels at or better than
        the given price bound. Deliberately a separate method from
        executable_liquidity_usd (which sums price*size, a USD notional,
        and only supports a `max_price` ceiling): a profit-target SELL
        needs a share-count floor check ("is there at least N shares of
        BID depth at or above my minimum acceptable price"), which is a
        different question with a different (opposite-direction) price
        filter — reusing the BUY-oriented ceiling for a SELL floor would
        silently check the wrong levels.

        `side` is the side of OUR order: a BUY consumes asks (optionally
        bounded above by `max_price`), a SELL consumes bids (optionally
        bounded below by `min_price`). An empty or one-sided book
        correctly returns 0.0, never raises.
        """
        if side not in _SIDES:
            raise ValueError(f"side must be one of {sorted(_SIDES)}, got {side!r}")
        levels = self.asks if side == "BUY" else self.bids
        total = 0.0
        for level in levels:
            if max_price is not None and level.price > max_price:
                continue
            if min_price is not None and level.price < min_price:
                continue
            total += level.size
        return total


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
    # Best bid/ask for the YES token, in dollars (0.00-1.00), used ONLY
    # by strategy.py's directional signal. NO's own real book
    # (OrderBookSnapshot, fetched separately for the specific outcome
    # about to be traded) is what sizing/liquidity checks use — see
    # engine.py. Approximating NO as `1 - YES` here would be fine for a
    # directional signal but wrong for a real liquidity/price check.
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
    src/strategy/base.py's SetupCandidate, but for one binary market.
    `suggested_entry_price` is a reference price for sizing only; the
    actual order's hard ceiling is `OrderRequest.max_price`, computed by
    engine.py from the real order book, not from this estimate."""

    market: BinaryMarket
    thesis: TradeThesis
    suggested_entry_price: float  # dollars per share, the ask (YES) or (1 - bid) (NO) being bought
    suggested_size_usd: float


@dataclass(frozen=True)
class OrderRequest:
    """A request to BUY or SELL shares of one outcome token. BUY opens/
    grows a position (see positions.py's module docstring on
    hold-to-resolution); SELL closes an existing one (see
    exit_manager.py) — never a naked short, always sized to at most the
    position's own remaining filled_shares.

    `order_type` defaults to FOK (fill-or-kill): the order either fills
    completely at a price no worse than `max_price`, or nothing happens
    at all. This is the deterministic-execution choice Task 3 asks for
    — it eliminates the ambiguous "partially filled a market order"
    case for new entries by construction. FAK (fill-and-kill: fill what
    you can, cancel the rest) is supported for callers that explicitly
    want partial fills; the reconciliation path (reconciliation.py)
    handles both correctly either way, never assuming either outcome.

    `quantity` is the EXACT share count for a SELL (exit) order — set
    directly from the position's own filled_shares, never derived from
    size_usd/max_price via floor division: reconstructing a share count
    that way was verified (via a 100k-trial randomized check) to
    mismatch the intended quantity roughly half the time under
    ordinary floating-point imprecision. BUY orders leave this None and
    keep deriving shares from size_usd/max_price exactly as before.
    `closes_client_order_id` links a SELL back to the PendingLiveOrder
    (by its own `id`) of the position being closed — see
    exit_manager.py's idempotency guard, which refuses to submit a
    second exit referencing the same id.
    """

    # condition_id/close_time are never sent to the exchange (client.py's
    # place_order only uses token_id/side/size_usd/max_price/order_type)
    # — they exist so a PendingLiveOrder, once persisted, is a
    # SELF-CONTAINED record of everything reconciliation.py needs to
    # build an OpenPosition or look up a resolution, with no dependency
    # on the original BinaryMarket object still being in memory. That
    # matters specifically because reconciliation must work standalone
    # after a restart (Task 5), when nothing but the pending-order file
    # on disk still exists.
    condition_id: str
    token_id: str
    outcome: str
    side: str
    size_usd: float
    max_price: float  # hard ceiling (BUY) the exchange will not cross — see SignedOrder max_price/min_price
    close_time: datetime
    reason: str
    order_type: str = "FOK"
    ref_id: str | None = None
    quantity: int | None = None
    closes_client_order_id: str | None = None

    def __post_init__(self) -> None:
        if self.outcome not in _OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(_OUTCOMES)}, got {self.outcome!r}")
        if self.side not in _SIDES:
            raise ValueError(f"side must be one of {sorted(_SIDES)}, got {self.side!r}")
        if self.order_type not in _ORDER_TYPES:
            raise ValueError(f"order_type must be one of {sorted(_ORDER_TYPES)}, got {self.order_type!r}")
        if not 0.0 < self.max_price < 1.0:
            raise ValueError("max_price must be between 0.0 and 1.0 (exclusive) — Polymarket shares never trade at or past the bounds")
        if self.size_usd <= 0:
            raise ValueError("size_usd must be > 0")
        if self.quantity is not None and self.quantity <= 0:
            raise ValueError("quantity must be > 0 when set")

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id, "token_id": self.token_id, "outcome": self.outcome, "side": self.side,
            "size_usd": self.size_usd, "max_price": self.max_price, "close_time": self.close_time.isoformat(),
            "reason": self.reason, "order_type": self.order_type, "ref_id": self.ref_id,
            "quantity": self.quantity, "closes_client_order_id": self.closes_client_order_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OrderRequest":
        return cls(
            condition_id=data["condition_id"], token_id=data["token_id"], outcome=data["outcome"], side=data["side"],
            size_usd=float(data["size_usd"]), max_price=float(data["max_price"]),
            close_time=datetime.fromisoformat(data["close_time"]),
            reason=data.get("reason", ""), order_type=data.get("order_type", "FOK"),
            ref_id=data.get("ref_id"),
            quantity=data.get("quantity"), closes_client_order_id=data.get("closes_client_order_id"),
        )


@dataclass(frozen=True)
class FillResult:
    """The authoritative answer to "what actually happened to this
    order" — produced only by reconciliation.py from a real, fresh
    lookup of the order's current state on the exchange (never derived
    from the original post-order response alone). This is the ONLY
    type positions.py's OpenPosition may be constructed from.

    `status="unknown"` is the fail-closed default for any response this
    system can't confidently interpret — callers must treat it exactly
    like "not filled," never as a fill.
    """

    order_id: str
    status: str  # one of _FILL_STATUSES
    requested_shares: float
    filled_shares: float
    avg_fill_price: float | None  # None iff filled_shares == 0
    raw: Mapping[str, Any] = field(default_factory=dict)
    # Actual exit commission/fee charged by the exchange for this fill,
    # in USD, when the API reports one (e.g. Polymarket US's
    # commissionNotionalTotalCollected) — see us_client.get_fill_status.
    # None means "not reported," never "zero": exit_manager.py must not
    # treat an absent fee as a known $0 fee when computing net P&L.
    fee_usd: float | None = None

    def __post_init__(self) -> None:
        if self.status not in _FILL_STATUSES:
            raise ValueError(f"status must be one of {sorted(_FILL_STATUSES)}, got {self.status!r}")
        if self.filled_shares < 0:
            raise ValueError("filled_shares must be >= 0")
        if self.filled_shares > 0 and self.avg_fill_price is None:
            raise ValueError("avg_fill_price is required whenever filled_shares > 0")
        if self.status not in FILLED_STATUSES and self.filled_shares != 0:
            raise ValueError(f"status={self.status!r} must have filled_shares == 0")

    @property
    def is_fill(self) -> bool:
        """True only when this result may be used to open/grow a
        position. Deliberately conservative: "resting"/"unknown" are
        NOT fills even though a later reconciliation pass might find
        one — see FILLED_STATUSES."""
        return self.status in FILLED_STATUSES and self.filled_shares > 0


@dataclass(frozen=True)
class SubmissionOutcome:
    """The immediate result of posting an order — deliberately NOT a
    fill determination. `exchange_order_id` is set whenever the
    exchange accepted the order for processing, regardless of whether
    anything has matched yet; reconciliation.py uses it to look up the
    authoritative FillResult. ok=False (rejected outright, e.g.
    fok_not_filled/not_enough_balance) always has exchange_order_id=None
    — there is nothing to reconcile for an order the exchange never
    accepted."""

    ok: bool
    exchange_order_id: str | None
    raw_status: str | None  # exchange's own status word ("matched"/"live"/"delayed"), if ok
    error_code: str | None = None  # exchange's own error code, if not ok
    error_message: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderResult:
    """What gateway.py hands back to a caller. `status` describes the
    SUBMISSION outcome only ("how far did this get"), never a fill —
    see fill_result for that. A caller that wants to know whether a
    position should exist must look at fill_result.is_fill, never at
    status alone."""

    status: str  # "simulated_fill" | "awaiting_approval" | "submitted" | "rejected" | "failed"
    request: OrderRequest
    submission: SubmissionOutcome | None = None
    fill_result: FillResult | None = None
    error: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PendingLiveOrder:
    """Mirrors src/execution/pending.py's PendingLiveOrder in spirit — a
    real order is NEVER placed by the method that creates this record;
    only confirm_and_place() (or auto-execute, if enabled) can
    transition it onward. `exchange_order_id` and `fill_reconciled` are
    the two fields reconciliation.py relies on for idempotency (see
    that module): once `fill_reconciled` is True, reconciling this
    pending order again is a guaranteed no-op, even across a restart.
    """

    id: str
    order: OrderRequest
    status: str  # one of PENDING_STATUSES
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    error: str | None = None
    exchange_order_id: str | None = None
    fill_reconciled: bool = False

    def __post_init__(self) -> None:
        if self.status not in PENDING_STATUSES:
            raise ValueError(f"status must be one of {sorted(PENDING_STATUSES)}, got {self.status!r}")

    @classmethod
    def new(cls, *, order: OrderRequest, expiry_seconds: int, now: datetime | None = None) -> "PendingLiveOrder":
        now = now or datetime.now(timezone.utc)
        return cls(
            id=str(uuid.uuid4()), order=order, status="awaiting_approval",
            created_at=now, expires_at=now + timedelta(seconds=expiry_seconds),
        )

    def with_status(
        self, status: str, *, decided_at: datetime | None = None, decided_by: str | None = None,
        error: str | None = None, exchange_order_id: str | None = None, fill_reconciled: bool | None = None,
    ) -> "PendingLiveOrder":
        return replace(
            self, status=status,
            decided_at=decided_at if decided_at is not None else self.decided_at,
            decided_by=decided_by if decided_by is not None else self.decided_by,
            error=error if error is not None else self.error,
            exchange_order_id=exchange_order_id if exchange_order_id is not None else self.exchange_order_id,
            fill_reconciled=fill_reconciled if fill_reconciled is not None else self.fill_reconciled,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "order": self.order.to_dict(), "status": self.status,
            "created_at": self.created_at.isoformat(), "expires_at": self.expires_at.isoformat(),
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decided_by": self.decided_by, "error": self.error,
            "exchange_order_id": self.exchange_order_id, "fill_reconciled": self.fill_reconciled,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PendingLiveOrder":
        return cls(
            id=data["id"], order=OrderRequest.from_dict(data["order"]), status=data["status"],
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            decided_at=datetime.fromisoformat(data["decided_at"]) if data.get("decided_at") else None,
            decided_by=data.get("decided_by"), error=data.get("error"),
            exchange_order_id=data.get("exchange_order_id"),
            fill_reconciled=bool(data.get("fill_reconciled", False)),
        )
