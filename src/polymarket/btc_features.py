"""Causal BTC feature computation for the predictive direction model
(see btc_direction_model.py) -- the SOURCE OF DIRECTION as of this
round, replacing simple_entry_signal.py's "whichever Polymarket side
is currently favored" rule entirely (see engine.py's module docstring
for the full list of what that replaces).

HONEST DATA-SOURCE SCOPE: the only BTC market data this system has a
real, working live feed for is Coinbase's public spot API
(CoinbaseBtcQuoteSource / BtcPriceHistoryStore -- see
btc_market_data.py), polled on this bot's own poll_interval_seconds
cadence and aggregated into 60-second OHLCV bars
(BtcPriceHistoryStore.get_bars(interval_seconds=60)). There is no real
sub-minute (5s/10s/15s/30s) candle data available from this feed --
Coinbase's own public REST candle granularities start at 60s, and this
system has never scraped trade-level ticks for finer resolution.
Rather than FABRICATE sub-minute returns by interpolating 1-minute
bars (fake precision that would also silently compute DIFFERENTLY in
backtest vs. live, breaking the paper/live decision-path parity this
round explicitly requires), every feature below is computed from the
SAME 1-minute-bar granularity in BOTH contexts. The feature set is a
deliberately reduced, honest subset of the long list this round's
instructions sketched: returns/momentum/volatility/volume over
1m/3m/5m/10m/15m windows, distance from price-to-beat, and time
remaining. Order-book imbalance, bid/ask spread, buy/sell pressure and
distance-from-VWAP are NOT included -- the Coinbase candle feed has no
order-book or trade-level data to compute them from honestly, and
Polymarket's OWN order book is BTC's price TARGET here, not a BTC data
source -- reading it for a BTC feature would smuggle the original bug
("substitute Polymarket's own price for BTC's price") back in through
a side door. Prefer a smaller, honestly-sourced feature set over a
long list of indicators backed by data this system doesn't actually
have.

PRICE-TO-BEAT: Polymarket US's real API (verified directly against the
installed polymarket-us SDK's typed Market/Event/MarketDetail
structures -- see us_client.py) exposes NO priceToBeat/strike/
reference-price field at all; the real captured event title for this
product is the generic "BTC Up or Down 15m" with an empty description,
confirmed against this codebase's own pinned, live-verified test
fixtures. So there is nothing to read `market.metadata` for here. Per
Polymarket's own published 15-minute BTC Up/Down resolution rules
(cites Chainlink's BTC/USD Data Stream -- see reference_divergence.py's
module docstring, researched in an earlier round), the actual
settlement reference is "the BTC price at the instant the window
opened." Chainlink Data Streams is a paid-only subscription with no
free tier (also already established in reference_divergence.py) --
this module uses the SAME Coinbase feed as the proxy reference,
anchored to `market.window_start` (real metadata: derived from the
event's own confirmed slug schedule, the SAME way close_time already
is -- see us_client._parse_btc_updown_window_from_slug). This is a
PROXY for Polymarket's actual settlement price, not Polymarket's own
authoritative value -- never hardcoded, never read from the order
book, never Polymarket's own YES/NO price substituted for BTC's price.

NO LOOK-AHEAD: compute_btc_features(bars, ..., at=T) only ever uses
bars whose start_time is strictly before T, re-filtering itself even
though BtcPriceHistoryStore.get_bars() already only returns fully
closed buckets -- a caller handing this function a bar list that
happens to include one covering or after T can never leak its close
price into a feature value at T. Every feature at timestamp T uses
only information available at or before T.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from src.market.models import PriceBar
from src.polymarket.btc_market_data import BtcQuoteSample

# (name, seconds) pairs -- see module docstring for why this is
# 1m/3m/5m/10m/15m rather than the full 5s..5m list this round's
# instructions sketched.
RETURN_WINDOWS_SECONDS: tuple[tuple[str, int], ...] = (
    ("1m", 60), ("3m", 180), ("5m", 300), ("10m", 600), ("15m", 900),
)
MOMENTUM_WINDOW_SECONDS = 300  # 5m linear-trend slope
VOLATILITY_WINDOW_SECONDS = 900  # 15m realized volatility (stdev of 1m log returns)
VOLUME_WINDOW_SECONDS = 300  # 5m volume sum + volume-acceleration comparison window
# How much slack a return lookup allows between its exact target
# instant and the nearest bar actually found before it -- one extra
# bar-width beyond the normal 60s granularity, generous enough for an
# ordinary single missed poll but never large enough to let a return
# silently span a real data-feed gap (see compute_btc_features's own
# return-loop).
_RETURN_LOOKBACK_TOLERANCE_SECONDS = 120

# The full, ordered list of numeric keys as_feature_dict()/the model
# both use -- a single source of truth so training and inference can
# never silently drift out of sync on which features exist or in what
# order.
FEATURE_NAMES: tuple[str, ...] = (
    "distance_from_price_to_beat_pct",
    "time_remaining_seconds",
    *[f"return_{name}" for name, _ in RETURN_WINDOWS_SECONDS],
    "momentum_slope_pct",
    "realized_volatility",
    "volume_acceleration",
)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class BtcFeatureVector:
    """Every value here is computed using ONLY bars/samples strictly
    before `at` (and the contract's own window_start for
    price_to_beat) -- see compute_btc_features(). None means "not
    enough history yet," never a fabricated 0; as_feature_dict() is
    the one place a None becomes a numeric 0.0, done identically for
    training and inference."""

    at: datetime
    current_price: float | None
    price_to_beat: float | None
    distance_from_price_to_beat: float | None  # current_price - price_to_beat, in dollars
    distance_from_price_to_beat_pct: float | None  # distance / price_to_beat
    time_remaining_seconds: float | None
    returns: dict[str, float | None] = field(default_factory=dict)  # keyed by RETURN_WINDOWS_SECONDS names
    momentum_slope_pct: float | None = None  # 5m linear-trend slope, as a fraction of current_price per second
    realized_volatility: float | None = None  # stdev of 1-minute log returns over VOLATILITY_WINDOW_SECONDS
    volume_recent: float | None = None  # summed volume over VOLUME_WINDOW_SECONDS
    volume_acceleration: float | None = None  # volume_recent / volume in the prior equal-length window - 1.0
    bar_count: int = 0  # bars actually available before `at` -- 0 means no usable history at all

    @property
    def has_minimum_data(self) -> bool:
        """The hard floor compute_model_entry_signal()/the backtest
        both enforce before trusting a prediction at all: a real
        current price AND a real price-to-beat AND at least enough
        bar history to have formed the longest return window. Missing
        any of these is NO TRADE/NO LABEL, never an imputed guess."""
        return (
            self.current_price is not None and self.price_to_beat is not None
            and self.time_remaining_seconds is not None
            and self.returns.get(RETURN_WINDOWS_SECONDS[-1][0]) is not None
        )

    def as_feature_dict(self) -> dict[str, float]:
        """Numeric-only view for the model -- None is imputed to 0.0
        HERE ONLY, so training and inference impute identically.
        `distance_from_price_to_beat_pct`/`time_remaining_seconds` are
        never None when has_minimum_data is True (callers must still
        check has_minimum_data themselves -- this never raises)."""
        out: dict[str, float] = {
            "distance_from_price_to_beat_pct": self.distance_from_price_to_beat_pct or 0.0,
            "time_remaining_seconds": self.time_remaining_seconds or 0.0,
            "momentum_slope_pct": self.momentum_slope_pct or 0.0,
            "realized_volatility": self.realized_volatility or 0.0,
            "volume_acceleration": self.volume_acceleration or 0.0,
        }
        for name, _ in RETURN_WINDOWS_SECONDS:
            out[f"return_{name}"] = self.returns.get(name) or 0.0
        return out

    def to_log_fields(self) -> dict[str, float | str | None]:
        """BTC_PRICE/PRICE_TO_BEAT/DISTANCE_TO_BEAT/TIME_REMAINING --
        this round's required log vocabulary for the feature side."""
        return {
            "BTC_PRICE": self.current_price,
            "PRICE_TO_BEAT": self.price_to_beat,
            "DISTANCE_TO_BEAT": self.distance_from_price_to_beat,
            "DISTANCE_TO_BEAT_PCT": self.distance_from_price_to_beat_pct,
            "TIME_REMAINING": self.time_remaining_seconds,
        }


