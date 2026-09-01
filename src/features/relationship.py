"""Relationship features: rolling correlation, rolling beta, and relative
strength between two symbols' bar series.

These are deliberately NOT `Feature` subclasses: every other feature in
this package answers a question about one symbol's own series, but a
relationship feature inherently needs two aligned series (e.g. a symbol
vs. a benchmark). Bolting that onto FeatureEngine's single-series
`compute(bars)` contract would either silently assume a global benchmark
or complicate every other feature's interface for a need only this
category has — so these are plain functions instead, operating on two
`Bar` sequences, called directly by research code that needs them rather
than being auto-run by FeatureEngine.compute(). Still fully causal:
window i only ever uses index <= i of both series.
"""

from __future__ import annotations

from typing import Sequence

from src.data.bar import Bar
from src.features._util import mean, pct_change, stdev


def align_by_timestamp(bars_a: Sequence[Bar], bars_b: Sequence[Bar]) -> tuple[list[Bar], list[Bar]]:
    """Keeps only timestamps present in both series, in ascending order —
    the prerequisite for any of the pairwise functions below."""
    b_by_ts = {b.timestamp: b for b in bars_b}
    a_out, b_out = [], []
    for a in bars_a:
        b = b_by_ts.get(a.timestamp)
        if b is not None:
            a_out.append(a)
            b_out.append(b)
    return a_out, b_out


def rolling_correlation(closes_a: Sequence[float], closes_b: Sequence[float], window: int) -> list[float | None]:
    """Causal Pearson correlation of the two series' simple 1-bar returns
    over a trailing `window`."""
    ra, rb = pct_change(closes_a, 1), pct_change(closes_b, 1)
    out: list[float | None] = [None] * len(closes_a)
    for i in range(len(closes_a)):
        if i < window:
            continue
        wa, wb = ra[i - window + 1 : i + 1], rb[i - window + 1 : i + 1]
        if any(v is None for v in wa) or any(v is None for v in wb):
            continue
        ma_, mb_ = mean(wa), mean(wb)  # type: ignore[arg-type]
        cov = sum((x - ma_) * (y - mb_) for x, y in zip(wa, wb)) / (len(wa) - 1)  # type: ignore[operator]
        sa, sb = stdev(wa), stdev(wb)  # type: ignore[arg-type]
        out[i] = None if sa == 0 or sb == 0 else cov / (sa * sb)
    return out


def rolling_beta(closes_a: Sequence[float], closes_b: Sequence[float], window: int) -> list[float | None]:
    """Causal beta of a's returns vs. b's returns: cov(a,b)/var(b), over a
    trailing `window`."""
    ra, rb = pct_change(closes_a, 1), pct_change(closes_b, 1)
    out: list[float | None] = [None] * len(closes_a)
    for i in range(len(closes_a)):
        if i < window:
            continue
        wa, wb = ra[i - window + 1 : i + 1], rb[i - window + 1 : i + 1]
        if any(v is None for v in wa) or any(v is None for v in wb):
            continue
        ma_, mb_ = mean(wa), mean(wb)  # type: ignore[arg-type]
        cov = sum((x - ma_) * (y - mb_) for x, y in zip(wa, wb)) / (len(wa) - 1)  # type: ignore[operator]
        var_b = sum((y - mb_) ** 2 for y in wb) / (len(wb) - 1)  # type: ignore[operator]
        out[i] = None if var_b == 0 else cov / var_b
    return out


def relative_strength(closes_a: Sequence[float], closes_b: Sequence[float], window: int) -> list[float | None]:
    """Ratio of a's trailing-window total return to b's, expressed as
    (1+ret_a)/(1+ret_b) - 1: positive means a outperformed b over the
    window, causal by construction (uses only [t-window, t])."""
    out: list[float | None] = [None] * len(closes_a)
    for i in range(len(closes_a)):
        if i < window:
            continue
        a0, a1 = closes_a[i - window], closes_a[i]
        b0, b1 = closes_b[i - window], closes_b[i]
        if a0 == 0 or b0 == 0:
            continue
        ret_a, ret_b = a1 / a0 - 1, b1 / b0 - 1
        out[i] = None if (1 + ret_b) == 0 else (1 + ret_a) / (1 + ret_b) - 1
    return out
