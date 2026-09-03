"""Phase 19, Part 2 — a dynamic, configurable universe of OPTIONABLE
underlyings for options-alpha research.

Distinct from `src.data.universe.Universe` (an equity universe) and from
Phase 18's `OptionContract`/`OptionChainObservation` (a single contract's
identity/quote): this module is about which UNDERLYINGS this research
phase is allowed to draw option contracts from, and on what evidentiary
basis each one was included.

Historical-vs-live field distinction (explicitly required by Part 2):
`has_verified_historical_options` is set ONLY from a real
`get_option_instruments(state="expired")` probe that returned at least
one contract for that underlying -- it says nothing about whether that
underlying currently has a live, tradable chain. `has_verified_live_options`
is the separate, live-chain question and is NOT set by this phase's
historical-discovery work (Phase 19 never called `get_option_chains`
against a live/current chain) -- it stays False/unverified rather than
being inferred from the historical flag. A future phase that does
probe the live chain should set it explicitly, the same way this phase
set the historical flag from its own real evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class OptionableUnderlying:
    symbol: str
    asset_type: str  # "equity" | "etf" -- mirrors src.data.universe.UniverseMember
    sector: str | None
    has_verified_historical_options: bool  # OBSERVED via a real get_option_instruments(state="expired") probe -- never assumed True just because the underlying is liquid
    has_verified_live_options: bool = False  # NOT set by Phase 19 -- no live get_option_chains probe was made this phase; stays honestly False
    verified_expirations: tuple[str, ...] = ()  # ISO date strings actually observed via a real probe, e.g. ("2022-03-18",)
    evidence_note: str = ""  # free-text pointer to the specific probe/session that established has_verified_historical_options

    def __post_init__(self) -> None:
        if self.has_verified_historical_options and not self.evidence_note:
            raise ValueError(
                f"{self.symbol}: has_verified_historical_options=True requires evidence_note documenting the "
                "real probe that established it -- never claim verification without a citable source"
            )


@dataclass(frozen=True)
class UnderlyingFilterConfig:
    """A configurable filter over an `UnderlyingUniverse` -- architecture
    only. No default here encodes an alpha judgment (e.g. no
    'min_expected_return'); every field is a DATA-AVAILABILITY or
    ASSET-CLASS-STRUCTURE constraint."""

    require_verified_historical_options: bool = True
    require_verified_live_options: bool = False
    asset_types: tuple[str, ...] | None = None  # None = no restriction; else e.g. ("equity",)
    sectors: tuple[str, ...] | None = None  # None = no restriction

    def matches(self, member: OptionableUnderlying) -> bool:
        if self.require_verified_historical_options and not member.has_verified_historical_options:
            return False
        if self.require_verified_live_options and not member.has_verified_live_options:
            return False
        if self.asset_types is not None and member.asset_type not in self.asset_types:
            return False
        if self.sectors is not None and member.sector not in self.sectors:
            return False
        return True


@dataclass(frozen=True)
class UnderlyingUniverse:
    name: str
    description: str
    members: tuple[OptionableUnderlying, ...]
    source_equity_universe_name: str  # e.g. "US_DIVERSIFIED" -- the equity pool this options universe was drawn from
    as_of: date | None = None  # when the verification probes were run; None = not tracked

    def __post_init__(self) -> None:
        symbols = [m.symbol for m in self.members]
        if len(set(symbols)) != len(symbols):
            raise ValueError(f"UnderlyingUniverse {self.name!r} has duplicate symbols: {symbols}")

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(m.symbol for m in self.members)

    def filtered(self, config: UnderlyingFilterConfig) -> "UnderlyingUniverse":
        kept = tuple(m for m in self.members if config.matches(m))
        return UnderlyingUniverse(
            name=f"{self.name}_FILTERED", description=f"{self.description} (filtered)",
            members=kept, source_equity_universe_name=self.source_equity_universe_name, as_of=self.as_of,
        )

    def member(self, symbol: str) -> OptionableUnderlying | None:
        return next((m for m in self.members if m.symbol == symbol), None)


def phase19_verified_underlying_universe() -> UnderlyingUniverse:
    """The real, evidence-backed universe this phase actually built its
    discovery panel from: 4 underlyings, each verified via a real
    `get_option_instruments(chain_symbol=X, state="expired",
    expiration_dates="2022-03-18")` call that returned real contracts
    (see logs/research_data/phase19_options_price_panel.json and
    scripts/phase19_step1_ingest_real_options_panel.py for the exact
    evidence trail). This is NOT a claim that these are the only
    optionable underlyings -- it is the specific, small, real set this
    phase's discovery campaign actually used."""
    evidence = "real get_option_instruments(chain_symbol=X, state='expired', expiration_dates='2022-03-18') probe, Phase 19 real-data gathering"
    members = (
        OptionableUnderlying("AAPL", "equity", "technology", has_verified_historical_options=True, verified_expirations=("2022-03-18",), evidence_note=evidence),
        OptionableUnderlying("NVDA", "equity", "technology", has_verified_historical_options=True, verified_expirations=("2022-03-18",), evidence_note=evidence),
        OptionableUnderlying("SPY", "etf", "broad_market", has_verified_historical_options=True, verified_expirations=("2022-03-18",), evidence_note=evidence),
        OptionableUnderlying("TSLA", "equity", "consumer_discretionary", has_verified_historical_options=True, verified_expirations=("2022-03-18",), evidence_note=evidence),
    )
    return UnderlyingUniverse(
        name="PHASE19_VERIFIED_OPTIONS_UNIVERSE",
        description="4 underlyings with real, verified historical option contract/price data for the 2022-03-18 expiration -- the exact set Phase 19's discovery campaign used.",
        members=members, source_equity_universe_name="US_DIVERSIFIED", as_of=date(2022, 3, 18),
    )
