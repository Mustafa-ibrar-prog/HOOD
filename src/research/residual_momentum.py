"""Phase 12, Parts 6B-6D, 8: market-residual and sector-residual return
construction — a NEW module. Needs OTHER symbols' bars (a market proxy,
sector peers), which doesn't fit the single-symbol
src.features.base.Feature contract (see src/features/relative_strength.py's
module docstring), so this lives here, at the panel/cross-symbol level,
following the exact convention Phase 9-11 already established for
cross-symbol research logic (e.g. src.research.regime_transitions,
src.research.exposure_mechanisms).

CAUSALITY (Part 8's explicit requirement, "every rolling regression/window
must be strictly causal"): beta at bar t is estimated from the TRAILING
`beta_window` returns ENDING AT t-1 (never including t's own return), then
applied to t's own market return to compute t's residual — the same
"baseline excludes the current bar" convention RelativeVolume (Phase 2)
and VolumeZScore/VolatilityZScore (Phase 9/10) already use. Sector
residual return construction is causal by a different, simpler argument:
it only ever combines SAME-BAR peer returns (bar t's own realized return
for every peer), never a peer's future bar — identical in spirit to how
cross-sectional IC (src.research.ic) compares same-timestamp peers, not a
lookahead.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from src.data.bar import Bar
from src.research.analysis import mean


def _daily_returns(bars: Sequence[Bar]) -> list[float | None]:
    closes = [b.close for b in bars]
    out: list[float | None] = [None]
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        out.append(None if prev <= 0 else (closes[i] - prev) / prev)
    return out


def estimate_rolling_beta(stock_bars: Sequence[Bar], market_bars: Sequence[Bar], *, beta_window: int) -> list[float | None]:
    """beta[t] = cov(stock_return, market_return) / var(market_return),
    estimated over the TRAILING `beta_window` returns strictly BEFORE t
    (indices [t-beta_window, t-1], never including t) — so beta[t] is
    known at the moment bar t's OWN residual return is being computed, no
    lookahead. `stock_bars` and `market_bars` must be the same length and
    share the same timestamps (the caller's responsibility, same
    convention as every other panel-alignment function in this package).
    None until beta_window prior returns are all defined, or when the
    market-return variance over that window is 0 (degenerate)."""
    if beta_window < 2:
        raise ValueError("beta_window must be >= 2 (need variance)")
    if len(stock_bars) != len(market_bars):
        raise ValueError("stock_bars and market_bars must be the same length")
    stock_returns = _daily_returns(stock_bars)
    market_returns = _daily_returns(market_bars)
    n = len(stock_bars)
    out: list[float | None] = [None] * n
    for i in range(n):
        window_stock = stock_returns[max(0, i - beta_window) : i]
        window_market = market_returns[max(0, i - beta_window) : i]
        if len(window_stock) < beta_window or any(v is None for v in window_stock) or any(v is None for v in window_market):
            continue
        m_mean = mean(window_market)  # type: ignore[arg-type]
        s_mean = mean(window_stock)  # type: ignore[arg-type]
        cov = sum((s - s_mean) * (m - m_mean) for s, m in zip(window_stock, window_market)) / (beta_window - 1)
        var = sum((m - m_mean) ** 2 for m in window_market) / (beta_window - 1)  # type: ignore[operator]
        out[i] = None if var == 0 else cov / var
    return out


def market_residual_returns(stock_bars: Sequence[Bar], market_bars: Sequence[Bar], *, beta_window: int) -> list[float | None]:
    """residual[t] = stock_return[t] - beta[t] * market_return[t], where
    beta[t] is estimated causally (see estimate_rolling_beta) using only
    information strictly before t. None wherever beta or either same-bar
    return is undefined."""
    stock_returns = _daily_returns(stock_bars)
    market_returns = _daily_returns(market_bars)
    beta = estimate_rolling_beta(stock_bars, market_bars, beta_window=beta_window)
    out: list[float | None] = []
    for s, m, b in zip(stock_returns, market_returns, beta):
        out.append(None if s is None or m is None or b is None else s - b * m)
    return out


def sector_residual_returns(stock_bars: Sequence[Bar], peer_bars_by_symbol: Mapping[str, Sequence[Bar]]) -> list[float | None]:
    """residual[t] = stock_return[t] - equal_weight_mean(peer_return[t]
    across peer_bars_by_symbol) — every peer's SAME-BAR (never future)
    return, excluding the stock itself (the caller passes peers only,
    never including the stock in `peer_bars_by_symbol`). None wherever
    the stock's own return or ALL peers' returns at that bar are
    undefined (a bar with zero available peers has no defined sector
    return, never silently defaults to 0)."""
    stock_returns = _daily_returns(stock_bars)
    peer_returns_by_symbol = {sym: _daily_returns(bars) for sym, bars in peer_bars_by_symbol.items()}
    n = len(stock_bars)
    out: list[float | None] = []
    for i in range(n):
        peer_vals = [rets[i] for rets in peer_returns_by_symbol.values() if i < len(rets) and rets[i] is not None]
        if stock_returns[i] is None or not peer_vals:
            out.append(None)
            continue
        out.append(stock_returns[i] - mean(peer_vals))
    return out


def market_sector_residual_returns(
    stock_bars: Sequence[Bar], market_bars: Sequence[Bar], peer_bars_by_symbol: Mapping[str, Sequence[Bar]], *, beta_window: int,
) -> list[float | None]:
    """Sequential residualization (Part 8's "market + sector"): first
    remove the market-beta component (causal, see market_residual_returns),
    THEN remove the sector's own average MARKET-RESIDUAL (i.e. peers are
    ALSO expressed in market-residual terms first, so what's being
    subtracted is "how the sector itself moved beyond the market," not
    the sector's raw return, which would double-count the market
    component already removed from the stock)."""
    stock_market_resid = market_residual_returns(stock_bars, market_bars, beta_window=beta_window)
    peer_market_resid_by_symbol = {sym: market_residual_returns(bars, market_bars, beta_window=beta_window) for sym, bars in peer_bars_by_symbol.items()}
    n = len(stock_bars)
    out: list[float | None] = []
    for i in range(n):
        peer_vals = [rets[i] for rets in peer_market_resid_by_symbol.values() if i < len(rets) and rets[i] is not None]
        if stock_market_resid[i] is None or not peer_vals:
            out.append(None)
            continue
        out.append(stock_market_resid[i] - mean(peer_vals))
    return out


def cumulative_residual_momentum(residual_returns: Sequence[float | None], *, window: int) -> list[float | None]:
    """"Momentum" of a residual RETURN series — since a residual return
    series has no natural "price" to take a ratio of, momentum here is
    the trailing SUM of the last `window` residual returns (a cumulative
    residual return), not a ratio-based RateOfChange. None until
    `window` consecutive defined residual returns are available."""
    if window < 1:
        raise ValueError("window must be >= 1")
    n = len(residual_returns)
    out: list[float | None] = [None] * n
    for i in range(n):
        if i < window - 1:
            continue
        window_vals = residual_returns[i - window + 1 : i + 1]
        if any(v is None for v in window_vals):
            continue
        out[i] = sum(window_vals)  # type: ignore[arg-type]
    return out
