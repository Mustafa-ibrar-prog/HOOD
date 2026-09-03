#!/usr/bin/env python3
"""Phase 25, STEP 1 — prints the consolidated ORATS provider-validation
report: the Part 4 field matrix, the PAID_PROOF_REQUIRED log, the Part
20 readiness scorecard, the Part 21 architecture-preservation note, the
Part 22 ingestion-flow design, the Part 23 certification spec, and the
Part 26/27 final decision and purchase recommendation. This is a
reporting script only -- it fetches no new data (every piece of real
evidence behind this report was already gathered this phase via
WebFetch/WebSearch against publicly reachable GitHub-hosted source
code, never via a paid account or API key) and registers no hypothesis
(Part 24: no new alpha hypotheses, no strategy, no backtest this phase).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.options.data_quality_certification import DATA_QUALITY_CERTIFICATION_SPEC  # noqa: E402
from src.options.provider_field_validation import (  # noqa: E402
    ORATS_FIELD_VALIDATION_MATRIX,
    PAID_PROOF_REQUIRED_LOG,
    rows_by_classification,
)
from src.options.provider_ingestion_pipeline import ARCHITECTURE_ROLE_PRESERVATION, PROVIDER_NEUTRAL_INGESTION_FLOW  # noqa: E402
from src.options.provider_readiness_scorecard import ORATS_READINESS_SCORECARD  # noqa: E402
from src.options.provider_validation_decision import FINAL_DECISION, FINAL_DECISION_RATIONALE, PURCHASE_RECOMMENDATION  # noqa: E402


def main() -> None:
    print(f"{'=' * 100}\nORATS FIELD VALIDATION MATRIX (Part 4)\n{'=' * 100}", flush=True)
    for row in ORATS_FIELD_VALIDATION_MATRIX:
        print(f"\n[{row.classification.value}] ({row.evidence_tier.value}) {row.field_category}", flush=True)
        print(f"  evidence: {row.evidence_source}", flush=True)
        print(f"  notes   : {row.notes}", flush=True)

    print(f"\n{'=' * 100}\nCLASSIFICATION COUNTS\n{'=' * 100}", flush=True)
    for classification, fields in rows_by_classification().items():
        print(f"  {classification.value}: {len(fields)} fields", flush=True)

    print(f"\n{'=' * 100}\nPAID_PROOF_REQUIRED LOG (Part 2)\n{'=' * 100}", flush=True)
    for entry in PAID_PROOF_REQUIRED_LOG:
        print(f"\n{entry.provider} -> {entry.classification}", flush=True)
        print(f"  {entry.requirement_note}", flush=True)

    print(f"\n{'=' * 100}\nREADINESS SCORECARD (Part 20)\n{'=' * 100}", flush=True)
    sc = ORATS_READINESS_SCORECARD
    for s in sc.scores:
        print(f"  {s.dimension.value:22s} {s.score}/5  -- {s.rationale}", flush=True)
    print(f"\n  TOTAL: {sc.total_score()}/{sc.max_possible_score()}", flush=True)
    print(f"  Critical blockers triggered: {[d.value for d in sc.triggered_critical_blockers()] or 'none'}", flush=True)
    print(f"  DISQUALIFIED: {sc.disqualified()}", flush=True)

    print(f"\n{'=' * 100}\nARCHITECTURE ROLE PRESERVATION (Part 21)\n{'=' * 100}", flush=True)
    print(f"  {ARCHITECTURE_ROLE_PRESERVATION}", flush=True)

    print(f"\n{'=' * 100}\nPROVIDER-NEUTRAL INGESTION FLOW DESIGN (Part 22)\n{'=' * 100}", flush=True)
    print("  " + " -> ".join(stage.value for stage in PROVIDER_NEUTRAL_INGESTION_FLOW), flush=True)

    print(f"\n{'=' * 100}\nDATA QUALITY CERTIFICATION SPEC (Part 23) -- design only, nothing assessed yet\n{'=' * 100}", flush=True)
    for c in DATA_QUALITY_CERTIFICATION_SPEC:
        print(f"  {c.criterion_id}: {c.title}", flush=True)

    print(f"\n{'=' * 100}\nFINAL DECISION (Part 26)\n{'=' * 100}", flush=True)
    print(f"  {FINAL_DECISION.value.upper()}", flush=True)
    print(f"  {FINAL_DECISION_RATIONALE}", flush=True)

    print(f"\n{'=' * 100}\nPURCHASE RECOMMENDATION (Part 27) -- NOT ACTED UPON, AWAITING HUMAN APPROVAL\n{'=' * 100}", flush=True)
    r = PURCHASE_RECOMMENDATION
    print(f"  RECOMMENDED_PROVIDER      : {r.recommended_provider}", flush=True)
    print(f"  EXACT_PRODUCT             : {r.exact_product}", flush=True)
    print(f"  WHY                       : {r.why}", flush=True)
    print(f"  FIELDS_AVAILABLE          : {r.fields_available}", flush=True)
    print(f"  HISTORICAL_DEPTH          : {r.historical_depth}", flush=True)
    print(f"  APPROXIMATE_COST          : {r.approximate_cost}", flush=True)
    print(f"  TRIAL_AVAILABILITY        : {r.trial_availability}", flush=True)
    print(f"  LICENSING                 : {r.licensing}", flush=True)
    print(f"  EXPECTED_RESEARCH_GAIN    : {r.expected_research_gain}", flush=True)
    print(f"  AWAITING_HUMAN_APPROVAL   : {r.awaiting_human_approval}", flush=True)

    print("\nSTEP 1 COMPLETE — provider validation report only. No data purchased. No account created. "
          "No API key obtained. No alpha hypothesis registered. No strategy created. No order placed.", flush=True)


if __name__ == "__main__":
    main()
