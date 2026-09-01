"""Phase 6, section 1: freezing a strategy definition before any holdout
analysis runs.

A `FrozenStrategyDefinition` is a complete, self-contained, immutable
record of exactly what a strategy IS — feature, entry rule, exit rule,
holding period, lookback, thresholds, position sizing, risk configuration,
and every execution/slippage/cost assumption — captured as plain data (not
code) so it can be written to disk, hashed, and checked for tampering.

`FrozenStrategyStore` is append-only, like `ExperimentStore` and
`HypothesisRegistry` (same convention, see src/research/experiment.py's
module docstring): `freeze()` can only ADD a new immutable record. Calling
it twice with the SAME (strategy_id, strategy_version) but DIFFERENT
content raises — a frozen version is frozen, not a draft. To change any
parameter, mint a new strategy_version (e.g. "MR-002-V2") instead; the
store keeps both, side by side, forever.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


class FrozenStrategyImmutabilityError(RuntimeError):
    """Raised when code attempts to re-freeze an existing strategy_version
    with different content — the whole point of freezing is that this is
    not allowed."""


@dataclass(frozen=True)
class FrozenStrategyDefinition:
    strategy_id: str
    strategy_version: str
    hypothesis_id: str
    feature_definition: str  # exact mathematical definition, e.g. "zscore(close, 20)"
    entry_rule: str
    exit_rule: str
    holding_period_bars: int
    lookback: int
    entry_threshold: float
    exit_threshold: float
    prediction_horizon_bars: int
    position_sizing: Mapping[str, Any]
    risk_configuration: Mapping[str, Any]
    execution_model: Mapping[str, Any]
    slippage_model: Mapping[str, Any]
    transaction_cost_model: Mapping[str, Any]
    spread_model: Mapping[str, Any]
    starting_cash_usd: float
    development_universe_name: str
    frozen_at: datetime
    frozen_rationale: str

    def content_hash(self) -> str:
        """A deterministic hash over every field EXCEPT frozen_at (which is
        a timestamp, not a parameter) — used to detect whether two records
        sharing a (strategy_id, strategy_version) actually agree."""
        d = asdict(self)
        d.pop("frozen_at", None)
        blob = json.dumps(d, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["frozen_at"] = self.frozen_at.isoformat()
        d["content_hash"] = self.content_hash()
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FrozenStrategyDefinition":
        data = dict(data)
        data.pop("content_hash", None)
        return cls(
            strategy_id=data["strategy_id"], strategy_version=data["strategy_version"], hypothesis_id=data["hypothesis_id"],
            feature_definition=data["feature_definition"], entry_rule=data["entry_rule"], exit_rule=data["exit_rule"],
            holding_period_bars=data["holding_period_bars"], lookback=data["lookback"],
            entry_threshold=data["entry_threshold"], exit_threshold=data["exit_threshold"],
            prediction_horizon_bars=data["prediction_horizon_bars"], position_sizing=dict(data["position_sizing"]),
            risk_configuration=dict(data["risk_configuration"]), execution_model=dict(data["execution_model"]),
            slippage_model=dict(data["slippage_model"]), transaction_cost_model=dict(data["transaction_cost_model"]),
            spread_model=dict(data["spread_model"]), starting_cash_usd=data["starting_cash_usd"],
            development_universe_name=data["development_universe_name"],
            frozen_at=datetime.fromisoformat(data["frozen_at"]), frozen_rationale=data["frozen_rationale"],
        )


class FrozenStrategyStore:
    def __init__(self, path: Path):
        self._path = path

    def freeze(self, definition: FrozenStrategyDefinition) -> FrozenStrategyDefinition:
        existing = self.get(definition.strategy_id, definition.strategy_version)
        if existing is not None:
            if existing.content_hash() != definition.content_hash():
                raise FrozenStrategyImmutabilityError(
                    f"{definition.strategy_id} {definition.strategy_version} is already frozen with different "
                    f"content (existing hash {existing.content_hash()[:12]}, new hash {definition.content_hash()[:12]}). "
                    "A frozen strategy version cannot be modified — mint a new strategy_version instead "
                    "(e.g. 'MR-002-V2') and treat it as a new strategy."
                )
            return existing  # idempotent re-freeze of identical content
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(definition.to_dict(), sort_keys=True, default=str))
            f.write("\n")
            f.flush()
        return definition

    def load_all(self) -> list[FrozenStrategyDefinition]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        return [FrozenStrategyDefinition.from_dict(json.loads(line)) for line in raw.splitlines() if line.strip()]

    def get(self, strategy_id: str, strategy_version: str) -> FrozenStrategyDefinition | None:
        for rec in self.load_all():
            if rec.strategy_id == strategy_id and rec.strategy_version == strategy_version:
                return rec
        return None


def build_mr002_frozen_definition(*, development_universe_name: str, frozen_at: datetime | None = None) -> FrozenStrategyDefinition:
    """The exact, canonical MR-002 definition — lookback=20, entry_z=-1.5,
    exit_z=0.0, holding_period_bars=5, prediction_horizon_bars=5 — these
    are the SAME defaults `MeanReversionStrategy(strategy_id="MR-002",
    lookback=20, ...)` has used, unmodified, since Phase 4's
    `campaign_hypotheses()` first defined the MR-002 hypothesis, and the
    same values `scripts/run_research_campaign_phase5.py` used as MR-002's
    canonical (non-swept) parameterization. The wide/narrow parameter
    grids used during Phase 4/5 *robustness testing* (10-40, 15/18/20/22/25)
    were sensitivity checks around this point, never a re-selection of it —
    freezing this exact point is not cherry-picking a favorable value out
    of that grid, it is fixing the value the hypothesis was always defined
    around. Execution/slippage/cost/spread models and position sizing
    match Phase 5's campaign script exactly (src.research.runner via
    scripts/run_research_campaign_phase5.py's `_models()`)."""
    return FrozenStrategyDefinition(
        strategy_id="MR-002", strategy_version="1.0", hypothesis_id="MR-002",
        feature_definition="zscore_20 = (close[t] - mean(close, 20)) / stdev(close, 20)  [RollingZScore(lookback=20), causal — uses only bars up to and including t]",
        entry_rule="LONG when zscore_20 <= entry_threshold (-1.5)",
        exit_rule="FLAT when zscore_20 >= exit_threshold (0.0), or after holding_period_bars, whichever the backtest engine's exit logic reaches first",
        holding_period_bars=5, lookback=20, entry_threshold=-1.5, exit_threshold=0.0, prediction_horizon_bars=5,
        position_sizing={"sizer": "FixedQuantitySizer", "quantity": 20},
        risk_configuration={
            "max_trades_per_day": 10, "max_daily_loss_usd": 1_000_000.0, "max_position_size_usd": 20_000.0,
            "cooldown_minutes_after_exit": 0, "stale_data_max_seconds": 10**9, "max_spread_pct": 1.0,
            "min_option_volume": 0, "min_option_open_interest": 0, "max_extended_move_pct": 100.0,
            "entry_cutoff_time": "23:59", "note": "same BacktestRiskAdapter(RiskManager(RiskLimits(...))) as Phase 5 — a genuine, unmodified reuse of the live RiskManager class",
        },
        execution_model={"type": "NextBarExecutionModel", "price_field": "open", "delay_bars": 1},
        slippage_model={"type": "FixedPercentSlippage", "rate": 0.001},
        transaction_cost_model={"type": "PerShareCommission", "rate_per_share": 0.005},
        spread_model={"type": "FixedPercentSpreadModel", "rate": 0.001},
        starting_cash_usd=100_000.0,
        development_universe_name=development_universe_name,
        frozen_at=frozen_at or datetime.now(timezone.utc),
        frozen_rationale=(
            "Phase 5 classified MR-002 PROMISING on US_DIVERSIFIED (88% wide-grid / 100% narrow-grid parameter "
            "acceptability, viable at 1x/2x/3x costs, 100% execution-robustness, zero leave-one-out sign flips, "
            "placebo fraction 0.04, bootstrap CI excluding zero) but with known limitations (~5 years of data, one "
            "universe, current-constituent survivorship bias, test set already used in tuning). Phase 6 freezes "
            "this exact definition to test whether it generalizes to data/universes it has never touched, without "
            "letting the holdout result feed back into the definition."
        ),
    )


def build_strategy_from_frozen(definition: FrozenStrategyDefinition, universe_symbols: Sequence[str]):
    """Instantiates the actual ResearchStrategy object from a frozen
    definition — kept in one place so the holdout runner never
    hand-constructs a strategy with parameters that could silently drift
    from what was frozen."""
    from src.research.strategies import MeanReversionStrategy

    if definition.strategy_id != "MR-002":
        raise NotImplementedError(f"build_strategy_from_frozen only supports MR-002 in Phase 6, got {definition.strategy_id!r}")
    return MeanReversionStrategy(
        strategy_id=definition.strategy_id, lookback=definition.lookback, universe=list(universe_symbols),
        entry_z=definition.entry_threshold, exit_z=definition.exit_threshold,
        prediction_horizon_bars=definition.prediction_horizon_bars, holding_period_bars=definition.holding_period_bars,
    )
