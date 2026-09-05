# Phase 38 — Validate an Options Strategy Using Real Live Robinhood Observations

**Status: NOT_READY. No strategy reached `VALIDATED_STRATEGY` this phase.**

This is a research/validation phase only. Its goal was never "find a strategy at
any cost" — it was to determine, from real evidence, whether any existing
candidate qualifies for `VALIDATED_STRATEGY`. The honest, evidence-driven
answer is **no**, for one simple, decisive reason: **zero real live
observation cycles have ever been recorded.** Every downstream requirement in
this phase (sample size, chronological splits, robustness, falsification,
affordability, option-level edge) is consequently unmet — not because the
statistical bar was failed, but because there is not yet any real data to
evaluate against it.

---

## 1. Executive summary

Phase 37 built and tested a live options research recorder
(`src/research_recorder/`) but never actually invoked it against the real
Robinhood integration — no scheduler, cron job, or manual run has ever
executed `run_observation_cycle` for real. This phase's Part 1 audit
confirmed that fact conclusively (see §2). Because Phase 38's entire mandate
is to validate strategies from real live observations, and there are none,
this phase built the complete validation machinery (causal dataset
construction, forward-return targets, candidate audit, underlying-vs-option
edge separation, immutable strategy spec reuse, chronological walk-forward
split, `TestRegistry`-backed statistical accounting, a battery of
falsification tests, economic validation, $1,000-account affordability
analysis, live-observation replication assessment, and a formal 17-condition
validation gate wired to Phase 36's `StrategyRegistry`) and ran it for real
against the actual (currently empty) Phase 37 stores. The result is
definitive: `n_dataset_rows=0`, `n_outcomes=0`, gate fails on 11 of 17
conditions, `MomentumBreakoutStrategy` remains `NOT_READY`. No orders of any
kind were created, submitted, modified, cancelled, or simulated. Live trading
authorization remains off; the emergency stop remains active.

## 2. Exact dataset used (Part 1 audit, A-H)

- **A. Live fields recorded by Phase 37:** Yes — `bid_price`, `ask_price`,
  `bid_size`, `ask_size`, `mark_price`, `adjusted_mark_price`, `volume`,
  `open_interest`, `implied_volatility`, all 5 Greeks, `break_even_price`,
  `chance_of_profit_long/short`, underlying quote/last-trade fields — all
  confirmed real (not fabricated) via prior Phase 18/28/34 live probes
  documented in `docs/options_architecture.md` and
  `docs/phase34_readiness_audit.md`, and parsed for the first time by
  `src/research_recorder/normalized_observation.py`.
- **B. Timestamps:** Per-call real retrieval timestamps
  (`observation_timestamp`) plus a shared `observation_cycle_id` per cycle —
  present in the schema, structurally enforced.
- **C. Contract identifiers:** `option_id` (the Robinhood instrument id) is
  present on every normalized option row and every `CausalFeatureRow`.
- **D. Provenance metadata:** Every field carries `LIVE` / `DERIVED_FROM_LIVE`
  / `MISSING` provenance (Phase 37's narrower vocabulary, deliberately
  distinct from the historical-research `DataProvenance` enum).
- **E. Raw data sufficient for causal features:** Yes, structurally — the raw
  payload plus fingerprint is preserved (`RawObservation`), and
  `build_causal_feature_row` can construct a fully causal row from it with no
  parameter through which a later observation could leak in (verified via
  `inspect.signature`).
- **F. Hypothetical decisions recorded:** Yes — `ResearchSignalRecord` with
  `label=HYPOTHETICAL_RESEARCH_DECISION`, produced by
  `evaluate_research_signal_for_cycle` wrapping the frozen Phase 36
  `MomentumBreakoutStrategy` adapter.
- **G. Historical observations actually available from Phase 37:** **Zero.**
  Confirmed by `find`/`grep` across the repository: no
  `research_recorder`-shaped JSONL file exists anywhere under `logs/`, no
  `Settings` field wires a recorder deployment path, and
  `logs/research_data/phase37/` does not exist. `run_observation_cycle` has
  never been invoked against the real Robinhood integration.
- **H. Enough for meaningful validation:** **No.** With zero real
  observations there is, by construction, no dataset to validate a strategy
  against. This is the load-bearing fact for the entire rest of this report.

**Exact dataset used this phase:** the real (as of 2026-09-05) Phase 37
stores at Phase 38's disclosed default path
`logs/research_data/phase37/{raw_observations,normalized_underlying,
normalized_options,research_signals,cycle_log}.jsonl` — none of which exist
yet. `run_phase38_campaign` was run directly against this real, empty state
(see §16 for the exact numbers). Phase 37 never specified a deployment path
for its own stores (a real gap this audit found); Phase 38 discloses its own
default, matching this project's `logs/research_data/` convention, and notes
a future phase should promote this into `Settings` once the recorder is
actually scheduled.

## 3. Candidates evaluated / excluded, and why

| Candidate | Origin | Prior classification | Included this phase? | Reason |
|---|---|---|---|---|
| `MOMENTUM_BREAKOUT_EXISTING_V1` | Phase 28 (live-wired), Phase 35 (frozen+validated spec) | `NOT_READY` (Phase 35: 2,071 causal entries, 2 matched to a real historical contract, 0 completed round-trip trades — underpowered, not pass/fail) | **Yes** | The only strategy with a live production adapter (Phase 36) and a real, frozen spec. Its Phase 35 rejection reason was *data volume* — exactly what Phase 37's recorder exists to eventually fix. No new evidence exists yet, so it cannot be promoted this phase, but it is the correct candidate to re-evaluate once real observations accumulate. |
| `options_alpha_round2` family (16 hypotheses) | Phase 31 | `NULL` (0/16 `DISCOVERY_SUPPORTED`/`PROMISING`) | No | Statistically unsupported after multiple-testing correction on the free historical dataset. No new live evidence this phase addresses that. |
| Bucketed options alpha family | Phase 32 | `NULL` | No | Same reasoning as Phase 31's family, at coarser granularity. |
| P22-OPT-013 + Phase 33 replication (P33-REPL-*) | Phase 22 / Phase 33 | `INCONCLUSIVE` (0/8 testable primary tests significant; fails 6/12 Promising-Finding-Gate criteria) | No | Technically eligible for re-evaluation (`INCONCLUSIVE`, not `REJECTED`) per Part 4's instruction, but its rejection reason was *historical-dataset density/sparsity*, and Phase 37's live recorder has not yet produced any real observation addressing that exact reason. A real candidate once live data accumulates. |

No previously-rejected candidate (inherited-from-underlying / outlier-dependent
/ cost-fragile / statistically-unsupported / unaffordable / data-artifact-driven)
was resurrected without genuinely new evidence addressing its exact rejection
reason — none had any.

No new alpha-discovery campaign was launched this phase, per Part 4's
explicit instruction.

## 4. Strategy specification used

`MOMENTUM_BREAKOUT_EXISTING_V1` — Phase 35's frozen spec, reused completely
unmodified via Phase 36's `MomentumBreakoutProductionAdapter`
(`src/production/momentum_breakout_adapter.py`), which this phase's
`src/research_recorder/research_signal.py` wraps purely for research-signal
evaluation (never feeding it into `run_live_decision_cycle`, never
registering/promoting it — see `test_adapter_has_no_live_trade_path` and
`test_phase37_safety.py::test_research_signal_module_never_registers_or_promotes_the_strategy`).
Universe, eligible contracts, signal definition, entry timing, contract
selection, DTE/moneyness constraints, liquidity requirements, sizing input,
exit logic, invalidation, max holding period, and cost/slippage assumptions
are all exactly as frozen in Phase 35 — no discretionary or LLM-judged logic
was introduced.

## 5. Feature and target definitions

- **Causal features:** `CausalFeatureRow` (`src/options/phase38_causal_validation_dataset.py`)
  — joins a normalized option observation with its same-cycle normalized
  underlying observation, preserving every Phase 37 field plus
  `field_provenance` and `raw_payload_fingerprint`. `build_causal_feature_row`
  has no parameter through which a later observation could be passed
  (verified via `inspect.signature`).
- **Targets:** `ForwardOutcome` (`src/options/phase38_targets.py`) — forward
  return (multi-horizon: 5min/15min/30min/1hr/EOD), MFE, MAE, directional
  outcome, risk-adjusted outcome, underlying-relative performance.
  `executable_return_pct` uses bid/ask exclusively (buy-to-open at ask,
  sell-to-close at bid); `mid_return_pct` is tracked separately and never
  substituted for the executable variant. `compute_forward_outcome` filters
  candidate later rows to strictly `observation_timestamp > entry.timestamp`
  and the same `option_id` before using any of them (verified against
  same-timestamp and different-option-id decoys). Unavailable targets
  (no later observation in tolerance, missing bid/ask) are marked
  explicitly, never fabricated.

## 6. Sample sizes

**Zero.** `n_dataset_rows=0`, `n_entry_signals=0`, `n_outcomes=0` against the
real Phase 37 stores. (Module-level tests exercise the full pipeline with
small synthetic/manually-constructed fixtures — see §16's caveat — but no
synthetic result is presented as evidence for this candidate.)

## 7. Chronological splits

`split_chronologically` requires ≥60 total outcomes for a three-way
DEVELOPMENT(50%)/VALIDATION(25%)/FINAL_HOLDOUT(25%) split, each ≥20. With 0
outcomes, `ChronologicalSplit` reports `sufficient=False`,
`reason="insufficient"`, and all three splits are empty. No data was
manufactured and no requirement was relaxed to force a split.

## 8. Statistical results

`evaluate_underlying_vs_option_edge` was run against each split (all empty):
`EdgeClassification.INSUFFICIENT_SAMPLE` for development, validation, and
holdout alike (`n=0` in each case; the classifier's `MIN_SAMPLE_FOR_A_VERDICT`
floor is 20).

## 9. Multiple-testing accounting

Every statistical claim this phase would make is routed through Phase 33's
existing `TestRegistry`/`apply_correction` — no unregistered significance
claim exists anywhere in the Phase 38 codebase (`phase38_test_registry_wiring.py`).
For the real (empty-data) run, 3 tests were registered
(edge result, randomized-signal placebo, shifted-signal timing robustness),
all under `PRIMARY_FAMILY`, all reporting `INSUFFICIENT_SAMPLE` rather than a
p-value, and correction was applied regardless (never skipped merely because
the underlying tests were underpowered).

## 10. Falsification results

All required falsification/robustness functions exist and run cleanly against
zero real outcomes, each reporting an explicit insufficient-sample verdict
rather than fabricating a result: randomized-signal placebo, shifted-signal
test, shuffled-feature-association test, cost-stress test, spread-stress
test, execution-delay test, leave-one-symbol-out, leave-one-period-out,
parameter-neighborhood test, outlier-removal test, concentration analysis
(`src/options/phase38_falsification.py`). None can be meaningfully evaluated
with 0 outcomes; none was forced to produce a pass.

## 11. Cost analysis

`build_economic_validation_report` and the cost/spread-stress tests are fully
implemented and reuse Phase 35/31 cost conventions; against 0 outcomes every
field is `None`/`INSUFFICIENT_SAMPLE` rather than a fabricated number.

## 12. Execution realism

`compute_forward_outcome` computes `executable_return_pct` strictly from
`entry_ask`/`exit_bid` — mid-price is never treated as executable (verified
by a dedicated test that the two values diverge when bid≠ask). Condition 9
of the validation gate (`execution_realism`) is the one gate condition that
**passes** even with zero data, because it is a structural property of the
target-construction code, not something that requires a populated dataset to
demonstrate.

## 13. Affordability ($1,000 account)

`evaluate_thousand_dollar_affordability` reuses Phase 31's
`affordability_filter_report`/`classify_account_feasibility` unchanged. With
zero priced rows, the real result is
`classification="ACCOUNT_FEASIBILITY_UNKNOWN_NO_PRICED_ROWS"` — no fixed
2-5%-daily-return requirement is imposed anywhere in this function (verified
structurally by
`test_affordability_never_imposes_a_fixed_daily_return_requirement`), and a
dedicated test (`test_affordability_flags_expensive_contracts_clearly`)
confirms the function would clearly flag a $3,500+/contract scenario if and
when real priced data exists.

## 14. Robustness

`leave_one_period_out` and `leave_one_symbol_out` are fully implemented and,
against zero real outcomes, both report empty result dictionaries (`{}`) —
condition 10/11 of the gate correctly report `passed=False` with
`"0 period(s)/symbol(s) checked"` rather than vacuously passing.

## 15. Holdout results

Never touched — `holdout_touched_before_freeze=False` in every real run.
With zero data, the holdout split is trivially empty and untouched; the gate
still checks (and would fail) `untouched_final_holdout` independently of
sample size, and confirms this candidate's holdout was never tuned against.

## 16. Live-observation replication

`evaluate_live_replication` (`src/options/phase38_live_replication.py`)
against the real stores: `n_cycles_available=0`, so it returns immediately
with `sufficient_for_replication=False` and the explicit reason "Zero
observation cycles have ever been recorded — `run_observation_cycle` has not
been invoked against the real Robinhood integration yet. There is nothing to
replicate against." No simulated account P&L was computed anywhere (Part 12's
explicit instruction) — this module only ever asks whether assumptions
(signal reproducibility, feature availability, timestamp monotonicity, live
field availability) hold, and signal reproducibility is reported as a
structural code-level fact (`MomentumBreakoutStrategy` contains no randomness
in its scan logic — Phase 28/35/36's own repeated audits), not something
empirically re-derived from a replay this phase did not build.

## 17. Final validation-gate result

`evaluate_validation_gate` — all 17 conditions, run against the real,
current evidence:

| # | Condition | Passed | Detail |
|---|---|---|---|
| 1 | deterministic_strategy_specification | ✅ | Reuses `MOMENTUM_BREAKOUT_EXISTING_V1` (Phase 35) unmodified. |
| 2 | causal_feature_construction | ✅ | Verified by `tests/test_phase38_causal_dataset_and_targets.py`'s anti-lookahead suite. |
| 3 | sufficient_sample_size | ❌ | Only 0 outcome(s) available (< 60 required). |
| 4 | chronological_validation | ❌ | validation split n=0 |
| 5 | untouched_final_holdout | ✅ | No parameter was ever tuned against final_holdout. |
| 6 | multiple_testing_accounting | ✅ | 3 test(s) registered. |
| 7 | economically_meaningful_results | ❌ | n=0, expectancy=None |
| 8 | realistic_transaction_cost_analysis | ❌ | Does not survive disclosed cost/spread stress, or was never computable. |
| 9 | execution_realism | ✅ | `compute_forward_outcome` uses bid/ask exclusively. |
| 10 | robustness_across_time | ❌ | 0 period(s) checked. |
| 11 | robustness_across_symbols | ❌ | 0 symbol(s) checked. |
| 12 | falsification_tests_passed | ❌ | placebo=INSUFFICIENT_SAMPLE, timing=INSUFFICIENT_SAMPLE |
| 13 | no_material_data_leakage | ✅ | Anti-lookahead structural guarantees (condition 2) apply identically. |
| 14 | no_unresolved_critical_data_quality_issue | ❌ | No data-quality report exists (zero cycles recorded). |
| 15 | affordability_assessment_completed | ❌ | `ACCOUNT_FEASIBILITY_UNKNOWN_NO_PRICED_ROWS` |
| 16 | option_level_implementation_edge_demonstrated | ❌ | Only 0 outcome(s) — underpowered. |
| 17 | reproducible_validation_artifact_generated | ❌ | One or more preceding conditions failed. |

**`GateResult.passed = False`.** Unmet conditions (11 of 17):
`sufficient_sample_size`, `chronological_validation`,
`economically_meaningful_results`, `realistic_transaction_cost_analysis`,
`robustness_across_time`, `robustness_across_symbols`,
`falsification_tests_passed`, `no_unresolved_critical_data_quality_issue`,
`affordability_assessment_completed`,
`option_level_implementation_edge_demonstrated`,
`reproducible_validation_artifact_generated`.

## 18. Exact NOT_READY reason per candidate

- **`MOMENTUM_BREAKOUT_EXISTING_V1`:** `NOT_READY`. Zero real live
  observations exist to validate against. This is not a statistical failure
  of the strategy — it is the complete absence of the evidentiary input the
  validation gate requires. The strategy's Phase 35 rejection reason (data
  volume) remains unaddressed; Phase 37's recorder exists to fix that but has
  never been run.
