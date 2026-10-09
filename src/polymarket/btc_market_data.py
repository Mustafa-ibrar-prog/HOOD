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

UPDATE — a real, unattended, non-MCP path now exists too:
DirectBtcQuoteSource (below) is a SEPARATE, provider-agnostic seam for
a BTC-USD candle source any plain Python process CAN call directly —
no agent, no MCP, works identically on Windows/Linux/Mac. The first
real implementation (CoinbaseBtcQuoteSource, btc_coinbase_source.py)
uses Coinbase Exchange's public, unauthenticated candles endpoint.
bootstrap_btc_price_history() and BtcFeedRefresher (below) are the
orchestration around it: fetch real, provider-given 1-minute candles
with their exact timestamps and real OHLCV (including real volume —
unlike get_crypto_quotes, a direct candle provider actually has
volume; see record_bars()), store them, and refresh on a new-minute
cadence independent of Polymarket's own poll loop. The OLD
BtcQuoteSource/record_quote()/feed_btc_quote.py path is UNCHANGED and
still works standalone — this is additive, not a replacement, so a
second/alternate provider (or the manual bridge) can always be plugged
in without touching anything else in this package.

A feed that goes silent after building real history is a DIFFERENT
failure mode from "never fed at all," and is just as dangerous if
unhandled: without a staleness check, old-but-real bars would keep
being reported as current evidence forever. See compute_feed_status()
below and btc_intelligence.assess_btc_market()'s own max_bar_age_seconds
gate — a bar older than that is treated as equivalent to "no bar,"
forcing INSUFFICIENT_DATA exactly like a feed that was never fed.
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


class DirectBtcQuoteSource(Protocol):
    """Provider-agnostic interface for an unattended, DIRECTLY-callable
    BTC-USD 1-minute-candle source — no agent, no MCP, no Python SDK
    binding required; just an ordinary network call a plain process can
    make on any OS. CoinbaseBtcQuoteSource (btc_coinbase_source.py) is
    the first implementation; a different provider (Binance, Kraken,
    ...) plugs in by implementing this exact same narrow signature —
    nothing else in this package (bootstrap_btc_price_history,
    BtcFeedRefresher, btc_intelligence.py, exit_manager.py) needs to
    change or even know which one is in use.
    """

    name: str  # short, human-readable label (e.g. "coinbase") for BTC_FEED_SOURCE logging

    def get_recent_candles(self, *, limit: int) -> list[PriceBar]:
        """Returns up to `limit` of the most recent available 1-minute
        candles, OLDEST FIRST, with real open/high/low/close/volume and
        the provider's own exact timestamps — never interpolated
        (PriceBar.interpolated is always False from a real provider),
        never fabricated. Implementations should raise on a genuine
        transport/parse failure rather than returning a guessed or
        empty-but-successful result — callers (bootstrap/refresh) treat
        any exception as "temporarily unavailable" and degrade safely,
        never as "confirmed no data."""
        ...


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


_FEED_STATUS_FRESH = "FRESH"
_FEED_STATUS_STALE = "STALE"
_FEED_STATUS_UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class BtcFeedStatus:
    """The answer to "can the BTC evidence engine trust its own most
    recent data point right now" — computed fresh every cycle from
    REAL wall-clock time vs. the real bar's own timestamp, so this is
    correct across a restart with zero extra work (a stale bar is
    still exactly as stale after a restart — see compute_feed_status).
    Logged verbatim (BTC_FEED_SOURCE/BTC_LAST_BAR_TIME/
    BTC_BAR_AGE_SECONDS/BTC_FEED_STATUS) by exit_manager.py every cycle."""

    source: str | None  # None iff status == UNAVAILABLE (no bar at all to attribute)
    last_bar_time: datetime | None
    bar_age_seconds: float | None
    status: str  # one of _FEED_STATUS_FRESH / _FEED_STATUS_STALE / _FEED_STATUS_UNAVAILABLE


