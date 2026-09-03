#!/usr/bin/env python3
"""Phase 19, STEP 1 — transcribes the REAL option contract/price data
gathered this phase (see logs/research_data/phase19_options_price_panel.json,
itself built from real `get_option_instruments`/`get_option_historicals`
MCP probes against AAPL/NVDA/SPY/TSLA's real 2022-03-18 expiration) into:

  1. `OptionContract` records, persisted via `OptionsDataStore` (Phase 18's
     real, working save_contracts()/load_contracts()/get_chain() path).
  2. `OptionResearchObservation` rows (Part 3) -- option OHLC + underlying
     close reference + moneyness + DTE + forward returns at the
     preregistered horizons -- written to
     logs/research_data/phase19_research_panel.jsonl for the discovery
     campaign (step 3) to load without re-deriving them.

No alpha statistic is computed here. No hypothesis is tested here. This
step is data transcription and feature construction only.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.store import HistoricalDataStore  # noqa: E402
from src.options.instrument import OptionContract  # noqa: E402
from src.options.price_history import STANDARD_FORWARD_HORIZONS, OptionPriceBar  # noqa: E402
from src.options.research_observation import build_research_series  # noqa: E402
from src.options.store import OptionsDataStore  # noqa: E402

PANEL_SOURCE = Path("logs/research_data/phase19_options_price_panel.json")
RESEARCH_PANEL_OUT = Path("logs/research_data/phase19_research_panel.jsonl")
UNDERLYINGS = ("AAPL", "NVDA", "SPY", "TSLA")
EXPIRATION = date(2022, 3, 18)


def _underlying_closes(store: HistoricalDataStore, symbol: str) -> dict[date, float]:
    bars = store.load(symbol, "day")
    return {b.timestamp.date(): b.close for b in bars}


def main() -> None:
    if not PANEL_SOURCE.is_file():
        raise SystemExit(f"{PANEL_SOURCE} not found -- run the real MCP data-gathering step first (see conversation record).")
    raw = json.loads(PANEL_SOURCE.read_text())
    print(f"Loaded real option price panel: source={raw['source']!r} contracts={raw['contract_count']} underlyings={raw['underlyings']}", flush=True)

    options_store = OptionsDataStore(Path("logs/research_data/options"))
    equity_store = HistoricalDataStore(Path("logs/research_data"))

    underlying_closes = {sym: _underlying_closes(equity_store, sym) for sym in UNDERLYINGS}
    for sym, closes in underlying_closes.items():
        print(f"  underlying closes loaded for {sym}: {len(closes)} days (from local HistoricalDataStore, no new MCP call)", flush=True)

    contracts_by_underlying: dict[str, list[OptionContract]] = {sym: [] for sym in UNDERLYINGS}
    research_rows: list[dict] = []
    dropped_no_underlying_close = 0

    for c in raw["contracts"]:
        contract = OptionContract(
            underlying_symbol=c["underlying_symbol"], option_id=c["option_id"], call_put=c["call_put"],
            strike=float(c["strike"]), expiration=EXPIRATION, contract_multiplier=int(c["multiplier"]),
            source="mcp__HOOD__get_option_instruments+get_option_historicals",
        )
        contracts_by_underlying[contract.underlying_symbol].append(contract)

        option_bars = [OptionPriceBar(date=date.fromisoformat(b["date"]), open=b["open"], high=b["high"], low=b["low"], close=b["close"]) for b in c["bars"]]
        before = len(option_bars)
        series = build_research_series(
            contract=contract, option_bars=option_bars, underlying_closes_by_date=underlying_closes[contract.underlying_symbol],
            horizons=STANDARD_FORWARD_HORIZONS,
        )
        dropped_no_underlying_close += before - len(series)

        for obs in series:
            research_rows.append({
                "timestamp": obs.observation_date.isoformat(),
                "option_id": contract.option_id,
                "underlying_symbol": contract.underlying_symbol,
                "call_put": contract.call_put,
                "strike": contract.strike,
                "expiration": contract.expiration.isoformat(),
                "option_open": obs.option_bar.open,
                "option_high": obs.option_bar.high,
                "option_low": obs.option_bar.low,
                "option_close": obs.option_bar.close,
                "underlying_close": obs.underlying_close,
                "dte": obs.dte,
                "dte_bucket": obs.dte_bucket.value,
                "log_moneyness": obs.moneyness.log_moneyness_value,
                "moneyness_ratio": obs.moneyness.moneyness_ratio_value,
                "moneyness_bucket": obs.moneyness.bucket.value,
                **{f"forward_return_{h}": obs.forward_returns.get(h) for h in STANDARD_FORWARD_HORIZONS},
            })

    for sym, contracts in contracts_by_underlying.items():
        options_store.save_contracts(sym, contracts)
        print(f"  persisted {len(contracts)} contracts for {sym} via OptionsDataStore.save_contracts()", flush=True)

    RESEARCH_PANEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    with RESEARCH_PANEL_OUT.open("w") as fh:
        for row in research_rows:
            fh.write(json.dumps(row, sort_keys=True))
            fh.write("\n")

    print(f"\nWrote {len(research_rows)} research rows to {RESEARCH_PANEL_OUT} "
          f"({dropped_no_underlying_close} option bars dropped for missing underlying close -- never fabricated).", flush=True)
    print(f"Underlyings: {len(UNDERLYINGS)}  Contracts: {sum(len(v) for v in contracts_by_underlying.values())}  "
          f"Expiration: {EXPIRATION}  Horizons: {STANDARD_FORWARD_HORIZONS}", flush=True)
    print("\nSTEP 1 COMPLETE — real data transcribed, no alpha computed.", flush=True)


if __name__ == "__main__":
    main()
