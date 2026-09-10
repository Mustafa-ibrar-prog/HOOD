# Phase 42 — Investigation: Can Robinhood Data Acquisition Be Made Genuinely Automatic?

**Short answer: no.** Direct, headless invocation of the Robinhood Trading
MCP tools from the running Python paper-trading process is not possible
in this environment, and no other genuinely automatic (agent-turn-free)
mechanism exists either. This document is the evidence for that
conclusion, and what — bounded and honestly caveated — IS available.

## What was checked

### 1. Can Python call an MCP tool directly?

No, unchanged since Phase 39. `src/market/hood_client.py` and
`src/live_bridge.py` have documented this since Phase 39: the HOOD MCP
server's tools are only reachable through the orchestrating AGENT's own
tool-call interface (the mechanism this conversation itself uses) — there
is no Python client library, SDK call, or socket this process can use to
reach the same tools. This investigation did not find anything that
changes that.

### 2. Can a subprocess `claude -p "..."` invocation reach the HOOD MCP server?

Checked directly:

```
$ claude mcp list
No MCP servers configured. Use `claude mcp add` to add a server.
```

The `claude` CLI binary is present in this container
(`/opt/node22/bin/claude`), but it has **zero MCP servers registered** at
the standard local config layer (no `.mcp.json` in the repo, no
project/user MCP config). The HOOD, GitHub, and `claude-code-remote` MCP
servers available to THIS conversation are provisioned by the hosting
harness specifically for this interactive agent session — they are not
exposed through the generic `claude mcp add`/`.mcp.json` mechanism a
locally spawned subprocess could pick up. A `subprocess.run(["claude",
"-p", "fetch AAPL quotes"])` launched from the paper-trading process
would start a real Claude Code session with **no Robinhood tool access at
all** — it could not fetch real data, and building against it would
either silently fail or (worse) invite someone to "fix" it by fabricating
a fake MCP client, which Phase 42's instructions explicitly forbid.
**Rejected — not a supported mechanism, confirmed empirically.**

### 3. `CronCreate` (this session's own scheduling tool)

A real, available mechanism — but for a narrower purpose than "automatic
data acquisition": it re-enqueues a **prompt into this same session**
when the REPL is next idle. Concretely:

- **Session-only**: the job lives only in this session's memory. Nothing
  is written to disk; it is gone the moment this session ends.
- **≤ 7 days**: recurring jobs auto-expire after 7 days (fires once more,
  then deleted) — shorter than the 14-day minimum experiment duration.
- **Best-effort timing**: fires "up to 10% of [the] period late (max 15
  min)" and only while the REPL is idle, never mid-turn.
- Firing wakes **this exact session/container**, so it DOES share this
  container's filesystem (the running scheduler, the inbox) — no
  cross-process transport problem.

This is a genuine way to automate *when* an agent turn happens, but the
agent turn itself still has to run the real Process A steps (fetch, save,
mark-ready) — it does not eliminate agent-mediation, only its manual
"RUN" trigger. **Available, real, but bounded — offered as an option
below, not silently wired in as infrastructure (it is a live,
session-affecting scheduling action, not a code change).**

### 4. `mcp__Claude_Code_Remote__create_trigger` (an account-level "Routine")

More durable than `CronCreate` (an account-level object, not just
in-session state), with two relevant modes:

- **Self-bind (default) mode** — fires into *this same session*. Same
  filesystem-sharing property as `CronCreate` above, but its own tool
  description states: *"Minimum interval is normally hourly (some
  projects allow shorter); a too-frequent schedule is rejected."* An
  hourly minimum directly conflicts with the required 15-minute cadence
  for every cycle — it could backfill data once an hour at best, leaving
  the three 15-minute slots in between honestly `DATA_COLLECTION_FAILED`
  (never fabricated — but not "automatic at every cadence slot" either).
