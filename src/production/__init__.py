"""Phase 36 — the production strategy contract + live decision pipeline.

Everything in this package is ARCHITECTURE: a strict, testable boundary
between a strategy's signal logic and the broker. Nothing here submits an
order, activates live trading, or declares any strategy validated. See
docs/phase36_production_strategy_contract.md for the full design and
docs/phase35_strategy_validation_and_execution_hardening.md for the
execution-boundary hardening this package builds on top of, unchanged.

Module map (mirrors the pipeline order, Part 15):
  decision.py                  -- DecisionType, StrategyDecision (Part 2)
  provenance.py                 -- DataProvenance, feature-acceptability rules (Part 7)
  live_snapshot.py              -- LiveMarketSnapshot and its pieces (Part 6)
  snapshot.py                   -- StrategySnapshot, the strategy's full input (Part 2)
  strategy_interface.py         -- ProductionStrategy ABC (Part 2-3)
  timestamps.py                 -- DecisionTimestamps, staleness/lookahead (Part 8)
  contract_validation.py        -- validate_option_contract, rejection codes (Part 9)
  liquidity.py                  -- LiquidityAssessment (Part 10)
  opportunity.py                -- Opportunity, the strategy/risk boundary object (Part 11)
  registry.py                   -- StrategyRegistry, StrategyStatus (Part 4)
  validation_artifact.py        -- ValidationArtifact, the only path to VALIDATED (Part 5)
  risk_handoff.py                -- Opportunity -> RiskEngine -> PositionSizer (Part 12)
  ranking.py                    -- rank_opportunities, no new alpha (Part 13)
  pipeline.py                   -- run_live_decision_cycle, fail-closed (Part 14)
  momentum_breakout_adapter.py  -- proves the interface fits the existing strategy (Part 18)
"""
