"""Phase 29, Part 5 — bid/ask/execution-realism certification for ORATS.

Deliberately NOT a bare re-use of `phase26_execution_realism.
build_execution_realism_report` -- that function's Grade A/B/C
distinction checks only whether its `trades` dict is non-empty, which
is correct for Phase 26/27's QuantConnect/Lean data (where a real trade
PRICE tick lives there) but would silently MIS-grade ORATS: this
provider's schema has no per-trade price/size field at all, only an
aggregate daily volume count (see orats_field_provenance.py) --
`orats_ingest.ingest_strike_rows` puts that volume figure into the same
`trades` dict slot Phase 26's store shape expects, which would make a
naive re-use of Phase 26's grader claim Grade A (bid/ask+sizes+trades)
when the honest, Part-5-literal answer is Grade B (bid/ask only -- no
real trade tick exists to compare against). This module reuses Phase
26's real spread-statistics MATH (still valid) but applies the correct
grade boundary for what ORATS's schema actually, really supplies.
"""

from __future__ import annotations

from dataclasses import replace

from src.options.phase26_dataset_builder import InMemoryLeanSampleStore
from src.options.phase26_execution_realism import ExecutionRealismGrade, build_execution_realism_report


def build_orats_execution_realism_report(store: InMemoryLeanSampleStore, contract_id: str):
    """Reuses Phase 26's real spread/midpoint/quote-availability
    computation unchanged, then corrects the grade: ORATS never has a
    real trade-price tick (only an aggregate volume figure, which is
    NOT what Part 5's 'trades' criterion means), so the ceiling grade is
    B, never A -- regardless of what Phase 26's generic has_trades check
    would otherwise claim."""
    report = build_execution_realism_report(store, contract_id)
    if report.grade == ExecutionRealismGrade.A:
        # Downgrade: real bid/ask (+sizes) were found, but the "trades"
        # Phase 26's generic check saw are ORATS's volume-only figures,
        # never a real trade price -- Part 5's A tier requires genuine
        # trade ticks, which this provider's schema does not supply.
        return replace(report, grade=ExecutionRealismGrade.B, n_trades=0)
    return report