def resolve_price_to_beat(
    *, bars: list[PriceBar], raw_samples: list[BtcQuoteSample] | None, window_start: datetime,
) -> float | None:
    """The contract's price-to-beat PROXY (see module docstring):
    the earliest known BTC price at or after `window_start`. Checked
    in two passes, both real, both causal -- never a hardcode, never
    the order book:
      1. A 1-minute bar whose own start_time == window_start (the
         SAME minute-aligned instant close_time is already derived
         from) -- its `open` price. This is the ONLY path available in
         a backtest, which only ever has bars.
      2. Live only: raw_samples (finer-grained than 1-minute bars) --
         the earliest sample with observed_at >= window_start, for the
         case where that minute's bar hasn't closed yet (we're
         evaluating within the first ~60s of a brand-new window).
    None if neither is available yet."""
    window_start = _as_utc(window_start)
    for bar in bars:
        if _as_utc(bar.start_time) == window_start:
            return bar.open
    if raw_samples:
        candidates = sorted(
            (s for s in raw_samples if _as_utc(s.observed_at) >= window_start), key=lambda s: s.observed_at,
        )
        if candidates:
            return candidates[0].price
    return None


def _latest_bar_strictly_before(bars: list[PriceBar], target: datetime) -> PriceBar | None:
    """The latest bar whose own window had already closed strictly
    before `target` -- the SAME selection rule compute_btc_features()
    uses to pick `current_price` itself (applied there at `at`, and
    here at `at - window_seconds`), so a return computed over exactly
    one bar-width (e.g. "1m" when bars are 1-minute) compares against
    the PREVIOUS bar, never the same one `current_price` already
    came from."""
    candidates = [b for b in bars if _as_utc(b.start_time) < target]
    return max(candidates, key=lambda b: b.start_time) if candidates else None


