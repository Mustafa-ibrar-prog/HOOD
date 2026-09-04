"""Phase 29, Part 12 — ORATS coverage matrix. Reuses Phase 27's exact
target-underlying/year lists (`phase27_coverage_report.TARGET_
UNDERLYINGS`/`TARGET_YEARS`) rather than re-deriving them -- Part 12's
own row/column lists here are identical to Phase 27's Part 12.

Every cell is honestly `NO_DATA` this phase -- zero real ORATS
observations exist for any underlying (`ORATS_ACTIVATION_PENDING_
HUMAN`). This module's real job is to prove the REPORTING MACHINERY is
ready and correct (tested against a small ORATS-shaped fixture), not to
claim any real coverage exists yet.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase27_coverage_report import TARGET_UNDERLYINGS, TARGET_YEARS

__all__ = ["TARGET_UNDERLYINGS", "TARGET_YEARS", "CoverageCell", "ORATSCoverageMatrix", "build_orats_coverage_matrix"]


class CoverageCell(enum.Enum):
    """Part 12's exact 3-value vocabulary this phase (no SYNTHETIC_ONLY
    value this time -- Part 12 does not ask for one, and none is ever
    used)."""

    REAL_DATA = "real_data"
    PARTIAL = "partial"
    NO_DATA = "no_data"


@dataclass(frozen=True)
class ORATSCoverageMatrix:
    cells: dict[tuple[str, int], CoverageCell]

    def cell(self, underlying: str, year: int) -> CoverageCell:
        return self.cells.get((underlying, year), CoverageCell.NO_DATA)

    def any_real_data(self) -> bool:
        return any(c == CoverageCell.REAL_DATA for c in self.cells.values())


def _years_with_data(store: InMemoryLeanSampleStore, underlying: str) -> set[int]:
    years = set()
    for cid, contract in store.contracts.items():
        if contract.underlying_symbol != underlying:
            continue
        for obs_dict in (store.quotes, store.trades, store.open_interest):
            for o in obs_dict.get(cid, []):
                if o.timestamps.event_time is not None:
                    years.add(o.timestamps.event_time.year)
    return years


def build_orats_coverage_matrix(store: InMemoryLeanSampleStore) -> ORATSCoverageMatrix:
    """`store` may be empty (this phase's real, honest case) or a real
    future store once Path B is reached -- the function itself never
    changes; only its input does."""
    cells: dict[tuple[str, int], CoverageCell] = {}
    for underlying in TARGET_UNDERLYINGS:
        years_present = _years_with_data(store, underlying)
        for year in TARGET_YEARS:
            # PARTIAL is reserved for a future real case (some fields present,
            # others missing, for a real year) -- not reachable from a purely
            # empty or fully-populated real store, so it is never assigned here.
            cells[(underlying, year)] = CoverageCell.REAL_DATA if year in years_present else CoverageCell.NO_DATA
    return ORATSCoverageMatrix(cells=cells)


# This phase's real, current, empty store -- zero real ORATS data exists.
EMPTY_STORE = InMemoryLeanSampleStore(contracts={}, lifecycles={}, quotes={}, trades={}, open_interest={}, underlying={})
CURRENT_ORATS_COVERAGE = build_orats_coverage_matrix(EMPTY_STORE)
