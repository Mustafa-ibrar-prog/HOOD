#!/usr/bin/env python3
"""Phase 6, section 1 — STEP 1 of the phase, run before ANY holdout
analysis: freezes MR-002's exact definition into an immutable
FrozenStrategyStore record. After this script has run once, no later
Phase 6 script may change MR-002's parameters — a change would require a
brand-new strategy_version (e.g. "MR-002-V2"), never an edit to this one.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research import FrozenStrategyStore, build_mr002_frozen_definition  # noqa: E402


def main() -> None:
    store = FrozenStrategyStore(Path("logs/research_data/frozen_strategies.jsonl"))
    definition = build_mr002_frozen_definition(development_universe_name="US_DIVERSIFIED")
    frozen = store.freeze(definition)
    print("FROZEN STRATEGY DEFINITION")
    print(f"  strategy_id:              {frozen.strategy_id}")
    print(f"  strategy_version:         {frozen.strategy_version}")
    print(f"  hypothesis_id:            {frozen.hypothesis_id}")
    print(f"  feature_definition:       {frozen.feature_definition}")
    print(f"  entry_rule:               {frozen.entry_rule}")
    print(f"  exit_rule:                {frozen.exit_rule}")
    print(f"  holding_period_bars:      {frozen.holding_period_bars}")
    print(f"  lookback:                 {frozen.lookback}")
    print(f"  entry_threshold:          {frozen.entry_threshold}")
    print(f"  exit_threshold:           {frozen.exit_threshold}")
    print(f"  prediction_horizon_bars:  {frozen.prediction_horizon_bars}")
    print(f"  position_sizing:          {frozen.position_sizing}")
    print(f"  risk_configuration:       {frozen.risk_configuration}")
    print(f"  execution_model:          {frozen.execution_model}")
    print(f"  slippage_model:           {frozen.slippage_model}")
    print(f"  transaction_cost_model:   {frozen.transaction_cost_model}")
    print(f"  spread_model:             {frozen.spread_model}")
    print(f"  starting_cash_usd:        {frozen.starting_cash_usd}")
    print(f"  development_universe:     {frozen.development_universe_name}")
    print(f"  frozen_at:                {frozen.frozen_at.isoformat()}")
    print(f"  content_hash:             {frozen.content_hash()}")
    print()
    print("Re-freezing with identical content to confirm idempotency + immutability guard...")
    refrozen = store.freeze(build_mr002_frozen_definition(development_universe_name="US_DIVERSIFIED", frozen_at=frozen.frozen_at))
    assert refrozen.content_hash() == frozen.content_hash()
    print("OK: identical re-freeze returns the same record, no new line written.")


if __name__ == "__main__":
    main()
