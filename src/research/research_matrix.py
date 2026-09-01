"""The research matrix (Phase 5, section 17) — evidence for each
candidate, NEVER a ranking. Rows are kept in whatever order the caller
supplies them (this module never sorts by performance); each row reports
what was found, not a score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from src.research.classification import ClassificationResult


@dataclass(frozen=True)
class ResearchMatrixRow:
    hypothesis_id: str
    strategy_name: str
    is_evidence: str
    validation_evidence: str
    oos_evidence: str
    parameter_stability: str
    time_stability: str
    universe_stability: str
    regime_stability: str
    cost_sensitivity: str
    execution_sensitivity: str
    placebo_bootstrap_evidence: str
    sample_size: int
    known_biases: tuple[str, ...]
    limitations: tuple[str, ...]
    classification: ClassificationResult


@dataclass(frozen=True)
class ResearchMatrix:
    rows: tuple[ResearchMatrixRow, ...]

    def render(self) -> str:
        lines = ["RESEARCH MATRIX (evidence only — NOT a ranking; row order is input order)", ""]
        for row in self.rows:
            lines += [
                f"[{row.hypothesis_id}] {row.strategy_name}",
                f"  IS evidence:            {row.is_evidence}",
                f"  Validation evidence:    {row.validation_evidence}",
                f"  OOS evidence:           {row.oos_evidence}",
                f"  Parameter stability:    {row.parameter_stability}",
                f"  Time stability:         {row.time_stability}",
                f"  Universe stability:     {row.universe_stability}",
                f"  Regime stability:       {row.regime_stability}",
                f"  Cost sensitivity:       {row.cost_sensitivity}",
                f"  Execution sensitivity:  {row.execution_sensitivity}",
                f"  Placebo/bootstrap:      {row.placebo_bootstrap_evidence}",
                f"  Sample size:            {row.sample_size}",
                f"  Known biases:           {', '.join(row.known_biases) or 'none noted'}",
                f"  Limitations:            {', '.join(row.limitations) or 'none noted'}",
                f"  CLASSIFICATION:         {row.classification.classification.value}  ({'; '.join(row.classification.reasons)})",
                "",
            ]
        return "\n".join(lines)
