"""Real BTC spot price history for the Polymarket dynamic-exit system
(see btc_intelligence.py) — built from scratch because, unlike equities
(mcp__HOOD__get_equity_historicals), there is NO OHLCV/candle endpoint
for crypto anywhere in this codebase's reach. The only crypto data
source is mcp__HOOD__get_crypto_quotes: real-time bid/ask/mark plus the
previous close — a point-in-time QUOTE, never a series, and carrying NO
volume field at all (confirmed by inspecting that tool's real schema).

THE HARD CONSTRAINT THIS MODULE IS BUILT AROUND: HOOD MCP tools can
only be invoked by an agent's own tool-call turn — never by a plain
Python process running unattended. This is explicitly documented in
src/market/hood_client.py's own module docstring ("nothing in this
codebase calls a HOOD MCP tool directly... there is no Python SDK
binding for them inside a plain Python process"), which is exactly why
the existing options position-monitor (src/position_manager/) is
agent-driven rather than an unattended loop, unlike
scripts/run_polymarket_bot.py (which works unattended only because
client.py/us_client.py call the Polymarket SDKs' real HTTP endpoints
directly, with zero agent involvement needed per cycle).

So real BTC spot data CANNOT be polled from inside the Polymarket bot's
own unattended loop. The architecture here is deliberately an
INJECTABLE SEAM, not a live poller:

  - BtcQuoteSource (below) is the exact same seam pattern as
    HoodToolClient: a Protocol that whatever component can actually
    reach the MCP tool (or relay to the agent that can) would
    implement. No production implementation of it exists in this
    codebase yet — intentionally deferred (see scripts/feed_btc_quote.py's
    docstring for the interim, manual/agent-assisted path that exists
    instead).
  - BtcPriceHistoryStore is a plain, file-persisted rolling buffer that
    ANYTHING can feed a (price, timestamp) sample into — an agent that
    just called get_crypto_quotes, a future automated bridge, or a
    human pasting a number. It aggregates those raw samples into real
    PriceBar OHLC bars (src/market/models.py — the same generic bar
    type the options side's indicators already use) purely from
    arithmetic over what was actually fed in. Volume is ALWAYS 0 for
    every BTC-sourced bar (get_crypto_quotes has no volume field) —
    never fabricated, and this module's own vwap()/volume_ratio
    consumers already treat a zero/absent-volume series as "no signal"
    rather than guessing (see market/indicators.vwap, which returns
    None for zero total volume).
  - Until something actually feeds it, get_bars() legitimately returns
    too little (or no) history. btc_intelligence.py's
    build_btc_momentum_evidence() then correctly produces
    INSUFFICIENT_DATA — never a fabricated read — and the dynamic-exit
    cascade HOLDs, deferring to the existing profit-target-as-soft-signal
    and settlement-fallback paths. This is intentional, not a bug: a
    system with no real evidence yet must do nothing, not guess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from src.market.models import PriceBar


class BtcPriceHistoryStoreError(RuntimeError):
    pass


class BtcQuoteSource(Protocol):
    """Mirrors mcp__HOOD__get_crypto_quotes's real request/response
    shape exactly, the same way src/market/hood_client.py's
    HoodToolClient mirrors its own tools — see module docstring for why
    no production implementation of this exists yet."""

    def get_crypto_quotes(self, symbols: list[str]) -> dict[str, Any]: ...


def extract_mark_price(quotes_response: dict[str, Any], symbol: str) -> float | None:
    """Pulls the mark price for `symbol` out of a raw get_crypto_quotes-
    shaped response. Returns None (never 0.0 or a guess) if the symbol
    isn't present or carries no mark price — response shape per the
    tool's own documented fields, matched on the unhyphenated symbol
    form the tool returns (e.g. "BTC-USD" in, "BTCUSD" back)."""
    target = symbol.upper().replace("-", "")
    for quote in quotes_response.get("results") or quotes_response.get("quotes") or []:
        if str(quote.get("symbol", "")).upper().replace("-", "") != target:
            continue
        mark = quote.get("mark_price") or quote.get("mark")
        if mark is None:
            return None
        return float(mark)
    return None


@dataclass(frozen=True)
class BtcQuoteSample:
    price: float
    observed_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {"price": self.price, "observed_at": self.observed_at.isoformat()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BtcQuoteSample":
        return cls(price=float(data["price"]), observed_at=datetime.fromisoformat(data["observed_at"]))


class BtcPriceHistoryStore:
    """File-persisted rolling buffer of raw BTC quote samples, same
    fail-closed convention as every other store in this package
    (PolymarketPositionStore/PolymarketPendingOrderStore): a corrupted
    file raises rather than silently resetting to empty history, which
    could otherwise let a real INSUFFICIENT_DATA state be silently
    papered over by a freshly-emptied, equally-insufficient one without
    anyone noticing the file was ever corrupted.

    Samples older than `retention_seconds` are pruned on every write —
    bounded growth, since nothing here ever needs more history than a
    few indicator-warmup windows' worth (see get_bars's interval/period
    math) regardless of how long the position/bot has been running.
    """

    def __init__(self, path: Path, *, retention_seconds: float = 6 * 3600):
        self._path = path
        self._retention_seconds = retention_seconds

    def load(self) -> list[BtcQuoteSample]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        try:
            return [BtcQuoteSample.from_dict(row) for row in json.loads(raw)]
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise BtcPriceHistoryStoreError(f"BTC price history file is corrupted or unreadable: {exc}") from exc

    def save(self, samples: list[BtcQuoteSample]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps([s.to_dict() for s in samples], indent=2, sort_keys=True))

    def record_quote(self, price: float, *, at: datetime | None = None) -> BtcQuoteSample:
        """The ONLY way this store's contents grow. Appends one raw
        sample and prunes anything older than retention_seconds
        (relative to `at`, so this stays deterministic/testable rather
        than depending on wall-clock time at prune time)."""
        at = at or datetime.now(timezone.utc)
        if price <= 0:
            raise ValueError("price must be > 0")
        sample = BtcQuoteSample(price=price, observed_at=at)
        samples = self.load()
        samples.append(sample)
        cutoff = at - timedelta(seconds=self._retention_seconds)
        samples = [s for s in samples if _as_utc(s.observed_at) >= cutoff]
        samples.sort(key=lambda s: s.observed_at)
        self.save(samples)
        return sample

    def get_bars(self, *, interval_seconds: int = 60, now: datetime | None = None) -> list[PriceBar]:
        """Aggregates the persisted raw samples into real OHLC bars,
        oldest first. Only FULLY CLOSED buckets are returned (a bucket
        whose end time is <= `now`) — the bucket still in progress is
        never included, so the same point in time never produces a
        "final" bar that later changes shape as more samples land in
        it. volume is always 0 (get_crypto_quotes has no volume field —
        see module docstring; never fabricated).

        Returns [] (never raises) when there are no samples yet —
        exactly the "not enough data" case build_btc_momentum_evidence()
        must turn into INSUFFICIENT_DATA, not a guess.
        """
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")
        now = now or datetime.now(timezone.utc)
        samples = self.load()
        if not samples:
            return []

        buckets: dict[int, list[BtcQuoteSample]] = {}
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        for sample in samples:
            bucket_index = int((_as_utc(sample.observed_at) - epoch).total_seconds() // interval_seconds)
            buckets.setdefault(bucket_index, []).append(sample)

        current_bucket = int((now - epoch).total_seconds() // interval_seconds)
        bars: list[PriceBar] = []
        for bucket_index in sorted(buckets):
            if bucket_index >= current_bucket:
                continue  # still in progress -- never return a half-formed bar
            bucket_samples = sorted(buckets[bucket_index], key=lambda s: s.observed_at)
            prices = [s.price for s in bucket_samples]
            bar_start = epoch + timedelta(seconds=bucket_index * interval_seconds)
            bars.append(PriceBar(
                start_time=bar_start, open=prices[0], high=max(prices), low=min(prices),
                close=prices[-1], volume=0,
            ))
        return bars


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
