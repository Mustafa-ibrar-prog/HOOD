"""Phase 38, Part 12 — live-observation replication.

Explicitly NOT paper trading and NEVER computes a simulated account P&L
(Part 12's own instruction) -- this module only checks whether the
strategy's ASSUMPTIONS hold against real recorded conditions: signal
reproducibility, feature availability, contract-selection reproducibility,
timestamp correctness, live field availability, and Phase 37's own
data-quality behavior (`src.research_recorder.quality_report`, reused
UNCHANGED, never recomputed here).

Signal reproducibility is a STRUCTURAL property, not something to
re-derive empirically from stored data: Phase 36's production adapter
for this candidate wraps the real `MomentumBreakoutStrategy`, which
contains no randomness anywhere in its scan logic (confirmed by code
inspection, Phase 28/35/36's own repeated audits) -- given the identical
market data it will always produce the identical decision. This module
reports that as a code-level fact, not a replay experiment, since
replaying a snapshot would require reconstructing a full
`MarketDataProvider` from stored rows, which is out of scope for a
validation phase that must not build a new market-data provider.

(This module does not import Phase 36's adapter class at all -- see
`tests/test_phase36_momentum_breakout_adapter.py::test_adapter_has_no_live_trade_path`,
which scans for exactly that class name outside its own defining module
and `src/research_recorder/research_signal.py`.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.options.phase38_causal_validation_dataset import CausalFeatureRow
from src.research_recorder.quality_report import DataQualityReport, build_data_quality_report

if TYPE_CHECKING:
    from src.research_recorder.recorder import RecorderStores


@dataclass(frozen=True)
class LiveReplicationReport:
    n_cycles_available: int
    n_signals_recorded: int
    n_hypothetical_enter_decisions: int
    signal_evaluation_is_deterministic: bool  # structural fact -- see module docstring
    feature_availability_pct: dict[str, float]  # per-field, fraction of causal rows where the field is present (not MISSING)
    cycle_timestamps_monotonic: bool | None
    data_quality: DataQualityReport | None
    sufficient_for_replication: bool
    reason: str


_REPLICATION_RELEVANT_FIELDS = ("option_bid", "option_ask", "implied_volatility", "delta", "open_interest", "volume", "dte", "moneyness")


def _feature_availability(dataset: list[CausalFeatureRow]) -> dict[str, float]:
    if not dataset:
        return {f: 0.0 for f in _REPLICATION_RELEVANT_FIELDS}
    n = len(dataset)
    availability = {}
    for field_name in _REPLICATION_RELEVANT_FIELDS:
        present = sum(1 for row in dataset if getattr(row, field_name, None) is not None)
        availability[field_name] = present / n
    return availability


def evaluate_live_replication(*, stores: "RecorderStores", dataset: list[CausalFeatureRow]) -> LiveReplicationReport:
    cycle_rows = stores.cycle_log.load_all_raw_dicts()
    signal_rows = stores.signal.load_all_raw_dicts()
    n_cycles = len(cycle_rows)
    n_signals = len(signal_rows)
    n_enter = sum(1 for r in signal_rows if r.get("decision") == "ENTER")

    if n_cycles == 0:
        return LiveReplicationReport(
            n_cycles_available=0, n_signals_recorded=0, n_hypothetical_enter_decisions=0,
            signal_evaluation_is_deterministic=True, feature_availability_pct=_feature_availability([]),
            cycle_timestamps_monotonic=None, data_quality=None, sufficient_for_replication=False,
            reason="Zero observation cycles have ever been recorded -- src.research_recorder.recorder.run_observation_cycle "
            "has not been invoked against the real Robinhood integration yet. There is nothing to replicate against.",
        )

    from datetime import datetime
    timestamps = [datetime.fromisoformat(r["started_at"]) for r in cycle_rows]
    monotonic = all(timestamps[i] <= timestamps[i + 1] for i in range(len(timestamps) - 1))

    quality = build_data_quality_report(stores)
    sufficient = n_cycles >= 20  # this project's established minimum-sample floor, applied to cycles here

    return LiveReplicationReport(
        n_cycles_available=n_cycles, n_signals_recorded=n_signals, n_hypothetical_enter_decisions=n_enter,
        signal_evaluation_is_deterministic=True, feature_availability_pct=_feature_availability(dataset),
        cycle_timestamps_monotonic=monotonic, data_quality=quality, sufficient_for_replication=sufficient,
        reason="OK" if sufficient else f"Only {n_cycles} cycle(s) recorded (< 20) -- insufficient for a meaningful replication assessment.",
    )
