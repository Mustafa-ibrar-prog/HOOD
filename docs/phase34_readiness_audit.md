# Phase 34 — Options Trading System Readiness & Strategy-Gap Audit

**This phase is an architectural and readiness audit only.** No strategy
was chosen, invented, or promoted. No paid data was purchased. No live
or paper order was placed. No execution-layer code was modified. The
only new code this phase adds is 11 structural regression tests
(`tests/test_phase34_readiness_audit.py`) that lock in findings below —
every one passes today and documents CURRENT behavior, not a fix.

Method: six independent read-only audits traced actual callable code
paths (not file existence) across the live decision pipeline, cross-
checked against each other and against this project's own prior claims
(Phase 12/18/28's architecture docs), then verified directly against
primary sources (`.env`, `README.md`, `git log`) rather than accepted at
face value. Where a prior phase's audit table was found to overstate
wiring, this report says so explicitly and corrects it.

---

## 1. Executive summary

- **No validated options strategy exists.** Every options-alpha
  hypothesis this project has tested (16 in Phase 31, 14 in Phase 32,
  the P22-OPT-013 replication in Phase 33) failed to reach
  `DISCOVERY_SUPPORTED`/`PROMISING` and pass the 12-criterion Promising
  Finding Gate. None was ever promoted into executable code — confirmed
  structurally (§2, §19), not merely by absence of a claim.
- **A different, pre-existing strategy is already live-wired and running
  by default.** `MomentumBreakoutStrategy` (options-only, calls-only,
  technical-analysis-based) is instantiated and scanned every cycle by
  `src/orchestrator.py`. It was never subjected to this project's
  statistical validation pipeline (no preregistration, no IC/bootstrap/
  placebo evidence, no multiple-testing correction, no Promising Finding
  Gate). This is the single most important, non-obvious finding of this
  audit — see §2.
- **The system HAS run live and autonomously once already**, outside
  active human supervision, and the account showed an unexplained
  buying-power loss ($100 → $0). No trade was ever filled (verified by
  the operator against `get_option_orders`/`get_realized_pnl`), and the
  system has since been reset to safe defaults — but this is documented,
  primary-source evidence, not a hypothetical risk. See §11.
- **The Phase 28 system-level authorization state machine
  (`SystemState`, 7 states, `EMERGENCY_STOP` included) is real, well-
  designed, and completely unwired** — it governs nothing in the actual
  live gate today. The real gate is three raw `Settings` booleans
  checked directly in `gateway.py`. See §10.
- **Technical execution capability without a validated strategy is not
  authorization to trade.** The correct, honest conclusion (§21) is that
  this system is NOT authorized to trade live, a validated strategy
  remains a `BLOCKER`, and no further alpha-discovery campaign is
  justified on the current free dataset.

## 2. Current architecture

Traced end to end from `src/orchestrator.py:run_trading_cycle()`, the
one real live-cycle entry point.

| Stage | Real module | Classification | Basis |
|---|---|---|---|
| MARKET DATA | `src/market/hood_provider.py` (`HoodMarketDataProvider`) | **PARTIAL** | Real, correctly-interfaced, unit/integration-tested in isolated slices — but no automated bridge exists; every real call is agent-mediated one tool call at a time (`live_bridge.py`), and no test exercises `run_trading_cycle` + the real provider together end to end. Reclassified down from Phase 28's "READY" (§below). |
| UNIVERSE SCANNER | `Settings.scan_universe` + `src/strategy/scanner.py` | **PARTIAL** | Real and live-wired, but is a static, config-driven symbol list (default 5 symbols; the account's real `.env` uses `NIO,MARA,SOFI,SOUN,PLUG`), not dynamic discovery. A separate, genuinely dynamic module (`src/options/universe.py`) exists but is never imported by any live-path file. |
| OPTION CHAIN SCANNER | `MomentumBreakoutStrategy._select_contract` + `HoodMarketDataProvider` | **COMPLETE** (code path) / **PARTIAL** (integration-tested) | Real pagination-following chain fetch and parsing exists and is tested (`tests/test_hood_provider.py`), but no test integrates the chain-fetch and contract-selection code together as one unit. |
| FEATURE ENGINE | `src/features/*` | **MISSING from the live path** | A real, substantial, causally-tested (24/24 no-lookahead tests pass) feature library — but imported only by `src/research/` and `src/backtesting/`, never by `orchestrator.py` or `strategy/`. `MomentumBreakoutStrategy` computes its own indicators via a separate, simpler path (`src/market/indicators.py`). Phase 28's "READY" table entry overstated this — corrected here. |
| SIGNAL ENGINE | `src/strategy/base.py` + `momentum_breakout.py` | **COMPLETE (but unvalidated)** | Exactly one concrete `Strategy` subclass exists (`MomentumBreakoutStrategy`), live-wired, options-only — but never statistically validated by this project's own pipeline. See §2's strategy-status detail below. |
| OPPORTUNITY RANKER | `src/options/opportunity_score.py` | **MISSING from the live path** | Explicitly "architecture only... no scoring function implemented" by its own docstring, and never imported by `orchestrator.py`/`strategy/`. The live "ranking" that actually runs is `StrategyScanner.scan_for_setups`'s plain sort by `candidate.score` (`momentum_breakout.py`'s own strengthening-score). Phase 28's "READY" table entry overstated this — corrected here. |
| LIQUIDITY FILTER | `RiskManager.check_spread` / `check_liquidity` | **COMPLETE** (core checks) / **MISSING** (bid/ask size) | Spread%, volume, OI, staleness, crossed/zero-bid rejection are real, config-driven, and live-wired. Bid size / ask size are not modeled anywhere in the live `OptionQuote` at all. |
| RISK ENGINE | `src/risk/manager.py` | **PARTIAL** | 11 real checks, live-wired (trade count, daily loss, position size, duplicate position, cooldown, staleness, spread, liquidity, extended move, cutoff time, no-size-increase-after-loss). Missing: portfolio exposure, concentration, correlated exposure, cumulative/multi-day drawdown, emergency-stop integration. Short options and vertical spreads are structurally impossible to hold (by design) so their risk math is moot for what the system can currently do. |
| POSITION SIZER | `RiskManager.check_position_size` | **PARTIAL** | A flat USD cap only (`MAX_POSITION_SIZE_USD`, default $250) — no equity-based, confidence-based, liquidity-aware, or concentration-aware sizing. `suggested_quantity` is hardcoded to 1 in the only live strategy. |
| EXECUTION ENGINE | `src/execution/gateway.py` | **PARTIAL** | Order construction/submission, the pending-approval flow, and the dual-switch live gate are real and well-tested. Missing: post-submission order-lifecycle tracking (no `get_option_orders` polling anywhere), partial-fill reconciliation, cancellation, retry/backoff, unexpected-fill detection. See §9. |
| ROBINHOOD | `mcp__HOOD__*` tools, agent-mediated only | **BLOCKED_BY_DATA / PARTIAL** | No Python process in this codebase can call a real HOOD MCP tool on its own — every live call requires an agent's own tool-call turn (`live_bridge.py`). This is an environmental constraint, not a code defect, but it means "autonomous" cannot mean headless in this deployment. |
| ORDER MONITOR | — | **MISSING** | No component polls live order status after submission; `get_option_orders` is called nowhere in `src/`. |
| POSITION MANAGER | `src/position_manager/*` | **COMPLETE** | Real positions synced read-only from the live account (`hood_sync.py`); paper positions in an internal ledger; a separate provenance store (`LiveBotPositionsStore`) tracks which real positions this system itself opened. |
| EXIT ENGINE | `src/position_manager/evaluator.py` | **COMPLETE, live-wired** | Real, non-trivial logic (thesis invalidation, stop-loss, expiration handling, trailing exit, momentum-driven early exit, profit target) invoked every cycle for both paper and real positions. |
| TRADE JOURNAL | `src/logging/trade_journal.py` | **PARTIAL** | Captures entry thesis, exit reason, realized P&L, hold time. Does not capture entry-time risk-check results or the live order's broker order ID in the same record — full reconstruction requires cross-referencing a separate decision log by symbol/timestamp. |

**A note on Phase 28's own "15/15 READY" table**: re-verifying it this
phase (rather than trusting it) found 3 of its 15 entries overstated —
FEATURE ENGINE and OPPORTUNITY RANKER are real modules that are not
actually reachable from the live path at all, and MARKET DATA's "READY"
undersells that no automated bridge or end-to-end test exists. This is
not a criticism of Phase 28's own honesty (its underlying source module,
`autonomous_architecture_audit.py`, only ever claimed the modules
*exist*, not that they're wired) — it is exactly the gap between "a
real module exists" and "a real module is reachable from a live
decision," which this phase's stricter standard was asked to find.

## 3. Strategy status

**No component in this repository meets all of**: options-only,
quantitatively defined, historically tested, no lookahead, statistically
validated, multiple-testing corrected, economically meaningful, robust
across time/symbols, affordable, explicit entry, explicit exit,
compatible with live option-chain data, and passed the Promising Finding
Gate.

**`NO VALIDATED OPTIONS STRATEGY EXISTS.`**

But this is not the same as "the system is strategy-less." Read
precisely:

| Candidate | Classification | Why it fails |
|---|---|---|
| `MomentumBreakoutStrategy` (`src/strategy/momentum_breakout.py`) | **production candidate — live-wired, currently runs every cycle** | Options-only (calls only), explicit entry (ask price) and exit (fixed %/trailing, enforced live), compatible with live option-chain data — but never preregistered, never IC/bootstrap/placebo-tested, never multiple-testing corrected, never run through `phase31_gate.evaluate_gate()`. A rules-based technical scanner (RSI/MACD/EMA/breakout structure), not a statistically validated finding. Predates this project's Phase 19+ options-alpha research entirely. |
| P22-OPT-013 (range expansion → MFE) | research-only, terminated | The only hypothesis to ever reach `DISCOVERY_SUPPORTED` (Phase 22) — downgraded to `TRADEABLE_SIGNAL_FRAGILE` and failed the 14-criterion advancement gate (Phase 23: median trade loses money, expected dollar P&L negative), then failed to replicate at the bucket level entirely (Phase 33: wrong-signed pooled estimate). Never became a `Strategy` subclass — confirmed by an empty grep of hypothesis IDs in `src/strategy/`, `src/execution/`, `src/orchestrator.py` (now also a permanent regression test, `test_no_research_hypothesis_id_referenced_in_live_execution_path`). |
| 16 Phase 31 `P31-OPT-*` hypotheses | research-only, rejected/null | 0 `DISCOVERY_SUPPORTED`/`PROMISING`; cross-sectional IC undefined for all 16. |
| 14 Phase 32 `P32-BKT-*` hypotheses | research-only, rejected/null | 0/14 significant after Bonferroni/Holm/BH; 0 pass the Promising Finding Gate. |
| `src/options/opportunity_score.py` | research-only, architecture skeleton | Scoring function never implemented (`composite_score=None`); disconnected from the live path. |
| `src/options/mechanical_baseline.py` | mechanical baseline | Not a strategy — a statistical attribution/null-check tool (option-vs-underlying IC comparison), one input to the Promising Finding Gate. |
| `src/backtesting/example_strategy.py`'s `MovingAverageCrossoverStrategy` | example/demo | Equity, not options; explicit backtest-engine demonstration, disconnected from `src.strategy.base.Strategy`/`orchestrator.py`. |
| `scripts/phase18_step0_options_capability_audit.py`'s demo `OrderRequest`s | example/demo | Constructs valid/invalid orders purely to demonstrate `assert_options_only()`; never calls a strategy or a gateway. |

Bottom line, stated precisely: **the codebase has a live-executable
options mechanism (`MomentumBreakoutStrategy` → risk engine → execution
gateway) and a rigorous, independently honest research-validation
pipeline (Phase 19–33) — but the two have never been joined.** Nothing
that passed statistical validation is executable, and nothing that's
executable has been statistically validated.

## 4. Research/production separation

**COMPLETE, verified structurally, bidirectionally, not by convention.**

- Zero real imports of `src.execution`/`src.orchestrator` anywhere under
  `src/research/*.py` or `src/options/phase*.py` (one docstring hit in
  `paper_trading_simulation.py` explicitly *disclaims* any such import).
- Zero imports of `src.options`/`src.research` from any live-path module
  (`src/market/`, `src/strategy/`, `src/risk/`, `src/position_manager/`,
  `src/execution/`, `src/orchestrator.py`) — separation is bidirectional.
- Type-level separation: the live path only ever produces/consumes
  `src/market/models.py` dataclasses; research data lives in
  structurally distinct types (`OptionChainObservation`,
  `ResearchObservation`, `InMemoryLeanSampleStore`) with no shared base
  class or adapter that could let one be passed where the other is
  expected.
- Provenance checks (`src/options/quality.py`'s OBSERVED/DERIVED/
  ESTIMATED) have no caller in any live-path module — moot rather than
  unenforced, since the live path never touches `src.options.*` types
  at all.
- No research code writes to `Settings`, `SystemState`, or calls into
  `src/execution/` (one hit: `src/options/orats_config.py`, a separate
  dotenv loader scoped only to `ORATS_API_KEY`/`ORATS_BASE_URL`, never
  touching `TRADING_MODE`/`LIVE_TRADING_CONFIRMED`/`LIVE_AUTO_EXECUTE`).
- This is independently, structurally enforced by AST-based
  `test_phaseNN_safety.py` import-boundary tests across every research
  phase from 6 through 33 (409 safety/system_state tests, all green),
  plus this phase's own cross-cutting re-assertion
  (`test_no_research_or_options_module_imports_execution_or_orchestrator`).

**No unsafe path was found in this category. Nothing required fixing.**

## 5. Live data audit

Ground truth: a real, live `get_option_quotes` probe (documented in
`src/options/capability_audit.py`, `docs/options_architecture.md`) and
the current parser (`src/market/hood_provider.py`, `src/market/models.py`).

| field | available live (observed) | parser exists | tested |
|---|---|---|---|
| bid | Yes | Y — `OptionQuote.bid_price` | Y |
| ask | Yes | Y — `OptionQuote.ask_price` | Y |
| bid size | Yes | **N** | N |
| ask size | Yes | **N** | N |
| mark | Yes (`mark_price`) | Y — repurposed into `last_trade_price` (options have no true last-trade field) | Y |
| adjusted mark | Yes (`adjusted_mark_price`) | Partial — fallback only if mark is null | Partial |
| last trade price | N/A for options (mark is used instead) | Y (see mark) | Y |
| volume | Yes | Y | Y |
| open interest | Yes | Y | Y |
| implied volatility | Yes (real probe: 0.822619) | **N** | N |
| delta | Yes (real probe: 0.982989) | **N** | N |
| gamma | Yes (real probe: 0.000756) | **N** | N |
| theta | Yes (real probe: -0.097964) | **N** | N |
| vega | Yes (real probe: 0.028455) | **N** | N |
| rho | Yes (real probe: 0.096388) | **N** | N |
| break-even price | Yes | **N** | N |
| chance of profit | Yes (long/short) | **N** | N |
| expiration | Yes | Y — raw pass-through, not on `OptionQuote` | Y |
| strike | Yes | Y — raw pass-through, not on `OptionQuote` | Y |
| option type | Yes | Partial — requested via filter, response's own field never asserted | Y (fixture-level) |
| underlying price | Yes | Y — `EquityQuote.last_trade_price` | Y |

Core pricing/liquidity fields are live-verified, parsed, and tested on
the real trading path. Every risk-relevant Greek/IV field, plus
bid_size/ask_size/break_even/chance_of_profit, is confirmed present in
the live payload but structurally absent from `OptionQuote` — an
honestly, explicitly documented gap (`docs/options_architecture.md`'s
"unclaimed extension point"), reconfirmed unchanged this phase and now
locked in by `test_option_quote_has_no_greeks_iv_or_size_fields`.
`RiskManager.evaluate_new_trade` therefore has zero access to
delta/IV-based risk sizing today.

## 6. Live option chain scanning

| Capability | Status |
|---|---|
| 1. Candidate underlying universe | **PARTIAL** — static config list (`Settings.scan_universe`), not dynamic discovery |
| 2. Option chains | **COMPLETE** — real, pagination-following fetch (`get_option_chains`/`get_option_instruments`), tested |
| 3. Enumerate valid contracts | **COMPLETE** — parses `id`/`strike_price`/expiration from real response shapes |
| 4. Live option quotes | **COMPLETE** — `get_option_quotes` → `OptionQuote`, tested |
| 5. Liquidity metrics | **COMPLETE** (spread%/volume/OI) — see §7 |
| 6. Moneyness | **COMPLETE** in the strategy's own contract-selection (nearest-strike-to-price); no standalone moneyness field on `OptionQuote` |
| 7. DTE | **COMPLETE** — `_select_expiration`'s DTE window filter |
| 8. Compare calls and puts | **MISSING from the live path** — `MomentumBreakoutStrategy` is calls-only by design; no put-side comparison exists live (research-only `src/options/` modules can, but aren't wired in) |
| 9. Compare strikes | **COMPLETE** — nearest-to-underlying-price selection |
| 10. Rank contracts | **PARTIAL** — only "nearest strike" ranking exists; no scoring across multiple strikes/expirations (`opportunity_score.py`'s richer ranking is disconnected, §2) |

No gap here requires inventing a strategy to fill — every missing item
is an architectural capability gap (put-side comparison, multi-contract
ranking), correctly left unimplemented per this phase's own instruction.

## 7. Liquidity engine audit

| Check | Status | Threshold source |
|---|---|---|
| Bid/ask spread % | **COMPLETE** | Config: `MAX_SPREAD_PCT` (default 0.10) |
| Bid size / ask size | **MISSING** | N/A — not modeled on `OptionQuote` at all |
| Volume | **COMPLETE** | Config: `MIN_OPTION_VOLUME` (default 50) |
| Open interest | **COMPLETE** | Config: `MIN_OPTION_OPEN_INTEREST` (default 100) |
| Quote freshness/staleness | **COMPLETE** | Config: `STALE_DATA_MAX_SECONDS` (default 90) |
| Zero-bid contracts | **COMPLETE** | Hardcoded structural check (`bid <= 0`), appropriately not configurable |
| Crossed markets | **COMPLETE** | Hardcoded structural check (`ask < bid`) |
| Wide markets | **COMPLETE** | = spread % check |
| Minimum liquidity | **COMPLETE** | = volume/OI check |
| Maximum acceptable spread | **COMPLETE** | = spread % check |

**Configuration gap flagged**: `MomentumBreakoutStrategy` runs its own
pre-filter spread/liquidity check with hardcoded dataclass defaults
(`max_spread_pct=0.15`, `min_volume=10`, `min_open_interest=50`) — not
sourced from `Settings`/env, and explicitly documented in its own code
as "pre-filter only; RiskManager enforces the real limit at entry." Low
severity (the config-driven `RiskManager` check is strictly the final,
authoritative gate), but a genuine inconsistency between two threshold
sets that nothing keeps synchronized.

## 8. Risk engine audit

| Structure/check | Status |
|---|---|
| Single-leg long call | **COMPLETE** |
| Single-leg long put | **COMPLETE (structurally), UNVALIDATED (no live strategy emits puts)** |
| Short options | **MISSING from live path** — structurally impossible to hold (`OpenPosition`/`SetupCandidate` reject anything but long_call/long_put); real risk math for it exists only in disconnected research code (`src/options/position.py`) |
| Vertical spreads | **MISSING from live path** — same reason |
| Maximum loss | **PARTIAL** — for long options only, implicitly equals premium paid; never explicitly computed/labeled as such |
| Maximum position risk | **PARTIAL** — same flat $ cap, not a distinct concept |
| Portfolio exposure (sum across positions) | **MISSING** |
| Concentration limits | **MISSING from live path** — real fields exist in `src/options/research_risk_engine.py`'s `ResearchRiskLimits` but that module is imported by nothing else in `src/` |
| Affordability check | **MISSING from per-trade live path** — real logic exists (`src/execution/preflight.py`) but is only invoked by a manual, one-time script, never per-cycle |
| Buying power check | **PARTIAL** — same as above: real, tested, but not wired into the per-cycle loop |
| Open-positions tracking | **COMPLETE** |
| Correlated exposure | **MISSING** |
| Daily loss limit | **COMPLETE** — config-driven, resets daily |
| Total account drawdown (cumulative/multi-day) | **MISSING** — `RiskStateStore` resets to zero whenever the stored date isn't today |
| Emergency stop | **MISSING** — the `SystemState.EMERGENCY_STOP` design exists but is unwired (§10) |

`analyze_position_risk()` (`src/options/position.py`) actually supports
single-leg long/short call/put and 2-leg same-expiration vertical
spreads, returning `UNSUPPORTED_STRUCTURE` for anything else — but it is
never imported by `risk/manager.py` or `orchestrator.py`. This currently
matters less than it might, since the live system can only ever hold
long_call/long_put anyway — but it means if short/spread structures
were ever wired into the live order path, there is presently no live
risk check that would compute their max loss correctly.

## 9. Position sizing audit

The only live sizing code is `RiskManager.check_position_size()` — a
flat USD cap (`proposed_size_usd <= self.limits.max_position_size_usd`,
default $250), taking only a dollar amount as input
(`test_check_position_size_takes_only_a_flat_usd_amount` locks this in).

| Input | Real code exists? |
|---|---|
| Account equity | **MISSING** — no code reads live equity/net-liq to size a trade |
| Option premium | **COMPLETE**, but only as an input to the flat cap, not a formula |
| Defined maximum loss | **PARTIAL** — numerically equals premium cost for long options, but never explicitly labeled/asserted as such |
| Portfolio exposure | **MISSING** |
| Existing positions | **PARTIAL** — used for duplicate/cooldown checks and "no size increase after a loss" (last trade only), never to reduce sizing based on total capital already deployed |
| Strategy confidence score | **MISSING** — `SetupCandidate.score` is computed and logged but never read by the risk manager |
| Liquidity-aware sizing | **MISSING** — liquidity is a binary pass/fail gate, entirely separate from sizing |
| Concentration | **MISSING** |

No production sizing rule is invented here — this section identifies
infrastructure gaps only, per the prompt's explicit instruction.

## 10. Autonomous trading state machine audit

**The state machine does NOT enforce the intended progression today —
it is not wired into anything.**

`src/execution/system_state.py` implements exactly the required 7
states (`RESEARCH, PAPER_TRADING, PAPER_VALIDATED,
HUMAN_LIVE_AUTHORIZATION, LIVE_AUTONOMOUS_TRADING, LIVE_PAUSED,
EMERGENCY_STOP`), with no per-trade-approval state, correct
code-computable forward progress, human-only gates into
`HUMAN_LIVE_AUTHORIZATION`/`LIVE_AUTONOMOUS_TRADING`, autonomous
pause/resume, and an `EMERGENCY_STOP` reachable from any state
autonomously but clearable only by a fresh human act. The design itself
is sound and thoroughly tested in isolation (`tests/test_phase28_system_state.py`
and companions).

**But its own module docstring says plainly: "This module is DESIGN
ONLY... nothing here is wired into `settings.py`, `gateway.py`, or
`orchestrator.py`."** Confirmed independently this phase: zero imports
of `system_state` from `gateway.py`, `settings.py`, or `orchestrator.py`
(now a permanent regression test,
`test_system_state_not_imported_by_gateway_settings_or_orchestrator`).

**The actual live gate today** is three raw `Settings` fields
(`trading_mode`, `live_trading_confirmed`, `live_auto_execute`), checked
directly in `LiveExecutionGateway.__init__`/`confirm_and_place`/
`submit_order`. This gate has no transition history, no audit-logged
"who authorized this and when," and — critically — **no code-level
emergency stop**: the only "kill switch" that exists in practice is a
human manually editing `.env`.

This is not a hypothetical gap — §11 documents a real incident where the
absence of this wiring (and of order-lifecycle tracking) meant an
unsupervised live-authorized configuration ran for two weeks before a
human discovered and reset it.

## 11. Human authorization boundary audit

**Verified: once `live_auto_execute=True` and a `LiveOrderPlacer` is
available, no per-trade human-approval gate re-enters.**
`submit_order()` calls `_place_pending(..., approved_by="system:auto_execute")`
immediately; `_place_pending()` is a single, undifferentiated funnel
used by both the auto-execute path and the human-approved
`confirm_and_place()` path, and performs no additional per-order human
check of its own. `RiskManager`/`PositionEvaluator`'s deterministic
checks (already run before `submit_order()` is reached) are the only
gate — exactly as intended by §11 of the prompt.

`record_human_authorized_transition` (the one function that could
formalize this) correctly rejects any `authorized_by` starting with
`"system:"` — a code caller cannot spoof a human identity — but, per
§10, nothing calls it from the live path at all today.

### The documented real incident

Read directly from this deployment's own primary sources (`.env`,
`README.md`, git history) rather than accepted secondhand:

- **2026-08-17**: a human explicitly authorized "fully automatic real
  orders" (via `AskUserQuestion`, choosing that option over
  "keep it pending-approval") for real account `987155785`. `.env` was
  set to `TRADING_MODE=live`, `LIVE_TRADING_CONFIRMED=true`,
  `LIVE_AUTO_EXECUTE=true`, with conservative limits
  (`MAX_POSITION_SIZE_USD=97`, `MAX_DAILY_LOSS_USD=20`,
  `MAX_TRADES_PER_DAY=2`, $100 buying power). Per `README.md`'s "Going
  live" section, the human-click-approve step was removed
  *procedurally* (the recurring cron-tick's own prompt was changed to
  make the real `place_option_order` call and immediately confirm it,
  never stopping for a separate approval turn) — the Python code in
  `gateway.py` itself was not modified.
- A **separate, platform-level scheduled Routine** was created
  2026-08-14 with a prompt that pre-authorizes an agent session to call
  `mcp__HOOD__place_option_order` directly, hourly — entirely outside
  this codebase's `src/execution/gateway.py`, with no `Settings`, no
  `LiveExecutionGateway`, no `orchestrator.py` involved at all. This is
  the critical detail: **this codebase's Python safety architecture
  (the dual-switch gate, the pending-approval flow, the single
  `_place_pending` choke point) was never the thing standing between the
  account and a real order** — a scheduled agent session with tool
  access can call the MCP tool directly, and nothing in `src/`
  constrains that.
- That Routine ran, "unauthorized-by-this-conversation," for roughly two
  weeks with a documented "two-week gap in this session's own
  continuity." It was discovered and disabled on 2026-08-31.
- **No trade was ever filled** — verified by the operator directly
  against the real account's `get_option_orders`/`get_realized_pnl`
  (zero closing trades, ever). The account's buying power nonetheless
  fell from $100 to $0 over the period, and this discrepancy remains
  **unexplained** in the repository's own record.
- `.env` was reset to safe defaults on 2026-08-31
  (`TRADING_MODE=paper`, `LIVE_TRADING_CONFIRMED=false`,
  `LIVE_AUTO_EXECUTE=false` — confirmed as this phase's own current
  state, §20) and the Routine is currently disabled.

**A live, present-tense factual error was also found and should be
corrected**: `README.md`'s "Going live" section (lines 537–570) still
asserts, in the present tense, that live trading "is built, tested, and
active in this deployment's real `.env`" with human approval "explicitly
removed" — this is no longer true (current `.env` is paper/unconfirmed)
and nothing in the repository flags the drift. A future reader (human or
agent) trusting the README over the actual `.env` could believe
autonomous live trading is still sanctioned, or could be prompted to
recreate the same kind of Routine. Flagged here as a **HIGH** item in
§18; not edited by this audit-only phase.

**Conclusion for this section**: the code-level per-trade approval
mechanics work exactly as designed and were not the failure point. The
actual gap is (a) no system-level, code-enforced authorization/audit
layer governing *when* `live_auto_execute` may be turned on and *who*
is watching once it is, and (b) no code-level control preventing an
out-of-band scheduled Routine from bypassing this codebase's safety
architecture entirely by calling the MCP tool directly. Both remain
open. Neither is fixable from inside `src/` alone — (b) in particular is
a platform/trigger-permissioning concern, not a Python code concern.

## 12. Exit management audit

| Capability | Status |
|---|---|
| Profit-taking | **COMPLETE** — `PositionEvaluator`, live-wired |
| Stop loss | **COMPLETE** |
| Time-based exit | **COMPLETE** (trailing exit, `TRAILING_ARM_FRACTION`/`TRAILING_GIVEBACK_FRACTION`) |
| Expiration handling | **COMPLETE** — profitable vs. unprofitable branching near expiration |
| Contract becoming illiquid | **PARTIAL** — the same liquidity checks that gate entry are not separately re-applied as an exit trigger; an illiquid position is still evaluated for exit on price alone |
| Quote disappearing | **PARTIAL** — `MarketDataError` is caught and logged (non-fatal to the cycle), but there's no explicit "quote gone, force-exit" policy, only "skip evaluating this position this cycle" |
| Broker rejection (of an exit order) | **PARTIAL** — same as entry-order rejection handling (§9): pre-submission rejection is modeled, post-submission broker-side rejection is not observable (no order-status polling) |
| Underlying halt | **MISSING** — no halt-detection logic anywhere in `src/` |
| Market close | **COMPLETE** — `is_within_monitoring_window` gates the whole cycle |
| Expiration day | **COMPLETE** — covered by expiration handling above |
| Assignment/exercise risk | **NOT_APPLICABLE** — short options are not held by this system (structurally impossible today) |

Exit logic is genuinely real, tested, and live-wired for both paper and
real positions — no strategy-specific exit parameter was invented here;
this section identifies architectural capability only, as instructed.

## 13. Market hours / operational safety audit

| Item | Status |
|---|---|
| Market open/closed, premarket/after-hours | **COMPLETE** — weekday + time-window gate |
| Holidays | **MISSING** — no holiday calendar anywhere in `src/`, self-documented as a known gap in `src/options/quality.py` |
| Trading halts | **MISSING** — no halt-detection logic |
| Stale market data | **COMPLETE** — `check_data_freshness`, config-driven |
| Missing option quotes | **COMPLETE** — fails closed (`check_liquidity` treats `None` volume/OI as a hard fail, never assumes liquid) |
| Robinhood API outage | **PARTIAL** — `MarketDataError` is caught and logged per-position, but there's no cycle-level "the whole provider is down" detection/alert |
| System restart/process crash | **PARTIAL** — every store fails closed on corruption (a good, consistent convention) and persists across restarts, but see below |
| Restart/recovery duplicate-order risk | **A real, unmitigated gap** — if the process crashes between a real `place_option_order` call succeeding and `_place_pending()` finishing its own bookkeeping, the pending order is left at `"awaiting_approval"` even though a real order was submitted; a subsequent `confirm_and_place()` call against that same pending order would place a **second, duplicate real order**, since nothing checks the broker for an existing order first. Additionally, a **pending (awaiting-approval) order is invisible to `check_duplicate_position`**, which only sees filled positions — two overlapping cycles could each propose a pending order for the same symbol before either is decided (now locked in as a documented gap by `test_check_duplicate_position_has_no_pending_order_parameter`). |

## 14. Observability audit

| Record | Wired into a real cycle? |
|---|---|
| Structured decision/audit log (`decision_logger.py`) | **Yes** |
| App/diagnostic log | **Yes** (mirrors the decision log) |
| Trade journal (closed trades) | **Yes** |
| Risk-decision/rejection-reason record | **Yes** — every check's pass/fail reason flows into the decision log |
| Execution-result record | **Yes** |
| Position-state record | **Yes** |
| Exit-decision record | **Yes** |
| Account-state/pre-trade eligibility record | **NO** — `preflight.py` is real and tested but never called from the live cycle |
| System-state-transition record | **NO** — `SystemStateAuditLog` is real but unwired (§10) |
| Opportunity-ranking record | **Partial** — only the winning candidate's fate is traceable; ranked-but-not-chosen candidates aren't individually logged with scores |

A human could mostly reconstruct why a past (actually-run) trade
happened and why it exited, by cross-referencing the decision log and
trade journal by symbol/timestamp — there is no single joined record,
and account eligibility / system-authorization state at the time is not
captured at all. **Concretely observed in this environment**: no
`logs/decisions.jsonl` exists, and `logs/trade_journal.jsonl` holds
exactly one entry that reads as synthetic test-fixture data
(`option_id: "opt-losing"`) — meaning no real trading cycle has left a
reconstructable trail here, and the §11 incident's own claimed
verification (against `get_option_orders`/`get_realized_pnl`) cannot
itself be independently verified from anything persisted in this
repository or environment.

## 15. Configuration safety audit

- **Single shared `Settings` object**, no separate research/production
  profile — but research code uses its own, entirely separate
  `ORATSConfig` (never touching `Settings`), so the one place production
  config lives is not accidentally reachable from research code.
- **Defaults are safe**: `trading_mode="paper"`,
  `live_trading_confirmed=False`, `live_auto_execute=False`, no
  hardcoded account number. `.env` is git-untracked (`.gitignore`), so a
  fresh clone can never inherit an unsafe configuration.
- **No environment-variable alias or typo-tolerant bypass** of either
  live-mode switch was found — `_get_bool` only recognizes an explicit
  allow-list of truthy strings.
- **The code-level guard was never actually breached** — what happened
  (§11) was a deliberate-at-the-time human configuration change plus an
  out-of-band Routine that didn't need the Python `Settings` object at
  all. The guard correctly does what it was designed to do; it was
  simply not the whole safety boundary.
- Current, live-verified `.env` values (this phase's own check, §20):
  `TRADING_MODE=paper`, `LIVE_TRADING_CONFIRMED=false`,
  `LIVE_AUTO_EXECUTE=false` — confirmed safe as of this report.

## 16. Test coverage audit

288 test files, 2,661 tests collected (2,657 pass + the same 4
pre-existing baseline failures, now including this phase's 11 new
tests). Live-path-relevant coverage:

| Category | Status |
|---|---|
| Unit — `gateway.py` | **Strong** — idempotency, fail-closed corruption handling, double-decision refusal, expiry, auto-execute path, paper-by-default guarantee |
| Unit — `risk/manager.py` | **Strong** — one test per check, 1:1 with the 11 documented checks |
| Unit — `position_manager/*` | **Strong** |
| Integration — `test_orchestrator.py` | **Weakened** — 9/13 pass; 4 fail on stale hardcoded fixture timestamps (the known baseline failures), meaning the full entry flow, full exit flow, and audit-log-completeness tests currently cannot verify in CI. **Zero tests exercise live mode** (`is_live`/`LiveExecutionGateway`) through the orchestrator — all orchestrator-level integration testing is paper-mode only. |
| Failure-mode (malformed/degraded responses) | **Strong** — `test_hood_provider.py` |
| Authorization/state-machine | **Tests exist but test unused infrastructure** — `system_state.py`'s tests are thorough but exercise design-only, unwired code; the actually-wired gate (`is_live`/`live_trading_confirmed`) is tested separately and adequately |
| Execution (submission, idempotency) | **Strong** |
| Options-only enforcement | **Strong, unusually rigorous** — source-scanning tests, not just behavioral |
| Risk (sizing, exposure) | **Strong** for what exists; no tests for what's missing (portfolio exposure, concentration — because no code exists to test) |
| Restart/recovery | **Gap** — no test simulates crash+restart and asserts no duplicate order results |
| Duplicate-order protection | **Gap for the pending-order case** — filled-position duplicates are well-tested; a duplicate *pending* proposal across cycles is untested (now documented, not fixed, by this phase's regression test) |
| Stale-data | **Strong** |
| Broker-error | **Strong** for pre-submission; no coverage for post-submission (because no polling code exists to test) |
| Emergency-stop | **Tests exist but test unused infrastructure**, same caveat as authorization above |

**Critical missing tests identified**: crash+restart duplicate-order
simulation; an orchestrator-level live-mode integration test; a test
that would fail the moment order-status polling is added without a
corresponding fill-reconciliation test. None of these were added this
phase (Phase 34 is audit-only) — they are listed in §18 as required
future work, not fabricated here.

## 17. Strategy data contract

Live and research feature computation are architecturally separate —
`MomentumBreakoutStrategy` imports only `src.market.indicators`/
`src.strategy.evidence`, never `src.features.*`.

| Feature/field | Source | Live | Historical/research | Causal | Missing-data behavior |
|---|---|---|---|---|---|
| RSI, MACD, EMA, higher/lower highs, breakout signals | `src.market.indicators`, live equity bars | **LIVE_AVAILABLE** | N/A (live-strategy-only computation) | Yes (uses only bars up to now) | `None`/`False` defaults, never fabricated positive signals |
| bid/ask (option) | `get_option_quotes` | **LIVE_AVAILABLE** | **UNAVAILABLE** (confirmed, any contract, any date) | N/A (point-in-time) | Fails closed — invalid/crossed quote rejects outright |
| volume, open interest (option) | `get_option_quotes` | **LIVE_AVAILABLE** | **UNAVAILABLE** (confirmed) | N/A | Fails closed — `None` is treated as "insufficient liquidity," never assumed 0/liquid |
| IV, Greeks | Present in raw live payload | **LIVE_AVAILABLE (unparsed)** | **UNAVAILABLE** | N/A | Not currently modeled anywhere in the live path — no risk of a live/backtest mismatch because nothing consumes them yet |
| Equity OHLC + volume (underlying) | `src.data.bar.Bar` | **BOTH** | **BOTH** | Yes, structurally enforced (`test_feature_no_lookahead.py`, 24/24 pass) | Feature-specific `lookback`-gated `None`, never a fabricated early value |

**No feature currently mixes a live-only and a historical-only field** —
the two systems don't share code, and the live side fails closed on
missing bid/ask/volume/OI rather than fabricating. This separation is a
genuine strength this project should preserve when a future strategy is
eventually built: any strategy candidate must be checked against this
exact table before its features are trusted to behave identically in
backtest and production.

## 18. Production readiness checklist

| Severity | Issue | Location | Reason | Required action | Blocks live trading? |
|---|---|---|---|---|---|
| **BLOCKER** | No validated options strategy exists | project-wide | Every hypothesis tested (30 total across Phase 31/32/33) failed to reach `DISCOVERY_SUPPORTED`/`PROMISING` and pass the gate | Do not authorize live trading until one exists; do not fabricate one | **Yes** |
| **BLOCKER** | System-state authorization machine is unwired | `src/execution/system_state.py` | No code-level record of who/when/why live trading was authorized; no code-level emergency stop | Wire `SystemState` into `settings.py`/`gateway.py`/`orchestrator.py` before any future live authorization | **Yes** |
| **BLOCKER** | No order-lifecycle tracking after submission | `src/execution/gateway.py`, no order-monitor module | `get_option_orders` is never called; no fill/partial-fill/broker-rejection/cancellation visibility once an order is placed | Build a post-submission order-status poller and reconcile fills before authorizing unattended live trading | **Yes** |
| **BLOCKER** | An out-of-band scheduled Routine can call `place_option_order` directly, bypassing all of `src/`'s safety architecture | platform/trigger layer, outside this codebase | Directly demonstrated by the documented 2026-08-14 to 2026-08-31 incident | Any future live authorization must also cover platform-level trigger/connector permissioning, not just this codebase's `gateway.py` | **Yes** |
| **HIGH** | `README.md`'s "Going live" section is stale and factually wrong | `README.md:537-570` | Still asserts live trading is "active" in the present tense; current `.env` is reset to paper/unconfirmed | Update to reflect current state and the 2026-08-31 reset before it misleads a future reader into recreating the incident | No (documentation only) |
| **HIGH** | Duplicate real order possible on crash-then-resume | `src/execution/gateway.py::confirm_and_place` | No check against the broker for an already-placed order before a retry/resume | Add a broker-side existing-order check before `confirm_and_place` proceeds | **Yes, for live mode** |
| **HIGH** | Pending (unapproved) orders invisible to duplicate-position check | `src/risk/manager.py::check_duplicate_position` | Only checks filled `open_positions`, never `PendingOrderStore` | Feed pending orders into the duplicate check, or gate scanning on outstanding pendings | **Yes, for live mode** |
| **HIGH** | `MomentumBreakoutStrategy` was never statistically validated | `src/strategy/momentum_breakout.py` | It is the only live-wired strategy, yet went through none of this project's own validation rigor | Decide explicitly (human decision) whether it should ever be allowed to trade real money, and under what governance — do not let it reach live status by default/omission | **Yes, for live mode** (currently paper-only by config default) |
| **MEDIUM** | Preflight (account eligibility/buying power) never runs per-cycle | `src/execution/preflight.py` | Real, tested code exists but only as a manual, one-time script | Wire into the live cycle before any live authorization, or explicitly document it as a pre-authorization-only, one-time gate | Contributes to BLOCKER above |
| **MEDIUM** | No portfolio exposure / concentration / correlated-exposure limits | `src/risk/manager.py` | Real fields exist in disconnected research code (`research_risk_engine.py`) | Wire equivalent limits into the live `RiskManager` before scaling beyond a single small position | Contributes to BLOCKER above |
| **MEDIUM** | No cumulative/multi-day drawdown limit | `src/risk/store.py` | State resets to zero every day; only same-day loss is checked | Add a persisted, rolling drawdown check | Contributes to BLOCKER above |
| **MEDIUM** | Position sizing is a flat cap only | `src/risk/manager.py::check_position_size` | No equity/confidence/liquidity/concentration-aware sizing | Build sizing infrastructure (not sizing rules) capable of enforcing these inputs once a strategy exists | Contributes to BLOCKER above |
| **MEDIUM** | No holiday calendar | project-wide | Self-documented gap in `src/options/quality.py` | Add a holiday calendar to market-hours gating | Contributes to operational-safety readiness |
| **LOW** | `assert_options_only()` is unwired dead code | `src/execution/asset_class_restriction.py` | The real protection is structural (no equity field exists to populate); this named guard adds no additional live protection today | Wire it into `gateway.py` as defense-in-depth, or accept the structural guarantee as sufficient | No |
| **LOW** | Two independent, non-synchronized liquidity threshold sets | `momentum_breakout.py` (hardcoded) vs. `RiskManager` (config-driven) | `RiskManager`'s is the authoritative final gate; the strategy pre-filter is looser and hardcoded | Source the strategy pre-filter from `Settings` too, for consistency | No |
| **LOW** | Trade journal and decision log are two separate files, not joined | `src/logging/` | Full reconstruction requires cross-referencing by symbol/timestamp | Add a shared trade/cycle ID across both logs | No |

## 19. No strategy fabrication

No moving-average, RSI, MACD, momentum, P22-OPT-013, underlying-stock,
or arbitrary options strategy was chosen this phase. No demo strategy
was created or labeled production. No null research result was
optimized into a strategy. `MomentumBreakoutStrategy`
(`src/strategy/momentum_breakout.py`) is pre-existing, unmodified code
from before this project's options-alpha research track began — its
existence and live-wiring is reported accurately in §2/§3/§18, never
presented as this phase's own choice or as validated. The system remains
strategy-less in the sense that matters: no statistically validated
options strategy exists, and none was manufactured to fill that gap.

## 20. Safety verification

Programmatically confirmed before this report was finalized:

- **No live order submitted**: no execution-layer file was modified
  this phase (`git diff --stat` against the pre-Phase-34 commit shows
  zero changes under `src/execution/` or `src/orchestrator.py`).
- **No paper order submitted**: same — `src/strategy/` unmodified.
- **No strategy deployed**: `test_exactly_one_concrete_strategy_class_exists_today`
  confirms the only concrete `Strategy` subclass is the pre-existing
  `MomentumBreakoutStrategy`; nothing new was added.
- **No paid provider activated**:
  `ORATSActivationState.CURRENT_STATE == ORATS_ACTIVATION_PENDING_HUMAN`,
  re-verified directly this phase.
- **No paid data purchased**: unchanged since Phase 28.
- **No live autonomous trading enabled**: current `.env`/`Settings`
  confirmed this phase — `trading_mode="paper"`,
  `live_trading_confirmed=False`, `live_auto_execute=False`.
- **No broker configuration changed**: `.env.example`/`src/config/`
  unmodified this phase (`git diff --stat` shows zero changes).

**Full test suite**: 2,661 collected — **2,657 passed**, the same **4**
pre-existing baseline failures in `tests/test_orchestrator.py`
(`test_full_cycle_finds_setup_and_opens_a_paper_position`,
`test_entries_still_allowed_before_local_cutoff_even_when_utc_clock_is_later`,
`test_existing_paper_position_stop_exits_and_is_removed_from_ledger`,
`test_everything_gets_logged`) — confirmed this phase to be caused by
hardcoded fixture timestamps now stale relative to the real current
date, tripping the staleness guard exactly as designed (not a
regression, not touched by this phase, preserved separately per every
prior phase's convention). 11 new tests added this phase, all passing.

## 21. Final conclusion and recommended next phase

**A. Does a validated options strategy exist?** **No.**
`NO VALIDATED OPTIONS STRATEGY EXISTS` — confirmed by direct inspection
of every candidate in the repository (§3).

**B. Is the system technically capable of autonomous execution?**
**Partially, and with real, documented gaps.** The core mechanism
(scan → risk-gate → pending order → auto-execute, with no per-trade
approval) is real and already exercised once in production (§11). But
"technically capable" is undermined by: no order-lifecycle tracking
after submission, no system-level authorization/audit layer, no
code-level emergency stop, a real crash-duplicate-order risk, and — most
fundamentally — no protection against an out-of-band Routine bypassing
this codebase's execution path entirely.

**C. Is the system authorized to trade live?** **No.** Current
configuration (verified this phase) is `TRADING_MODE=paper`,
`LIVE_TRADING_CONFIRMED=false`, `LIVE_AUTO_EXECUTE=false`. Nothing in
this phase changed that, and this report does not recommend changing it.

**D. What exact blockers remain before live authorization?** Four
BLOCKER-severity items (§18): no validated strategy; the unwired
system-state authorization machine; no post-submission order-lifecycle
tracking; and no platform-level control over out-of-band Routine access
to `place_option_order`. Several HIGH-severity items compound these
(stale README, crash-duplicate-order risk, invisible pending-order
duplicates, an unvalidated default strategy).

**E. Is additional historical options data currently required?** Not
for this phase's purpose (an architecture audit). For a future
discovery campaign, see F — but note separately that better historical
options data would not address any of this report's BLOCKER items,
which are execution/authorization architecture gaps, not data gaps.

**F. Is another alpha-discovery campaign justified on the current free
dataset?** **No.** Phase 31 (16 hypotheses), Phase 32 (14 hypotheses),
and Phase 33's replication all independently converged on the same
binding constraint: too few real underlyings with daily-resolution
options coverage in the free dataset to populate cross-sectional peer
groups, at either the contract or bucket level. Repeating that campaign
a fourth time on the same data would not resolve a data-density problem
already diagnosed three times. This is unchanged by anything found in
this phase's architecture audit.

### Recommended next phase

Not a strategy-development phase, and not another discovery campaign.
The two legitimate, independent next steps are: (1) an
**architecture-hardening phase** addressing the BLOCKER/HIGH items in
§18 that are fixable from inside this codebase (order-lifecycle
tracking, wiring `SystemState`, crash-duplicate-order protection,
pending-order duplicate visibility, the stale README) — none of which
requires or implies a strategy exists yet; and (2) a **human decision**,
outside any code change, on whether `MomentumBreakoutStrategy`'s
continued live-wired (if currently paper-mode) presence is acceptable
governance, or whether it should be explicitly gated/disabled pending
its own validation. Per this phase's own instruction: **STOP after
Phase 34. Do not begin Phase 35 automatically.**
