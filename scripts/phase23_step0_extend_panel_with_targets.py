#!/usr/bin/env python3
"""Phase 23, Part 5 preparation — builds a target-validation panel on
top of Phase 22's already-gathered feature panel
(logs/research_data/phase22_research_panel.jsonl). NO new MCP data is
fetched. Adds exactly the columns Part 5's target-falsification family
needs that Phase 22 didn't already compute:

  - mae_5 (max adverse excursion over the same forward 5-bar window
    Phase 22's mfe_5 used -- reuses src.options.return_normalization
    directly, the SAME function call Phase 22 used for mfe_5, so this
    script also serves as an independent reproduction check: the mfe_5
    it recomputes here must match Phase 22's stored mfe_5 EXACTLY)
  - mfe_minus_mae_5 (Target H)
  - target_positive_indicator_5 (Target J: 1.0/0.0 whether forward_
    return_5 > 0 -- a binary outcome fed through the same Spearman-IC
    machinery, a standard point-biserial-style rank correlation)
  - abs_underlying_forward_return_5 (Control 2)
  - abs_log_moneyness (Control 9's continuous "distance from ATM" proxy)

Phase 22's panel and every P22-OPT-013 field are read, never modified.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.options.price_history import OptionPriceBar  # noqa: E402
from src.options.return_normalization import compute_normalized_return  # noqa: E402

SOURCE_PANEL = Path("logs/research_data/phase22_research_panel.jsonl")
OUT_PANEL = Path("logs/research_data/phase23_research_panel.jsonl")
HORIZON = 5


def main() -> None:
    if not SOURCE_PANEL.is_file():
        raise SystemExit(f"{SOURCE_PANEL} not found -- Phase 22 must have run first.")

    rows = [json.loads(line) for line in SOURCE_PANEL.read_text().splitlines() if line.strip()]
    by_contract: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_contract[r["option_id"]].append(r)

    out_rows: list[dict] = []
    mismatches = 0
    for option_id, contract_rows in by_contract.items():
        contract_rows = sorted(contract_rows, key=lambda r: r["timestamp"])
        bars = [OptionPriceBar(date=date.fromisoformat(r["timestamp"]), open=r["option_open"], high=r["option_high"], low=r["option_low"], close=r["option_close"]) for r in contract_rows]

        for i, r in enumerate(contract_rows):
            row = dict(r)
            mfe = mae = None
            if i + HORIZON < len(bars):
                window = bars[i: i + HORIZON + 1]
                if window[0].close > 0:
                    normalized = compute_normalized_return(window)
                    mfe, mae = normalized.max_favorable_excursion, normalized.max_adverse_excursion
            if mfe is not None and row.get("mfe_5") is not None and abs(mfe - row["mfe_5"]) > 1e-9:
                mismatches += 1
            row["mae_5"] = mae
            row["mfe_minus_mae_5"] = (mfe - mae) if (mfe is not None and mae is not None) else None
            fwd5 = row.get("forward_return_5")
            row["target_positive_indicator_5"] = (1.0 if fwd5 > 0 else 0.0) if fwd5 is not None else None
            uf5 = row.get("underlying_forward_return_5")
            row["abs_underlying_forward_return_5"] = abs(uf5) if uf5 is not None else None
            lm = row.get("log_moneyness")
            row["abs_log_moneyness"] = abs(lm) if lm is not None else None
            out_rows.append(row)

    if mismatches:
        raise SystemExit(f"REPRODUCTION FAILURE: {mismatches} rows' recomputed mfe_5 disagrees with Phase 22's stored value -- refusing to proceed.")
    print(f"Reproduction check passed: recomputed mfe_5 matches Phase 22's stored mfe_5 exactly for all {len(out_rows)} rows.", flush=True)

    OUT_PANEL.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PANEL.open("w") as fh:
        for row in out_rows:
            fh.write(json.dumps(row, sort_keys=True))
            fh.write("\n")
    print(f"Wrote {len(out_rows)} rows to {OUT_PANEL} ({len(by_contract)} contracts).", flush=True)
    print("STEP 0 COMPLETE.", flush=True)


if __name__ == "__main__":
    main()
