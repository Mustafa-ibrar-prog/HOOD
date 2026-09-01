"""A configurable research-universe abstraction (Phase 5, sections 1-3).

Before this phase, every research script hardcoded a symbol list
(Phase 4's `UNIVERSE = ["NIO", "MARA", "SOFI", "SOUN", "PLUG"]`). The
research engine now accepts a `Universe` object instead — symbols,
per-symbol asset type/sector, inclusion/exclusion rules, and a
point-in-time membership interface.

SURVIVORSHIP BIAS — read before using any universe below: this codebase
has no historical index-constituent database (nothing in the HOOD MCP
connection's read-only tools returns "what was in the S&P 500 on
2022-03-01"). Every `Universe` built here is therefore a CURRENT-
CONSTITUENT universe — every member is a security that exists and is
listed TODAY, checked backward through history, not what genuinely
belonged to some benchmark AT THE TIME. `Universe.survivorship_bias_status`
says so explicitly on every instance, and `symbols_as_of()` is honest
about behaving identically to `symbols` (the full current membership)
because there is no other membership history to fall back on. The
`effective_start`/`effective_end` fields on `UniverseMember` exist so a
FUTURE integration with a real point-in-time constituent source has
somewhere to attach real data — they are not populated with anything
today, and setting them to fabricated dates would be worse than leaving
them None.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping


CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED = "CURRENT-CONSTITUENT / SURVIVORSHIP-BIASED UNIVERSE"
POINT_IN_TIME_AVAILABLE = "POINT-IN-TIME (historical constituent data available)"


@dataclass(frozen=True)
class UniverseMember:
    symbol: str
    asset_type: str  # "equity" | "etf"
    sector: str | None  # None when not applicable (e.g. a broad-market ETF) or genuinely unknown
    # Point-in-time membership window. None/None (today's reality for
    # every built-in universe below) means "no historical membership
    # window is tracked — treat this member as present for the entire
    # requested research period," which is exactly the survivorship-bias
    # limitation Universe.survivorship_bias_status names explicitly.
    effective_start: date | None = None
    effective_end: date | None = None

    def is_effective_on(self, as_of: date) -> bool:
        start_ok = self.effective_start is None or self.effective_start <= as_of
        end_ok = self.effective_end is None or as_of <= self.effective_end
        return start_ok and end_ok


@dataclass(frozen=True)
class Universe:
    name: str
    description: str
    members: tuple[UniverseMember, ...]
    inclusion_rules: tuple[str, ...]
    exclusion_rules: tuple[str, ...]
    survivorship_bias_status: str = CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED

    def __post_init__(self) -> None:
        symbols = [m.symbol for m in self.members]
        if len(set(symbols)) != len(symbols):
            raise ValueError(f"Universe {self.name!r} has duplicate symbols: {symbols}")

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(m.symbol for m in self.members)

    def symbols_as_of(self, as_of: date) -> tuple[str, ...]:
        """Point-in-time membership query. Honest about what it actually
        is: for a CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED universe (every
        built-in one today), every member's window is unbounded, so this
        returns the exact same set as `.symbols` regardless of `as_of` —
        it does NOT retroactively know who was in this universe years
        ago. This method exists so a future point-in-time-aware universe
        (`survivorship_bias_status == POINT_IN_TIME_AVAILABLE`) can be
        swapped in without changing any caller."""
        return tuple(m.symbol for m in self.members if m.is_effective_on(as_of))

    def by_sector(self) -> dict[str, tuple[str, ...]]:
        buckets: dict[str, list[str]] = {}
        for m in self.members:
            key = m.sector or "unclassified"
            buckets.setdefault(key, []).append(m.symbol)
        return {k: tuple(v) for k, v in buckets.items()}

    def by_asset_type(self) -> dict[str, tuple[str, ...]]:
        buckets: dict[str, list[str]] = {}
        for m in self.members:
            buckets.setdefault(m.asset_type, []).append(m.symbol)
        return {k: tuple(v) for k, v in buckets.items()}

    def sector_of(self, symbol: str) -> str | None:
        for m in self.members:
            if m.symbol == symbol:
                return m.sector
        return None


# ==============================================================================
# Built-in universes — every one is CURRENT-CONSTITUENT / SURVIVORSHIP-BIASED.
# Symbols chosen for sector/asset-type diversity, NOT for expected performance
# (section 2's explicit instruction) — large, liquid, real, currently-listed
# US securities only.
# ==============================================================================


def us_diversified_universe() -> Universe:
    """~20 large, liquid, currently-listed US names spanning technology,
    financials, healthcare, industrials, consumer (staples and
    discretionary), energy, growth, and three broad-market/benchmark
    ETFs — the Phase 5 expanded universe (section 2)."""
    members = (
        UniverseMember("AAPL", "equity", "technology"),
        UniverseMember("MSFT", "equity", "technology"),
        UniverseMember("GOOGL", "equity", "technology"),
        UniverseMember("NVDA", "equity", "technology"),
        UniverseMember("JPM", "equity", "financials"),
        UniverseMember("BAC", "equity", "financials"),
        UniverseMember("JNJ", "equity", "healthcare"),
        UniverseMember("UNH", "equity", "healthcare"),
        UniverseMember("CAT", "equity", "industrials"),
        UniverseMember("HON", "equity", "industrials"),
        UniverseMember("PG", "equity", "consumer_defensive"),
        UniverseMember("KO", "equity", "consumer_defensive"),
        UniverseMember("WMT", "equity", "consumer_defensive"),
        UniverseMember("AMZN", "equity", "consumer_discretionary"),
        UniverseMember("XOM", "equity", "energy"),
        UniverseMember("CVX", "equity", "energy"),
        UniverseMember("TSLA", "equity", "consumer_discretionary"),
        UniverseMember("SPY", "etf", "broad_market"),
        UniverseMember("QQQ", "etf", "broad_market"),
        UniverseMember("IWM", "etf", "broad_market"),
    )
    return Universe(
        name="US_DIVERSIFIED",
        description="Large-cap, liquid, sector-diversified US equities plus 3 broad-market ETFs, chosen for diversity across sectors/asset types, not expected performance.",
        members=members,
        inclusion_rules=(
            "large, liquid, currently-listed US-domiciled security",
            "verified via a real get_equity_historicals call returning a full 5-year daily bar series",
            "at least one representative from each of: technology, financials, healthcare, industrials, consumer staples, consumer discretionary, energy, broad-market ETF",
        ),
        exclusion_rules=(
            "no security selected based on expected future performance",
            "no penny stocks / no securities below institutional liquidity norms",
        ),
        survivorship_bias_status=CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED,
    )


def us_diversified_secondary_universe() -> Universe:
    """Phase 6, section 4: a SECOND, independent 20-symbol universe with
    ZERO overlap with `us_diversified_universe()` — communication
    services, utilities, materials, real estate, consumer discretionary,
    technology, healthcare, financials, industrials, energy, and one
    broad-market ETF, none of them shared with the Phase 5 universe.
    Symbols were selected for sector coverage and being real, liquid,
    currently-listed securities disjoint from Phase 5's list — BEFORE any
    backtest was run on them, and independent of how MR-002 (or anything
    else) performs on them. Same survivorship-bias caveat as every other
    built-in universe here: current-constituent, not point-in-time."""
    members = (
        UniverseMember("META", "equity", "communication_services"),
        UniverseMember("DIS", "equity", "communication_services"),
        UniverseMember("NEE", "equity", "utilities"),
        UniverseMember("DUK", "equity", "utilities"),
        UniverseMember("LIN", "equity", "materials"),
        UniverseMember("FCX", "equity", "materials"),
        UniverseMember("PLD", "equity", "real_estate"),
        UniverseMember("O", "equity", "real_estate"),
        UniverseMember("HD", "equity", "consumer_discretionary"),
        UniverseMember("NKE", "equity", "consumer_discretionary"),
        UniverseMember("ADBE", "equity", "technology"),
        UniverseMember("CRM", "equity", "technology"),
        UniverseMember("PFE", "equity", "healthcare"),
        UniverseMember("ABBV", "equity", "healthcare"),
        UniverseMember("GS", "equity", "financials"),
        UniverseMember("MS", "equity", "financials"),
        UniverseMember("BA", "equity", "industrials"),
        UniverseMember("UPS", "equity", "industrials"),
        UniverseMember("COP", "equity", "energy"),
        UniverseMember("DIA", "etf", "broad_market"),
    )
    return Universe(
        name="US_DIVERSIFIED_SECONDARY",
        description=(
            "A second, independent 20-symbol universe disjoint from US_DIVERSIFIED, spanning 10 sectors plus one "
            "broad-market ETF. Built for Phase 6's holdout validation — every symbol here was untouched by any "
            "Phase 4/5 parameter selection, feature choice, or classification decision for any strategy."
        ),
        members=members,
        inclusion_rules=(
            "large, liquid, currently-listed US-domiciled security",
            "verified via a real get_equity_historicals call returning a full multi-year daily bar series",
            "zero symbol overlap with us_diversified_universe()",
            "at least one representative from communication services, utilities, materials, real estate, consumer "
            "discretionary, technology, healthcare, financials, industrials, energy, and one broad-market ETF",
        ),
        exclusion_rules=(
            "no security selected based on expected future performance",
            "no security already present in us_diversified_universe() or us_small_cap_volatile_universe()",
            "no penny stocks / no securities below institutional liquidity norms",
        ),
        survivorship_bias_status=CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED,
    )


def us_small_cap_volatile_universe() -> Universe:
    """The ORIGINAL Phase 1-4 universe (this codebase's live-system
    SCAN_UNIVERSE) — now an explicitly labeled, non-default sub-universe
    rather than a hardcoded default (section 1's requirement)."""
    members = (
        UniverseMember("NIO", "equity", "consumer_discretionary"),
        UniverseMember("MARA", "equity", "technology"),
        UniverseMember("SOFI", "equity", "financials"),
        UniverseMember("SOUN", "equity", "technology"),
        UniverseMember("PLUG", "equity", "energy"),
    )
    return Universe(
        name="US_SMALL_CAP_VOLATILE",
        description="The original 5-symbol universe used in Phase 4 — small-cap, high-volatility names, kept as a distinct labeled universe for comparison, not as the default.",
        members=members,
        inclusion_rules=("this codebase's live-system SCAN_UNIVERSE at the time of Phase 4",),
        exclusion_rules=(),
        survivorship_bias_status=CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED,
    )


def us_etf_benchmark_universe() -> Universe:
    """Broad-market ETFs only — useful as a low-noise benchmark/regime
    reference distinct from the diversified equity universe."""
    members = (
        UniverseMember("SPY", "etf", "broad_market"),
        UniverseMember("QQQ", "etf", "broad_market"),
        UniverseMember("IWM", "etf", "broad_market"),
    )
    return Universe(
        name="US_ETFS",
        description="Broad-market benchmark ETFs.",
        members=members, inclusion_rules=("broad-market index ETF",), exclusion_rules=(),
        survivorship_bias_status=CURRENT_CONSTITUENT_SURVIVORSHIP_BIASED,
    )


def test_universe() -> Universe:
    """A tiny, fixed universe for tests — never mutated by test code."""
    members = (
        UniverseMember("AAPL", "equity", "technology"),
        UniverseMember("JPM", "equity", "financials"),
        UniverseMember("XOM", "equity", "energy"),
    )
    return Universe(name="TEST_UNIVERSE", description="Fixed tiny universe for tests.", members=members, inclusion_rules=(), exclusion_rules=())