- **`create_new_session_on_fire=true` mode** — spawns a **fresh session**
  on each firing. This was checked concretely: `list_environments`
  reports this project's environment as `kind: "anthropic_cloud"`, and
  this session's own system context states the standard model for that
  kind explicitly: *"the repository was cloned fresh when the container
  started, and the container is reclaimed after a period of
  inactivity."* A freshly spawned session is a **new, independent
  container cloned fresh from GitHub** — it does not share this
  container's local disk. It would not see the running scheduler
  process, the experiment's `logs/paper_experiments/` state (gitignored,
  never committed — confirmed by `tests/test_phase40_safety.py::
  test_logs_paper_experiments_directory_is_gitignored`, unchanged), or
  the inbox directory the scheduler polls. Making this mode work would
  require inventing a NEW cross-session durable transport (e.g.
  repurposing the Artifact database as a cross-container message bus for
  live financial market data) — a materially larger, riskier change than
  "the smallest safe adapter," and not something this investigation
  found any existing, purpose-built support for. **Rejected for this use
  case.**

## Conclusion

No mechanism available in this environment lets the Python paper-trading
process (or any headless process it could launch) invoke the Robinhood
MCP tools itself. The two session-scheduling tools that exist
(`CronCreate`, `create_trigger` self-bind mode) can automate *when* an
agent is re-invoked to do the fetch, within real bounds (session
lifetime, ≤ 7 days or hourly-minimum, best-effort timing) — they do not
make data acquisition itself independent of an agent turn. This is the
same architectural fact `src/live_bridge.py` has documented since Phase
39, reconfirmed here with concrete, current evidence rather than
re-asserted from memory.

## What Phase 42 builds instead

Per the instruction not to fake automation, Phase 42 hardens the
honestly-still-agent-mediated "Process A" role instead of pretending it
can be eliminated:

- `src/paper_trading/acquisition_planning.py` — `compute_cycle_identity`
  (the exact slot id + inbox directory the agent must write to, reusing
  Phase 41's `market_calendar` unmodified) and `compute_symbol_strike_
  tasks` (per-symbol target strikes once real prices are known).
- `src/paper_trading/near_the_money.py` — `compute_target_strikes`: a
  deterministic, bounded set of exact strikes to query directly via
  `get_option_instruments(..., strike_price=<value>)`, centered on the
  real fetched price and covering the same moneyness band
  `ContractSelectionBounds` will later filter to. This is the formalized,
  tested version of the exact-strike-filter technique already used
  successfully, ad hoc, in Phase 41's real cycle 3 and the real automatic
  cycle (`2026-09-10-slot0024`, symbol GOOGL) — see "Option instrument
  pagination" below.
- `scripts/prepare_acquisition_plan.py` — a CLI so an agent doing Process
  A never hand-computes a slot id or eyeballs strikes.
- `src/paper_trading/data_acquisition.py::mark_inbox_slot_ready` — now
  writes the `READY` sentinel atomically (temp file + `os.replace`, same
  directory) instead of a direct `write_text`, so a concurrently polling
  scheduler can never observe a partially-written sentinel.

None of this makes data acquisition itself automatic. It makes the
still-required agent step (whether triggered by an explicit "RUN", or by
a `CronCreate`/Routine wake-up the user opts into) fast, deterministic,
and hard to get wrong — the honest ceiling given what this environment
actually supports.

## Option instrument pagination

`src/market/hood_provider.py::HoodMarketDataProvider._fetch_all_
instruments` already implements real, bounded cursor pagination
(`_MAX_INSTRUMENT_PAGES = 25`, unmodified by this phase — see
`tests/test_hood_provider.py`) for when a broad, unfiltered chain scan is
genuinely wanted, and `src/live_bridge.py::merge_option_instrument_pages`
(Phase 39, unmodified — see `tests/test_phase39_operational_glue.py`)
already handles merging multiple real agent-fetched pages into one
recordable file (required because `StaticHoodClient.get_option_
instruments` keys a recording by `chain_id` alone, so an un-merged
multi-page recording would replay only the first page).

Phase 42 does not change either of these — they were already correct and
already tested. What Phase 42 adds is the alternative that avoids
pagination's actual failure mode entirely (Phase 41 cycle 2's real,
observed problem: a broad, un-filtered page starting from the chain's
lowest strike sometimes never reaches a high-priced underlying's current
price at all, even after several pages): `compute_target_strikes` lets
Process A ask for exact strikes directly, bounded (`max_strikes`,
default 6), always centered on the real current price — so "does this
page reach the current price" stops being a question at all.
