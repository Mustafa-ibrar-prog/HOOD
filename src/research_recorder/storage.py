"""Phase 37, Part 16/20/21 — the research dataset's three, strictly
separate, append-only storage layers.

    A. raw observations       -- RawObservationStore
    B. normalized observations -- NormalizedUnderlyingStore / NormalizedOptionStore
    C. research signals        -- ResearchSignalStore

Plus a 4th, deliberately SEPARATE layer -- `CycleLogStore` -- holding
operational metadata about the recording PROCESS itself (which cycles
ran, which symbols succeeded/failed, when). This is not a fourth
observation/signal layer and is never queried alongside A/B/C for
research purposes; `quality_report.py` is its only real reader. Keeping
it distinct (rather than folding cycle bookkeeping into any of A/B/C)
is what "never mixed" (Part 16) requires.

Never mixed (Part 16's explicit instruction) -- three separate files,
three separate classes, no shared row shape. Each store is append-only
JSONL, following the SAME convention `FrozenStrategyStore`/
`ValidationArtifactStore`/`TradeJournal` already established in this
project, and each detects a duplicate append (by a natural key, not by
re-hashing the whole file) rather than silently writing a second,
possibly-conflicting record for the same real observation (Part 20).

Restart-safety (Part 21): every store's duplicate-detection index is
rebuilt from the existing file's own contents at construction time --
a fresh instance pointed at the same path after a process restart
behaves identically to the instance that was running before the crash.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

from src.research_recorder.normalized_observation import NormalizedOptionObservation, NormalizedUnderlyingObservation
from src.research_recorder.raw_observation import RawObservation
from src.research_recorder.research_signal import ResearchSignalRecord


class _AppendOnlyJSONLStore:
    """Not part of this module's public surface -- a shared implementation
    detail for the three stores below, none of which expose a generic
    'write anything' method (each has its own narrowly-typed `append`)."""

    def __init__(self, path: Path, *, key_fn: Callable[[Mapping[str, Any]], tuple]):
        self._path = path
        self._key_fn = key_fn
        self._seen: set[tuple] = set()
        if self._path.is_file():
            for line in self._path.read_text().splitlines():
                if line.strip():
                    self._seen.add(self._key_fn(json.loads(line)))

    def append(self, record: Mapping[str, Any]) -> bool:
        key = self._key_fn(record)
        if key in self._seen:
            return False
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(record, sort_keys=True, default=str))
            f.write("\n")
        self._seen.add(key)
        return True

    def load_all_raw_dicts(self) -> list[dict[str, Any]]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        return [json.loads(line) for line in raw.splitlines() if line.strip()]


class RawObservationStore:
    def __init__(self, path: Path):
        self._impl = _AppendOnlyJSONLStore(
            path,
            key_fn=lambda d: (
                d["observation_cycle_id"], d["tool_name"], d["payload_fingerprint"],
                json.dumps(d.get("request_context", {}), sort_keys=True, default=str),
            ),
        )

    def append(self, observation: RawObservation) -> bool:
        """Returns True if newly appended, False if this exact
        (cycle, tool, fingerprint, request_context) was already recorded
        -- a detected duplicate, never a silent second write."""
        return self._impl.append(observation.to_dict())

    def load_all(self) -> list[RawObservation]:
        return [RawObservation.from_dict(d) for d in self._impl.load_all_raw_dicts()]


class NormalizedUnderlyingStore:
    def __init__(self, path: Path):
        self._impl = _AppendOnlyJSONLStore(path, key_fn=lambda d: (d["observation_cycle_id"], d["symbol"]))

    def append(self, observation: NormalizedUnderlyingObservation) -> bool:
        d = {
            "symbol": observation.symbol, "observation_cycle_id": observation.observation_cycle_id,
            "observation_timestamp": observation.observation_timestamp.isoformat(),
            "market_timestamp": observation.market_timestamp.isoformat() if observation.market_timestamp else None,
            "bid": observation.bid, "ask": observation.ask, "last": observation.last, "midpoint": observation.midpoint,
            "volume": observation.volume, "field_provenance": dict(observation.field_provenance),
        }
        return self._impl.append(d)

    def load_all_raw_dicts(self) -> list[dict[str, Any]]:
        return self._impl.load_all_raw_dicts()


class NormalizedOptionStore:
    def __init__(self, path: Path):
        self._impl = _AppendOnlyJSONLStore(path, key_fn=lambda d: (d["observation_cycle_id"], d["option_id"]))

    def append(self, observation: NormalizedOptionObservation) -> bool:
        d = {
            "option_id": observation.option_id, "underlying": observation.underlying,
            "observation_cycle_id": observation.observation_cycle_id,
            "observation_timestamp": observation.observation_timestamp.isoformat(),
            "market_timestamp": observation.market_timestamp.isoformat() if observation.market_timestamp else None,
            "option_type": observation.option_type, "strike": observation.strike,
            "expiration": observation.expiration.isoformat() if observation.expiration else None,
            "dte": observation.dte, "contract_state": observation.contract_state,
            "contract_tradability": observation.contract_tradability,
            "bid": observation.bid, "ask": observation.ask, "bid_size": observation.bid_size,
            "ask_size": observation.ask_size, "mark": observation.mark, "adjusted_mark": observation.adjusted_mark,
            "last_trade": observation.last_trade, "midpoint": observation.midpoint, "volume": observation.volume,
            "open_interest": observation.open_interest, "implied_volatility": observation.implied_volatility,
            "delta": observation.delta, "gamma": observation.gamma, "theta": observation.theta,
            "vega": observation.vega, "rho": observation.rho, "break_even": observation.break_even,
            "chance_of_profit_long": observation.chance_of_profit_long,
            "chance_of_profit_short": observation.chance_of_profit_short, "moneyness": observation.moneyness,
            "moneyness_underlying_price_used": observation.moneyness_underlying_price_used,
            "moneyness_version": observation.moneyness_version, "field_provenance": dict(observation.field_provenance),
        }
        return self._impl.append(d)

    def load_all_raw_dicts(self) -> list[dict[str, Any]]:
        return self._impl.load_all_raw_dicts()


class CycleLogStore:
    """The 4th, deliberately separate operational layer -- see module
    docstring. One row per `run_observation_cycle` call that actually
    executed (never one for a `MARKET_CLOSED` short-circuit, since no
    cycle_id is even minted in that case)."""

    def __init__(self, path: Path):
        self._impl = _AppendOnlyJSONLStore(path, key_fn=lambda d: (d["observation_cycle_id"],))

    def append_from_cycle_result(self, result) -> bool:  # ObservationCycleResult -- typed in recorder.py, avoided here to prevent a circular import
        d = {
            "observation_cycle_id": result.observation_cycle_id, "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat(),
            "symbols_attempted": [r.symbol for r in result.symbol_results],
            "symbols_succeeded": [r.symbol for r in result.symbol_results if r.succeeded],
            "symbols_failed": [{"symbol": r.symbol, "reason": r.failure_reason} for r in result.symbol_results if not r.succeeded],
            "contracts_observed": sum(r.contracts_observed for r in result.symbol_results),
            "duplicates_detected": sum(r.duplicates_detected for r in result.symbol_results),
        }
        return self._impl.append(d)

    def load_all_raw_dicts(self) -> list[dict[str, Any]]:
        return self._impl.load_all_raw_dicts()


class ResearchSignalStore:
    def __init__(self, path: Path):
        self._impl = _AppendOnlyJSONLStore(path, key_fn=lambda d: (d["observation_cycle_id"], d["strategy_id"]))

    def append(self, record: ResearchSignalRecord) -> bool:
        d = {
            "observation_cycle_id": record.observation_cycle_id, "strategy_id": record.strategy_id,
            "signal_timestamp": record.signal_timestamp.isoformat(), "produced_signal": record.produced_signal,
            "underlying": record.underlying, "candidate_option_id": record.candidate_option_id,
            "decision": record.decision, "features": dict(record.features), "reason": record.reason,
            "label": record.label, "evaluation_error": record.evaluation_error,
        }
        return self._impl.append(d)

    def load_all_raw_dicts(self) -> list[dict[str, Any]]:
        return self._impl.load_all_raw_dicts()
