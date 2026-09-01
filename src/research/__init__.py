"""Research tooling: turn (bars + features) into datasets, split them
chronologically, test features for a measurable relationship with future
returns, and track every experiment run — all explicitly separate from
the live/paper trading path (src/orchestrator.py, src/strategy/,
src/execution/), which never imports from this package.

RESEARCH ONLY. Nothing in this package places, modifies, or evaluates a
live trade, and nothing here automatically turns a statistically
interesting result into a trading strategy — that stays a human decision,
for a later phase.
"""

from __future__ import annotations

from src.research.analysis import FeatureAnalysisResult, QuantileResult, analyze_feature
from src.research.dataset import ResearchDataset, ResearchDatasetGenerator
from src.research.experiment import ExperimentRecord, ExperimentStore
from src.research.splits import DatasetSplit, SplitConfig, SplitConfigError, chronological_split
from src.research.targets import future_return

__all__ = [
    "future_return",
    "ResearchDataset",
    "ResearchDatasetGenerator",
    "SplitConfig",
    "SplitConfigError",
    "DatasetSplit",
    "chronological_split",
    "analyze_feature",
    "FeatureAnalysisResult",
    "QuantileResult",
    "ExperimentRecord",
    "ExperimentStore",
]
