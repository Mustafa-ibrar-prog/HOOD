#!/usr/bin/env python3
"""Phase 7 — STEP 4: records MR-002's ALREADY-IMMUTABLE Phase 6 finding
into the new 12-stage research gate vocabulary (src.research.research_gate),
without re-evaluating, re-running, or advancing it in any way. Phase 6's
own narrower gate (src.research.paper_trading_gate) already concluded
NOT_READY for MR-002 (eligible_for_paper_trading_review=False) — this
script does not question that, does not touch src/research/frozen_strategy.py
or logs/research_data/frozen_strategies.jsonl, and does not run any new
analysis on MR-002. It exists only so MR-002 is visible in the SAME gate
vocabulary every future hypothesis will use, per the explicit instruction:
"Existing MR-002 should remain NOT_READY unless an existing immutable
record says otherwise."
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research import FrozenStrategyStore, ResearchGateStore, ResearchLifecycleStage  # noqa: E402


def main() -> None:
    frozen_store = FrozenStrategyStore(Path("logs/research_data/frozen_strategies.jsonl"))
    frozen = frozen_store.get("MR-002", "1.0")
    if frozen is None:
        raise RuntimeError("MR-002 1.0 is not frozen — nothing to record. This script must not fabricate a gate entry for a strategy that was never frozen.")

    gate_store = ResearchGateStore(Path("logs/research_data/phase7_gate_transitions.jsonl"))
    if gate_store.current_stage("MR-002", "1.0") is not None:
        print(f"MR-002 1.0 already has a gate record ({gate_store.current_stage('MR-002', '1.0').value}) — not re-recording.", flush=True)
        return

    # Retroactive stages that Phase 4-6's actual (pre-Phase-7) research
    # process satisfies in substance, even though the FORMAL preregistration/
    # partition machinery this phase introduces didn't exist yet:
    #   IDEA -> PREREGISTERED (Phase 4's Hypothesis, written before any result)
    #   -> DISCOVERY_TESTED -> DEVELOPMENT_VALIDATED (Phase 4's full backtest + walk-forward)
    #   -> STATISTICALLY_SUPPORTED (Phase 5's expanded-universe re-test, PROMISING classification)
    #   -> INDEPENDENT_HOLDOUT (Phase 6 ran the frozen strategy against a genuine holdout)
    # Phase 6's own immutable conclusion was NOT_READY — recorded here as
    # the terminal state, exactly as it already stands.
    chain = [
        (ResearchLifecycleStage.IDEA, "Phase 4: MR-002 hypothesis written before any result (campaign_hypotheses())"),
        (ResearchLifecycleStage.PREREGISTERED, "Phase 4: Hypothesis registered in HypothesisRegistry before testing"),
        (ResearchLifecycleStage.DISCOVERY_TESTED, "Phase 4: cross-sectional IC/quantile analysis performed"),
        (ResearchLifecycleStage.DEVELOPMENT_VALIDATED, "Phase 4-5: full event-driven backtest + walk-forward validation"),
        (ResearchLifecycleStage.STATISTICALLY_SUPPORTED, "Phase 5: PROMISING classification on the expanded US_DIVERSIFIED universe (88%/100% parameter-grid acceptable, viable at 1x/2x/3x costs)"),
        (ResearchLifecycleStage.INDEPENDENT_HOLDOUT, "Phase 6: frozen strategy definition run against a genuinely untouched holdout (temporal + secondary-universe)"),
        (ResearchLifecycleStage.NOT_READY, f"Phase 6's own immutable, unmodified conclusion: holdout evidence did not clear the pre-registered pass criteria (single-symbol/top-5%-trades concentration on the secondary universe; n=3 on the primary temporal holdout) — gate stage NOT_READY, eligible_for_paper_trading_review=False"),
    ]

    for stage, reason in chain:
        gate_store.transition(hypothesis_id="MR-002", hypothesis_version="1.0", to_stage=stage, reason=reason, evidence_summary=f"content_hash={frozen.content_hash()[:16]}")
        print(f"MR-002 1.0 -> {stage.value}: {reason}", flush=True)

    print(f"\nFinal recorded stage: {gate_store.current_stage('MR-002', '1.0').value} — matches Phase 6's own conclusion. Not advanced further.", flush=True)


if __name__ == "__main__":
    main()
