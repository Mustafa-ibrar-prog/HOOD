"""The first real implementation of btc_market_data.DirectBtcQuoteSource:
Coinbase Exchange's public, unauthenticated market-data API. No API
key, no account, no agent/MCP mediation — a plain HTTPS GET any Python
process can make, on Windows, Linux, or Mac, from inside
scripts/run_polymarket_bot.py's own unattended loop.

Endpoint: GET https://api.exchange.coinbase.com/products/BTC-USD/candles
          ?granularity=60
Response: a JSON array of [time, low, high, open, close, volume] rows,
`time` in UNIX seconds, returned in DESCENDING time order (newest
first). `granularity=60` selects 1-minute candles — the one cadence
this system uses (see btc_market_data.py's and btc_intelligence.py's
module docstrings on why 1-minute bars match the existing
min_bars_for_indicators warm-up math).

NOT independently verified against a live response from this sandbox:
a direct curl from this development environment to
api.exchange.coinbase.com was rejected at the CONNECT-tunnel level by
this organization's own egress policy (403 — "policy denial", recorded
in the agent proxy's own status output) — the exact same class of
restriction already documented in client.py/us_client.py for
polymarket.com/clob.polymarket.com, for the same reason (an
organization-level network policy, not a code problem). This client is
built against Coinbase's long-stable, publicly documented candle
response shape (the row layout above has been stable and documented
this way for years), not a live-verified capture. Re-verify with a
real HTTP call — e.g. `python3 -c "from src.polymarket.btc_coinbase_source
import CoinbaseBtcQuoteSource; print(CoinbaseBtcQuoteSource().get_recent_candles(limit=5))"`
from an environment that can actually reach Coinbase — before trusting
this with real decisions, the same caution client.py/us_client.py
already document for their own, equally real-but-sandbox-unreachable
APIs. All tests for this module use a deterministic fake HTTP
transport (see tests/test_polymarket_btc_coinbase_source.py), never a
real network call.

LIVE INCIDENT, FIXED: a real run showed the newest returned candle
frozen at the EXACT same timestamp across several real, one-minute-
apart refreshes (BtcFeedRefresher.maybe_refresh() calling this once a
minute, as designed — 18:42/18:43/18:44 all reported recorded=5,
newest=18:39, the gap climbing until STALE). Root cause: every request
used the IDENTICAL URL every single time
(.../candles?granularity=60) — no `start`/`end`, no time-varying
parameter whatsoever. Per Coinbase's own documented behavior for this
endpoint, "if either one of the start or end fields are not provided,
BOTH fields will be ignored," so omitting them (the previous code)
left the exact window Coinbase actually returns unspecified and
exactly identical request-to-request — exactly the shape a caching
layer (Coinbase's own edge, or an intermediate proxy) would serve a
stale cached response to, request after request, with no way for this
client to ever know. The fix: request.py now computes and sends an
explicit, NOW-anchored `start`/`end` on every call — this makes each
request's URL genuinely unique over time (defeating any naive
URL-keyed cache) AND unambiguously asks for the window ending at
`now`, rather than relying on whatever undocumented thing happens when
both are omitted. This is a request-construction fix, not a staleness-
threshold change: compute_feed_status()'s own 300s gate is untouched,
and a provider that genuinely keeps returning old data (for whatever
reason) still correctly reads STALE, never papered over as fresh.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from src.market.models import PriceBar

_CANDLES_URL_TEMPLATE = "https://api.exchange.coinbase.com/products/{product_id}/candles"
_GRANULARITY_SECONDS = 60  # 1-minute candles -- this system's one supported cadence
_EXPECTED_ROW_LENGTH = 6  # [time, low, high, open, close, volume] -- Coinbase's documented candle row shape
# Small buffer beyond `limit` candles' worth of history for the
# request window -- absorbs normal clock/aggregation slop at the
# provider so the requested window isn't razor-thin against exactly
# `limit` candles actually existing in it.
_REQUEST_WINDOW_BUFFER_CANDLES = 5

_logger = logging.getLogger(__name__)


class CoinbaseBtcQuoteSourceError(RuntimeError):
    pass


class CoinbaseBtcQuoteSource:
    """Implements btc_market_data.DirectBtcQuoteSource. Structurally
    duck-typed against that Protocol (not a subclass) — same
    convention as us_client.PolymarketUSClient vs. client.PolymarketClient
    both implementing the same informal interface without inheritance."""

    name = "coinbase"

    def __init__(self, *, product_id: str = "BTC-USD", timeout_seconds: float = 10.0):
        self._product_id = product_id
        self._timeout_seconds = timeout_seconds

    def get_recent_candles(self, *, limit: int = 60, now: datetime | None = None) -> list[PriceBar]:
        """Returns up to `limit` of the most recent 1-minute candles,
        OLDEST FIRST (Coinbase's own response is newest-first; this
        method re-sorts, matching every other venue-normalization
        convention in this package — see us_client.get_order_book's
        own re-sort for the same reason: never trust a raw API's
        ordering). Real open/high/low/close/volume and exact provider
        timestamps throughout — nothing here is interpolated or
        fabricated; `PriceBar.interpolated` is always False.

        Always sends an explicit `start`/`end` anchored to `now`
        (defaulting to the real wall clock) — see this module's
        docstring on why an unparameterized, identical-every-time
        request is exactly what let a cached/stale response go
        undetected in a real incident. `start`/`end`, the HTTP response
        status, row/candle counts, and the newest candle timestamp in
        the raw response are all logged via the standard `logging`
        module on every call, success or failure.

        Raises CoinbaseBtcQuoteSourceError on any transport, HTTP, or
        parse failure — callers (bootstrap_btc_price_history,
        BtcFeedRefresher) are responsible for treating that as
        "temporarily unavailable" and degrading safely (never a crash,
        never a fabricated fallback value — see those functions'
        docstrings)."""
        now = now or datetime.now(timezone.utc)
        start = now - timedelta(seconds=_GRANULARITY_SECONDS * (limit + _REQUEST_WINDOW_BUFFER_CANDLES))
        params = {"granularity": str(_GRANULARITY_SECONDS), "start": start.isoformat(), "end": now.isoformat()}
        url = f"{_CANDLES_URL_TEMPLATE.format(product_id=self._product_id)}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": "polymarket-btc-feed/1.0"})
        _logger.info("coinbase candles request: product=%s params=%s", self._product_id, params)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                status = getattr(response, "status", None)
                raw = response.read()
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            _logger.warning("coinbase candles request failed: product=%s params=%s error=%s", self._product_id, params, exc)
            raise CoinbaseBtcQuoteSourceError(f"Coinbase candles request failed: {exc}") from exc

        try:
            rows = json.loads(raw)
        except json.JSONDecodeError as exc:
            _logger.warning("coinbase candles response was not valid JSON: status=%s error=%s", status, exc)
            raise CoinbaseBtcQuoteSourceError(f"Coinbase candles response was not valid JSON: {exc}") from exc
        if not isinstance(rows, list):
            _logger.warning("coinbase candles response was not a list: status=%s type=%s", status, type(rows).__name__)
            raise CoinbaseBtcQuoteSourceError(f"Coinbase candles response was not a list: {type(rows).__name__}")

        bars = [_row_to_bar(row) for row in rows]
        bars.sort(key=lambda b: b.start_time)  # Coinbase returns newest-first; this package's convention is oldest-first
        trimmed = bars[-limit:] if limit and limit < len(bars) else bars
        newest_in_raw_response = bars[-1].start_time.isoformat() if bars else None
        newest_returned = trimmed[-1].start_time.isoformat() if trimmed else None
        _logger.info(
            "coinbase candles response: status=%s rows=%d returned=%d newest_in_raw_response=%s "
            "newest_returned=%s request_start=%s request_end=%s",
            status, len(rows), len(trimmed), newest_in_raw_response, newest_returned,
            params["start"], params["end"],
        )
        return trimmed


def _row_to_bar(row: object) -> PriceBar:
    if not isinstance(row, list) or len(row) != _EXPECTED_ROW_LENGTH:
        raise CoinbaseBtcQuoteSourceError(
            f"Coinbase candle row did not have exactly {_EXPECTED_ROW_LENGTH} fields: {row!r}"
        )
    time_s, low, high, open_, close, volume = row
    return PriceBar(
        start_time=datetime.fromtimestamp(float(time_s), tz=timezone.utc),
        open=float(open_), high=float(high), low=float(low), close=float(close),
        # Real, provider-reported volume -- fractional BTC, never
        # rounded/truncated to satisfy PriceBar.volume's `int` type
        # hint (dataclasses never enforce field types at runtime; see
        # btc_market_data._bar_from_dict's identical note).
        volume=float(volume), interpolated=False,
    )
