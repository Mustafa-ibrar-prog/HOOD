"""Phase 37, Part 1/5/21/22 — the observation-cycle orchestration.

`run_observation_cycle()` is the one callable a future external
scheduler invokes (Part 5: "Do NOT create an external scheduler in this
phase"). No `while True`/`sleep(300)` loop exists anywhere in this
package, matching the exact convention `src/position_manager/monitor.py`
already established for the live position-monitoring cycle
(`is_within_monitoring_window()` + `run_once()`, called by something
external) — this module is that same shape, for observation instead of
monitoring.

Reuses the EXISTING Robinhood integration only:
  - `HoodMarketDataProvider.get_option_expirations`/`get_option_chain_candidates`
    (already real, tested, paginated chain-scanning code) for chain
    discovery.
  - The SAME injected `HoodToolClient` (`get_equity_quotes`/
    `get_option_quotes`) directly for QUOTES specifically -- bypassing
    `HoodMarketDataProvider`'s own narrowing parser deliberately, because
    Part 7/8 require this recorder to preserve the RAW payload and
    extract several real, live-confirmed fields (`bid_size`, `ask_size`,
    Greeks, IV, break-even, chance-of-profit) that
    `HoodMarketDataProvider`'s `OptionQuote`/`EquityQuote` narrowing
    would otherwise discard. No new market-data provider or tool is
    added -- this is the exact same `HoodToolClient` every other module
    in this codebase already uses.

Restart-safety (Part 21): a crash mid-cycle, restarted with the SAME
`observation_cycle_id`, re-processes every symbol, but every store
detects each already-recorded (cycle_id, symbol/option_id) pair as a
duplicate (storage.py) and skips re-appending it — no duplicate cycles,
no overwritten data, no special "resume" logic needed. Reusing the same
`observation_cycle_id` across a restart of the same intended observation
slot is the CALLER's responsibility (a future scheduler derives it from
the intended slot timestamp, not wall-clock-at-call-time); this function
defaults to a fresh, wall-clock-derived id only when none is supplied.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

from src.research_recorder.contract_selection import ContractSelectionBounds, select_observation_contracts
from src.research_recorder.market_hours import is_market_open_for_recording
from src.research_recorder.normalized_observation import (
    build_normalized_option_observation,
    build_normalized_underlying_observation,
)
from src.research_recorder.quote_quality import DEFAULT_STALE_QUOTE_SECONDS, QualityAssessment, assess_quote_quality
from src.research_recorder.raw_observation import RawObservation
from src.research_recorder.research_signal import ResearchSignalRecord, evaluate_research_signal_for_cycle
from src.research_recorder.storage import (
    CycleLogStore,
    NormalizedOptionStore,
    NormalizedUnderlyingStore,
    RawObservationStore,
    ResearchSignalStore,
)
from src.research_recorder.target_universe import TARGET_UNIVERSE

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.market.data_provider import MarketDataProvider
    from src.market.hood_client import HoodToolClient

MARKET_CLOSED = "MARKET_CLOSED"
PROVIDER_NAME = "robinhood_hood_mcp"


@dataclass(frozen=True)
class RecorderConfig:
    observation_interval_minutes: int = 5  # documentation of the intended cadence -- NOT enforced/slept here (Part 5: no scheduler in this phase)
    max_quote_age_seconds: float = DEFAULT_STALE_QUOTE_SECONDS
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0
    contract_selection_bounds: ContractSelectionBounds = field(default_factory=ContractSelectionBounds)


@dataclass(frozen=True)
class RecorderStores:
    raw: RawObservationStore
    underlying: NormalizedUnderlyingStore
    option: NormalizedOptionStore
    signal: ResearchSignalStore
    cycle_log: CycleLogStore


@dataclass(frozen=True)
class SymbolObservationResult:
    symbol: str
    succeeded: bool
    contracts_observed: int
    duplicates_detected: int
    quality_assessments: tuple[QualityAssessment, ...]
    failure_reason: str | None


@dataclass(frozen=True)
class ObservationCycleResult:
    observation_cycle_id: str
    started_at: datetime
    finished_at: datetime
    symbol_results: tuple[SymbolObservationResult, ...]
    research_signal: ResearchSignalRecord | None


def new_cycle_id(now: datetime) -> str:
    return f"cyc-{now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def _call_with_retry(
    fn: Callable[[], Any], *, max_retries: int, backoff_seconds: float, sleep_fn: Callable[[float], None],
) -> tuple[Any, str | None]:
    """Bounded retries with linear backoff (Part 22). Never an
    unbounded/aggressive loop -- `max_retries` is a hard cap."""
    last_error: str | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn(), None
        except Exception as exc:  # noqa: BLE001 -- any failure degrades to a recorded failure, never a crash
            last_error = str(exc)
            if attempt < max_retries:
                sleep_fn(backoff_seconds * (attempt + 1))
    return None, last_error


def _match_row_by_key(results: Sequence[Mapping[str, Any]], key_field: str, key_value: str) -> Mapping[str, Any] | None:
    """Never a first-row fallback -- matches `hood_provider.py`'s own
    established discipline (an unresolved symbol/instrument_id is
    silently omitted by the real tool, never returned as a null
    placeholder)."""
    for row in results:
        quote = row.get("quote") or {}
        if str(quote.get(key_field, "")).upper() == str(key_value).upper() or quote.get(key_field) == key_value:
            return quote
    return None


def _observe_symbol(
    symbol: str, *, client: "HoodToolClient", market: "MarketDataProvider", settings: "Settings",
    stores: RecorderStores, now: datetime, cycle_id: str, config: RecorderConfig, sleep_fn: Callable[[float], None],
) -> SymbolObservationResult:
    equity_response, error = _call_with_retry(
        lambda: client.get_equity_quotes([symbol]), max_retries=config.max_retries,
        backoff_seconds=config.retry_backoff_seconds, sleep_fn=sleep_fn,
    )
    if error is not None:
        return SymbolObservationResult(symbol, False, 0, 0, (), f"get_equity_quotes failed: {error}")

    stores.raw.append(RawObservation.build(
        observation_cycle_id=cycle_id, provider=PROVIDER_NAME, tool_name="get_equity_quotes",
        retrieval_timestamp=datetime.now(timezone.utc), market_timestamp=None,
        raw_payload=equity_response if isinstance(equity_response, dict) else {"_unparseable": True},
        request_context={"symbol": symbol},
    ))

    equity_results = (equity_response.get("data", {}) or {}).get("results", []) if isinstance(equity_response, dict) else []
    quote_row = _match_row_by_key(equity_results, "symbol", symbol)
    underlying_obs = build_normalized_underlying_observation(
        symbol=symbol, observation_cycle_id=cycle_id, observation_timestamp=now, quote_row=quote_row,
    )
    stores.underlying.append(underlying_obs)

    if underlying_obs.last is None and underlying_obs.midpoint is None:
        return SymbolObservationResult(symbol, False, 0, 0, (), "No usable underlying price this cycle")

    underlying_price = underlying_obs.midpoint if underlying_obs.midpoint is not None else underlying_obs.last

    candidates, chain_error = _call_with_retry(
        lambda: market.get_option_chain_candidates(symbol), max_retries=config.max_retries,
        backoff_seconds=config.retry_backoff_seconds, sleep_fn=sleep_fn,
    )
    if chain_error is not None:
        return SymbolObservationResult(symbol, False, 0, 0, (), f"get_option_chain_candidates failed: {chain_error}")
    if not candidates:
        return SymbolObservationResult(symbol, False, 0, 0, (), "No option chain candidates returned")

    selected = select_observation_contracts(
        candidates, underlying_price=underlying_price, now=now, market_timezone=settings.market_timezone,
        bounds=config.contract_selection_bounds,
    )
    option_ids = [str(c.chain_row.get("id")) for c in selected if c.chain_row.get("id")]
    if not option_ids:
        return SymbolObservationResult(symbol, False, 0, 0, (), "No selected contracts carried a usable option_id")

    option_response, quote_error = _call_with_retry(
        lambda: client.get_option_quotes(option_ids), max_retries=config.max_retries,
        backoff_seconds=config.retry_backoff_seconds, sleep_fn=sleep_fn,
    )
    if quote_error is not None:
        return SymbolObservationResult(symbol, False, 0, 0, (), f"get_option_quotes failed: {quote_error}")

    stores.raw.append(RawObservation.build(
        observation_cycle_id=cycle_id, provider=PROVIDER_NAME, tool_name="get_option_quotes",
        retrieval_timestamp=datetime.now(timezone.utc), market_timestamp=None,
        raw_payload=option_response if isinstance(option_response, dict) else {"_unparseable": True},
        request_context={"symbol": symbol, "option_ids": option_ids},
    ))
    option_results = (option_response.get("data", {}) or {}).get("results", []) if isinstance(option_response, dict) else []

    assessments = []
    duplicates_detected = 0
    for candidate in selected:
        option_id = str(candidate.chain_row.get("id"))
        option_quote_row = _match_row_by_key(option_results, "instrument_id", option_id)
        normalized = build_normalized_option_observation(
            option_id=option_id, underlying=symbol, observation_cycle_id=cycle_id, observation_timestamp=now,
            market_timezone=settings.market_timezone, quote_row=option_quote_row, chain_row=candidate.chain_row,
            underlying_price=underlying_price,
        )
        newly_appended = stores.option.append(normalized)
        if not newly_appended:
            duplicates_detected += 1
        assessment = assess_quote_quality(
            normalized, now=now, max_quote_age_seconds=config.max_quote_age_seconds, is_duplicate=not newly_appended,
        )
        assessments.append(assessment)

    return SymbolObservationResult(symbol, True, len(selected), duplicates_detected, tuple(assessments), None)


def run_observation_cycle(
    *,
    client: "HoodToolClient",
    market: "MarketDataProvider",
    settings: "Settings",
    stores: RecorderStores,
    now: datetime | None = None,
    cycle_id: str | None = None,
    universe: Sequence[str] = TARGET_UNIVERSE,
    config: RecorderConfig = RecorderConfig(),
    sleep_fn: Callable[[float], None] = time.sleep,
) -> ObservationCycleResult | str:
    """Returns the literal string MARKET_CLOSED (never a fabricated
    observation) when `now` falls outside regular US market hours. See
    the module docstring for restart-safety and cycle_id conventions."""
    now = now or datetime.now(timezone.utc)
    if not is_market_open_for_recording(now, settings):
        return MARKET_CLOSED

    cycle_id = cycle_id or new_cycle_id(now)
    started_at = datetime.now(timezone.utc)

    symbol_results = tuple(
        _observe_symbol(
            symbol, client=client, market=market, settings=settings, stores=stores, now=now, cycle_id=cycle_id,
            config=config, sleep_fn=sleep_fn,
        )
        for symbol in universe  # a fixed, bounded universe -- never an unbounded/dynamic symbol loop (Part 22)
    )

    signal = evaluate_research_signal_for_cycle(market=market, universe=universe, observation_cycle_id=cycle_id, now=now)
    stores.signal.append(signal)

    cycle_result = ObservationCycleResult(
        observation_cycle_id=cycle_id, started_at=started_at, finished_at=datetime.now(timezone.utc),
        symbol_results=symbol_results, research_signal=signal,
    )
    stores.cycle_log.append_from_cycle_result(cycle_result)
    return cycle_result
