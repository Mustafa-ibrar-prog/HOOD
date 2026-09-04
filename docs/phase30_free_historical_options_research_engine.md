# Phase 30 — Free Historical Options Research Engine

## 1. Decision context

The user decided **not** to purchase ORATS or any other paid historical
options provider. Phase 29's final ORATS state
(`ORATSActivationState.ORATS_ACTIVATION_PENDING_HUMAN`) is unchanged and
unmodified by this phase — no credential was added, no API call was made,
no account was created, no payment was made.

`HISTORICAL_OPTIONS_DATA_PARTIAL` (Phase 27's `EXPANDED_FINAL_GATE`) is
now accepted as a **permanent** characteristic of this research platform,
not a defect to keep chasing a paid fix for. Phase 30's entire scope is
building the strongest possible research **infrastructure** around the
real, free, already-certified QuantConnect/Lean sample (7,358 real
contracts, 6 real underlyings: AAPL, FOXA, GOOG, NWSA, SPY, TWX,
~20.9M observations) — no new alpha hypothesis, no paid provider, no live
trading, no profitability optimization.

## 2. What was built (12 subsystems, Parts 1–9, 11–12, 15)

| Part | Module | Purpose |
|---|---|---|
| 1 | `src/options/research_dataset.py` | Research-facing dataset view over the certified free store — one row per real (contract, timestamp), every row carrying DATA_SOURCE/DATA_QUALITY/PIT_STATUS/PROVENANCE, moneyness/DTE computed from date-aligned real prices, nothing fabricated. |
| 2 | `src/options/research_features.py` | Strictly causal (no-lookahead, index i sees only [0..i]) contract/price/liquidity/underlying feature families; IV is only ever `RECONSTRUCTED_IV` (Black-Scholes), never presented as vendor-supplied; `market_relative_return` is always `None` (no benchmark series exists in this dataset). |
| 3 | `src/options/contract_selection.py` | ELIGIBLE/REJECTED contract-selection engine with the full 11-code rejection vocabulary (NO_BID, NO_ASK, WIDE_SPREAD, INSUFFICIENT_VOLUME, INSUFFICIENT_OI, INVALID_DTE, INVALID_MONEYNESS, INSUFFICIENT_DATA, PIT_FAILURE, PRICE_TOO_HIGH, DATA_QUALITY_FAILURE); every threshold configurable, defaults deliberately permissive. |
| 4 | `src/options/research_opportunity_score.py` | Architecture-only OpportunityScore (Confidence/ExpectedReturn/ExpectedRisk/LiquidityScore/ExecutionScore/DataQualityScore/ReasonCodes) with a `__post_init__` guard preventing a computed value without a real `scoring_method`; the only concrete implementation shipped is `NullScoringMethod`, which computes nothing (Part 10 compliance). |
| 5 | `src/options/affordability.py` | ~$1,000-account affordability analysis (premium cost, contracts affordable, max capital required, capital %, tick impact, spread cost) from real ask/bid — analysis only, no dollar/day target assumed. |
| 6 | `src/options/execution_realism_pricing.py` | BUY_AT_ASK/SELL_AT_BID/BUY_AT_MID/SELL_AT_MID/DELAYED_EXECUTION/SLIPPAGE_ASSUMPTION/EXECUTION_DATA_LIMITED price abstractions; close price is never used as an executable price; a missing quote always yields `EXECUTION_DATA_LIMITED`, never an invented price. |
| 7 | `src/options/research_position_view.py` | Reporting-ready position snapshots wrapping Phase 18's existing `OptionsPosition`/`analyze_position_risk` (LONG_CALL/LONG_PUT/SHORT_CALL/SHORT_PUT + vertical spreads, UNSUPPORTED_STRUCTURE otherwise) — adds market_value, per-leg DTE, realized_pnl pass-through, and Greeks reconstructed via Black-Scholes (`DERIVED_FROM_MODEL`) only when a real mark and underlying price are both available. |
| 8 | `src/options/research_risk_engine.py` | Portfolio-level risk assessment: capital at risk, position size, underlying/expiration/correlated-group concentration, spread, liquidity, gap risk, assignment/exercise risk, data quality. Every limit defaults to `None` ("NOT_CONFIGURED") — nothing is hard-coded as an artificially conservative default. |
| 9 | `src/options/research_events.py` | MARKET_EVENT (reuses Phase 3's `MarketEvent` directly), OPTION_CHAIN_EVENT, CONTRACT_EVENT, SIGNAL_EVENT, ORDER_SIMULATION_EVENT, POSITION_EVENT, EXIT_EVENT — `ResearchEventQueue` subclasses Phase 3's `EventQueue`, inheriting its exact chronological/no-lookahead guarantee (`LookAheadViolationError`). |
| 11 | `src/options/free_dataset_limitations.py` | Permanent, 12-category limitations registry (missing underlyings/years, no native IV/Greeks, volume/OI/quote limitations, corporate-action limitations, contract-lifecycle limitations, survivorship concerns, coverage concentration, resolution limitations); `attach_limitations_disclosure()` wraps any future report body with the full registry automatically. |
| 12 | `src/options/live_research_bridge.py` | LIVE (Robinhood) vs. RESEARCH (FREE_REFERENCE_DATASET) origin labeling; `assert_single_origin()` raises `MixedOriginError` the instant a batch spans both; all 12 target-universe symbols are always `live_visible=True`, with `LIVE_ONLY_NO_HISTORICAL_RESEARCH` labeling the 10 symbols (of 12) with no historical research coverage. |
| 15 | `src/options/paper_trading_simulation.py` | Paper-trading simulation library: order submission, real bid/ask-based fills, partial fills (liquidity-constrained), slippage assumptions, commissions/fees, an in-memory position ledger, exits, rejected orders, and "market changed" re-evaluation against a newer real row. **Built but not started** — no import of `src.execution.gateway`/`live_client`/`orchestrator`, nothing calls a live/paper order-placement tool. |

Part 10 (no new alpha hypothesis) and Parts 13–14 (system-state machine
and OPTIONS_ONLY reconfirmation) are verification requirements, not new
modules — enforced by `tests/test_phase30_safety.py` and
`tests/test_phase30_parts13_14_reconfirmation.py`.

## 3. Reuse discipline

No existing file's behavior was modified this phase. Every new module's
docstring documents exactly what it reuses and why it is a new module
rather than a modification:

- `research_position_view.py` wraps (never modifies) Phase 18's
  `src/options/position.py` — which, on inspection, already implemented
  LONG_CALL/LONG_PUT/SHORT_CALL/SHORT_PUT + vertical spreads with an
  honest `UNSUPPORTED_STRUCTURE` fallback. Part 7's real remaining gap was
  reporting fields (`market_value`, DTE, Greeks, realized_pnl), not
  risk-structure logic.
- `research_risk_engine.py` is a new portfolio-level module, distinct
  from `src/risk/manager.py`'s live per-trade entry/exit gate — the two
  answer different questions and share only the check-result pattern.
- `research_events.py`'s `ResearchEventQueue` subclasses Phase 3's
  `EventQueue` and overrides only `push()`; `pop()`/`__len__`/`__bool__`
  and the look-ahead guarantee are inherited unchanged.
- `research_opportunity_score.py` is a new module relative to Phase 19's
  `opportunity_score.py` (built against live-pipeline types), sharing
  only the architecture-only `__post_init__` guard pattern.
- `affordability.py`/`research_position_view.py` reuse
  `STANDARD_US_EQUITY_OPTION_MULTIPLIER` and
  `ASSUMED_RISK_FREE_RATE`/`ASSUMED_DIVIDEND_YIELD` directly from Phase
  26 rather than redeclaring them.

## 4. Test results

- **129 new tests**, across 12 new src modules and 14 new test files
  (13 `test_phase30_*.py` files + the shared `tests/phase30_fixtures.py`
  SYNTHETIC_TEST_DATA support module).
- **Full suite: 2,394 passed, 4 failed** — the same 4 pre-existing
  `test_orchestrator.py` failures present before this phase began (paper
  trading cycle / decision-logging tests, unrelated to Phase 30's
  research-infrastructure work). No new failures introduced.
- Git diff footprint is **purely additive**: every changed path is a new
  file (`git status --porcelain` shows only `??` entries) — no existing
  file was modified this phase, unlike Phase 29's one factual correction
  to Phase 28.
- Every module has an explicit no-lookahead / adversarial / malformed-data
  test: `test_phase30_research_features.py::test_no_lookahead_synthetic_leakage_check`
  (poison-future-data leakage test, mirroring `src/features/base.py`'s
  own contract), PIT-failure rejection in
  `test_phase30_contract_selection.py`, undetermined/unbounded risk
  handling in `test_phase30_research_risk_engine.py`, and rejected/
  data-limited paths throughout `test_phase30_execution_realism_pricing.py`
  and `test_phase30_paper_trading_simulation.py`.

## 5. What was explicitly NOT done (per the phase's own critical rules)

- ORATS was not purchased, activated, or contacted. No credential was
  added anywhere.
- No live or paper order was placed. `paper_trading_simulation.py` never
  imports the live order-placement path (structurally verified via AST).
- Autonomous live trading was not started. `SystemState` remains exactly
  the 7 states Phase 28 defined; no Phase 30 module calls
  `record_human_authorized_transition`.
- No new alpha hypothesis, trading strategy, or backtest was created or
  optimized. `NullScoringMethod` is the only `ScoringMethod` this phase
  ships, and it computes nothing.
- OPTIONS_ONLY remains structurally enforced (`OrderLeg.option_id: str`
  required on every leg; no equity/share order shape exists).

## 6. Permanent limitations (see `free_dataset_limitations.py` for full detail)

Only AAPL and SPY (of the 12 target underlyings) have any real historical
options data, and even then coverage is sparse and mostly outside the
project's 2019–2026 research window. No native IV or Greeks exist
anywhere in the dataset. These are now treated as permanent, registered
facts every future research report automatically carries via
`attach_limitations_disclosure()`, not open questions to keep re-raising.

## 7. Commit

Commit hash: see `git log -1` on branch `claude/inspect-repo-mcp-tools-s5ic0p`
immediately following this report's addition.
