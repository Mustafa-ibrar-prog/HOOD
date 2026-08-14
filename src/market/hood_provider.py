"""The real MarketDataProvider, backed by the HOOD MCP tools (via an
injected HoodToolClient — see hood_client.py for why this is a seam rather
than a direct import).

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
  never a guess.

- RSI/MACD/EMA/VWAP are computed LOCALLY from the fetched OHLCV bars,
  using the same tested functions in market/indicators.py, rather than by
  calling mcp__HOOD__get_equity_technical_indicators. This was a deliberate
  choice: that tool's *response* shape wasn't inspectable in this session
  (only its request parameters were), so parsing it would mean guessing at
  field names for numbers that directly drive exit decisions. Computing
  from real, fetched OHLCV bars is still genuine data (never fabricated),
  reuses code that already has its own indicator tests, and avoids that
  risk. Swapping in get_equity_technical_indicators as the primary source
  (falling back to local computation on failure) is a reasonable future
  enhancement once its response shape is confirmed against a live call.

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
            fetched_at=now,
        )

    def get_option_chain_candidates(self, underlying_symbol: str, **filters: Any) -> list[dict[str, Any]]:
        try:
            chains_response = self._client.get_option_chains(underlying_symbol=underlying_symbol)
        except Exception as exc:  # noqa: BLE001 - normalize any client failure
            raise HoodToolError(f"get_option_chains failed for {underlying_symbol}: {exc}") from exc

        chains = chains_response.get("chains") or []
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
            candidates.extend(instruments_response.get("instruments") or [])
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
            bars = _parse_bars(response)
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
            bars = _parse_bars(response)
        except HoodToolError as exc:
            self._logger.warning("Could not parse option bars for %s: %s; continuing without option bars", option_id, exc)
            return []
        return _drop_interpolated(bars, self._logger, f"option bars for {option_id}")


# --- Parsing helpers ----------------------------------------------------------------------
#
# Assumed response shapes are documented at each parser below. They are the
# best-effort interpretation of each tool's documented behavior (only
# request schemas were inspectable in this session) — verify against a real
# response before depending on this in a live session. A shape mismatch
# raises a clear HoodToolError rather than silently fabricating a value.


def _parse_equity_quote(response: dict[str, Any], symbol: str) -> EquityQuote:
    """Assumed shape: {"quotes": [{"symbol": "...", "last_trade_price": ...,
    "previous_close": ...}, ...], "closes_error": ...}."""
    quotes = response.get("quotes") if isinstance(response, dict) else None
    if not quotes:
        raise QuoteUnavailableError(f"No quote returned for {symbol}")

    row = next((q for q in quotes if str(q.get("symbol", "")).upper() == symbol.upper()), quotes[0])
    try:
        last = _to_float(row.get("last_trade_price"))
        previous_close = _to_float(row.get("previous_close"))
    except (TypeError, ValueError) as exc:
        raise HoodToolError(f"Could not parse equity quote for {symbol}: {exc}") from exc

    if last is None:
        raise QuoteUnavailableError(f"Quote for {symbol} has no last_trade_price")

    try:
        return EquityQuote(symbol=symbol, last_trade_price=last, previous_close=previous_close, as_of=datetime.now(timezone.utc))
    except ValueError as exc:
        raise InvalidQuoteError(f"Equity quote for {symbol} failed validation: {exc}") from exc


def _parse_option_quote(response: dict[str, Any], option_id: str) -> OptionQuote:
    """Assumed shape: {"quotes": [{"instrument_id": "...", "bid_price": ...,
    "ask_price": ..., "last_trade_price": ..., "previous_close": ...,
    "volume": ..., "open_interest": ...}, ...], "closes_error": ...}."""
    quotes = response.get("quotes") if isinstance(response, dict) else None
    if not quotes:
        raise OptionContractNotFoundError(f"No quote returned for option contract {option_id}")

    row = next((q for q in quotes if str(q.get("instrument_id", "")) == option_id), quotes[0])
    try:
        bid = _to_float(row.get("bid_price"))
        ask = _to_float(row.get("ask_price"))
        last = _to_float(row.get("last_trade_price"))
        previous_close = _to_float(row.get("previous_close"))
        volume = _to_int(row.get("volume"))
        open_interest = _to_int(row.get("open_interest"))
    except (TypeError, ValueError) as exc:
        raise HoodToolError(f"Could not parse option quote for {option_id}: {exc}") from exc

    if bid is None or ask is None:
        raise QuoteUnavailableError(f"Option contract {option_id} is missing bid/ask")

    try:
        return OptionQuote(
            instrument_id=option_id,
            bid_price=bid,
            ask_price=ask,
            last_trade_price=last,
            previous_close=previous_close,
            volume=volume,
            open_interest=open_interest,
            as_of=datetime.now(timezone.utc),
        )
    except ValueError as exc:
        raise InvalidQuoteError(f"Option quote for {option_id} failed validation: {exc}") from exc


def _parse_bars(response: dict[str, Any]) -> list[PriceBar]:
    """Assumed shape: {"bars": [{"start_time"|"begins_at": ..., "open": ...,
    "high": ..., "low": ..., "close": ..., "volume": ..., "interpolated":
    bool}, ...]}, or {"results": [{"symbol"|"instrument_id": ..., "bars":
    [...]}]} for the multi-symbol variant (this provider only ever
    requests one symbol/instrument at a time, so the first result is used).

    Individual unusable rows (missing OHLC, unparseable timestamp, or a
    high<low violation) are skipped rather than failing the whole fetch —
    that is the "incomplete candle data" handling for malformed rows; a
    fully unparseable *response* still raises HoodToolError.
    """
    if not isinstance(response, dict):
        raise HoodToolError(f"Expected a dict response for historicals, got {type(response).__name__}")

    raw_bars = response.get("bars")
    if raw_bars is None:
        results = response.get("results") or []
        raw_bars = results[0].get("bars", []) if results else []

    if not isinstance(raw_bars, list):
        raise HoodToolError(f"Expected a list of bars, got {type(raw_bars).__name__}")

    bars: list[PriceBar] = []
    for raw in raw_bars:
        if not isinstance(raw, dict):
            continue  # an unusable row — skip it, don't fabricate a value

        start_raw = raw.get("start_time") or raw.get("begins_at") or raw.get("timestamp")
        start_time = _parse_datetime(start_raw)
        try:
            open_ = _to_float(raw.get("open"))
            high = _to_float(raw.get("high"))
            low = _to_float(raw.get("low"))
            close = _to_float(raw.get("close"))
            volume = _to_int(raw.get("volume")) or 0
        except (TypeError, ValueError) as exc:
            raise HoodToolError(f"Could not parse a price bar: {exc}") from exc

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