- **All other audited candidates:** excluded this phase per §3 (unchanged
  since their prior phase's classification; no new evidence).

## 19. Did any strategy reach VALIDATED_STRATEGY?

**No.** `promote_if_validated` — the sole function in this codebase
permitted to call `StrategyRegistry.mark_validated` — was never called for
`MOMENTUM_BREAKOUT_EXISTING_V1` or any other real candidate this phase (only
in synthetic, explicitly-never-real fixture tests proving the plumbing
works). `MOMENTUM_BREAKOUT_EXISTING_V1` remains `NOT_READY` in the default
registry (`test_momentum_breakout_still_not_ready_in_the_default_registry`).
No `ValidationArtifact` was approved for a real candidate.

## 20. Explicit no-orders-created statement

**No broker order of any kind — equity, option, or crypto — was created,
submitted, modified, cancelled, or simulated at any point in this phase.**
No paper trading was implemented. No simulated fill, simulated position, or
simulated P&L was created anywhere. Live trading authorization remains
`False`. The emergency stop remains active (`is_stopped() is True` against a
missing store, its documented fail-safe default). `.env`/broker
configuration was not touched. `place_option_order` is still called from
exactly one place in the whole codebase (`src/execution/gateway.py`) after
this phase, verified by both a static AST/substring scan and a
subprocess-isolated dynamic import check across every one of Phase 38's 13
new modules — none of them import `src.execution.gateway` or
`src.execution.live_client` at any level, directly or transitively.

## 21. Test counts

- Phase 38 module-level test files (9 files): 93 tests, all passing.
  (`test_phase38_causal_dataset_and_targets.py` 14,
  `test_phase38_candidate_audit_and_edge.py` 9,
  `test_phase38_chronological_split.py` 4,
  `test_phase38_falsification_and_registry.py` 23,
  `test_phase38_economic_affordability_replication.py` 12,
  `test_phase38_validation_gate_and_registry.py` 10,
  `test_phase38_campaign.py` 5, `test_phase38_safety.py` 16 — sums to 93.)
- Full project test suite: **3,041 passed, 4 failed** (`python -m pytest
  tests/ -q`). The 4 failures are exactly the same pre-existing
  `test_orchestrator.py` baseline failures from before this phase
  (`test_full_cycle_finds_setup_and_opens_a_paper_position`,
  `test_entries_still_allowed_before_local_cutoff_even_when_utc_clock_is_later`,
  `test_existing_paper_position_stop_exits_and_is_removed_from_ledger`,
  `test_everything_gets_logged`) — unrelated to Phase 38, untouched by it.
  One transient regression was found and fixed during this phase's own
  verification: a docstring in `phase38_live_replication.py` mentioned
  `MomentumBreakoutProductionAdapter` by name, which tripped Phase 36's
  existing textual-reference safety test
  (`test_phase36_momentum_breakout_adapter.py::test_adapter_has_no_live_trade_path`)
  even though the module never imports or uses that class. Fixed by
  rewording the docstring; the module still does not reference the class at
  all, confirmed by re-running both test files together (98 passed) and then
  the full suite again (back to exactly the 4 baseline failures).

## 22. Commit hash

See the commit that accompanies this report on branch
`claude/inspect-repo-mcp-tools-s5ic0p` (this file is committed in the same
commit as all Phase 38 source and test files).

---

## Final verdict

**B. NO VALIDATED STRATEGY — NOT_READY.**

Exact missing evidence: zero real live observation cycles have ever been
recorded (`src.research_recorder.recorder.run_observation_cycle` has never
been invoked against the real Robinhood integration in production). Every
one of the 11 unmet validation-gate conditions traces back to this single
root cause — sufficient sample size, chronological validation, economically
meaningful results, realistic transaction-cost analysis, robustness across
time and symbols, falsification tests, data-quality confirmation,
affordability assessment, and option-level implementation edge all require a
populated dataset that does not yet exist. No statistical requirement was
weakened to manufacture a different outcome. No strategy was promoted. No
order was created, submitted, modified, or cancelled. Live trading
authorization remains off and the emergency stop remains active.

This phase does not proceed to Phase 39 automatically.
