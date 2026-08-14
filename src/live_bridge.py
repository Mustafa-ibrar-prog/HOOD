"""The manual live-data bridge: how a real trading cycle actually runs.

Read this before assuming there's a headless, code-only path to live
automation — there isn't, and this module is the honest documentation of
why, plus the supporting code that makes running a cycle by hand fast and
low-error.

Nothing in this codebase can call a HOOD MCP tool from Python — only the
orchestrating agent's own tool-call interface can (see hood_client.py's
module docstring, repeated everywhere this matters). HoodMarketDataProvider
decides WHICH tool to call and WITH WHAT ARGUMENTS as it runs — it might
call get_option_chain_candidates for one symbol and not another, depending
on what get_underlying_snapshot returned for the first one. That means the
calls can't be fully pre-planned and pre-fetched in a batch; the agent has
to drive the cycle step by step, supplying each response as
HoodMarketDataProvider asks for it.

StaticHoodClient is the seam that makes this practical: instead of a live
network client, it's populated with real tool-call responses the agent
just fetched, keyed by the same identifiers HoodMarketDataProvider uses
internally (symbol, option_id, chain_id) rather than by exact call
signature — so the agent can record "here's the get_equity_quotes response
for AAPL" without having to replicate get_equity_quotes' internal
start_time/end_time string formatting.

THE MANUAL RUNBOOK (what the agent does at each ~5-minute wake, during
market hours):
  1. get_option_positions(account_number, nonzero=true) -> record it.
  2. If any long positions came back, get_option_instruments(ids="...")
     for their option_ids (batched) -> record it.
  3. For each symbol in Settings.scan_universe AND each symbol of any
     currently-open paper position: get_equity_quotes([symbol]) and
     get_equity_historicals([symbol], start_time=..., interval="5minute")
     -> record both.
  4. For each open position (paper or synced real): get_option_quotes
     ([option_id]) and get_option_historicals([option_id], ...) -> record
     both.
  5. For each underlying that looks like a bullish breakout (the agent can
     eyeball this from step 3's data, or just proceed and let the strategy
     decide): get_option_chains(underlying_symbol=symbol) -> record it;
     then get_option_expirations-equivalent filtering, then
     get_option_instruments(chain_id=..., expiration_dates=..., type=
     "call", ...) for the chosen expiration -> record it; then
     get_option_quotes for the chosen contract -> record it.
  6. Build a StaticHoodClient from everything recorded, wrap it in a
     HoodMarketDataProvider, and call
     src.orchestrator.run_trading_cycle(settings=..., market_data=...,
     hood_client=..., now=<real current time>).
  7. Report the CycleReport. Never call place_option_order /
     review_option_order / cancel_option_order at any point — TRADING_MODE
     stays paper throughout, and the execution gateway refuses anyway.

This is real automation in the sense that matters: every decision is
computed by the same tested Python logic (evaluator, risk manager,
strategy, orchestrator) against real, live, just-fetched market data — it
is not a code-level fake, and it never touches order placement. It is
agent-mediated rather than a headless daemon, because that is what this
platform's architecture allows; pretending otherwise would be the "fake
scheduler" this project was explicitly told not to build.
"""

from __future__ import annotations

from typing import Any


class StaticHoodClient:
    """A HoodToolClient built from real responses recorded during one
    manual live cycle (see module docstring). Raises KeyError with a clear
    message — not a fabricated empty response — when asked for something
    that wasn't recorded, so a caller can tell "no data" apart from
    "nobody fetched it yet"."""

    def __init__(self) -> None:
        self._equity_quotes: dict[str, dict[str, Any]] = {}
        self._equity_historicals: dict[str, dict[str, Any]] = {}
        self._option_quotes: dict[str, dict[str, Any]] = {}
        self._option_historicals: dict[str, dict[str, Any]] = {}
        self._option_chains: dict[str, dict[str, Any]] = {}
        self._option_instruments: dict[str, dict[str, Any]] = {}
        self._option_positions: dict[str, dict[str, Any]] = {}

    # --- recording (call these with real tool-call results) --------------------------

    def record_equity_quotes(self, symbol: str, response: dict[str, Any]) -> None:
        self._equity_quotes[symbol] = response

    def record_equity_historicals(self, symbol: str, response: dict[str, Any]) -> None:
        self._equity_historicals[symbol] = response

    def record_option_quotes(self, option_id: str, response: dict[str, Any]) -> None:
        self._option_quotes[option_id] = response

    def record_option_historicals(self, option_id: str, response: dict[str, Any]) -> None:
        self._option_historicals[option_id] = response

    def record_option_chains(self, underlying_symbol: str, response: dict[str, Any]) -> None:
        self._option_chains[underlying_symbol] = response

    def record_option_instruments(self, key: str, response: dict[str, Any]) -> None:
        """`key` is whatever the agent chooses to identify this call by —
        typically the chain_id, or the `ids` string for a positions-sync
        lookup. Must match what get_option_instruments is called with
        below."""
        self._option_instruments[key] = response

    def record_option_positions(self, account_number: str, response: dict[str, Any]) -> None:
        self._option_positions[account_number] = response

    # --- HoodToolClient protocol -------------------------------------------------------

    def get_equity_quotes(self, symbols: list[str]) -> dict[str, Any]:
        return self._lookup(self._equity_quotes, symbols[0], "get_equity_quotes")

    def get_equity_historicals(self, symbols: list[str], start_time: str, **kwargs: Any) -> dict[str, Any]:
        return self._lookup(self._equity_historicals, symbols[0], "get_equity_historicals")

    def get_option_quotes(self, instrument_ids: list[str]) -> dict[str, Any]:
        return self._lookup(self._option_quotes, instrument_ids[0], "get_option_quotes")

    def get_option_historicals(self, instrument_ids: list[str], start_time: str, **kwargs: Any) -> dict[str, Any]:
        return self._lookup(self._option_historicals, instrument_ids[0], "get_option_historicals")

    def get_option_chains(self, underlying_symbol: str | None = None, ids: str | None = None) -> dict[str, Any]:
        key = underlying_symbol or ids or ""
        return self._lookup(self._option_chains, key, "get_option_chains")

    def get_option_instruments(
        self,
        chain_symbol: str | None = None,
        chain_id: str | None = None,
        ids: str | None = None,
        cursor: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        key = chain_id or ids or chain_symbol or ""
        return self._lookup(self._option_instruments, key, "get_option_instruments")

    def get_option_positions(self, account_number: str, nonzero: bool | None = None, **kwargs: Any) -> dict[str, Any]:
        return self._lookup(self._option_positions, account_number, "get_option_positions")

    @staticmethod
    def _lookup(store: dict[str, dict[str, Any]], key: str, method: str) -> dict[str, Any]:
        try:
            return store[key]
        except KeyError as exc:
            raise KeyError(
                f"{method}({key!r}) was never recorded on this StaticHoodClient — "
                "fetch it live and call the matching record_* method first"
            ) from exc
