"""Phase 37 — the Live Options Research Recorder.

    Robinhood Live Data -> Research Recorder -> Immutable Raw Observation
    -> Canonical LiveMarketSnapshot -> Feature Calculation -> Strategy
    Signal Evaluation -> Hypothetical Opportunity -> Research Journal

HARD STOP: this package contains NO order creation, NO order submission,
and has NO import path (direct or transitive) to `src.execution.gateway`,
`src.execution.live_client`, `src.market.hood_client`'s broker-order
methods, or any order-submission function. This is verified structurally
by `tests/test_phase37_no_trading_boundary.py`, not merely asserted by
`live_auto_execute=False`.

THIS IS NOT PAPER TRADING. There are no simulated fills, no simulated
positions, no P&L, no paper orders. The recorder observes and records
real market data and hypothetical strategy decisions only — see
`docs/phase37_live_options_research_recorder.md`.

Module map:
  target_universe.py     -- the fixed 12-symbol observation universe (Part 4)
  market_hours.py         -- market-hours gating, reimplemented standalone (Part 6)
  provenance.py           -- LIVE / DERIVED_FROM_LIVE / MISSING only (Part 9)
  raw_observation.py      -- immutable raw payload + fingerprint (Part 8)
  quote_quality.py        -- quality flags, never auto-deletes (Part 10)
  contract_selection.py   -- deterministic, broad, documented selection (Part 11-12)
  moneyness.py            -- observation-time-only moneyness (Part 17)
  dte.py                  -- observation-time-only DTE (Part 18)
  normalized_observation.py -- canonical LiveMarketSnapshot-shaped records (Part 7, 13)
  research_signal.py      -- HYPOTHETICAL_RESEARCH_DECISION only, via Phase 36's adapter (Part 14)
  storage.py              -- three separate append-only layers (Part 16, 20)
  recorder.py             -- run_observation_cycle(), the callable a future scheduler invokes (Part 1, 5, 21, 22)
  quality_report.py        -- aggregate data-quality report, never alpha evidence (Part 19)
  security.py              -- credential/secret redaction for any logged text (Part 23)
"""
