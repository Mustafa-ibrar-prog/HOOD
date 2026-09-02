"""Phase 12, Parts 6B-6D, 8, 28: residual-momentum construction tests —
no-lookahead (rolling beta, market residual, sector residual, market+
sector residual) plus hand-computed correctness.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data.bar import Bar
from src.research.residual_momentum import (
    cumulative_residual_momentum,
    estimate_rolling_beta,
    market_residual_returns,
    market_sector_residual_returns,
    sector_residual_returns,
)

TOTAL = 160
CUTOFF = 100


def _bars(symbol: str, closes: list[float]) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [Bar(timestamp=start + timedelta(days=i), symbol=symbol, timeframe="day", open=c, high=c + 0.2, low=c - 0.2, close=c, volume=1000) for i, c in enumerate(closes)]


def _random_walk(n: int, seed: int, drift: float = 0.0) -> list[float]:
    import random

    rng = random.Random(seed)
    price = 100.0
    closes = []
    for _ in range(n):
        price *= 1 + drift + rng.uniform(-0.02, 0.02)
        closes.append(max(price, 1.0))
    return closes


def _mutate_future(bars: list[Bar]) -> list[Bar]:
    out = list(bars[: CUTOFF + 1])
    start = bars[CUTOFF].timestamp
    for i in range(CUTOFF + 1, len(bars)):
        out.append(Bar(timestamp=start + timedelta(days=i - CUTOFF), symbol=bars[0].symbol, timeframe="day", open=1e9, high=2e9, low=5e8, close=1.5e9, volume=999_999_999))
    return out


def test_beta_matches_hand_computed_perfect_two_beta_relationship():
    """If stock_return = 2 * market_return exactly (no noise), the
    estimated beta should converge to ~2.0 once the window is full."""
    market_closes = _random_walk(80, seed=1)
    stock_closes = [100.0]
    for i in range(1, 80):
        market_ret = (market_closes[i] - market_closes[i - 1]) / market_closes[i - 1]
        stock_closes.append(stock_closes[-1] * (1 + 2 * market_ret))
    stock_bars = _bars("STOCK", stock_closes)
    market_bars = _bars("MKT", market_closes)
    beta = estimate_rolling_beta(stock_bars, market_bars, beta_window=20)
    non_none = [b for b in beta if b is not None]
    assert non_none
    assert abs(non_none[-1] - 2.0) < 0.05


def test_beta_none_before_window_is_full():
    market_closes = _random_walk(30, seed=2)
    stock_closes = _random_walk(30, seed=3)
    beta = estimate_rolling_beta(_bars("S", stock_closes), _bars("M", market_closes), beta_window=20)
    assert all(b is None for b in beta[:20])


def test_beta_requires_matching_lengths():
    with pytest.raises(ValueError):
        estimate_rolling_beta(_bars("S", [100, 101]), _bars("M", [100, 101, 102]), beta_window=2)


def test_market_residual_is_near_zero_when_stock_exactly_tracks_beta_times_market():
    market_closes = _random_walk(80, seed=4)
    stock_closes = [100.0]
    for i in range(1, 80):
        market_ret = (market_closes[i] - market_closes[i - 1]) / market_closes[i - 1]
        stock_closes.append(stock_closes[-1] * (1 + 1.5 * market_ret))
    residual = market_residual_returns(_bars("S", stock_closes), _bars("M", market_closes), beta_window=20)
    late_residuals = [r for r in residual[40:] if r is not None]
    assert late_residuals
    assert all(abs(r) < 0.01 for r in late_residuals)  # residual near 0 once beta has converged


def test_market_residual_no_lookahead():
    market_closes = _random_walk(TOTAL, seed=5)
    stock_closes = _random_walk(TOTAL, seed=6)
    stock_bars = _bars("S", stock_closes)
    market_bars = _bars("M", market_closes)
    stock_mut = _mutate_future(stock_bars)
    market_mut = _mutate_future(market_bars)
    r1 = market_residual_returns(stock_bars, market_bars, beta_window=20)
    r2 = market_residual_returns(stock_mut, market_mut, beta_window=20)
    for i in range(CUTOFF + 1):
        assert r1[i] == r2[i]


def test_sector_residual_hand_computed():
    stock_bars = _bars("S", [100, 110, 121])  # returns: None, 0.10, 0.10
    peer_a = _bars("A", [50, 52, 54.6])  # returns: None, 0.04, 0.05
    peer_b = _bars("B", [200, 210, 220.5])  # returns: None, 0.05, 0.05
    residual = sector_residual_returns(stock_bars, {"A": peer_a, "B": peer_b})
    # at i=1: stock_ret=0.10, peer_mean=(0.04+0.05)/2=0.045 -> residual=0.055
    assert residual[1] is not None and abs(residual[1] - 0.055) < 1e-9
    # at i=2: stock_ret=0.10, peer_mean=(0.05+0.05)/2=0.05 -> residual=0.05
    assert residual[2] is not None and abs(residual[2] - 0.05) < 1e-9
    assert residual[0] is None


def test_sector_residual_none_when_no_peers_defined():
    stock_bars = _bars("S", [100, 110])
    residual = sector_residual_returns(stock_bars, {})
    assert all(r is None for r in residual)


def test_sector_residual_no_lookahead():
    stock_closes = _random_walk(TOTAL, seed=7)
    peer_closes = {p: _random_walk(TOTAL, seed=s) for p, s in (("A", 8), ("B", 9))}
    stock_bars = _bars("S", stock_closes)
    peer_bars = {p: _bars(p, c) for p, c in peer_closes.items()}
    stock_mut = _mutate_future(stock_bars)
    peer_bars_mut = {p: _mutate_future(b) for p, b in peer_bars.items()}
    r1 = sector_residual_returns(stock_bars, peer_bars)
    r2 = sector_residual_returns(stock_mut, peer_bars_mut)
    for i in range(CUTOFF + 1):
        assert r1[i] == r2[i]


def test_market_sector_residual_no_lookahead():
    market_closes = _random_walk(TOTAL, seed=10)
    stock_closes = _random_walk(TOTAL, seed=11)
    peer_closes = {"A": _random_walk(TOTAL, seed=12), "B": _random_walk(TOTAL, seed=13)}
    stock_bars = _bars("S", stock_closes)
    market_bars = _bars("M", market_closes)
    peer_bars = {p: _bars(p, c) for p, c in peer_closes.items()}
    r1 = market_sector_residual_returns(stock_bars, market_bars, peer_bars, beta_window=20)
    stock_mut, market_mut = _mutate_future(stock_bars), _mutate_future(market_bars)
    peer_bars_mut = {p: _mutate_future(b) for p, b in peer_bars.items()}
    r2 = market_sector_residual_returns(stock_mut, market_mut, peer_bars_mut, beta_window=20)
    for i in range(CUTOFF + 1):
        assert r1[i] == r2[i]


def test_cumulative_residual_momentum_hand_computed():
    residuals = [None, 0.01, 0.02, -0.01, 0.03]
    momentum = cumulative_residual_momentum(residuals, window=3)
    assert momentum[0] is None and momentum[1] is None and momentum[2] is None  # not enough defined history
    assert momentum[3] is not None and abs(momentum[3] - (0.01 + 0.02 - 0.01)) < 1e-9
    assert momentum[4] is not None and abs(momentum[4] - (0.02 - 0.01 + 0.03)) < 1e-9


def test_cumulative_residual_momentum_invalid_window():
    with pytest.raises(ValueError):
        cumulative_residual_momentum([0.01, 0.02], window=0)
