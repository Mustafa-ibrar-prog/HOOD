"""Phase 35, Part L/T — for every input `MOMENTUM_BREAKOUT_EXISTING_V1`
needs, determine whether the live Robinhood integration can supply it
AT DECISION TIME. Built from direct inspection of `src/market/hood_provider.py`,
`src/market/models.py`, and `docs/options_architecture.md`'s own
documented live-probe evidence (Phase 34's independent re-verification of
the same fields) -- never assumed from documentation alone.

FEATURE | HISTORICAL | LIVE | CAUSAL | PARSED | REQUIRED
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiveFeatureCompatibilityRow:
    feature: str
    historical: str  # "YES" | "NO" | "PARTIAL (3 of 5 underlyings)"
    live: str  # "YES" | "NO"
    causal: str  # "YES" | "N/A"
    parsed: str  # "YES" | "NO (raw payload has it, OptionQuote/UnderlyingSnapshot does not surface it)"
    required: bool  # is this feature REQUIRED by the frozen strategy (vs. optional/diagnostic)?
    is_blocker: bool
    note: str


LIVE_FEATURE_COMPATIBILITY_TABLE: tuple[LiveFeatureCompatibilityRow, ...] = (
    LiveFeatureCompatibilityRow(
        "underlying RSI(14)", "PARTIAL (AAPL/SPY/GOOG only, daily-bar reinterpretation)", "YES", "YES", "YES (computed locally, src/market/indicators.py)",
        True, False, "Live: computed from 5-minute bars, 180-min lookback. Historical: only daily bars exist; reinterpreted at daily granularity, DATA_LIMITED (see Part C).",
    ),
    LiveFeatureCompatibilityRow(
        "underlying MACD(12,26,9) histogram", "PARTIAL (AAPL/SPY/GOOG only)", "YES", "YES", "YES", True, False,
        "Same 5-minute-vs-daily granularity mismatch as RSI.",
    ),
    LiveFeatureCompatibilityRow(
        "underlying EMA(9)/EMA(21)", "PARTIAL (AAPL/SPY/GOOG only)", "YES", "YES", "YES", True, False,
        "Same granularity mismatch as RSI.",
    ),
    LiveFeatureCompatibilityRow(
        "higher_highs/lower_highs (5-bar structure)", "PARTIAL (AAPL/SPY/GOOG only)", "YES", "YES", "YES", True, False,
        "Same granularity mismatch -- a 5-bar window is ~25 minutes live, ~1 trading week in the daily reinterpretation.",
    ),
    LiveFeatureCompatibilityRow(
        "breakout_continuation / failed_breakout (20+2-bar)", "PARTIAL (AAPL/SPY/GOOG only)", "YES", "YES", "YES", True, False,
        "Same granularity mismatch -- ~110 minutes live vs. ~1 calendar month in the daily reinterpretation.",
    ),
    LiveFeatureCompatibilityRow(
        "volume_ratio", "NO", "YES", "YES", "YES", True, False,
        "DATA_LIMITED historically: this project's real underlying series (phase31_panel_builder.build_underlying_series) carries only `close`, never real daily volume, so volume_ratio could not be computed at all in this phase's backtest (always None -- never fabricated).",
    ),
    LiveFeatureCompatibilityRow(
        "option chain enumeration (expirations/strikes)", "PARTIAL (sparse, non-exhaustive -- see Part C)", "YES", "YES", "YES", True, False,
        "Historical: no real listing/tradability feed exists (Phase 26's own documented finding) -- only contracts that happen to have a real observation near a given date.",
    ),
    LiveFeatureCompatibilityRow(
        "option bid/ask", "YES (sparse, per-observation)", "YES", "YES", "YES", True, False,
        "Real bid/ask exists in both, but historically only for whichever contract-days were sampled into the free dataset.",
    ),
    LiveFeatureCompatibilityRow(
        "option volume/open_interest", "PARTIAL (OI real for AAPL/GOOG only in the fetched files; SPY/FOXA/NWSA lack it)", "YES", "YES", "YES", True, False,
        "Used only for the strategy's own PRE-FILTER (non-authoritative); the live RiskManager gate needs it too.",
    ),
    LiveFeatureCompatibilityRow(
        "option implied volatility / Greeks (delta/gamma/theta/vega/rho)", "NO", "YES (confirmed in a real live probe)", "YES", "NO -- not surfaced by OptionQuote", False,
        False, "NOT required by MomentumBreakoutStrategy today (it never reads IV/Greeks) -- listed for completeness per Part L's instruction to report every feature a strategy might plausibly use, not just what this one currently uses.",
    ),
    LiveFeatureCompatibilityRow(
        "option bid_size / ask_size", "NO", "YES (confirmed live)", "YES", "NO -- not surfaced by OptionQuote", False, False,
        "Not required by this strategy today; a real, disclosed live-data gap (Phase 34's finding), listed for completeness.",
    ),
    LiveFeatureCompatibilityRow(
        "underlying last trade price (for strike selection)", "YES", "YES", "YES", "YES (EquityQuote.last_trade_price)", True, False,
        "Available both live and historically.",
    ),
)


def blockers() -> tuple[LiveFeatureCompatibilityRow, ...]:
    """Part L: 'Any required feature unavailable live is a BLOCKER.'"""
    return tuple(r for r in LIVE_FEATURE_COMPATIBILITY_TABLE if r.required and r.is_blocker)
