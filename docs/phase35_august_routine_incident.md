# The August 2026 Out-of-Band Routine Incident

Phase 35, Part Q. A historical security/operational event, documented
here as a standing reference so a future phase never has to
re-investigate what happened, why the code-level safety architecture
did not prevent it, and what has (and has not) changed since. No
credential, token, API key, or account secret is reproduced anywhere in
this document — every value below is either a non-secret configuration
field or a figure the operator independently verified against the real
account.

This document does not modify any code; it is a factual record, drawn
from the same primary sources Phase 34's readiness audit already read
directly (`.env`'s git history, `README.md`, this repository's own
commit/session history) plus this phase's own re-verification that the
underlying facts have not changed.

## 1. Timeline

| Date | Event |
|---|---|
| 2026-08-14 | A separate, platform-level scheduled Routine was created with a prompt that pre-authorizes an agent session to call `mcp__HOOD__place_option_order` directly, on an hourly schedule. |
| 2026-08-17 | A human explicitly authorized "fully automatic real orders" for real account `987155785` (via an `AskUserQuestion` choice, in a *different* conversation than the one that created the Routine). `.env` was set to `TRADING_MODE=live`, `LIVE_TRADING_CONFIRMED=true`, `LIVE_AUTO_EXECUTE=true`, with conservative limits (`MAX_POSITION_SIZE_USD=97`, `MAX_DAILY_LOSS_USD=20`, `MAX_TRADES_PER_DAY=2`, ~$100 buying power). |
| 2026-08-14 → 2026-08-31 | The Routine ran, unsupervised by either conversation, for roughly two weeks. |
| 2026-08-31 | The Routine was discovered and disabled. `.env` was reset to safe defaults (`TRADING_MODE=paper`, `LIVE_TRADING_CONFIRMED=false`, `LIVE_AUTO_EXECUTE=false`). |

## 2. Mechanism — why this codebase's safety architecture was never the thing standing in the way

This is the load-bearing fact of the whole incident, and the reason
Phase 35's Parts N-P exist:

**The Routine never went through `src/`.** It called
`mcp__HOOD__place_option_order` directly from a scheduled agent-session
prompt, entirely outside `src/execution/gateway.py`. There was no
`Settings` object involved, no `LiveExecutionGateway`, no
`PendingOrderStore`, no `orchestrator.py` call — none of it. The
dual-switch gate (`TRADING_MODE`/`LIVE_TRADING_CONFIRMED`), the
pending-approval flow, and the single `_place_pending()` choke point all
worked exactly as designed for the code path they actually govern; they
were simply never the boundary an out-of-band scheduled Routine with
direct tool access has to cross. A platform-level Routine with
`place_option_order` in its own prompt can call it whether
`src/execution/gateway.py` exists, is imported, or is even installed.

Separately, and on a longer fuse: on 2026-08-17 a human also
procedurally removed the human-click-approve step from a *different*,
in-repo recurring cycle — by changing that cycle's own operating prompt
so the agent immediately confirmed a real `place_option_order` result
rather than pausing for a separate turn. The Python code in
`gateway.py` was not modified for this — `live_auto_execute=True`
already existed and behaved as documented (see that module's docstring).
This second change is not the root cause of the incident (the
`get_option_orders`/`get_realized_pnl` finding below shows no order from
either path was ever filled), but it is a second, independent way this
codebase's per-trade approval mechanic can be bypassed *procedurally*
without a single line of Python changing — worth naming plainly rather
than treating the Routine as the only lesson.

## 3. Observed outcome

- **No trade was ever filled.** Verified by the operator directly
  against the real account's `get_option_orders` and `get_realized_pnl`
  — zero closing trades, ever, across the entire window.
- The account's buying power nonetheless fell from ~$100 to $0 over the
  period. This discrepancy is **unexplained** and remains unexplained as
  of this phase — nothing in this repository's own logs (`decision_log`,
  `trade_journal`) can account for it, because (as Phase 34 §14 found)
  no real trading cycle through `src/` ever left a reconstructable trail
  matching the incident window; the Routine's activity, by construction,
  never touched any of this codebase's own logging either.
- `.env` was reset to safe defaults on 2026-08-31 and the Routine was
  disabled. Both remain true as of this phase (re-verified: current
  `.env`-equivalent defaults are `TRADING_MODE=paper`,
  `LIVE_TRADING_CONFIRMED=false`, `LIVE_AUTO_EXECUTE=false` — see this
  phase's own safety verification, §Q below and `test_phase35_safety.py`).

## 4. Current remediation (as of Phase 35)

Phase 35's Parts N-P add three new, code-level guards to
`LiveExecutionGateway._place_pending()` — the single method in this
entire codebase that calls `place_option_order` (a fact re-verified this
phase by `test_place_option_order_is_called_from_exactly_one_place_in_all_of_src`,
Phase 18's original invariant, still holding):

1. **`assert_options_only(order)`** (Part N) — now actually called, not
   merely defined.
2. **A real, code-level emergency stop** (`src/execution/emergency_stop.py`,
   Part P) — file-backed, defaults to STOPPED, survives process
   restart, requires no authorization to trip and a real human identity
   to clear.
3. **A wired system-authorization gate** (`src/execution/system_state.py`'s
   `is_live_trading_authorized`, Part O) — real placement now requires
   the persisted system state to be exactly `LIVE_AUTONOMOUS_TRADING`,
   reached only through an explicit, auditable, human-authorized
   transition chain.

**What this remediation does and does not cover, stated plainly:**
these three guards hardened `src/`'s own gateway — a *real*
improvement, and now independently tested (`tests/test_phase35_execution_boundary.py`)
to show none of them can be bypassed by `live_auto_execute=True`, by
strategy code, or by omitting the stores at construction time (a
missing store is treated as the blocked answer, never a permissive
default). **They do not, and structurally cannot, prevent a repeat of
this incident's actual mechanism** — a platform-level scheduled Routine
that calls `mcp__HOOD__place_option_order` directly still bypasses all
three, exactly as it bypassed the original dual-switch gate, because
none of this lives inside a Python call stack the Routine ever enters.
That remains a platform/trigger-permissioning concern, outside `src/`,
consistent with Phase 34's own conclusion on this point.

## 5. Prevention controls — what should exist going forward

Code-level (in scope for this repository, and now real, per Part N-P):

- The three guards above, on every real order.
- `README.md`'s stale "Going live" section (flagged **HIGH** by Phase
  34 §18, asserting in the present tense that live trading is "active")
  should be corrected before a future reader mistakes it for current
  state and recreates the conditions for a repeat. Not edited by this
  document (Phase 35 is a validation/hardening phase, not a
  documentation-correction phase for that specific file) — flagged here
  again as an open item for a future phase.

Platform-level (outside `src/`, a process/operational control rather
than a code control):

- Any scheduled Routine or trigger with `place_option_order` (or any
  other order-placement tool) named in its own prompt should require the
  same explicit, auditable human-authorization step this repository now
  has for its own gateway — a Routine is, in effect, a second execution
  path, and Phase 35's own system-state machine has no way to see or
  gate it.
- Periodic review of active scheduled Routines/triggers against real
  account activity (`get_option_orders`, `get_realized_pnl`,
  `get_portfolio`) — the two-week detection gap here was entirely a
  monitoring gap, not a code gap.
