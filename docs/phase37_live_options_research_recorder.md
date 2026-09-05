# Phase 37 — Live Options Research Recorder

A NEW capability: real, live Robinhood options market data is now
collected and recorded for RESEARCH PURPOSES ONLY. **This is not paper
trading.** There are no simulated fills, no simulated positions, no P&L,
no paper orders, no live orders, and no strategy deployment anywhere in
this phase's work.

## 1. Executive summary

Phases 31-35 established, repeatedly, that the free historical options
archive cannot support statistical validation of an options strategy —
contract histories are sparse and same-day peer density is too thin
(Phase 35: 2,071 signals, 2 real matches, 0 completed round trips). The
user chose not to purchase a paid provider. Phase 37 responds to that
constraint the only way left: collect real, live market observations
going forward, so a future phase has an actual dataset to validate
against instead of a permanently-sparse historical archive.

The new `src/research_recorder/` package implements exactly the
pipeline the phase specified:

```
Robinhood Live Data -> Research Recorder -> Immutable Raw Observation
-> Canonical LiveMarketSnapshot -> Feature Calculation -> Strategy
Signal Evaluation -> Hypothetical Opportunity -> Research Journal
```

with a hard, structurally-enforced stop before order creation or
submission — verified three independent ways (§2), not merely by
`live_auto_execute=False`. 91 new tests pass; the full suite is 2,948
passed, 4 failed (the same pre-existing, time-drift-related baseline
failures from before this phase, untouched).

