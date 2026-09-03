"""Phase 28, Part 15 — free dataset preservation.

Nothing in this module touches `logs/research_data/phase26_raw/` or
`phase27_raw/`, or any Phase 26/27 `src/options/phase26_*.py`/
`phase27_*.py` module -- this is purely a label/classification, applied
by reference, never by copying or merging data.
"""

from __future__ import annotations

import enum


class DatasetRole(enum.Enum):
    FREE_REFERENCE_DATASET = "free_reference_dataset"
    PAID_RESEARCH_DATASET = "paid_research_dataset"  # not yet populated -- no paid data has ever been acquired


# Real, unchanged since Phase 26/27 -- re-affirmed, not re-derived, this phase.
FREE_REFERENCE_DATASET_SOURCES: tuple[str, ...] = (
    "logs/research_data/phase26_raw/ (QuantConnect/Lean sample: AAPL, SPY)",
    "logs/research_data/phase27_raw/ (QuantConnect/Lean sample expansion: FOXA, GOOG, NWSA, TWX + additional AAPL/SPY dates)",
)

FREE_REFERENCE_DATASET_USES: tuple[str, ...] = (
    "parser tests", "regression tests", "schema validation", "PIT tests", "ingestion tests", "certification tests",
)

# Part 15's explicit instruction: never silently merge the free dataset
# into future paid data. This constant exists so a future phase's own
# safety test can assert against it by name.
NEVER_SILENTLY_MERGE_WITH_PAID_DATA = True