def _linear_slope(points: list[tuple[float, float]]) -> float | None:
    """Ordinary least squares slope of y vs x -- no numpy dependency,
    this is a handful of bars. None when there are fewer than 2 points
    or x has zero variance (can't be fit)."""
    n = len(points)
    if n < 2:
        return None
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    denom = sum((x - mean_x) ** 2 for x, _ in points)
    if denom == 0:
        return None
    numer = sum((x - mean_x) * (y - mean_y) for x, y in points)
    return numer / denom


def compute_btc_features(
    bars: list[PriceBar], *, at: datetime, price_to_beat: float | None, close_time: datetime,
) -> BtcFeatureVector:
    """Pure and deterministic. `bars` may be any length/order -- this
    re-filters to strictly-before-`at` itself (see module docstring's
    NO LOOK-AHEAD section) and re-sorts, so a caller's own bar-store
    ordering is never trusted blindly."""
    at = _as_utc(at)
    close_time = _as_utc(close_time)
    usable = sorted((b for b in bars if _as_utc(b.start_time) < at), key=lambda b: b.start_time)
    time_remaining_seconds = max(0.0, (close_time - at).total_seconds())

    if not usable:
        return BtcFeatureVector(
            at=at, current_price=None, price_to_beat=price_to_beat, distance_from_price_to_beat=None,
            distance_from_price_to_beat_pct=None, time_remaining_seconds=time_remaining_seconds, bar_count=0,
        )

    current_price = usable[-1].close
    distance = current_price - price_to_beat if price_to_beat is not None else None
    distance_pct = (distance / price_to_beat) if (distance is not None and price_to_beat) else None

    returns: dict[str, float | None] = {}
    for name, seconds in RETURN_WINDOWS_SECONDS:
        target = at - timedelta(seconds=seconds)
        past_bar = _latest_bar_strictly_before(usable, target)
        # A GAP in the underlying data (feed outage, etc.) must never
        # silently stand in for "N seconds ago" with a bar that's
        # actually much older -- that would compute a real-looking but
        # meaningless return across missing history. Only trust a past
        # bar found within one bar-width of slack beyond the exact
        # target; further than that is "no data for this window," same
        # as having no bar at all.
        if past_bar is not None and (target - _as_utc(past_bar.start_time)).total_seconds() > _RETURN_LOOKBACK_TOLERANCE_SECONDS:
            past_bar = None
        returns[name] = ((current_price - past_bar.close) / past_bar.close) if past_bar else None

    momentum_cutoff = at - timedelta(seconds=MOMENTUM_WINDOW_SECONDS)
    momentum_bars = [b for b in usable if _as_utc(b.start_time) >= momentum_cutoff]
    slope = _linear_slope([((_as_utc(b.start_time) - at).total_seconds(), b.close) for b in momentum_bars])
    momentum_slope_pct = (slope / current_price) if (slope is not None and current_price) else None

    vol_cutoff = at - timedelta(seconds=VOLATILITY_WINDOW_SECONDS)
    vol_bars = [b for b in usable if _as_utc(b.start_time) >= vol_cutoff]
    log_returns = []
    for prev_bar, bar in zip(vol_bars, vol_bars[1:]):
        if prev_bar.close > 0 and bar.close > 0:
            log_returns.append(math.log(bar.close / prev_bar.close))
    realized_volatility = _stdev(log_returns) if len(log_returns) >= 2 else None

    volume_cutoff = at - timedelta(seconds=VOLUME_WINDOW_SECONDS)
    prior_cutoff = volume_cutoff - timedelta(seconds=VOLUME_WINDOW_SECONDS)
    recent_bars = [b for b in usable if _as_utc(b.start_time) >= volume_cutoff]
    prior_bars = [b for b in usable if prior_cutoff <= _as_utc(b.start_time) < volume_cutoff]
    volume_recent = sum(b.volume for b in recent_bars) if recent_bars else None
    volume_prior = sum(b.volume for b in prior_bars) if prior_bars else None
    volume_acceleration = (
        (volume_recent / volume_prior - 1.0) if (volume_recent is not None and volume_prior) else None
    )

    return BtcFeatureVector(
        at=at, current_price=current_price, price_to_beat=price_to_beat, distance_from_price_to_beat=distance,
        distance_from_price_to_beat_pct=distance_pct, time_remaining_seconds=time_remaining_seconds,
        returns=returns, momentum_slope_pct=momentum_slope_pct, realized_volatility=realized_volatility,
        volume_recent=volume_recent, volume_acceleration=volume_acceleration, bar_count=len(usable),
    )


def _stdev(values: list[float]) -> float:
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(variance)
