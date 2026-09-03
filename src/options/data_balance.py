"""Phase 20, Part 7 — data-balance / concentration reporting.

A generic top-share concentration metric applied across whatever
dimension a caller asks about (symbol, sector, expiration, moneyness
bucket, call/put, year). Reporting only: this module computes numbers,
it does not decide whether a given concentration is "acceptable" --
Part 7's own example makes the bar explicit ('If 80% of observations
come from NVDA, the research must NOT be described as broadly
diversified') and callers/report-writers apply that judgment using the
numbers below.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class ConcentrationResult:
    dimension: str  # e.g. "symbol", "sector", "expiration", "moneyness_bucket", "call_put", "year"
    total_observations: int
    counts_by_key: dict[str, int]
    top_key: str | None
    top_key_share: float  # top_key's count / total_observations

    def render(self) -> str:
        if self.top_key is None:
            return f"{self.dimension}: no observations"
        return f"{self.dimension}: top={self.top_key!r} ({self.top_key_share:.1%} of {self.total_observations} observations)"


def compute_concentration(values: Sequence[str], *, dimension: str) -> ConcentrationResult:
    total = len(values)
    counts = Counter(values)
    if total == 0:
        return ConcentrationResult(dimension=dimension, total_observations=0, counts_by_key={}, top_key=None, top_key_share=0.0)
    top_key, top_count = counts.most_common(1)[0]
    return ConcentrationResult(
        dimension=dimension, total_observations=total, counts_by_key=dict(counts),
        top_key=top_key, top_key_share=top_count / total,
    )


@dataclass(frozen=True)
class DataBalanceReport:
    symbol_concentration: ConcentrationResult
    sector_concentration: ConcentrationResult
    expiration_concentration: ConcentrationResult
    moneyness_concentration: ConcentrationResult
    call_put_concentration: ConcentrationResult
    year_concentration: ConcentrationResult

    def render(self) -> str:
        return "\n".join(c.render() for c in (
            self.symbol_concentration, self.sector_concentration, self.expiration_concentration,
            self.moneyness_concentration, self.call_put_concentration, self.year_concentration,
        ))


def build_data_balance_report(rows: Sequence[dict], *, sector_by_symbol: dict[str, str | None]) -> DataBalanceReport:
    """`rows` are research-panel rows carrying `underlying_symbol`,
    `expiration` (str), `moneyness_bucket` (str), `call_put` (str), and
    `timestamp` (date) -- `sector_by_symbol` comes from a real
    `UnderlyingUniverse` lookup (never guessed)."""
    symbols = [r["underlying_symbol"] for r in rows]
    sectors = [sector_by_symbol.get(r["underlying_symbol"]) or "unclassified" for r in rows]
    expirations = [r["expiration"] for r in rows]
    buckets = [r["moneyness_bucket"] for r in rows if r.get("moneyness_bucket") is not None]
    call_puts = [r["call_put"] for r in rows]
    years = [str(r["timestamp"].year) for r in rows]

    return DataBalanceReport(
        symbol_concentration=compute_concentration(symbols, dimension="symbol"),
        sector_concentration=compute_concentration(sectors, dimension="sector"),
        expiration_concentration=compute_concentration(expirations, dimension="expiration"),
        moneyness_concentration=compute_concentration(buckets, dimension="moneyness_bucket"),
        call_put_concentration=compute_concentration(call_puts, dimension="call_put"),
        year_concentration=compute_concentration(years, dimension="year"),
    )
