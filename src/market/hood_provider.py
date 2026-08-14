"""The real MarketDataProvider, backed by the HOOD MCP tools (via an
injected HoodToolClient — see hood_client.py for why this is a seam rather
than a direct import).

Response shapes below were VERIFIED against live, read-only calls (SPY
underlying; a SPY $780 call expiring 2026-08-21 for the option contract)
made during development of this module — not guessed. Every HOOD read-only
tool used here wraps its payload as {"data": {...}, "guide": "..."}; the
inner shape differs per tool and is documented at each parser below.

Design decisions worth knowing:

- Quotes are CRITICAL. If get_equity_quotes or get_option_quotes fails, or
  returns something we can't parse into a sane quote, get_market_snapshot
  raises (QuoteUnavailableError / OptionContractNotFoundError /
  InvalidQuoteError / HoodToolError). The position evaluator cannot safely
  run without a current option price, so there is no silent fallback here
  — PositionMonitor already treats any of these as "hold, don't act blind"
  (see position_manager/monitor.py).

- Historical bars and technical indicators are SUPPLEMENTARY. If
  get_equity_historicals / get_option_historicals fails or can't be
  parsed, this provider logs a warning and degrades to an empty bar list
  rather than aborting the whole snapshot. Downstream, an empty bar list
  naturally flows into MomentumEvidence as missing indicator data, which
  strategy/evidence.py already treats as INSUFFICIENT_DATA — a safe HOLD,
  never a guess. Confirmed live: option bars carry NO volume field at all
  (per that tool's own guide text) — this provider defaults a bar's volume
  to 0 in that case rather than fabricating a number; volume_ratio is only
  ever computed from underlying (equity) bars, which do carry volume.

- RSI/MACD/EMA/VWAP are computed LOCALLY from the fetched OHLCV bars,
  using the same tested functions in market/indicators.py, rather than by
  calling mcp__HOOD__get_equity_technical_indicators. That tool's response
  shape has still not been verified in this codebase (only the six tools
  this module actually calls have been) — computing from real, fetched
  OHLCV bars is still genuine data (never fabricated) and reuses code that
  already has its own indicator tests. Swapping in
  get_equity_technical_indicators as the primary source (falling back to
  local computation on failure) remains a reasonable future enhancement
  once its response shape is verified the same way this module's tools were.

- "Incomplete candle data": bars the tool marks `interpolated=True` were
  synthesized to fill a gap and carry no new information (per
  get_option_historicals/get_equity_historicals's own documentation) — they
  are filtered out before being used for structure/breakout detection or
  local indicator math, with a warning logged if a significant number were
  dropped.

- "Market closed": detected via regular-hours-in-the-configured-timezone
  and logged as a warning (quotes/bars may reflect the last session) —
  informational only. It does not change the risk manager's staleness
  math (Settings.stale_data_max_seconds / RiskManager.check_data_freshness
  are unchanged, per the task's "keep existing risk controls unchanged").

- Freshness uses the tools' OWN timestamps, not just "when we called the
  API". get_equity_quotes returns venue_last_trade_time (and
  venue_last_non_reg_trade_time); get_option_quotes returns updated_at.
  Each quote's `as_of` is set from that real timestamp — picking, for the
  equity quote, whichever of the regular/non-regular trade timestamps is
  actually more recent (matching that tool's own documented guidance) —
  rather than the wall-clock time of our fetch. MarketSnapshot.fetched_at
  is then the OLDEST (most conservative) of: our own fetch time, the
  underlying quote's as_of, and the option quote's as_of, so a quote that
  Robinhood itself hasn't refreshed recently is correctly flagged as stale
  even if our own tool call just returned quickly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from logging import Logger
from typing import Any
from zoneinfo import ZoneInfo

from src.config.constants import TRADING_WEEKDAYS
from src.config.settings import Settings
from src.logging.app_logger import get_app_logger
from src.market import indicators
from src.market.data_provider import MarketDataProvider
from src.market.errors import (
    HoodToolError,
    InvalidQuoteError,
    OptionContractNotFoundError,
    QuoteUnavailableError,
)
from src.market.hood_client import HoodToolClient
from src.market.models import EquityQuote, MarketSnapshot, OptionQuote, PriceBar


class HoodMarketDataProvider(MarketDataProvider):
    def __init__(
        self,
        client: HoodToolClient,
        settings: Settings,
        *,
        history_lookback_minutes: int = 180,
        history_interval: str = "5minute",
        ema_fast_period: int = 9,
        ema_slow_period: int = 21,
        rsi_period: int = 14,
        logger: Logger | None = None,
    ):
        self._client = client
        self._settings = settings
        self._history_lookback_minutes = history_lookback_minutes
        self._history_interval = history_interval
        self._ema_fast_period = ema_fast_period
        self._ema_slow_period = ema_slow_period
        self._rsi_period = rsi_period
        self._logger = logger or get_app_logger()

    # --- MarketDataProvider interface ---------------------------------------------------

    def get_market_snapshot(
        self, option_id: str, underlying_symbol: str, now: datetime | None = None
    ) -> MarketSnapshot:
        now = now or datetime.now(timezone.utc)

        if not _is_regular_market_hours(now, self._settings):
            self._logger.warning(
                "Fetching a market snapshot for %s outside regular market hours "
                "(%s); quotes/bars may reflect the last session, not live trading.",
                underlying_symbol,
                self._settings.market_timezone,
            )

        # --- Critical: no snapshot without a current, sane quote on both legs ---
        underlying_quote = self._fetch_equity_quote(underlying_symbol)
        option_quote = self._fetch_option_quote(option_id)

        # --- Supplementary: degrade to empty/None rather than abort --------------
        start_time = _rfc3339(now - timedelta(minutes=self._history_lookback_minutes))
        end_time = _rfc3339(now)
        underlying_bars = self._fetch_equity_bars(underlying_symbol, start_time, end_time)
        option_bars = self._fetch_option_bars(option_id, start_time, end_time)

        closes = [b.close for b in underlying_bars]
        rsi_series = indicators.rsi(closes, period=self._rsi_period) if closes else []
        _, _, histogram_series = indicators.macd(closes) if closes else ([], [], [])
        ema_fast_series = indicators.ema(closes, period=self._ema_fast_period) if closes else []
        ema_slow_series = indicators.ema(closes, period=self._ema_slow_period) if closes else []
        vwap_value = indicators.vwap(underlying_bars) if underlying_bars else None
        volume_ratio = _compute_volume_ratio(underlying_bars)

        # Conservative (oldest) of: our fetch time, and each quote's own
        # reported timestamp — see module docstring "Freshness" note.
        fetched_at = min(now, underlying_quote.as_of, option_quote.as_of)

        return MarketSnapshot(
            option=option_quote,
            underlying=underlying_quote,
            option_bars=tuple(option_bars),
            underlying_bars=tuple(underlying_bars),
            rsi=_nth_from_end(rsi_series, 1),
            rsi_prev=_nth_from_end(rsi_series, 2),
            macd_histogram=_nth_from_end(histogram_series, 1),
            macd_histogram_prev=_nth_from_end(histogram_series, 2),
            ema_fast=_nth_from_end(ema_fast_series, 1),
            ema_slow=_nth_from_end(ema_slow_series, 1),
            vwap=vwap_value,
            volume_ratio=volume_ratio,
            fetched_at=fetched_at,
        )

    def get_option_chain_candidates(self, underlying_symbol: str, **filters: Any) -> list[dict[str, Any]]:
        try:
            chains_response = self._client.get_option_chains(underlying_symbol=underlying_symbol)
        except Exception as exc:  # noqa: BLE001 - normalize any client failure
            raise HoodToolError(f"get_option_chains failed for {underlying_symbol}: {exc}") from exc

        chains_data = _unwrap_data(chains_response, "get_option_chains")
        chains = chains_data.get("chains") or []
        if not chains:
            self._logger.warning("No option chain found for %s", underlying_symbol)
            return []

        candidates: list[dict[str, Any]] = []
        for chain in chains:
            chain_id = chain.get("id")
            if not chain_id:
                continue
            try:
                instruments_response = self._client.get_option_instruments(chain_id=chain_id, **filters)
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("get_option_instruments failed for chain %s (%s): %s", chain_id, underlying_symbol, exc)
                continue
            try:
                instruments_data = _unwrap_data(instruments_response, "get_option_instruments")
            except HoodToolError as exc:
                self._logger.warning("Could not parse get_option_instruments response for chain %s: %s", chain_id, exc)
                continue
            candidates.extend(instruments_data.get("instruments") or [])
        return candidates

    # --- Internal fetch helpers -----------------------------------------------------------

    def _fetch_equity_quote(self, symbol: str) -> EquityQuote:
        try:
            response = self._client.get_equity_quotes([symbol])
        except Exception as exc:  # noqa: BLE001
            raise HoodToolError(f"get_equity_quotes failed for {symbol}: {exc}") from exc
        return _parse_equity_quote(response, symbol)

    def _fetch_option_quote(self, option_id: str) -> OptionQuote:
        try:
            response = self._client.get_option_quotes([option_id])
        except Exception as exc:  # noqa: BLE001
            raise HoodToolError(f"get_option_quotes failed for {option_id}: {exc}") from exc
        return _parse_option_quote(response, option_id)

    def _fetch_equity_bars(self, symbol: str, start_time: str, end_time: str) -> list[PriceBar]:
        try:
            response = self._client.get_equity_historicals(
                [symbol], start_time=start_time, end_time=end_time, interval=self._history_interval, bounds="regular"
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("get_equity_historicals failed for %s: %s; continuing without underlying bars", symbol, exc)
            return []
        try:
            bars = _parse_bars(response, "get_equity_historicals")
        except HoodToolError as exc:
            self._logger.warning("Could not parse equity bars for %s: %s; continuing without underlying bars", symbol, exc)
            return []
        return _drop_interpolated(bars, self._logger, f"equity bars for {symbol}")

    def _fetch_option_bars(self, option_id: str, start_time: str, end_time: str) -> list[PriceBar]:
        try:
            response = self._client.get_option_historicals(
                [option_id], start_time=start_time, end_time=end_time, interval=self._history_interval, bounds="regular"
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("get_option_historicals failed for %s: %s; continuing without option bars", option_id, exc)
            return []
        try:
            bars = _parse_bars(response, "get_option_historicals")
        except HoodToolError as exc:
            self._logger.warning("Could not parse option bars for %s: %s; continuing without option bars", option_id, exc)
            return []
        return _drop_interpolated(bars, self._logger, f"option bars for {option_id}")


# --- Parsing helpers ----------------------------------------------------------------------
#
# Shapes documented at each parser were verified against real, read-only
# HOOD MCP responses (see module docstring). A shape mismatch raises a
# clear HoodToolError rather than silently fabricating a value.


def _unwrap_data(response: Any, context: str) -> dict[str, Any]:
    """Every HOOD read-only tool used here wraps its payload as
    {"data": {...}, "guide": "..."} — confirmed for get_equity_quotes,
    get_equity_historicals, get_option_chains, get_option_instruments,
    get_option_quotes, and get_option_historicals."""
    if not isinstance(response, dict) or not isinstance(response.get("data"), dict):
        raise HoodToolError(f"{context}: expected a top-level 'data' object, got {type(response).__name__}")
    return response["data"]


def _pick_most_recent_price(*candidates: tuple[Any, Any]) -> tuple[float | None, datetime | None]:
    """Each candidate is (price, timestamp). Returns the price paired with
    the latest parseable timestamp — matching get_equity_quotes' own
    guidance to prefer whichever of last_trade_price /
    last_non_reg_trade_price is actually more recent. Candidates missing
    either a parseable price or timestamp are ignored, not guessed."""
    best_price: float | None = None
    best_time: datetime | None = None
    for price_raw, ts_raw in candidates:
        price = _to_float(price_raw)
        ts = _parse_datetime(ts_raw)
        if price is None or ts is None:
            continue
        if best_time is None or ts > best_time:
            best_price, best_time = price, ts
    return best_price, best_time


def _parse_equity_quote(response: dict[str, Any], symbol: str) -> EquityQuote:
    """Verified shape (get_equity_quotes):
    {"data": {"results": [{
        "quote": {"symbol", "last_trade_price", "venue_last_trade_time",
                  "last_non_reg_trade_price", "venue_last_non_reg_trade_time",
                  "previous_close", "adjusted_previous_close",
                  "bid_price", "ask_price", "has_traded", "state", ...},
        "close": {"price", "date", "interpolated", "source", ...}
    }, ...]}}.
    """
    data = _unwrap_data(response, "get_equity_quotes")
    results = data.get("results") or []
    row = next(
        (r for r in results if str((r.get("quote") or {}).get("symbol", "")).upper() == symbol.upper()),
        results[0] if results else None,
    )
    if row is None:
        raise QuoteUnavailableError(f"No quote returned for {symbol}")

    quote = row.get("quote") or {}
    close = row.get("close")

    state = quote.get("state")
    if quote.get("has_traded") is False or state not in (None, "active"):
        raise QuoteUnavailableError(
            f"Quote for {symbol} is not usable (has_traded={quote.get('has_traded')!r}, state={state!r})"
        )

    try:
        last_price, as_of = _pick_most_recent_price(
            (quote.get("last_trade_price"), quote.get("venue_last_trade_time")),
            (quote.get("last_non_reg_trade_price"), quote.get("venue_last_non_reg_trade_time")),
        )
        previous_close = _to_float(close.get("price")) if close else None
        if previous_close is None:
            previous_close = _to_float(quote.get("previous_close"))
            if previous_close is None:
                previous_close = _to_float(quote.get("adjusted_previous_close"))
    except (TypeError, ValueError) as exc:
        raise HoodToolError(f"Could not parse equity quote for {symbol}: {exc}") from exc

    if last_price is None:
        raise QuoteUnavailableError(f"Quote for {symbol} has no usable last-trade price/timestamp")

    try:
        return EquityQuote(
            symbol=symbol,
            last_trade_price=last_price,
            previous_close=previous_close,
            as_of=as_of or datetime.now(timezone.utc),
        )
    except ValueError as exc:
        raise InvalidQuoteError(f"Equity quote for {symbol} failed validation: {exc}") from exc


def _parse_option_quote(response: dict[str, Any], option_id: str) -> OptionQuote:
    """Verified shape (get_option_quotes):
    {"data": {"results": [{
        "quote": {"instrument_id", "bid_price", "ask_price", "mark_price",
                  "adjusted_mark_price", "previous_close_price",
                  "previous_close_date", "volume", "open_interest",
                  "updated_at", "implied_volatility", "delta", ...},
        "close": {"price", "date", "interpolated", "source", ...}
    }, ...]}}.

    Options have no "last_trade_price" field at all — mark_price is the
    tool's own documented "current price" (its guide text says so
    explicitly). It is stored in OptionQuote.last_trade_price, the closest
    existing field for "the current reference price" — PositionEvaluator
    itself uses OptionQuote.mid_price (bid/ask average), not this field,
    for P&L math.
    """
    data = _unwrap_data(response, "get_option_quotes")
    results = data.get("results") or []
    row = next(
        (r for r in results if (r.get("quote") or {}).get("instrument_id") == option_id),
        results[0] if results else None,
    )
    if row is None:
        raise OptionContractNotFoundError(f"No quote returned for option contract {option_id}")

    quote = row.get("quote") or {}
    close = row.get("close")

    try:
        bid = _to_float(quote.get("bid_price"))
        ask = _to_float(quote.get("ask_price"))
        mark = _to_float(quote.get("mark_price"))
        if mark is None:
            mark = _to_float(quote.get("adjusted_mark_price"))
        previous_close = _to_float(quote.get("previous_close_price"))
        if previous_close is None and close:
            previous_close = _to_float(close.get("price"))
        volume = _to_int(quote.get("volume"))
        open_interest = _to_int(quote.get("open_interest"))
        as_of = _parse_datetime(quote.get("updated_at"))
    except (TypeError, ValueError) as exc:
        raise HoodToolError(f"Could not parse option quote for {option_id}: {exc}") from exc

    if bid is None or ask is None:
        raise QuoteUnavailableError(f"Option contract {option_id} is missing bid/ask")

    try:
        return OptionQuote(
            instrument_id=option_id,
            bid_price=bid,
            ask_price=ask,
            last_trade_price=mark,
            previous_close=previous_close,
            volume=volume,
            open_interest=open_interest,
            as_of=as_of or datetime.now(timezone.utc),
        )
    except ValueError as exc:
        raise InvalidQuoteError(f"Option quote for {option_id} failed validation: {exc}") from exc


def _parse_bars(response: dict[str, Any], context: str) -> list[PriceBar]:
    """Verified shape (get_equity_historicals / get_option_historicals):
    {"data": {"results": [{
        "symbol" | "instrument_id": ..., "interval", "bounds",
        "bars": [{"begins_at", "open_price", "high_price", "low_price",
                  "close_price", "volume" (equity bars only — option bars
                  carry no volume field at all), "interpolated" (omitted
                  when false), "session"}, ...]
    }]}}. This provider only ever requests one symbol/instrument at a
    time, so the first result is used.

    Individual unusable rows (missing OHLC, unparseable timestamp, or a
    high<low violation) are skipped rather than failing the whole fetch —
    that is the "incomplete candle data" handling for malformed rows; a
    fully unparseable *response* still raises HoodToolError.
    """
    data = _unwrap_data(response, context)
    results = data.get("results") or []
    raw_bars = results[0].get("bars") if results else []
    if not isinstance(raw_bars, list):
        raise HoodToolError(f"{context}: expected a list of bars, got {type(raw_bars).__name__}")

    bars: list[PriceBar] = []
    for raw in raw_bars:
        if not isinstance(raw, dict):
            continue  # an unusable row — skip it, don't fabricate a value

        start_time = _parse_datetime(raw.get("begins_at"))
        try:
            open_ = _to_float(raw.get("open_price"))
            high = _to_float(raw.get("high_price"))
            low = _to_float(raw.get("low_price"))
            close = _to_float(raw.get("close_price"))
            volume = _to_int(raw.get("volume")) or 0  # absent entirely on option bars
        except (TypeError, ValueError) as exc:
            raise HoodToolError(f"{context}: could not parse a price bar: {exc}") from exc

        if start_time is None or None in (open_, high, low, close):
            continue  # missing data on this row — skip it, don't fabricate a value

        try:
            bars.append(
                PriceBar(
                    start_time=start_time,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    interpolated=bool(raw.get("interpolated", False)),
                )
            )
        except ValueError:
            continue  # e.g. a malformed high<low row — skip rather than abort the fetch

    return bars


def _drop_interpolated(bars: list[PriceBar], logger: Logger, label: str) -> list[PriceBar]:
    """Interpolated bars were synthesized to fill a gap and carry no new
    information (per the historicals tools' own documentation) — exclude
    them from structure/indicator computation."""
    real_bars = [b for b in bars if not b.interpolated]
    dropped = len(bars) - len(real_bars)
    if dropped:
        logger.warning("%s: dropped %d interpolated (gap-filled) bar(s) out of %d", label, dropped, len(bars))
    return real_bars


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _nth_from_end(series: list[float], n: int) -> float | None:
    """1-indexed from the end: n=1 is the latest value, n=2 the one before
    it. Returns None (never a fabricated number) if the series is too
    short."""
    return series[-n] if len(series) >= n else None


def _compute_volume_ratio(bars: list[PriceBar]) -> float | None:
    """Most recent bar's volume relative to the average of the bars before
    it. None (not a guessed 1.0) when there isn't enough history to judge."""
    if len(bars) < 2:
        return None
    *history, latest = bars
    average = sum(b.volume for b in history) / len(history)
    if average <= 0:
        return None
    return latest.volume / average


def _is_regular_market_hours(now_utc: datetime, settings: Settings) -> bool:
    local_now = now_utc.astimezone(ZoneInfo(settings.market_timezone))
    if local_now.weekday() not in TRADING_WEEKDAYS:
        return False
    return settings.market_open_time <= local_now.time() <= settings.market_close_time