def compute_feed_status(
    bars: list[PriceBar], *, max_bar_age_seconds: float, source: str = "manual", now: datetime | None = None,
) -> BtcFeedStatus:
    """UNAVAILABLE when there are no usable bars at all (never fed, or
    a provider outage with nothing yet persisted) — the SAME terminal
    state a missing feed has always produced. STALE when bars exist but
    the newest one is older than `max_bar_age_seconds` — a feed that
    WAS working and then went silent, which a bare "do we have any
    bars" check would miss forever (see module docstring). Only FRESH
    bars are ever usable evidence — see
    btc_intelligence.assess_btc_market()."""
    now = now or datetime.now(timezone.utc)
    if not bars:
        return BtcFeedStatus(source=None, last_bar_time=None, bar_age_seconds=None, status=_FEED_STATUS_UNAVAILABLE)
    last_bar = bars[-1]
    age = (now - _as_utc(last_bar.start_time)).total_seconds()
    status = _FEED_STATUS_FRESH if age <= max_bar_age_seconds else _FEED_STATUS_STALE
    return BtcFeedStatus(source=source, last_bar_time=last_bar.start_time, bar_age_seconds=age, status=status)


def _bar_to_dict(bar: PriceBar) -> dict[str, Any]:
    return {
        "start_time": bar.start_time.isoformat(), "open": bar.open, "high": bar.high, "low": bar.low,
        "close": bar.close, "volume": bar.volume, "interpolated": bar.interpolated,
    }


