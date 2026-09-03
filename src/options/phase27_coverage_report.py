"""Phase 27, Part 12 — the coverage matrix: target underlyings x years,
built entirely from the real ingested store. Never fills a gap with
synthetic data (Part 12's explicit instruction) -- a cell with no real
observation is `NO_DATA`, always.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from src.options.phase26_dataset_builder import InMemoryLeanSampleStore

# Part 12's exact row list.
TARGET_UNDERLYINGS: tuple[str, ...] = ("AAPL", "NVDA", "TSLA", "SPY", "QQQ", "MSFT", "AMD", "AMZN", "META", "GOOGL", "NFLX", "IWM")
TARGET_YEARS: tuple[int, ...] = (2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026)

# Real underlyings this dataset actually has that are NOT on the target list
# (GOOG is a genuinely different ticker/share-class from GOOGL -- never
# credited to GOOGL's row) -- reported separately, honestly, not hidden.
BONUS_NON_TARGET_UNDERLYINGS: tuple[str, ...] = ("GOOG", "FOXA", "NWSA", "TWX")


class CoverageCell(enum.Enum):
    REAL_DATA = "real_data"
    NO_DATA = "no_data"
    PARTIAL = "partial"
    SYNTHETIC_ONLY = "synthetic_only"  # never actually used by this phase -- no synthetic data is ever presented as coverage


@dataclass(frozen=True)
class CoverageMatrix:
    cells: dict[tuple[str, int], CoverageCell]
    bonus_coverage: dict[tuple[str, int], CoverageCell]

    def cell(self, underlying: str, year: int) -> CoverageCell:
        return self.cells.get((underlying, year), CoverageCell.NO_DATA)


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


def build_coverage_matrix(store: InMemoryLeanSampleStore) -> CoverageMatrix:
    cells: dict[tuple[str, int], CoverageCell] = {}
    for underlying in TARGET_UNDERLYINGS:
        years_present = _years_with_data(store, underlying)
        for year in TARGET_YEARS:
            cells[(underlying, year)] = CoverageCell.REAL_DATA if year in years_present else CoverageCell.NO_DATA

    bonus: dict[tuple[str, int], CoverageCell] = {}
    for underlying in BONUS_NON_TARGET_UNDERLYINGS:
        years_present = _years_with_data(store, underlying)
        for year in sorted(years_present):
            bonus[(underlying, year)] = CoverageCell.REAL_DATA

    return CoverageMatrix(cells=cells, bonus_coverage=bonus)


@dataclass(frozen=True)
class FieldAvailabilityReport:
    underlying: str
    contract_count: int
    observation_count: int
    expiration_count: int
    moneyness_buckets: tuple[str, ...]
    call_count: int
    put_count: int
    has_daily_resolution: bool
    has_intraday_resolution: bool
    quote_available: bool
    volume_available: bool
    open_interest_available: bool
    iv_available_native: bool  # always False for this dataset -- see phase26_iv_greeks_certification
    greeks_available_native: bool  # always False for this dataset


def moneyness_bucket(strike: float, underlying_prices: list[float]) -> str:
    if not underlying_prices:
        return "unknown_no_underlying_price"
    ref = underlying_prices[len(underlying_prices) // 2]  # a real, representative (median-index) underlying price
    ratio = strike / ref
    if ratio < 0.9:
        return "deep_itm_or_otm_below_0.9x"
    if ratio < 0.98:
        return "0.90x-0.98x"
    if ratio <= 1.02:
        return "0.98x-1.02x_near_atm"
    if ratio <= 1.10:
        return "1.02x-1.10x"
    return "above_1.10x"


def build_field_availability_report(store: InMemoryLeanSampleStore, underlying: str) -> FieldAvailabilityReport:
    """Moneyness honesty note: a contract is only classified against a
    REAL underlying price observed on (or nearest to) that SAME
    contract's own real observation date -- never against an arbitrary
    historical price from a different era of the same symbol's series.
    This matters concretely for this dataset: SPY's paired equity file
    only covers 1998-2021-03-31, so a naive "any available SPY price"
    reference would silently misclassify the real 2023-08-03 SPY
    contracts against a decade-stale price. Contracts with no
    date-aligned real underlying price stay `unknown_no_underlying_price`."""
    contracts = [c for c in store.contracts.values() if c.underlying_symbol == underlying]
    cids = [c.option_id for c in contracts]
    price_by_date = {o.timestamps.event_time.date(): o.value for o in store.underlying.get(underlying, [])
                      if o.field == "close" and o.value is not None and o.timestamps.event_time is not None}

    obs_count = sum(len(store.quotes.get(cid, [])) + len(store.trades.get(cid, [])) + len(store.open_interest.get(cid, [])) for cid in cids)
    expirations = {c.expiration for c in contracts}

    bucket_set = set()
    for c in contracts:
        lifecycle = store.lifecycles.get(c.option_id)
        ref_date = lifecycle.first_observable_date if lifecycle else None
        ref_price = price_by_date.get(ref_date) if ref_date else None
        bucket_set.add(moneyness_bucket(c.strike, [ref_price] if ref_price is not None else []))
    buckets = tuple(sorted(bucket_set))
    calls = sum(1 for c in contracts if c.call_put == "call")
    puts = sum(1 for c in contracts if c.call_put == "put")

    has_daily = any(o.timestamps.event_time is not None and o.timestamps.event_time.hour == 0 and o.timestamps.event_time.minute == 0
                     for cid in cids for o in store.quotes.get(cid, []))
    has_intraday = any(o.timestamps.event_time is not None and not (o.timestamps.event_time.hour == 0 and o.timestamps.event_time.minute == 0)
                        for cid in cids for o in store.quotes.get(cid, []))

    quote_available = any(store.quotes.get(cid) for cid in cids)
    volume_available = any(o.field == "volume" for cid in cids for o in store.trades.get(cid, []))
    oi_available = any(store.open_interest.get(cid) for cid in cids)

    return FieldAvailabilityReport(
        underlying=underlying, contract_count=len(contracts), observation_count=obs_count,
        expiration_count=len(expirations), moneyness_buckets=buckets, call_count=calls, put_count=puts,
        has_daily_resolution=has_daily, has_intraday_resolution=has_intraday,
        quote_available=quote_available, volume_available=volume_available, open_interest_available=oi_available,
        iv_available_native=False, greeks_available_native=False,
    )
