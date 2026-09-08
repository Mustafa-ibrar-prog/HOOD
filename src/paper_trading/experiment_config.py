"""Phase 40, Part 2/5 — the immutable experiment configuration.

`ExperimentStrategyMode.PAPER_EXPERIMENT_ONLY` is a Phase-40-LOCAL enum,
structurally unrelated to `src.production.registry.StrategyStatus`
(never imported here, never referenced by it). There is no function
anywhere in this package that can set a `StrategyRegistry` entry's
status, and no function in `src.production` reads anything from this
package — the two are simply disconnected code paths, which is what
makes "this status must never be accepted by the live execution path"
true structurally rather than by convention
(`tests/test_phase40_safety.py::test_no_paper_trading_module_touches_the_strategy_registry`).

`ExperimentConfig` is frozen and, once approved via `ExperimentConfigStore`,
immutable for the life of the experiment — the SAME
write-once/raise-on-conflicting-rewrite convention
`src.production.validation_artifact.ValidationArtifactStore` and
`src.research.frozen_strategy.FrozenStrategyStore` already established,
reused here rather than re-invented.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class ExperimentStrategyMode(str, Enum):
    PAPER_EXPERIMENT_ONLY = "PAPER_EXPERIMENT_ONLY"


MINIMUM_EXPERIMENT_DAYS = 14
DEFAULT_STARTING_CAPITAL_USD = 1000.0  # matches src.options.phase35_frozen_strategy_spec's own starting_cash_usd=1000.0 for this exact strategy


class ExperimentConfigImmutabilityError(RuntimeError):
    """Raised when re-approving an existing experiment_id with different
    content — an approved experiment configuration is a permanent
    record for the life of the experiment, never silently edited."""


def strategy_content_hash() -> str:
    """A real, reproducible hash of the FROZEN strategy specification this
    experiment uses (src.options.phase35_frozen_strategy_spec) — the same
    sha256-of-canonical-JSON convention
    src.research.frozen_strategy.FrozenStrategyDefinition.content_hash()
    already uses, applied here to the exact dataclass fields that fully
    determine MOMENTUM_BREAKOUT_EXISTING_V1's live behavior. Reused, not
    duplicated: this hashes the SAME frozen spec object Phase 35/36 already
    built, never a re-transcription of it."""
    from src.options.phase35_frozen_strategy_spec import MOMENTUM_BREAKOUT_EXISTING_V1

    spec = MOMENTUM_BREAKOUT_EXISTING_V1
    blob = json.dumps(
        {
            "strategy_id": spec.strategy_id,
            "frozen_as_of": spec.frozen_as_of,
            "underlying_signals": asdict(spec.underlying_signals),
            "option_selection": asdict(spec.option_selection),
            "position_sizing": asdict(spec.position_sizing),
            "exit": asdict(spec.exit),
        },
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExperimentConfig:
    experiment_id: str
    starting_capital_usd: float
    strategy_id: str
    strategy_version: str
    strategy_mode: ExperimentStrategyMode
    strategy_content_hash: str
    start_timestamp: datetime
    planned_minimum_end_timestamp: datetime  # start_timestamp + MINIMUM_EXPERIMENT_DAYS calendar days
    universe: tuple[str, ...]
    execution_assumptions: Mapping[str, Any]  # e.g. {"entry_price_rule": "live ask", "exit_price_rule": "live bid", ...}
    risk_configuration: Mapping[str, Any]  # e.g. {"max_position_size_usd_rule": "min(available_cash, aggressive_ceiling)", ...}
    data_provenance: str  # e.g. "Phase 37 recorder + Phase 39 live bridge, real Robinhood quotes only"

    def __post_init__(self) -> None:
        if self.starting_capital_usd <= 0:
            raise ValueError("starting_capital_usd must be > 0")
        if self.strategy_mode != ExperimentStrategyMode.PAPER_EXPERIMENT_ONLY:
            raise ValueError(f"strategy_mode must be PAPER_EXPERIMENT_ONLY, got {self.strategy_mode!r}")
        if not self.universe:
            raise ValueError("universe must not be empty")
        min_end = self.start_timestamp.replace() + _timedelta_days(MINIMUM_EXPERIMENT_DAYS)
        if self.planned_minimum_end_timestamp < min_end:
            raise ValueError(
                f"planned_minimum_end_timestamp ({self.planned_minimum_end_timestamp.isoformat()}) is earlier than "
                f"the required {MINIMUM_EXPERIMENT_DAYS}-calendar-day minimum from start_timestamp "
                f"({self.start_timestamp.isoformat()})"
            )

    def content_hash(self) -> str:
        d = self.to_dict()
        d.pop("content_hash", None)
        blob = json.dumps(d, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "starting_capital_usd": self.starting_capital_usd,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_mode": self.strategy_mode.value,
            "strategy_content_hash": self.strategy_content_hash,
            "start_timestamp": self.start_timestamp.isoformat(),
            "planned_minimum_end_timestamp": self.planned_minimum_end_timestamp.isoformat(),
            "universe": list(self.universe),
            "execution_assumptions": dict(self.execution_assumptions),
            "risk_configuration": dict(self.risk_configuration),
            "data_provenance": self.data_provenance,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExperimentConfig":
        return cls(
            experiment_id=data["experiment_id"], starting_capital_usd=float(data["starting_capital_usd"]),
            strategy_id=data["strategy_id"], strategy_version=data["strategy_version"],
            strategy_mode=ExperimentStrategyMode(data["strategy_mode"]), strategy_content_hash=data["strategy_content_hash"],
            start_timestamp=datetime.fromisoformat(data["start_timestamp"]),
            planned_minimum_end_timestamp=datetime.fromisoformat(data["planned_minimum_end_timestamp"]),
            universe=tuple(data["universe"]), execution_assumptions=dict(data["execution_assumptions"]),
            risk_configuration=dict(data["risk_configuration"]), data_provenance=data["data_provenance"],
        )


def _timedelta_days(n: int):
    from datetime import timedelta

    return timedelta(days=n)


def new_experiment_id(now: datetime) -> str:
    import uuid

    return f"exp-{now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def build_experiment_config(
    *, now: datetime, starting_capital_usd: float = DEFAULT_STARTING_CAPITAL_USD, minimum_days: int = MINIMUM_EXPERIMENT_DAYS,
    universe: tuple[str, ...] | None = None, experiment_id: str | None = None,
    max_position_size_fraction_of_equity: float = 1.0,
) -> ExperimentConfig:
    """Builds a real ExperimentConfig for MOMENTUM_BREAKOUT_EXISTING_V1 --
    the only strategy this phase wires up (Part 10). `universe` defaults
    to the established 12-symbol candidate universe
    (src.research_recorder.target_universe.TARGET_UNIVERSE, reused
    unchanged); the engine may narrow it dynamically per cycle based on
    real liquidity/data (Part 7), never expand it.
    `max_position_size_fraction_of_equity=1.0` (Part 15: "aggressive...
    do not artificially make the experiment conservative") means a
    position is only ever capped by the account's OWN real remaining
    cash, never an additional arbitrary dollar ceiling -- see
    engine.py's use of this value."""
    from src.options.phase35_frozen_strategy_spec import STRATEGY_ID
    from src.research_recorder.target_universe import TARGET_UNIVERSE

    now = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    universe = universe or TARGET_UNIVERSE
    experiment_id = experiment_id or new_experiment_id(now)

    return ExperimentConfig(
        experiment_id=experiment_id,
        starting_capital_usd=starting_capital_usd,
        strategy_id=STRATEGY_ID,
        strategy_version="1.0",
        strategy_mode=ExperimentStrategyMode.PAPER_EXPERIMENT_ONLY,
        strategy_content_hash=strategy_content_hash(),
        start_timestamp=now,
        planned_minimum_end_timestamp=now + _timedelta_days(minimum_days),
        universe=tuple(universe),
        execution_assumptions={
            "entry_price_rule": "live ask (marketable buy-to-open limit) — never midpoint",
            "exit_price_rule": "live bid (marketable sell-to-close limit) — never midpoint",
            "no_executable_quote_rule": "NO_EXECUTABLE_QUOTE, no fill, if bid/ask is missing at decision time",
            "market_hours_rule": "no paper order outside regular US market hours (MARKET_CLOSED)",
        },
        risk_configuration={
            "max_position_size_usd_rule": (
                f"min(available_cash, {max_position_size_fraction_of_equity:.2f} * starting_capital_usd) — "
                "capped by real remaining cash, not an arbitrary conservative dollar figure"
            ),
            "max_position_size_fraction_of_equity": max_position_size_fraction_of_equity,
            "reused_risk_manager": "src.risk.manager.RiskManager (11 checks, unmodified)",
            "reused_risk_limits_base": "src.risk.models.RiskLimits.from_settings, overridden only in max_position_size_usd and scan_universe per cycle",
        },
        data_provenance=(
            "Real Robinhood market data only, via the Phase 37 recorder "
            "(src.research_recorder.recorder.run_observation_cycle) and the Phase 39 live "
            "bridge (src.live_bridge) — never fabricated, never historical-as-current."
        ),
    )


class ExperimentConfigStore:
    """Write-once JSON file: approve() raises if a DIFFERENT config is
    ever approved under the same path (the same
    write-once/raise-on-conflict convention as ValidationArtifactStore/
    FrozenStrategyStore)."""

    def __init__(self, path: Path):
        self._path = Path(path)

    def get(self) -> ExperimentConfig | None:
        if not self._path.is_file():
            return None
        raw = self._path.read_text()
        if not raw.strip():
            return None
        return ExperimentConfig.from_dict(json.loads(raw))

    def approve(self, config: ExperimentConfig) -> None:
        existing = self.get()
        if existing is not None:
            if existing.content_hash() != config.content_hash():
                raise ExperimentConfigImmutabilityError(
                    f"An experiment config already exists at {self._path} with a DIFFERENT content hash "
                    f"(existing {existing.content_hash()[:12]}, new {config.content_hash()[:12]}). "
                    "Once started, an experiment's configuration is immutable — stop this experiment and "
                    "start a new one (new experiment_id) instead of editing it in place."
                )
            return  # identical re-approval is a harmless no-op (idempotent restart)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(config.to_dict(), indent=2, sort_keys=True))
