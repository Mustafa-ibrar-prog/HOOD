"""Phase 27, Part 13 — sample-balance / concentration measurement. The
dataset must not be reported as diversified merely because many files
exist -- these functions report real concentration ratios computed from
the actual ingested store.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from src.options.phase26_dataset_builder import InMemoryLeanSampleStore

# Real, external, GICS-style sector classification -- a fact about these
# companies, not something this dataset's own files state. FOXA/NWSA are
# both News Corp-family entities (a real, structural fact: both were part
# of the 21st Century Fox / News Corp 2013 split) -- reported honestly,
# not hidden, since it directly affects how "diversified" this sample
# really is.
SECTOR_MAP: dict[str, str] = {
    "AAPL": "technology", "GOOG": "communication_services", "SPY": "broad_market_etf",
    "FOXA": "communication_services_news_corp_family", "NWSA": "communication_services_news_corp_family",
    "TWX": "communication_services_media",
}


@dataclass(frozen=True)
class ConcentrationReport:
    top_underlying: str
    top_underlying_pct: float
    top_year: int | None
    top_year_pct: float
    top_expiration: str
    top_expiration_pct: float
    top_moneyness_bucket: str
    top_moneyness_bucket_pct: float
    call_put_ratio: float | None  # calls / puts; None if puts == 0
    n_underlyings: int
    n_expirations: int
    top_sector: str
    top_sector_pct: float


def _pct_of_top(counter: Counter) -> tuple[object, float]:
    if not counter:
        return None, 0.0
    top_key, top_count = counter.most_common(1)[0]
    total = sum(counter.values())
    return top_key, (top_count / total if total else 0.0)


def build_concentration_report(store: InMemoryLeanSampleStore, *, moneyness_by_underlying) -> ConcentrationReport:
    """`moneyness_by_underlying` is a callable(underlying, strike) ->
    bucket label, reused from phase27_coverage_report so bucket
    definitions are computed identically in exactly one place."""
    underlying_counts = Counter(c.underlying_symbol for c in store.contracts.values())
    expiration_counts = Counter(c.expiration.isoformat() for c in store.contracts.values())
    call_put_counts = Counter(c.call_put for c in store.contracts.values())

    year_counts: Counter = Counter()
    for cid in store.contracts:
        for o in store.quotes.get(cid, []) + store.trades.get(cid, []) + store.open_interest.get(cid, []):
            if o.timestamps.event_time is not None:
                year_counts[o.timestamps.event_time.year] += 1

    moneyness_counts: Counter = Counter()
    for c in store.contracts.values():
        moneyness_counts[moneyness_by_underlying(c.underlying_symbol, c.strike)] += 1

    sector_counts: Counter = Counter()
    for c in store.contracts.values():
        sector_counts[SECTOR_MAP.get(c.underlying_symbol, "unknown_sector")] += 1

    top_underlying, top_underlying_pct = _pct_of_top(underlying_counts)
    top_year, top_year_pct = _pct_of_top(year_counts)
    top_expiration, top_expiration_pct = _pct_of_top(expiration_counts)
    top_bucket, top_bucket_pct = _pct_of_top(moneyness_counts)
    top_sector, top_sector_pct = _pct_of_top(sector_counts)

    calls, puts = call_put_counts.get("call", 0), call_put_counts.get("put", 0)
    ratio = (calls / puts) if puts else None

    return ConcentrationReport(
        top_underlying=top_underlying or "", top_underlying_pct=top_underlying_pct,
        top_year=top_year, top_year_pct=top_year_pct,
        top_expiration=top_expiration or "", top_expiration_pct=top_expiration_pct,
        top_moneyness_bucket=top_bucket or "", top_moneyness_bucket_pct=top_bucket_pct,
        call_put_ratio=ratio, n_underlyings=len(underlying_counts), n_expirations=len(expiration_counts),
        top_sector=top_sector or "", top_sector_pct=top_sector_pct,
    )