def _bar_from_dict(data: dict[str, Any]) -> PriceBar:
    return PriceBar(
        start_time=datetime.fromisoformat(data["start_time"]), open=float(data["open"]), high=float(data["high"]),
        low=float(data["low"]), close=float(data["close"]),
        # Deliberately NOT coerced to int: PriceBar.volume is typed int
        # for the options/equities convention (whole shares), which
        # dataclasses never enforce at runtime -- BTC volume is
        # genuinely fractional, and rounding/truncating it would be
        # exactly the kind of fabrication this feature must never do.
        volume=data["volume"], interpolated=bool(data.get("interpolated", False)),
    )


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
        # A sibling file, never the same file as the raw-quote-sample
        # ledger above -- keeps the OLD format (a bare JSON list of
        # samples) byte-for-byte unchanged for anything still using
        # record_quote()/feed_btc_quote.py, while real provider candles
        # (record_bars) get their own, independent, richer storage.
        self._bars_path = path.parent / f"{path.stem}.bars{path.suffix}"

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

    def load_real_bars(self) -> list[PriceBar]:
        if not self._bars_path.is_file():
            return []
        raw = self._bars_path.read_text()
        if not raw.strip():
            return []
        try:
            return [_bar_from_dict(row) for row in json.loads(raw)]
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise BtcPriceHistoryStoreError(f"BTC real-candle history file is corrupted or unreadable: {exc}") from exc

    def save_real_bars(self, bars: list[PriceBar]) -> None:
        self._bars_path.parent.mkdir(parents=True, exist_ok=True)
        self._bars_path.write_text(json.dumps([_bar_to_dict(b) for b in bars], indent=2, sort_keys=True))

    def record_bars(self, bars: list[PriceBar]) -> int:
        """Upserts REAL, provider-given candles (exact OHLCV, exact
        timestamps — never derived from quote samples) keyed by
        start_time. get_bars() always prefers a real candle over
        anything reconstructed from raw quote samples for the SAME
        bucket. Idempotent: calling this again with overlapping
        candles just replaces them — safe on every bootstrap/refresh
        regardless of how much the fetched window overlaps what's
        already stored.

        Same retention policy as raw samples, keyed off the newest
        timestamp in THIS batch (so a bootstrap/refresh call always
        prunes relative to data it just confirmed is current, never
        relative to a possibly-stale `now` the caller forgot to pass).

        Returns the number of candles written (len(bars)) — `bars`
        empty is a legitimate "provider returned nothing new" result,
        not an error."""
        if not bars:
            return 0
        existing = {b.start_time: b for b in self.load_real_bars()}
        for bar in bars:
            existing[bar.start_time] = bar
        newest = max(_as_utc(b.start_time) for b in bars)
        cutoff = newest - timedelta(seconds=self._retention_seconds)
        merged = sorted((b for b in existing.values() if _as_utc(b.start_time) >= cutoff), key=lambda b: b.start_time)
        self.save_real_bars(merged)
        return len(bars)

    def get_bars(self, *, interval_seconds: int = 60, now: datetime | None = None) -> list[PriceBar]:
        """Aggregates the persisted raw samples into real OHLC bars,
        oldest first, PREFERRING a real, provider-given candle
        (record_bars) over one reconstructed from raw quote samples
        whenever both exist for the same bucket — richer, more
        accurate data always wins; the two are never blended for a
        single bucket. Only FULLY CLOSED buckets are returned (a
        bucket whose end time is <= `now`) — the bucket still in
        progress is never included, so the same point in time never
        produces a "final" bar that later changes shape as more data
        lands in it. A quote-reconstructed bar's volume is always 0
        (get_crypto_quotes has no volume field — never fabricated); a
        real candle's volume is whatever the provider actually reported.

        Returns [] (never raises) when there is no data at all yet —
        exactly the "not enough data" case build_btc_momentum_evidence()
        must turn into INSUFFICIENT_DATA, not a guess.
        """
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")
        now = now or datetime.now(timezone.utc)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        current_bucket = int((now - epoch).total_seconds() // interval_seconds)

        real_by_bucket: dict[int, PriceBar] = {}
        for bar in self.load_real_bars():
            bucket_index = int((_as_utc(bar.start_time) - epoch).total_seconds() // interval_seconds)
            real_by_bucket[bucket_index] = bar

        samples = self.load()
        buckets: dict[int, list[BtcQuoteSample]] = {}
        for sample in samples:
            bucket_index = int((_as_utc(sample.observed_at) - epoch).total_seconds() // interval_seconds)
            if bucket_index in real_by_bucket:
                continue  # a real candle already covers this bucket -- never blend partial quote data into it
            buckets.setdefault(bucket_index, []).append(sample)

        bars: list[PriceBar] = []
        for bucket_index in sorted(set(real_by_bucket) | set(buckets)):
            if bucket_index >= current_bucket:
                continue  # still in progress -- never return a half-formed bar
            if bucket_index in real_by_bucket:
                bars.append(real_by_bucket[bucket_index])
                continue
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


def bootstrap_btc_price_history(store: BtcPriceHistoryStore, source: DirectBtcQuoteSource, *, min_bars: int) -> int:
    """Run ONCE at bot startup (see scripts/run_polymarket_bot.py) —
    fetches enough recent 1-minute candles to cover at least `min_bars`
    CLOSED bars (a small buffer beyond `min_bars` absorbs the one
    in-progress bucket get_bars() always excludes) and records them
    with their REAL, provider-given OHLCV and exact timestamps — never
    interpolated, never fabricated.

    Idempotent and safe to call on every startup regardless of whether
    the store already has history: record_bars() upserts by timestamp,
    so a restart with fresh persisted data just re-fetches a small,
    mostly-overlapping window and changes nothing; a restart with
    STALE persisted data gets a real chance to catch back up to fresh.

    Never raises: a provider failure here must not prevent the bot
    from starting at all — see requirement that a temporarily
    unavailable BTC provider never crashes normal Polymarket operation.
    Returns 0 (and leaves the store untouched) on any such failure.
    """
    try:
        candles = source.get_recent_candles(limit=min_bars + 5)
    except Exception:  # noqa: BLE001 - any provider/transport/parse failure -> no bootstrap data, never a crash
        return 0
    if not candles:
        return 0
    return store.record_bars(candles)


@dataclass(frozen=True)
class BtcFeedRefreshResult:
    """The full, inspectable outcome of ONE maybe_refresh() call —
    every call returns one of these; nothing about a refresh attempt
    is ever discarded silently (the pre-this-field version returned a
    bare int, so a persistent provider failure was invisible except as
    its eventual downstream symptom — a climbing BTC_BAR_AGE_SECONDS —
    with no record anywhere of WHY: no request time, no provider
    error, nothing to distinguish "Coinbase timed out" from "Coinbase
    returned no candles" from "never even attempted this cycle").

    `attempted` is False only for the intentional same-minute skip (see
    maybe_refresh's own docstring) — no network call was made, nothing
    else on this result is meaningful. Every OTHER case (success,
    provider exception, empty response, a failure persisting to the
    store) has `attempted=True`, so a caller logging only attempted
    calls (see scripts/run_polymarket_bot.py) never misses a real
    attempt and never spams a log with routine skips.

    `newest_candle_time`/`candle_age_seconds` are populated from the
    candles THIS attempt actually received (never from what was
    already persisted) — age is measured against `now`, the same wall-
    clock moment this call was evaluated at, so a caller can tell
    "fresh" from "stale" (per compute_feed_status's own
    max_bar_age_seconds convention — that threshold is NOT duplicated
    here; this class only reports the raw numbers, callers compare
    them against whatever threshold they already have)."""

    attempted: bool
    now: datetime
    candles_recorded: int
    newest_candle_time: datetime | None
    candle_age_seconds: float | None
    error: str | None


class BtcFeedRefresher:
    """Keeps BTC price history warm across the bot's own poll loop
    WITHOUT hammering the direct provider: only actually calls it once
    a NEW 1-minute bucket has become available since the last attempt
    — independent of, and typically much less frequent than,
    POLYMARKET_POLL_INTERVAL_SECONDS (which this never reads or
    touches — Polymarket's own polling cadence is completely
    unaffected by this class existing at all).

    In-memory only (same spirit as engine.MarketHistory) — a restart
    just re-bootstraps instead (see bootstrap_btc_price_history), which
    is cheap, idempotent, and already handles the "lost all in-memory
    state" case correctly.
    """

    def __init__(self, store: BtcPriceHistoryStore, source: DirectBtcQuoteSource):
        self._store = store
        self._source = source
        self._last_refresh_minute: datetime | None = None

    def maybe_refresh(self, *, now: datetime | None = None) -> BtcFeedRefreshResult:
        """No-ops (makes no network call, `attempted=False`) unless a
        new 1-minute boundary has passed since the last call that
        actually reached the provider — this is the "cache/reuse data
        within the current candle, refresh when a new minute becomes
        available" requirement, enforced here rather than left to the
        caller to get right.

        Never raises: a provider hiccup (or a failure persisting the
        fetched candles) is captured on the returned
        BtcFeedRefreshResult.error rather than propagated — the NEXT
        minute's attempt tries again on its own regardless; see
        compute_feed_status() for how a prolonged outage is actually
        DETECTED and ACTED ON by the exit-decision path (this class is
        purely about call cadence and reporting, not that safety gate
        — nothing here changes the 300s staleness threshold or ever
        reuses stale data)."""
        now = now or datetime.now(timezone.utc)
        current_minute = now.replace(second=0, microsecond=0)
        if self._last_refresh_minute is not None and current_minute <= self._last_refresh_minute:
            # Already attempted this minute -- reuse what's persisted,
            # no new call. Not logged as an "attempt" by design (see
            # this result type's own docstring) -- a caller that wants
            # to confirm maybe_refresh() is being invoked every loop
            # iteration should count CALLS to this method, not
            # attempted=True results, which only happens once a minute.
            return BtcFeedRefreshResult(
                attempted=False, now=now, candles_recorded=0, newest_candle_time=None, candle_age_seconds=None, error=None,
            )
        self._last_refresh_minute = current_minute
        try:
            candles = self._source.get_recent_candles(limit=5)  # a small, cheap catch-up window
        except Exception as exc:  # noqa: BLE001 - provider hiccup -- never crash, never fabricate; report, then skip
            return BtcFeedRefreshResult(
                attempted=True, now=now, candles_recorded=0, newest_candle_time=None, candle_age_seconds=None,
                error=f"{type(exc).__name__}: {exc}",
            )
        if not candles:
            return BtcFeedRefreshResult(
                attempted=True, now=now, candles_recorded=0, newest_candle_time=None, candle_age_seconds=None, error=None,
            )
        newest = max(_as_utc(c.start_time) for c in candles)
        try:
            recorded = self._store.record_bars(candles)
        except Exception as exc:  # noqa: BLE001 - a persistence failure must never crash the bot either
            return BtcFeedRefreshResult(
                attempted=True, now=now, candles_recorded=0, newest_candle_time=newest,
                candle_age_seconds=(now - newest).total_seconds(), error=f"failed to persist candles: {exc}",
            )
        return BtcFeedRefreshResult(
            attempted=True, now=now, candles_recorded=recorded, newest_candle_time=newest,
            candle_age_seconds=(now - newest).total_seconds(), error=None,
        )
