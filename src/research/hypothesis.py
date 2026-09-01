"""The hypothesis registry (Phase 4, section 3).

Research philosophy, stated once here rather than repeated everywhere:
this is NOT "find indicators that make money." Every research strategy in
this codebase traces back to a Hypothesis written and recorded BEFORE any
result is computed — economic intuition, mathematical definition, and
expected direction, on the record, so results can never be used to
quietly rewrite the claim being tested. HypothesisRegistry is append-only
for the same reason ExperimentStore is: a hypothesis, once registered, is
never edited to fit what the data later showed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class HypothesisRegistryError(RuntimeError):
    """Raised on an attempt to violate the append-only/no-retroactive-edit
    invariant, or on a corrupted registry file — fails closed, same
    convention as every other store in this codebase."""


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str  # e.g. "MOM-001" — human-assigned, stable
    name: str
    description: str
    economic_intuition: str
    mathematical_definition: str
    required_data: tuple[str, ...]  # e.g. ("daily OHLCV",)
    required_features: tuple[str, ...]  # feature names this hypothesis depends on
    prediction_horizon_bars: int
    test_methodology: str
    expected_direction: str  # "positive" | "negative" | "unsigned"
    assumptions: tuple[str, ...]
    version: str = "1.0"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.expected_direction not in ("positive", "negative", "unsigned"):
            raise ValueError("expected_direction must be 'positive', 'negative', or 'unsigned'")
        if self.prediction_horizon_bars < 1:
            raise ValueError("prediction_horizon_bars must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Hypothesis":
        return cls(
            hypothesis_id=data["hypothesis_id"],
            name=data["name"],
            description=data["description"],
            economic_intuition=data["economic_intuition"],
            mathematical_definition=data["mathematical_definition"],
            required_data=tuple(data.get("required_data", ())),
            required_features=tuple(data.get("required_features", ())),
            prediction_horizon_bars=int(data["prediction_horizon_bars"]),
            test_methodology=data["test_methodology"],
            expected_direction=data["expected_direction"],
            assumptions=tuple(data.get("assumptions", ())),
            version=data.get("version", "1.0"),
            created_at=datetime.fromisoformat(data["created_at"]),
        )


class HypothesisRegistry:
    """Append-only JSONL registry, same mechanics as ExperimentStore
    (src.research.experiment) and TradeJournal (src.logging.trade_journal)
    — deliberately, since all three share the same "never silently
    mutate/lose the record" requirement."""

    def __init__(self, path: Path):
        self._path = path

    def register(self, hypothesis: Hypothesis) -> Hypothesis:
        existing = self.get(hypothesis.hypothesis_id)
        if existing is not None:
            raise HypothesisRegistryError(
                f"hypothesis_id {hypothesis.hypothesis_id!r} is already registered "
                f"(version {existing.version}) — register a new hypothesis_id or a new "
                "version for a genuinely revised hypothesis; never edit one in place"
            )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(hypothesis.to_dict(), sort_keys=True, default=str))
            f.write("\n")
            f.flush()
        return hypothesis

    def load_all(self) -> list[Hypothesis]:
        if not self._path.is_file():
            return []
        raw = self._path.read_text()
        if not raw.strip():
            return []
        try:
            return [Hypothesis.from_dict(json.loads(line)) for line in raw.splitlines() if line.strip()]
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise HypothesisRegistryError(f"Hypothesis registry is corrupted or unreadable: {exc}") from exc

    def get(self, hypothesis_id: str) -> Hypothesis | None:
        for h in self.load_all():
            if h.hypothesis_id == hypothesis_id:
                return h
        return None
