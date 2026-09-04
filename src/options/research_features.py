"""Phase 30, Part 2/17 — the strictly causal options feature engine.

STRICT NO-FUTURE-DATA RULE, same contract as `src/features/base.py`'s
existing equity-feature framework (Phase 2): every feature value at row
index i is computed ONLY from rows[0..i] of the SAME contract, sorted by
`observation_timestamp` ascending, never from rows[i+1:]. This module
does not subclass `src.features.base.Feature` — that framework's
`compute(bars: Sequence[Bar])` contract is built around equity OHLCV
`Bar` objects (`src/data/bar.py`), a materially different shape from
`ResearchObservation` (which carries option-specific fields — bid/ask,
strike, moneyness, DTE — that have no `Bar` equivalent). Reusing it would
mean forcing option rows through an equity bar shape or duplicating the
Feature ABC with a second signature; a small, purpose-built causal
computation here is more honest than either. The NO-FUTURE-DATA
*contract* itself (index i sees only [0..i]) is followed exactly, and
this module is tested the same way `tests/test_feature_no_lookahead.py`
tests the equity features: a synthetic-leakage test that replaces every
row after a cutoff with extreme values and asserts nothing at or before
the cutoff changes.

Reuse: `implied_volatility_bisection`/`BlackScholesInputs` (Phase 26's
`black_scholes.py`) and `ASSUMED_RISK_FREE_RATE`/`ASSUMED_DIVIDEND_YIELD`
(Phase 26's `phase26_iv_greeks_certification.py` — the same explicit,
externally-documented assumption, not re-derived here) do the IV
reconstruction. Every reconstructed IV value is labeled `RECONSTRUCTED_IV`
(`iv_source` field) — this dataset has ZERO native/vendor-supplied IV
(Phase 26/27 established this as a real, permanent finding), so a
reconstructed value must never be presented unlabeled as if it were
observed. `market_relative_return` is always `None`: this dataset carries
no market-benchmark/index series at all (a real, permanent limitation —
see Part 11's registry), so it is never approximated from a single
underlying's own return.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime

from src.options.black_scholes import BlackScholesInputs, implied_volatility_bisection
from src.options.phase26_iv_greeks_certification import ASSUMED_DIVIDEND_YIELD, ASSUMED_RISK_FREE_RATE
from src.options.research_dataset import ResearchObservation

DEFAULT_LOOKBACK = 5


@dataclass(frozen=True)
class FeatureRow:
    option_id: str
    observation_timestamp: datetime

    # --- contract features ---
    moneyness: float | None
    log_moneyness: float | None
    dte: int | None
    time_to_expiration_years: float | None
    is_call: bool
    strike_distance_pct: float | None

    # --- price features (option's own price series) ---
    option_return: float | None
    rolling_vol: float | None
    recent_range_pct: float | None
    momentum: float | None
    mean_reversion: float | None
    range_expansion_ratio: float | None

    # --- liquidity features ---
    spread: float | None
    spread_pct: float | None
    volume: float | None
    open_interest: float | None
    volume_oi_ratio: float | None
    quote_availability: bool

    # --- underlying features ---
    underlying_momentum: float | None
    underlying_realized_vol: float | None
    vol_regime: str | None  # "LOW" | "MEDIUM" | "HIGH" -- illustrative, configurable thresholds, not optimized
    trend: str | None  # "UP" | "DOWN" | "FLAT"
    drawdown: float | None
    market_relative_return: None  # always None -- no benchmark series exists in this dataset (Part 11)

    # --- IV feature (reconstructed only -- see module docstring) ---
    reconstructed_iv: float | None
    iv_source: str | None  # "RECONSTRUCTED_IV" when reconstructed_iv is not None, else None


def _pct_return(prev: float | None, cur: float | None) -> float | None:
    if prev is None or cur is None or prev == 0:
        return None
    return (cur - prev) / prev


def _stdev(values: list[float]) -> float | None:
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return None
    return statistics.stdev(clean)


def compute_features_for_contract(rows: list[ResearchObservation], *, lookback: int = DEFAULT_LOOKBACK) -> list[FeatureRow]:
    """`rows` must already be all observations for exactly ONE contract,
    in ascending timestamp order (as `build_research_observations`
    already returns them per contract) -- this function does not
    re-sort or re-group, so passing mixed-contract rows would silently
    compute nonsense across unrelated contracts."""
    out: list[FeatureRow] = []

    closes: list[float | None] = []
    highs: list[float | None] = []
    lows: list[float | None] = []
    underlying_prices: list[float] = []  # carried-forward real observed prices only, never fabricated
    last_underlying_price: float | None = None

    for row in rows:
        closes.append(row.option_close)
        highs.append(row.option_high)
        lows.append(row.option_low)

        if row.underlying_price is not None:
            last_underlying_price = row.underlying_price
        underlying_prices.append(last_underlying_price)  # None until the first real observation seen

        window_closes = [c for c in closes[-(lookback + 1):] if c is not None]
        prev_close = closes[-2] if len(closes) >= 2 else None
        option_return = _pct_return(prev_close, row.option_close)
        rolling_returns = [_pct_return(a, b) for a, b in zip(window_closes, window_closes[1:])]
        rolling_vol = _stdev([r for r in rolling_returns if r is not None])

        recent_highs = [h for h in highs[-lookback:] if h is not None]
        recent_lows = [l for l in lows[-lookback:] if l is not None]
        recent_range_pct = None
        if recent_highs and recent_lows and row.option_close:
            recent_range_pct = (max(recent_highs) - min(recent_lows)) / row.option_close

        momentum = None
        if len(closes) > lookback and closes[-1 - lookback] not in (None, 0) and row.option_close is not None:
            momentum = (row.option_close - closes[-1 - lookback]) / closes[-1 - lookback]

        mean_reversion = None
        if window_closes and row.option_close is not None:
            mean_val = statistics.mean(window_closes)
            if mean_val != 0:
                mean_reversion = (row.option_close - mean_val) / mean_val

        range_expansion_ratio = None
        if row.option_high is not None and row.option_low is not None:
            current_range = row.option_high - row.option_low
            past_ranges = [h - l for h, l in zip(highs[-(lookback + 1):-1], lows[-(lookback + 1):-1]) if h is not None and l is not None]
            if past_ranges and statistics.mean(past_ranges) > 0:
                range_expansion_ratio = current_range / statistics.mean(past_ranges)

        spread = None
        spread_pct = None
        if row.bid is not None and row.ask is not None:
            spread = row.ask - row.bid
            mid = (row.ask + row.bid) / 2
            if mid > 0:
                spread_pct = spread / mid
        quote_availability = row.bid is not None and row.ask is not None
        volume_oi_ratio = None
        if row.volume is not None and row.open_interest not in (None, 0):
            volume_oi_ratio = row.volume / row.open_interest

        log_moneyness = None
        if row.moneyness is not None and row.moneyness > 0:
            import math
            log_moneyness = math.log(row.moneyness)
        time_to_expiration_years = row.dte / 365.0 if row.dte is not None else None
        strike_distance_pct = None
        if row.underlying_price:
            strike_distance_pct = abs(row.strike - row.underlying_price) / row.underlying_price

        u_window = [p for p in underlying_prices[-(lookback + 1):] if p is not None]
        underlying_momentum = None
        if len(u_window) >= 2 and u_window[0] != 0:
            underlying_momentum = (u_window[-1] - u_window[0]) / u_window[0]
        u_returns = [_pct_return(a, b) for a, b in zip(u_window, u_window[1:])]
        underlying_realized_vol = _stdev([r for r in u_returns if r is not None])

        vol_regime = None
        if underlying_realized_vol is not None:
            if underlying_realized_vol < 0.01:
                vol_regime = "LOW"
            elif underlying_realized_vol < 0.03:
                vol_regime = "MEDIUM"
            else:
                vol_regime = "HIGH"

        trend = None
        if underlying_momentum is not None:
            if underlying_momentum > 0.001:
                trend = "UP"
            elif underlying_momentum < -0.001:
                trend = "DOWN"
            else:
                trend = "FLAT"

        drawdown = None
        u_full_window = [p for p in underlying_prices if p is not None][-max(lookback, 1):]
        if u_full_window and last_underlying_price is not None:
            peak = max(u_full_window)
            if peak > 0:
                drawdown = (last_underlying_price - peak) / peak

        reconstructed_iv = None
        iv_source = None
        target_price = row.option_close if row.option_close is not None else (
            (row.bid + row.ask) / 2 if row.bid is not None and row.ask is not None else None
        )
        if (target_price is not None and target_price > 0 and row.underlying_price is not None
                and time_to_expiration_years is not None and time_to_expiration_years > 0):
            inputs_ok = row.underlying_price > 0 and row.strike > 0
            if inputs_ok:
                reconstructed_iv = implied_volatility_bisection(
                    target_price=target_price, underlying_price=row.underlying_price, strike=row.strike,
                    time_to_expiration_years=time_to_expiration_years, risk_free_rate=ASSUMED_RISK_FREE_RATE,
                    dividend_yield=ASSUMED_DIVIDEND_YIELD, call_put=row.call_put,
                )
                if reconstructed_iv is not None:
                    iv_source = "RECONSTRUCTED_IV"

        out.append(FeatureRow(
            option_id=row.option_id, observation_timestamp=row.observation_timestamp,
            moneyness=row.moneyness, log_moneyness=log_moneyness, dte=row.dte,
            time_to_expiration_years=time_to_expiration_years, is_call=(row.call_put == "call"),
            strike_distance_pct=strike_distance_pct,
            option_return=option_return, rolling_vol=rolling_vol, recent_range_pct=recent_range_pct,
            momentum=momentum, mean_reversion=mean_reversion, range_expansion_ratio=range_expansion_ratio,
            spread=spread, spread_pct=spread_pct, volume=row.volume, open_interest=row.open_interest,
            volume_oi_ratio=volume_oi_ratio, quote_availability=quote_availability,
            underlying_momentum=underlying_momentum, underlying_realized_vol=underlying_realized_vol,
            vol_regime=vol_regime, trend=trend, drawdown=drawdown, market_relative_return=None,
            reconstructed_iv=reconstructed_iv, iv_source=iv_source,
        ))
    return out


def compute_features(observations: list[ResearchObservation], *, lookback: int = DEFAULT_LOOKBACK) -> list[FeatureRow]:
    """Groups by `option_id` (preserving each group's real timestamp
    order) and computes each contract's features independently -- never
    letting one contract's history leak into another's."""
    by_contract: dict[str, list[ResearchObservation]] = {}
    for row in observations:
        by_contract.setdefault(row.option_id, []).append(row)

    out: list[FeatureRow] = []
    for option_id in sorted(by_contract):
        contract_rows = sorted(by_contract[option_id], key=lambda r: r.observation_timestamp)
        out.extend(compute_features_for_contract(contract_rows, lookback=lookback))
    return out