`MomentumBreakoutStrategy` is evaluated every cycle purely as a research
signal (via Phase 36's own, unmodified `MomentumBreakoutProductionAdapter`)
and every record is labeled `HYPOTHETICAL_RESEARCH_DECISION` — never
`TRADE`/`ORDER`/`POSITION`/`FILL`. It remains `NOT_READY` in the
registry; nothing in this phase registers or promotes it.

## 2. Architecture — and the structural no-trading boundary

The pipeline above is implemented as 13 focused modules (see
`src/research_recorder/__init__.py`'s module map). The hard stop is
verified three independent ways, per Part 2's explicit "do not rely
solely on `live_auto_execute=False`" instruction:

1. **Static AST import scan** (`tests/test_phase37_no_trading_boundary.py`) —
   every file in the package is parsed and every `import`/`from ... import`
   at ANY nesting level (module-level or function-local) is checked
   against `src.execution.gateway`/`src.execution.live_client`. None found.
2. **Static call-substring scan** — `place_option_order(`, `submit_order(`,
   `cancel_order(`, `modify_order(`, `confirm_and_place(`, and seven more,
   scanned with string literals and comments blanked out (the same
   AST-based technique every safety test since Phase 28 has used). None found.
3. **Dynamic, subprocess-isolated check** — a FRESH Python process (never
   the test-runner's own process, whose `sys.modules` is already
   contaminated by unrelated test files that legitimately import the
   gateway for their own tests) imports every real module in the package
   and inspects that process's own `sys.modules` afterward. This catches
   a TRANSITIVE import a per-file static scan could miss entirely (module
   A imports module B, B imports the gateway) — genuinely necessary: an
   earlier draft of `market_hours.py` would have imported
   `src.position_manager.monitor.is_within_monitoring_window` (the
   obvious, natural reuse candidate), which itself imports
   `src.execution.gateway` — caught by this exact check, and fixed by
   reimplementing the same primitives standalone instead (§6).

Also reconfirmed: `place_option_order(` still appears as an executable
call in exactly one file in all of `src/` (`src/execution/gateway.py`'s
`_place_pending`) — the same Phase 18/35/36 invariant, still holding
after adding this entire new package.

## 3. Robinhood data fields actually available

Traced from the actual repository implementation (`src/market/hood_provider.py`,
`src/market/hood_client.py`, `docs/options_architecture.md`,
`docs/phase34_readiness_audit.md`'s live-data-audit table — every claim
below backed by a real, documented live probe, never assumed from
tool-name conventions):

| Field | Confirmed available live | Parsed by `OptionQuote` today | Parsed by this recorder |
|---|---|---|---|
| bid / ask | Yes | Yes | Yes |
| bid_size / ask_size | Yes (real probe) | No | **Yes — new this phase** |
| mark / adjusted_mark | Yes | Yes (mark only) | Yes (both) |
| volume / open_interest | Yes | Yes | Yes |
| implied_volatility | Yes (real probe: 0.822619) | No | **Yes — new this phase** |
| delta / gamma / theta / vega / rho | Yes (real probe) | No | **Yes — new this phase** |
| break_even_price | Yes | No | **Yes — new this phase** |
| chance_of_profit_long / short | Yes | No | **Yes — new this phase** |
| strike / expiration / option type | Yes | Raw pass-through only | Yes (via chain-candidate rows) |
| underlying last trade price | Yes | Yes | Yes |
| underlying bid/ask | **Not confirmed** — `EquityQuote` carries no bid/ask field | No | No (stays `None`) |

This recorder reads the raw dict directly rather than through
`OptionQuote`'s narrower parser, specifically to capture the fields the
"unclaimed extension point" (`docs/options_architecture.md`) already
identified as real and available but never before surfaced anywhere in
this codebase. No new tool call was added — every field above comes
from the exact same `get_equity_quotes`/`get_option_quotes` calls this
codebase already makes.

## 4. Target universe

`src.research_recorder.target_universe.TARGET_UNIVERSE`: NVDA, TSLA,
SPY, QQQ, AAPL, MSFT, AMD, AMZN, META, GOOGL, NFLX, IWM — exactly the
12 symbols specified, observation targets only. A symbol that returns no
usable chain data this cycle is recorded as a failed
`SymbolObservationResult` with an explicit reason, never silently
dropped from the cycle's own record
(`test_symbol_with_no_chain_candidates_recorded_as_failed_not_dropped`).

## 5. Observation frequency

`RecorderConfig.observation_interval_minutes` defaults to 5 — documented
intent only; nothing in this package sleeps, loops, or schedules itself.
`run_observation_cycle()` is the one callable a future external
scheduler invokes, matching the exact convention
`src/position_manager/monitor.py`'s `is_within_monitoring_window()` +
`run_once()` already established for the live monitoring cycle.

## 6. Market-hours behavior

`src.research_recorder.market_hours.is_market_open_for_recording`
reimplements (deliberately, NOT imports) `is_within_monitoring_window`'s
exact logic — the same `TRADING_WEEKDAYS`/`market_open_time`/
`market_close_time`/`market_timezone` primitives — because importing
that function directly would transitively pull `src.execution.gateway`
into this package (§2's finding #3). Behavioral equivalence is verified
directly (`test_matches_is_within_monitoring_window_semantics`, run
against both naive and timezone-aware timestamps, weekday and weekend).
Outside regular hours, `run_observation_cycle` returns the literal
string `MARKET_CLOSED` and calls neither the client nor the market
provider at all — verified with fakes that raise if invoked.

## 7. Raw-data format

`RawObservation` (layer A) is frozen and immutable; every field Part 8
required is present: `provider`, `retrieval_timestamp`, `market_timestamp`
(when the tool supplied one), `payload_fingerprint` (a sorted-key SHA-256
over the raw payload — verified deterministic regardless of key order),
`schema_version`, `parser_version`. `__post_init__` refuses to construct
an instance whose declared fingerprint doesn't match its own payload —
a fingerprint can never silently drift from the content it describes.

## 8. Normalized-data format

`NormalizedUnderlyingObservation` / `NormalizedOptionObservation` (layer
B) carry every field Part 7 listed. Every field is populated ONLY if the
real raw key was present and parseable; otherwise it stays `None` with
`MISSING` provenance — never reconstructed, filled, or carried forward
(verified directly: `test_option_observation_never_fabricates_bid_size_or_greeks_when_absent`).
Options' "last trade" field is always `None`, WITH an explicit
`MISSING` provenance entry (`mark_price` is the tool's own documented
current-price field instead — the same finding `hood_provider.py`
already made) — documented, not silently omitted.

## 9. Provenance

`LiveObservationProvenance`: exactly `LIVE`, `DERIVED_FROM_LIVE`,
`MISSING` — a deliberately SEPARATE, narrower enum from
`src.production.provenance.DataProvenance` (which also has
`HISTORICAL`/`RECONSTRUCTED`, legitimate for a research backtest, never
for this live recorder). Every normalized observation carries a
`field_provenance` mapping covering every one of its fields — verified
present and correctly tagged for both underlying and option
observations, in both the fully-populated and fully-missing cases.

## 10. Quote-quality system

`assess_quote_quality` detects every condition Part 10 listed —
missing/non-positive bid or ask, crossed market, extreme spread, stale
timestamp, duplicate observation, malformed/expired/inactive contract —
and attaches flags to an UNCHANGED observation; nothing is ever deleted
(`test_bad_observation_is_flagged_never_deleted`). `EXTREME_SPREAD`'s
50% default and `STALE_TIMESTAMP`'s 90-second default are disclosed,
configurable OBSERVATION thresholds, not trading thresholds.

## 11. Contract selection

`select_observation_contracts` implements the exact, documented rule
Part 11 asked for: candidates are bucketed into 3 DTE bands (`SHORT`
1-15, `MEDIUM` 16-45, `LONG` 46-90 by default) × 3 moneyness bands
(`MODEST_ITM`, `NEAR_ATM`, `MODEST_OTM`, ±20% band by default), and for
each of up to 9 (× 2 option types = 18) buckets, the single nearest-to-
target candidate is kept — deterministic (verified:
`test_selection_is_deterministic`), never a random sample, never "first
N returned." Bounds are broad, disclosed, and configurable
(`ContractSelectionBounds`) — explicitly not final trading thresholds.
Selection uses ONLY the same-cycle underlying price and the
chain-candidate row already fetched this cycle
(`test_selection_uses_only_same_cycle_underlying_price`) — never a
later price, never future contract behavior.

## 12. Strike/DTE coverage

Directly satisfied by §11's bucket design: near-ATM, modestly-ITM, and
modestly-OTM, crossed with short/medium/long DTE, are exactly the 9
(×2 option types) buckets the selection algorithm targets — verified
against a synthetic 7-strike × 6-DTE chain, all 18 (option_type, DTE
bucket, moneyness bucket) combinations produced
(`test_selection_covers_all_nine_buckets_per_option_type`).

## 13. Observation-cycle consistency

Every raw and normalized record carries the same `observation_cycle_id`
and its OWN real `retrieval_timestamp`/`observation_timestamp` — never
a pretended shared instant. Sequential API calls within one cycle (one
equity-quote call, one batched option-quotes call per symbol) each get
their own real `datetime.now(timezone.utc)` at the moment they actually
returned.

## 14. Strategy signal recording

`MOMENTUM_BREAKOUT_EXISTING_V1` is evaluated every cycle via Phase 36's
own, completely unmodified `MomentumBreakoutProductionAdapter` — no new
adapter, no parameter change. Every result is labeled
`HYPOTHETICAL_RESEARCH_DECISION` (verified:
`test_research_signal_labeled_hypothetical_never_trade_or_order`, which
also asserts `TRADE`/`ORDER`/`POSITION`/`FILL` never appear as the
label or decision value). A strategy-evaluation failure (e.g. a market
data error) degrades to a recorded failure with `evaluation_error` set,
never a crashed cycle. This module never touches `StrategyRegistry` or
`ValidationArtifact` — nothing here registers or promotes the strategy.

## 15. Storage

Three separate, append-only JSONL layers, never mixed, following the
SAME convention `FrozenStrategyStore`/`ValidationArtifactStore`/
`TradeJournal` already established: `RawObservationStore` (A),
`NormalizedUnderlyingStore`/`NormalizedOptionStore` (B),
`ResearchSignalStore` (C) — plus a deliberately separate 4th,
operational-only `CycleLogStore` (which cycles ran, which symbols
succeeded/failed) that `quality_report.py` reads from and nothing else
does. Each store's duplicate-detection index is rebuilt from the
existing file's own contents at construction — no external database
dependency introduced.

## 16. Restart/recovery

Verified directly: a fresh store instance pointed at an existing file
(simulating a process restart) recovers the exact same duplicate-
detection state a running instance would have
(`test_raw_store_detects_duplicate_across_restart`). Re-running
`run_observation_cycle` with the SAME `observation_cycle_id` after a
simulated crash produces zero duplicate rows and correctly reports
every re-attempted contract as a detected duplicate
(`test_restart_with_same_cycle_id_never_duplicates_data`); an
incomplete cycle (crash after symbol 1, restart adds symbol 2) merges
correctly with no re-duplication of symbol 1
(`test_incomplete_cycle_then_restart_completes_remaining_symbols`). A
crash can never produce an executable order — nothing in this package
constructs one at all.

## 17. API safety

Every live call is wrapped in `_call_with_retry` — a hard-bounded retry
count (`RecorderConfig.max_retries`, default 2) with linear backoff, an
injectable `sleep_fn` (never a real sleep in tests), and a recorded
failure reason on exhaustion (`test_retry_is_bounded_never_an_infinite_loop`
proves the call count is exactly `1 + max_retries`, never unbounded).
Requests are batched (one `get_option_quotes` call per symbol per
cycle, covering all ~18 selected contracts at once, never one call per
contract) and the universe itself is a fixed, bounded 12-symbol tuple —
never a dynamic or unbounded loop.

## 18. Security

`src.research_recorder.security.redact`/`assert_no_credential_shaped_content`
strip or reject any `key: value`/`key=value`/`Bearer <token>`-shaped
text. This recorder never handles a broker credential directly — it
calls the same injected `HoodToolClient` every other read-only module in
this codebase already uses, whose auth lives entirely outside this
Python process (`src/market/hood_client.py`'s own documented boundary).

## 19. Test coverage

91 new tests across 10 files, all passing:

| File | Tests |
|---|---|
| `test_phase37_no_trading_boundary.py` | 6 (the critical architectural boundary, incl. the subprocess-isolated dynamic check) |
| `test_phase37_provenance_dte_moneyness.py` | 12 |
| `test_phase37_raw_observation_and_normalization.py` | 13 |
| `test_phase37_quote_quality_and_contract_selection.py` | 20 |
| `test_phase37_market_hours_and_security.py` | 7 |
| `test_phase37_recorder_and_storage.py` | 15 |
| `test_phase37_quality_report_and_no_pnl.py` | 6 |
| `test_phase37_safety.py` | 12 |

Plus one pre-existing Phase 36 test
(`test_phase36_momentum_breakout_adapter.py::test_adapter_has_no_live_trade_path`)
updated with one explicit, documented exception for
`research_signal.py`'s legitimate, non-executing reference — the only
existing file touched this phase.

Full suite: **2,948 passed, 4 failed** (the same pre-existing,
time-drift-related baseline failures, untouched).

## 20. Safety verification

Programmatically verified before completion:
- No live order submitted (§2, three independent checks).
- No paper order submitted (no `simulate_paper_order`/`SimulatedFill` anywhere in the package).
- No strategy deployed (`orchestrator.py` does not import `research_recorder`; no registry promotion anywhere in the package).
- No paid provider activated / no paid historical data purchased (no purchase/checkout/API-key-assignment pattern anywhere; the same free `HoodToolClient` integration is reused unchanged).
- Live authorization remains OFF (`is_live_trading_authorized` returns `False` with no record; `.env` unchanged — still `TRADING_MODE=paper`, `LIVE_TRADING_CONFIRMED=false`, `LIVE_AUTO_EXECUTE=false`).
- Emergency stop remains ACTIVE (`EmergencyStopStore` defaults to `STOPPED` with no record; no file created).
- `MomentumBreakoutStrategy` remains `NOT_READY` (`build_default_registry()` unchanged, reconfirmed).
- The recorder contains no order-submission capability (every store class exposes only `append`-shaped methods; none named order-related).

## 21. Known limitations

1. This phase collects NO data yet — `run_observation_cycle` is built,
   tested, and ready, but nothing calls it on a real schedule (Part 5's
   explicit "do not create an external scheduler in this phase"). A
   future phase (or a human operator) must invoke it periodically for a
   real dataset to accumulate.
2. Underlying bid/ask remain unavailable — `EquityQuote`'s real response
   shape has no such field (confirmed by this phase's own inspection,
   consistent with every prior phase's finding); underlying quality is
   necessarily last-trade-price-only.
3. Contract selection's 18-per-symbol-per-cycle cap means the FULL chain
   is never observed — a deliberate, disclosed research-cross-section
   choice (Part 11), not a limitation to be "fixed" by observing more;
   doing so would risk an aggressive request pattern Part 22 explicitly
   forbids.
4. No live probe was actually run this phase (no MCP tool call was
   made) — every field-availability claim in §3 is grounded in this
   project's own prior, already-documented live probes (Phase 18/28/34),
   re-verified by inspecting the current parser code, not by a fresh
   live call. The recorder's OWN correctness against a truly live
   response has not yet been exercised outside its test fakes.

## 22. Recommendation for Phase 38

Do not build any trading/paper-trading logic on top of this recorder
yet. The natural next step is operational: invoke
`run_observation_cycle` on a real schedule (a Routine, a supervised
process — this phase deliberately does not build that) against the real
`HoodToolClient`, let real data accumulate for a meaningful period, then
build a genuinely NEW research phase that reads the resulting dataset
(§15's three layers) the same way Phase 31-33 read the free historical
archive — applying the SAME validation discipline (frozen strategy,
formal backtest, cost stress, statistical gate) this project has used
throughout, never treating raw observation counts as evidence of
anything on their own.

---

## Answers to the phase's explicit questions

**A. Is this paper trading?** No.

**B. Was any simulated P&L generated?** No — verified structurally
(no P&L-shaped field or function exists anywhere in the package).

**C. Can the recorder submit orders?** No — verified three independent
ways (§2): static import scan, static call scan, and a subprocess-
isolated dynamic import check.

**D. Does MomentumBreakoutStrategy remain NOT_READY?** Yes.

**E. Does a validated strategy exist?** No.

**F. Is live authorization OFF?** Yes.

**G. Is the emergency stop ACTIVE?** Yes (default, no record exists).

**H. Was any live order submitted?** No.

**I. Was any paid data purchased?** No.

**J. Is the collected data intended for future research only?** Yes —
this phase does not interpret any observation as alpha evidence, and
`quality_report.py`'s own docstring says so explicitly.

**STOP after Phase 37.** Phase 38 is not begun automatically. Trading
is not enabled or authorized. No strategy was created. No observation
is treated as evidence of profitability.
