# Phase 36 — Production Strategy Contract + Live Decision Pipeline

An architecture phase: define the exact production strategy contract and
connect the live decision pipeline end to end, without activating it. No
strategy was created, optimized, or declared validated. No order — live
or paper — was submitted. `MomentumBreakoutStrategy` remains `NOT_READY`.

## 1. Executive summary

This phase adds a new package, `src/production/`, that sits strictly
between any future strategy's signal logic and the broker:

```
Strategy -> Decision -> Opportunity -> Liquidity -> Risk -> Position Size
-> Order Validation -> Authorization -> Execution -> ...
```

Every stage up to and including a read-only Authorization status check
is implemented and tested (96 new tests, all passing). Nothing calls
`submit_order`/`place_option_order` from this package — `place_option_order(`
still appears as an executable call in exactly one file in all of `src/`
(`src/execution/gateway.py`'s `_place_pending`), reconfirmed by a
repo-wide AST scan after adding this entire package.

The registry pre-registers `MOMENTUM_BREAKOUT_EXISTING_V1` at its real,
Phase-35-established status, `NOT_READY`, and the registry mechanically
cannot promote any strategy to `VALIDATED`/`LIVE_AUTHORIZED` without a
genuine, evidence-complete `ValidationArtifact` on file — there is no
enum flip that bypasses this. `orchestrator.py` was not touched: the
pipeline is connected, not activated.

## 2. Strategy interface

`src/production/strategy_interface.py::ProductionStrategy` — one abstract
method, `decide(snapshot: StrategySnapshot) -> StrategyDecision`. No
`submit()`/`place_order()` exists on it or on `StrategyDecision`
(`src/production/decision.py`); a strategy can only describe what it
would like to happen.

`StrategySnapshot` (`src/production/snapshot.py`) bundles exactly what
Part 2 asked for, reusing existing dataclasses wherever one already
existed rather than redefining it: `timestamp`; `account` (new
`AccountState`); `underlying` (`src.market.models.UnderlyingSnapshot`,
reused unchanged); `option_chain` (the same loose dict shape
`MarketDataProvider.get_option_chain_candidates` already returns);
`option_quotes` (a mapping to the new `LiveMarketSnapshot`, Part 6);
`positions` (`src.position_manager.models.OpenPosition`, reused);
`risk_state` (new `RiskStateSnapshot`, bundling the exact kwargs
`RiskManager.evaluate_new_trade` already needs); `risk_limits`
(`src.risk.models.RiskLimits`, reused); `settings`
(`src.config.settings.Settings`, reused).

`StrategyDecision` is one of `NO_TRADE` / `ENTER` / `EXIT` / `HOLD`
(`DecisionType`), with the exact minimum field set Part 2 specified
(`strategy_id`, `timestamp`, `underlying`, `option_id`, `option_type`,
`strike`, `expiration`, `side`, `quantity_recommendation`,
`signal_score`, `expected_holding_period_minutes`, `reason`, `features`,
`confidence`, `decision`). `__post_init__` enforces internal consistency
(`MalformedDecisionError`): an `ENTER` must carry `underlying`,
`option_id`, `side`, and `quantity_recommendation`; an `EXIT` must carry
`underlying`/`option_id`; `NO_TRADE`/`HOLD` must not carry a quantity
recommendation. A strategy's own `quantity_recommendation`/`signal_score`
are downstream **hints only** — the real order quantity always comes
from `PositionSizer.target_quantity()` via `risk_handoff.py`, never
copied directly (verified by
`test_strategy_quantity_recommendation_never_becomes_the_final_order_quantity`).

## 3. Strategy registry

`src/production/registry.py::StrategyRegistry` holds `StrategyMetadata`
per `(strategy_id, version)` — status plus every field Part 4 listed
(version, status, created_at, validation_status,
historical_evidence_status, live_data_compatibility_status,
allowed_option_structures, parameter_specification, risk_profile,
author_or_research_provenance). Statuses: `RESEARCH`,
`VALIDATION_PENDING`, `VALIDATED`, `LIVE_AUTHORIZED`, `DISABLED`,
`REJECTED`, `NOT_READY`.

`production_eligible_strategies()` is the **only** list the pipeline
ever reads, and only ever contains `VALIDATED`/`LIVE_AUTHORIZED` entries.
`build_default_registry()` pre-registers
`MOMENTUM_BREAKOUT_EXISTING_V1` at `NOT_READY`, transcribing Phase 35's
real classification verbatim (0 completed backtest trades, below the
20-trade floor) — this module does not reclassify it.

## 4. Validation artifact

`src/production/validation_artifact.py::ValidationArtifact` requires
every evidence field Part 5 listed to be genuinely populated
(`IncompleteValidationEvidenceError` on a placeholder or empty dict) —
`strategy_content_hash`, `research_dataset_version`,
`feature_definitions`, `target_definitions`, `backtest_configuration`,
`out_of_sample_results`, `cost_assumptions`, `robustness_results`,
`statistical_results`, `multiple_testing_status`, `affordability`,
`execution_realism`, `known_limitations`, `validation_date`,
`validation_decision`, `approved_by`. `ValidationArtifactStore` is
append-only and immutable after approval (`ValidationArtifactImmutabilityError`
on a conflicting re-approval for the same version), mirroring
`FrozenStrategyStore`'s established convention exactly.

`StrategyRegistry.mark_validated()` is the **only** way a status can
become `VALIDATED`/`LIVE_AUTHORIZED`, and it hard-requires a matching,
approved artifact in the injected store — `StrategyNotEligibleError`
otherwise. No other file in `src/production/` references
`StrategyStatus.VALIDATED`/`LIVE_AUTHORIZED` or calls `mark_validated`
(enforced by `test_no_phase36_file_marks_a_strategy_validated_directly`).

## 5. Live market snapshot

`src/production/live_snapshot.py::LiveMarketSnapshot` (`UnderlyingLiveState`
+ `OptionLiveState`) is a new canonical shape carrying every field Part 6
asked for — including several this codebase's current models
(`OptionQuote`/`EquityQuote`) don't surface at all today: bid/ask size,
implied volatility, Greeks, strike, expiration, DTE, option type, chain
state/tradability. `build_live_market_snapshot()` maps the **existing**
`EquityQuote`/`OptionQuote` into it; every field neither of those
dataclasses carries stays `None` — never fabricated
(`test_build_live_market_snapshot_never_fabricates_missing_fields`). See
§18 for exactly which of these fields this codebase's real Robinhood
integration can populate today.

## 6. Data provenance

`src/production/provenance.py::DataProvenance` — `LIVE`, `HISTORICAL`,
`RECONSTRUCTED`, `DERIVED`. `assert_feature_acceptable_for_live_decision`
raises `HistoricalFeatureRequiredLiveError` when a feature the strategy
declares `required=True` is only available as `HISTORICAL`/
`RECONSTRUCTED` — an optional/diagnostic feature at those provenances is
accepted. `assert_reconstructed_never_masquerades_as_live` guards the
inverse failure mode: a caller relabeling a `RECONSTRUCTED` feature as
`LIVE` when assembling a snapshot.

## 7. Timestamp model

`src/production/timestamps.py::DecisionTimestamps` carries three
distinct timestamps (`market_data_timestamp`,
`strategy_evaluation_timestamp`, `decision_timestamp`) and enforces
non-decreasing order in `__post_init__` (`LookaheadViolationError`
otherwise) — the live-path analogue of `BacktestEngine`'s no-lookahead
invariant. `assert_quote_not_stale`/`StaleQuoteError` detect a stale
quote **before** it can reach a strategy at all, upstream of
`RiskManager.check_data_freshness`'s own (advisory) staleness check.

## 8. Contract validation

`src/production/contract_validation.py::validate_option_contract` — an
explicit `ContractRejectionCode` for every failure Part 9 listed
(`MISSING_OPTION_ID`, `CONTRACT_NOT_FOUND`, `EXPIRED`, `INACTIVE`,
`NOT_TRADABLE`, `INVALID_PRICE`, `ZERO_OR_CROSSED_MARKET`,
`STALE_QUOTE`, `MISSING_UNDERLYING`). Every check reads a real field on
`OptionLiveState` — no price or status is ever invented to produce a
rejection message.

## 9. Liquidity assessment

`src/production/liquidity.py::assess_liquidity` reuses whatever is
**already validated and operating** in this codebase's real risk
configuration (`RiskLimits.max_spread_pct`/`min_option_volume`/
`min_option_open_interest`/`stale_data_max_seconds` — the exact numbers
`RiskManager` already gates real trades on) rather than inventing new
production thresholds. `bid_size`/`ask_size` have no validated threshold
anywhere in this project today — both are always reported in
`LiquidityAssessment.configuration_required`, per Part 10's explicit
instruction, and never used to reject a contract.

## 10. Opportunity model

`src/production/opportunity.py::Opportunity` is built only from an
`ENTER` decision (`NotAnEntryDecisionError` otherwise) — `EXIT` decisions
never route through it (closing risk is always allowed,
`RiskManager.evaluate_exit_conditions` is advisory-only and unchanged;
`HOLD`/`NO_TRADE` produce nothing to route). Carries strategy_id,
timestamp, underlying, the option contract, the decision, the liquidity
assessment, `estimated_entry_price` (the live ask, matching
`MOMENTUM_BREAKOUT_EXISTING_V1`'s own `entry_price_rule` convention),
`estimated_maximum_loss_usd` (full premium, long-options-only, via the
reused `CONTRACT_MULTIPLIER`), `proposed_holding_period_minutes`,
`reason`, `confidence`. No constructor path from `StrategyDecision`
straight to an `OrderRequest` exists anywhere in this module.

## 11. Risk handoff

`src/production/risk_handoff.py::evaluate_opportunity_against_risk`
implements exactly `Opportunity -> RiskEngine -> PositionSizer ->
ExecutionOrder`: calls the real, unmodified
`RiskManager.evaluate_new_trade`; if `RiskDecision.allowed` is `False`,
no `OrderRequest` is ever constructed. If allowed, the real order
quantity comes from `PositionSizer.target_quantity()` (reusing
`src.backtesting.sizing`, the only sizer abstraction in this project) —
never the strategy's own `quantity_recommendation`. The resulting
`OrderRequest` passes through `assert_options_only()` (Phase 18/35,
reused) as the Order Validation stage. This module has no reference to
`src.execution.gateway`, `LiveOrderPlacer`, or any authorization/
emergency-stop store — constructing the inert `OrderRequest` dataclass
is not submitting it.

## 12. Ranking

`src/production/ranking.py::rank_opportunities` composites strategy
score, confidence, liquidity classification, spread, a concentration
penalty (already-held underlying), and an affordability penalty
(estimated max loss vs. account buying power) — never a new predictive
signal, never price history, never an indicator import
(`test_ranking_never_imports_a_signal_or_indicator_module`). Part 13's
fail-closed rule is enforced twice: once by `pipeline.py`'s earlier gate,
and again inside `rank_or_no_validated_strategy` itself, which returns
the literal string `NO_VALIDATED_STRATEGY` rather than a list whenever
`has_validated_strategy=False`.

## 13. No-strategy fail-closed behavior

`src/production/pipeline.py::run_live_decision_cycle`'s **first**
action, unconditionally, before touching risk config, account balance,
opportunity score, or market conditions, is
`registry.production_eligible_strategies()`. Empty => `NO_TRADE` /
`NO_VALIDATED_STRATEGY`, immediately. Verified directly against the
project's real, current registry (`build_default_registry()`, which
correctly contains zero eligible strategies today) by
`test_default_registry_produces_no_validated_strategy`, and against an
artificially generous risk/account configuration by
`test_no_strategy_fail_closed_regardless_of_risk_or_account_state` —
still blocked first. A strategy present in `strategies_by_id` but not
registry-eligible is never even called
(`test_registered_but_not_read_strategy_never_gets_called`).

## 14. Autonomous execution compatibility

`PipelineResult` (`pipeline.py`) has no per-trade-approval field of any
kind (`test_pipeline_result_has_no_per_trade_approval_field`) — once a
strategy is legitimately `VALIDATED` and a human enables
`LIVE_AUTONOMOUS_TRADING`, nothing in this pipeline re-introduces a
per-cycle human click. The full stage order
(`Market Data -> Strategy -> Opportunity -> Liquidity -> Risk ->
Position Size -> Authorization -> Execution -> Order Monitor ->
Position Manager -> Exit Engine`) is implemented through Authorization;
Execution/Order Monitor/Position Manager/Exit Engine are the existing,
unmodified modules from prior phases (`src.execution.gateway`,
`src.position_manager`) — this phase connects up to the boundary, it
does not rebuild what already exists beyond it.

## 15. Human authorization

Reused entirely unchanged from Phase 35: `is_live_trading_authorized`
(`src.execution.system_state`) is the single, system-wide check the
pipeline reads — never a per-Opportunity/per-decision field
(`test_authorization_gate_is_a_system_level_state_not_a_per_opportunity_field`).
`record_human_authorized_transition` still rejects a `"system:"`-prefixed
identity, reconfirmed unchanged. `system_state.py` was not touched this
phase.

## 16. Emergency stop

Reused entirely unchanged from Phase 35: `EmergencyStopStore` still
defaults to `STOPPED` with no record on disk, still requires a real
human identity to clear, still requires no authorization to trip.
`emergency_stop.py` was not touched this phase.
`run_live_decision_cycle` treats a missing store, or an active stop, as
the blocked answer (`EMERGENCY_STOP_ACTIVE`), checked strictly before the
Authorization/system-state check, and it is never bypassable by
anything upstream (an otherwise-fully-authorized synthetic test strategy
is still blocked by a tripped stop —
`test_full_positive_path_still_blocked_if_emergency_stop_tripped_after_authorization`).

## 17. MomentumBreakout adapter

`src/production/momentum_breakout_adapter.py::MomentumBreakoutProductionAdapter`
constructs the real, unmodified `MomentumBreakoutStrategy` and calls its
real, unmodified `scan()` — no `MomentumBreakoutConfig` override exists
anywhere in the adapter (`test_adapter_does_not_modify_the_real_strategys_logic`).
It correctly maps a real `SetupCandidate` into an `ENTER` decision and
"no setup found" into `NO_TRADE`, proving the interface fits. It remains
registered at `NOT_READY` in the default registry
(`test_adapter_strategy_remains_not_ready_in_the_default_registry`) and
is referenced nowhere outside its own defining module — no live trade
path exists for it (`test_adapter_has_no_live_trade_path`).

## 18. Robinhood compatibility

Traced from the actual implementation (`src/market/hood_provider.py`,
`src/market/hood_client.py`, `src/market/models.py`), not documentation,
against every `LiveMarketSnapshot` field:

| Field | Tool source | Parser/model | Timestamp behavior | Tested? | Available live? | Required by MOMENTUM_BREAKOUT_EXISTING_V1? | Missing today? |
|---|---|---|---|---|---|---|---|
| underlying.last | `get_equity_quotes` | `_parse_equity_quote` -> `EquityQuote.last_trade_price` | picks whichever of `venue_last_trade_time`/`venue_last_non_reg_trade_time` is more recent | Yes | Yes | Yes | No |
| underlying.bid/ask | `get_equity_quotes` | -- | -- | -- | Not confirmed by this codebase's own live probe | No | Yes -- `EquityQuote` has no bid/ask field at all |
| underlying.volume | `get_equity_historicals` (bars, not the quote) | `_parse_bars` -> `PriceBar.volume` | per-bar `begins_at` | Yes | Yes | No (only `volume_ratio`, computed from bars, is used) | Not on the quote itself, but on bars |
| option.bid / option.ask | `get_option_quotes` | `_parse_option_quote` -> `OptionQuote.bid_price`/`ask_price` | `updated_at` | Yes | Yes | Yes | No |
| option.mark | `get_option_quotes` (`mark_price`, tool's own "current price") | `_parse_option_quote` -> `OptionQuote.last_trade_price` | `updated_at` | Yes | Yes | No (strategy uses bid/ask, not mark) | No |
| option.volume / open_interest | `get_option_quotes` | `_parse_option_quote` | `updated_at` | Yes | Yes | Yes (pre-filter + RiskManager) | No |
| option.bid_size / ask_size | `get_option_quotes` (per Phase 34's live probe, the tool exposes size fields) | Not parsed -- `OptionQuote` has no such field | n/a | No | Confirmed available live (Phase 34), not yet surfaced by this codebase | No (not read by MOMENTUM_BREAKOUT_EXISTING_V1) | Yes -- a real, disclosed gap, not required by the one strategy that exists |
| option.implied_volatility / Greeks | `get_option_quotes` (confirmed in a real live probe, Phase 34) | Not parsed -- `OptionQuote` has no such field | n/a | No | Yes (Phase 34's live probe) | No | Yes -- same as above |
| option.strike / expiration / option_type | `get_option_chains` + `get_option_instruments` (chain-candidate rows, a raw dict, not `OptionQuote`) | `HoodMarketDataProvider.get_option_chain_candidates`/`_fetch_all_instruments` -- raw dicts, not mapped onto `OptionLiveState` by any existing parser | n/a (static contract terms) | Yes (chain fetch is tested) | Yes | Yes | No, but requires a caller (e.g. a future strategy or adapter) to thread the chain-candidate row's fields into `build_live_market_snapshot`'s separate parameters -- `OptionQuote` alone cannot supply them |
| option.dte_days | Derived from expiration - now | n/a (computed, not fetched) | n/a | Yes (via `MomentumBreakoutConfig`'s DTE window logic) | Yes | Yes | No |
| option.state / tradability | `get_option_instruments` chain-candidate row (`state`, `tradability` fields; `momentum_breakout.py`'s own `chain_filters` reads these) | Same raw-dict chain-candidate row, not `OptionQuote` | n/a | Yes (via the live strategy's own selection logic) | Yes | Yes | Same threading requirement as strike/expiration/option_type above |
| account.buying_power_usd | `get_portfolio` (`preflight.py`'s own real, tested parser) | `verify_account_preflight` | n/a | Yes (`preflight.py`, though never called from the live cycle -- Phase 34 §14 finding) | Yes | Yes (risk sizing) | Not missing, but not currently wired into a per-cycle `AccountState` anywhere |
| account.equity_usd | `get_portfolio` | Same as above (`total_value`) | n/a | Yes (shape verified) | Yes | No | Same as above |

**Conclusion, matching Phase 34/35's own prior finding exactly**: no
field `MOMENTUM_BREAKOUT_EXISTING_V1` actually requires is unavailable
live. The real gaps are (a) bid/ask size and IV/Greeks are confirmed
available by the underlying tool but not yet parsed into any model in
this codebase (not required by the one strategy that exists, but a real
gap for a future strategy that might need them), and (b) strike/
expiration/option_type/state/tradability live on the raw chain-candidate
dict, not on `OptionQuote` — `build_live_market_snapshot` already accepts
them as separate parameters for exactly this reason, but no existing
code path threads a chain-candidate row into it yet (that wiring is
future work, not a blocker discovered here).

## 19. Failure modes

| Failure mode | Representation | Where enforced |
|---|---|---|
| No validated strategy | `NO_VALIDATED_STRATEGY` | `pipeline.py` (first check) + `ranking.py` (defense-in-depth) |
| Account unavailable | `ACCOUNT_UNAVAILABLE` | `pipeline.py`, before any strategy is called |
| Stale quote | `StaleQuoteError` / `ContractRejectionCode.STALE_QUOTE` | `timestamps.py`, `contract_validation.py` |
| Missing quote | `ContractRejectionCode.CONTRACT_NOT_FOUND`/`MISSING_OPTION_ID` | `contract_validation.py` |
| Invalid/expired/inactive contract | `ContractRejectionCode.INVALID_PRICE`/`EXPIRED`/`INACTIVE`/`NOT_TRADABLE`/`ZERO_OR_CROSSED_MARKET` | `contract_validation.py` |
| Malformed decision | `MalformedDecisionError` | `decision.py.__post_init__` |
| Risk rejection | `RiskDecision.allowed=False` -> `RISK_REJECTED` | `risk_handoff.py` (reuses `RiskManager`, unchanged) |
| Emergency stop | `EMERGENCY_STOP_ACTIVE` | `pipeline.py` (reuses Phase 35's `EmergencyStopStore`, unchanged) |
| Unauthorized system state | `NOT_AUTHORIZED` | `pipeline.py` (reuses Phase 35's `is_live_trading_authorized`, unchanged) |
| Duplicate order/position | (unchanged) `RiskManager.check_duplicate_position` + `PendingOrderStore` | Phase 34/35, reconfirmed, not rebuilt |
| Broker unavailable | `BrokerUnavailableError` (defined for callers outside this package -- this package never calls the broker) | `failure_modes.py` |

No failure mode above produces an `order_request` — `PipelineResult.order_request`
is populated ONLY on the single `READY_FOR_AUTHORIZATION` outcome, and
even then this module never submits it.

## 20. Tests

96 new tests across 10 files, all passing:

| File | Tests | Covers |
|---|---|---|
| `test_phase36_decision.py` | 10 | StrategyDecision structural validation |
| `test_phase36_strategy_isolation.py` | 9 | Part 3's architectural boundary, incl. the repo-wide place_option_order re-scan |
| `test_phase36_registry_and_validation_artifact.py` | 11 | Registry status gating, ValidationArtifact evidence requirements/immutability |
| `test_phase36_live_snapshot_provenance_timestamps.py` | 15 | LiveMarketSnapshot, provenance rules, timestamp/lookahead/staleness |
| `test_phase36_contract_validation_liquidity_opportunity.py` | 19 | Every rejection code, liquidity classification, Opportunity construction |
| `test_phase36_risk_handoff_and_ranking.py` | 10 | Risk handoff (incl. "strategy cannot override risk"), ranking |
| `test_phase36_pipeline.py` | 10 | Fail-closed with the REAL default registry, the full positive path (synthetic test-only strategy), every gate independently |
| `test_phase36_autonomous_and_authorization.py` | 7 | No per-trade approval field, human-authorization/emergency-stop reuse verification |
| `test_phase36_momentum_breakout_adapter.py` | 5 | Adapter correctness, unmodified inner logic, NOT_READY status, no live path |
| `test_phase36_safety.py` | 14 | No live/paper order, no strategy marked validated directly, orchestrator not wired, safe defaults |

Full suite: **2,857 passed, 4 failed** (the same pre-existing,
time-drift-related baseline failures preserved unchanged since Phase 30,
untouched by this phase).

## 21. Remaining blockers

1. No validated strategy exists — this phase cannot and does not change
   that; it only builds the contract a future validated strategy would
   need to satisfy.
2. Chain-candidate fields (strike/expiration/option_type/state/tradability)
   are not yet threaded from `MarketDataProvider.get_option_chain_candidates`'s
   raw dict rows into `build_live_market_snapshot` by any existing code
   path — future wiring work, not a blocker to this phase's own
   deliverable.
3. bid/ask size and IV/Greeks remain unparsed by `OptionQuote` — a real,
   disclosed gap for any future strategy that might need them (not
   required by anything that exists today).
4. The pipeline is not wired into `orchestrator.py`'s real cycle — by
   design this phase ("architecture ... without activating it"), but a
   future phase will need to do that wiring deliberately once a real
   validated strategy exists.

## 22. Recommendation for Phase 37

Do not attempt to validate a new strategy through this contract yet —
there still isn't one. If a future phase produces a genuinely validated
strategy (a real `ValidationArtifact`, approved through
`ValidationArtifactStore`, backing a `StrategyRegistry.mark_validated()`
call), Phase 37 would be the natural point to (a) thread real chain-
candidate fields into `LiveMarketSnapshot` end to end, and (b) wire
`run_live_decision_cycle` into `orchestrator.py`'s real cycle — still
without enabling `LIVE_AUTONOMOUS_TRADING` itself, which remains a
separate, explicit human act per Phase 35's authorization gate.

---

## Answers to the phase's explicit questions

**A. Does a validated strategy currently exist?** No.

**B. Does MomentumBreakoutStrategy remain NOT_READY?** Yes —
unchanged from Phase 35, reconfirmed by
`test_momentum_breakout_still_not_ready_in_the_default_registry`.

**C. Can the live pipeline trade without a VALIDATED strategy?** No —
`run_live_decision_cycle` returns `NO_TRADE`/`NO_VALIDATED_STRATEGY`
before any strategy, risk check, or order is even considered, verified
against the project's real, current registry.

**D. Does any per-trade human approval exist or will be required once
live authorization is legitimately enabled?** No, and none will be —
`PipelineResult` has no such field, and the authorization check is a
single system-wide status, never a per-opportunity gate.

**E. Is live authorization active?** No. No `SystemStateAuditLog`
record exists; `is_live_trading_authorized` returns `False`.

**F. Is the emergency stop active?** Yes (by default) — no
`EmergencyStopStore` record exists, and the default is `STOPPED`.

**G. Was any order submitted?** No.

**H. Did any paper trading occur?** No.

**I. Was any paid historical data purchased?** No.

**STOP after Phase 36.** Phase 37 is not begun automatically.
