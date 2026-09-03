"""Phase 20, Part 5 — expiration diversity measurement, and the explicit
CROSS_SECTIONAL_IC_UNDEFINED discipline.

Phase 19 exposed a real, structural problem: a research panel built from
a SINGLE expiration has zero cross-sectional variance in DTE, so a
cross-sectional IC on that feature is not "weak" -- it is mathematically
UNDEFINED (nothing to rank). This module makes that check explicit and
reusable rather than something a script silently discovers via a `None`
average_ic and has to remember to explain in prose.

`has_cross_sectional_variance` must NEVER be bypassed by substituting a
pooled time-series statistic and calling it "cross-sectional" -- the two
are computed by entirely different functions in this codebase
(cross-sectional: `src.research.ic.compute_ic_series`; pooled
time-series: `src.research.analysis.spearman_correlation` applied
directly to a stacked column) and must be reported under different,
explicit labels. See `docs/options_universe_expansion.md`'s discovery
campaign section for a worked example of both, side by side, never
mixed into one number.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Sequence

CROSS_SECTIONAL_IC_UNDEFINED = "CROSS_SECTIONAL_IC_UNDEFINED"


def has_cross_sectional_variance(panel_rows: Sequence[dict], feature_col: str, *, timestamp_col: str = "timestamp") -> bool:
    """True iff there exists at least one timestamp where `feature_col`
    takes on 2+ distinct real values across the rows sharing that
    timestamp. A panel built from one expiration will have this be False
    for `dte` (every contract shares the same DTE on a given day) even
    though the panel has many rows."""
    by_ts: dict = defaultdict(set)
    for row in panel_rows:
        v = row.get(feature_col)
        if v is not None:
            by_ts[row[timestamp_col]].add(v)
    return any(len(values) >= 2 for values in by_ts.values())


@dataclass(frozen=True)
class ExpirationCoverage:
    expiration: date
    contract_count: int
    usable_observation_count: int  # bars actually present across all contracts for this expiration
    dte_at_first_observation: int | None  # None if no observation exists


@dataclass(frozen=True)
class ExpirationDiversityReport:
    underlying_symbol: str
    expirations: tuple[ExpirationCoverage, ...]

    @property
    def expiration_count(self) -> int:
        return len(self.expirations)

    @property
    def expiration_spacing_days(self) -> tuple[int, ...]:
        """Calendar days between consecutive expirations, sorted. Empty
        or single-element for 0-1 expirations -- 'spacing' is undefined
        with fewer than 2 points, not zero."""
        dates = sorted(e.expiration for e in self.expirations)
        return tuple((b - a).days for a, b in zip(dates, dates[1:]))

    @property
    def has_multiple_expirations(self) -> bool:
        return self.expiration_count >= 2


def build_expiration_diversity_report(underlying_symbol: str, contracts_by_expiration: dict[date, list[dict]]) -> ExpirationDiversityReport:
    """`contracts_by_expiration` maps expiration -> list of {"bar_count": int, "first_bar_date": date | None}
    dicts (one per contract for that expiration) -- callers build this
    from their own real, transcribed contract data; this function does
    not fetch anything."""
    coverages = []
    for expiration, contracts in sorted(contracts_by_expiration.items()):
        total_bars = sum(c["bar_count"] for c in contracts)
        first_dates = [c["first_bar_date"] for c in contracts if c.get("first_bar_date") is not None]
        dte_at_first = (expiration - min(first_dates)).days if first_dates else None
        coverages.append(ExpirationCoverage(
            expiration=expiration, contract_count=len(contracts), usable_observation_count=total_bars,
            dte_at_first_observation=dte_at_first,
        ))
    return ExpirationDiversityReport(underlying_symbol=underlying_symbol, expirations=tuple(coverages))
