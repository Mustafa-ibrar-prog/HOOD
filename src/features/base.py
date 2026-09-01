"""The Feature framework's contract.

STRICT NO-FUTURE-DATA RULE (Phase 2, section 6 — critical): every Feature
implementation's `compute(bars)` must return a list where output[i]
depends ONLY on bars[0..i] inclusive, never on bars[i+1:]. This is not
enforced by a runtime sandbox — Python can't stop a badly-written feature
from indexing ahead — so the enforcement here is structural and tested:

  1. Every concrete feature in this package is built out of
     src/features/_util.py's rolling_apply/shifted/pct_change primitives,
     which are themselves incapable of looking past index i by
     construction (they only ever slice series[:i+1]).
  2. tests/test_feature_no_lookahead.py runs every registered feature
     through a synthetic-leakage test: compute features once on a real
     series, once on the same series with everything AFTER a cutoff index
     replaced by extreme/huge values, and assert every value at or before
     the cutoff is byte-for-byte identical. A feature that ever reaches
     forward would fail that test immediately.

A new feature that doesn't use the shared primitives should still pass
that same leakage test — it's the actual contract, not the primitives
themselves.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.data.bar import Bar


@dataclass(frozen=True)
class FeatureSpec:
    """Everything needed to identify, reproduce, and document one feature
    — this is what feeds compute_feature_version() (src/data/versioning.py)
    and FeatureEngine.manifest(), so a research experiment can always be
    traced back to exactly which feature definitions produced it."""

    name: str
    version: str
    params: Mapping[str, Any] = field(default_factory=dict)
    required_columns: tuple[str, ...] = ("close",)
    lookback: int = 0
    description: str = ""


class Feature(ABC):
    """Base class for one named, versioned, independently-testable
    feature. Implementations should be pure functions of `bars` — no
    hidden state, no side effects, safely reusable across many
    computations."""

    spec: FeatureSpec

    @abstractmethod
    def compute(self, bars: Sequence[Bar]) -> list[float | None]:
        """One output value per input bar, aligned by index. The first
        `spec.lookback` entries should be None (not enough history yet)
        rather than a fabricated early value — see module docstring for
        the no-future-data contract this must uphold in the other
        direction (index i may use bars[0..i], never bars[i+1:])."""
        raise NotImplementedError

    def _closes(self, bars: Sequence[Bar]) -> list[float]:
        return [b.close for b in bars]

    def _highs(self, bars: Sequence[Bar]) -> list[float]:
        return [b.high for b in bars]

    def _lows(self, bars: Sequence[Bar]) -> list[float]:
        return [b.low for b in bars]

    def _volumes(self, bars: Sequence[Bar]) -> list[float]:
        return [float(b.volume) for b in bars]
