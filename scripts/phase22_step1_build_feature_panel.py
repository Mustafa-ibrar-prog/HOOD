#!/usr/bin/env python3
"""Phase 22, STEP 1 — builds a feature-augmented research panel on top
of Phase 20's already-gathered, real, 120-contract/9,044-row panel
(logs/research_data/phase20_research_panel.jsonl). NO new MCP data is
fetched this phase (Part 21's 12-underlying universe is already fully
covered by Phase 19+20's real data) -- every new column here is a
CAUSAL DERIVED FEATURE computed from OHLC that was already gathered via
genuine get_option_historicals/get_equity_historicals probes.

Adds (Part 4/5/6/7, Themes A-G):
  - option-own-price features (Theme C): momentum, acceleration, gap,
    trend persistence, range expansion, REALIZED_OPTION_PRICE_VOLATILITY
    _PROXY (close-to-close + Parkinson + true-range, never called IV)
  - underlying-side features (Theme B): vol expansion/compression ratio,
    range expansion, mean-abs-return, squared return
  - OPTION_UNDERLYING_RELATIVE_RETURN (Theme A/D): naive and rolling-
    beta-scaled excess features AND targets, an empirical realized-beta
    estimate (rolling_beta) that is explicitly NOT a Greek (see
    src.options.relative_return's module docstring)
  - two NEW preregistered interaction features (Theme E/F): vol-
    expansion x moneyness, squared-move x DTE -- new hypotheses, NOT a
    revival of Phase 21's rejected raw log-moneyness (P19-OPT-009)
  - one path-dependent target (Part 5/13): 5-bar-forward max favorable
    excursion (mfe_5), reusing src.options.return_normalization directly

Writes logs/research_data/phase22_research_panel.jsonl (gitignored, same
convention as every prior phase's derived panel). No hypothesis is
tested, no statistic beyond simple feature construction is computed
here.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.store import HistoricalDataStore  # noqa: E402
from src.options.momentum_features import (  # noqa: E402
    option_gap,
    option_range_expansion,
    option_return_acceleration,
    trailing_option_return,
    trend_persistence,
)
from src.options.price_history import OptionPriceBar  # noqa: E402
from src.options.price_volatility_proxy import (  # noqa: E402
    close_to_close_volatility,
    mean_abs_return,
    parkinson_volatility,
    range_expansion_ratio,
    trailing_return,
    true_range_proxy,
    volatility_ratio,
)
from src.options.relative_return import beta_scaled_excess_return, naive_excess_return, rolling_beta  # noqa: E402
from src.options.return_normalization import compute_normalized_return  # noqa: E402
from src.options.universe import phase20_verified_underlying_universe  # noqa: E402

SOURCE_PANEL = Path("logs/research_data/phase20_research_panel.jsonl")
OUT_PANEL = Path("logs/research_data/phase22_research_panel.jsonl")

# Windows fixed BEFORE any Phase 22 result is computed -- not tuned after seeing anything.
SHORT_VOL_WINDOW = 5
LONG_VOL_WINDOW = 20
PARKINSON_WINDOW = 10
TRUE_RANGE_WINDOW = 10
MOMENTUM_SHORT = 5
MOMENTUM_MEDIUM = 10
TREND_WINDOW = 10
RANGE_EXPANSION_WINDOW = 5
ROLLING_BETA_WINDOW = 15
RATIO_MIN_DENOMINATOR = 0.002  # |trailing 5-day underlying return| below this makes a ratio numerically unstable -- excluded, not fabricated


def _load_panel_rows() -> list[dict]:
    return [json.loads(line) for line in SOURCE_PANEL.read_text().splitlines() if line.strip()]


def main() -> None:
    if not SOURCE_PANEL.is_file():
        raise SystemExit(f"{SOURCE_PANEL} not found -- Phase 20 must have run first (no new MCP fetch this phase).")

    universe = phase20_verified_underlying_universe()
    equity_store = HistoricalDataStore(Path("logs/research_data"))

    # --- underlying-side derived features, keyed by (symbol, date) -- computed on the FULL continuous
    # equity series (never a contract-gapped subset), mirroring Phase 20's own underlying-feature convention.
    underlying_derived: dict[str, dict[date, dict]] = {}
    for sym in universe.symbols:
        bars = equity_store.load(sym, "day")
        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        vol_short = close_to_close_volatility(closes, SHORT_VOL_WINDOW)
        vol_long = close_to_close_volatility(closes, LONG_VOL_WINDOW)
        vol_ratio = volatility_ratio(vol_short, vol_long)
        range_exp = range_expansion_ratio(highs, lows, closes, RANGE_EXPANSION_WINDOW)
        mean_abs = mean_abs_return(closes, SHORT_VOL_WINDOW)
        trailing_und_5 = trailing_return(closes, MOMENTUM_SHORT)
        by_date: dict[date, dict] = {}
        for i, b in enumerate(bars):
            by_date[b.timestamp.date()] = {
                "underlying_vol_ratio_5_20": vol_ratio[i],
                "underlying_range_expansion_5": range_exp[i],
                "underlying_mean_abs_return_5": mean_abs[i],
                "trailing_underlying_return_5": trailing_und_5[i],
            }
        underlying_derived[sym] = by_date
        print(f"  underlying-derived Phase 22 features built for {sym}: {len(by_date)} days", flush=True)

    rows = _load_panel_rows()
    by_contract: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_contract[r["option_id"]].append(r)

    out_rows: list[dict] = []
    for option_id, contract_rows in by_contract.items():
        contract_rows = sorted(contract_rows, key=lambda r: r["timestamp"])
        bars = [OptionPriceBar(date=date.fromisoformat(r["timestamp"]), open=r["option_open"], high=r["option_high"], low=r["option_low"], close=r["option_close"]) for r in contract_rows]
        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]

        opt_mom_5 = trailing_option_return(bars, MOMENTUM_SHORT)
        opt_mom_10 = trailing_option_return(bars, MOMENTUM_MEDIUM)
        opt_accel = option_return_acceleration(bars)
        opt_gap = option_gap(bars)
        opt_trend = trend_persistence(bars, TREND_WINDOW)
        opt_range_exp = option_range_expansion(bars, RANGE_EXPANSION_WINDOW)
        opt_vol_short = close_to_close_volatility(closes, SHORT_VOL_WINDOW)
        opt_vol_long = close_to_close_volatility(closes, LONG_VOL_WINDOW)
        opt_vol_ratio = volatility_ratio(opt_vol_short, opt_vol_long)
        opt_parkinson = parkinson_volatility(highs, lows, PARKINSON_WINDOW)
        opt_true_range = true_range_proxy(highs, lows, closes, TRUE_RANGE_WINDOW)

        option_daily_returns = [r.get("option_daily_return") for r in contract_rows]
        underlying_daily_returns = [r.get("underlying_daily_return") for r in contract_rows]
        beta_15 = rolling_beta(option_daily_returns, underlying_daily_returns, ROLLING_BETA_WINDOW)

        for i, r in enumerate(contract_rows):
            und_feats = underlying_derived.get(r["underlying_symbol"], {}).get(date.fromisoformat(r["timestamp"]), {})
            trailing_und_5 = und_feats.get("trailing_underlying_return_5")

            row = dict(r)  # every Phase 19/20 column carried through unchanged
            row["underlying_vol_ratio_5_20"] = und_feats.get("underlying_vol_ratio_5_20")
            row["underlying_range_expansion_5"] = und_feats.get("underlying_range_expansion_5")
            row["underlying_mean_abs_return_5"] = und_feats.get("underlying_mean_abs_return_5")
            row["underlying_squared_return"] = (r["underlying_daily_return"] ** 2) if r.get("underlying_daily_return") is not None else None

            row["option_momentum_5"] = opt_mom_5[i]
            row["option_momentum_10"] = opt_mom_10[i]
            row["option_return_acceleration"] = opt_accel[i]
            row["option_gap"] = opt_gap[i]
            row["option_trend_persistence_10"] = opt_trend[i]
            row["option_range_expansion_5"] = opt_range_exp[i]
            row["option_vol_ratio_5_20"] = opt_vol_ratio[i]
            row["option_parkinson_vol_10"] = opt_parkinson[i]
            row["option_true_range_proxy_10"] = opt_true_range[i]
            row["option_rolling_beta_15"] = beta_15[i]

            # --- Theme A: OPTION_UNDERLYING_RELATIVE_RETURN (naive + beta-scaled), feature AND target forms ---
            row["option_naive_excess_momentum_5"] = naive_excess_return(opt_mom_5[i], trailing_und_5)
            row["option_beta_scaled_excess_momentum_5"] = beta_scaled_excess_return(opt_mom_5[i], trailing_und_5, beta_15[i])
            row["option_naive_excess_return_5"] = naive_excess_return(r.get("forward_return_5"), r.get("underlying_forward_return_5"))
            row["option_beta_scaled_excess_return_5"] = beta_scaled_excess_return(r.get("forward_return_5"), r.get("underlying_forward_return_5"), beta_15[i])

            # --- Theme D: option/underlying return RATIO (distinct transformation from the Theme A difference above) ---
            ratio = None
            if opt_mom_5[i] is not None and trailing_und_5 is not None and abs(trailing_und_5) >= RATIO_MIN_DENOMINATOR:
                ratio = opt_mom_5[i] / trailing_und_5
            row["option_underlying_return_ratio_5"] = ratio

            # --- Theme E/F: new, preregistered interaction terms (NOT a revival of Phase 21's rejected raw log-moneyness) ---
            row["vol_expansion_x_moneyness"] = (
                und_feats["underlying_vol_ratio_5_20"] * r["log_moneyness"]
                if und_feats.get("underlying_vol_ratio_5_20") is not None and r.get("log_moneyness") is not None else None
            )
            row["squared_move_x_dte"] = (
                row["underlying_squared_return"] * r["dte"] if row["underlying_squared_return"] is not None and r.get("dte") is not None else None
            )

            # --- Part 5/13: a path-dependent target (max favorable excursion over the 5-bar forward window) ---
            mfe_5 = None
            if i + MOMENTUM_SHORT < len(bars):
                window = bars[i: i + MOMENTUM_SHORT + 1]
                if window[0].close > 0:
                    mfe_5 = compute_normalized_return(window).max_favorable_excursion
            row["mfe_5"] = mfe_5

            out_rows.append(row)

    OUT_PANEL.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PANEL.open("w") as fh:
        for row in out_rows:
            fh.write(json.dumps(row, sort_keys=True))
            fh.write("\n")

    print(f"\nWrote {len(out_rows)} feature-augmented rows to {OUT_PANEL} "
          f"({len(by_contract)} contracts, {len({r['underlying_symbol'] for r in out_rows})} underlyings) -- "
          f"no new MCP data fetched, every new column derived causally from already-gathered real OHLC.", flush=True)
    print("STEP 1 COMPLETE — feature panel built, no hypothesis tested.", flush=True)


if __name__ == "__main__":
    main()
