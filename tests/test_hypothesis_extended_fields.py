"""Phase 7 additive extension of src.research.hypothesis.Hypothesis —
confirms every Phase 4-6 hypothesis record still loads unchanged and the
new fields round-trip correctly."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.research.hypothesis import Hypothesis, HypothesisRegistry


def _phase4_style_dict():
    """Exactly the shape a Phase 4 hypothesis record was written in —
    none of the Phase 7 fields present at all."""
    return {
        "hypothesis_id": "MOM-001", "name": "5-Day Momentum", "description": "d", "economic_intuition": "e",
        "mathematical_definition": "m", "required_data": ["daily OHLCV"], "required_features": ["roc_5"],
        "prediction_horizon_bars": 5, "test_methodology": "t", "expected_direction": "positive", "assumptions": [],
        "version": "1.0", "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
    }


def test_a_pre_phase7_record_loads_with_empty_defaults_for_new_fields():
    h = Hypothesis.from_dict(_phase4_style_dict())
    assert h.family == ""
    assert h.target_definition == ""
    assert h.holding_period_bars is None
    assert h.entry_rule == ""
    assert h.exit_rule == ""
    assert h.universe == ()
    assert h.expected_mechanism == ""
    assert h.falsification_criteria == ()


def test_new_fields_round_trip_through_to_dict_and_from_dict():
    h = Hypothesis(
        hypothesis_id="P7-X", name="n", description="d", economic_intuition="e", mathematical_definition="m",
        required_data=(), required_features=(), prediction_horizon_bars=5, test_methodology="t",
        expected_direction="positive", assumptions=(), family="momentum", target_definition="target_future_return_5bar",
        holding_period_bars=5, entry_rule="LONG top quantile", exit_rule="after 5 bars", universe=("AAPL", "MSFT"),
        expected_mechanism="trend continuation", falsification_criteria=("no IC", "sign flips"),
    )
    restored = Hypothesis.from_dict(json.loads(json.dumps(h.to_dict(), default=str)))
    assert restored.family == "momentum"
    assert restored.holding_period_bars == 5
    assert restored.universe == ("AAPL", "MSFT")
    assert restored.falsification_criteria == ("no IC", "sign flips")


def test_existing_hypothesis_registry_file_from_before_phase7_still_loads(tmp_path):
    """Simulates a registry file written before Phase 7 (no new fields at
    all) and confirms HypothesisRegistry.load_all() doesn't choke on it."""
    path = tmp_path / "hyps.jsonl"
    with path.open("w") as f:
        f.write(json.dumps(_phase4_style_dict()) + "\n")
    registry = HypothesisRegistry(path)
    loaded = registry.load_all()
    assert len(loaded) == 1
    assert loaded[0].hypothesis_id == "MOM-001"
    assert loaded[0].family == ""


def test_registering_a_phase7_generated_hypothesis_alongside_old_ones(tmp_path):
    from src.research.hypothesis_generator import generate_hypotheses

    registry = HypothesisRegistry(tmp_path / "hyps.jsonl")
    old = Hypothesis.from_dict(_phase4_style_dict())
    registry.register(old)
    new = generate_hypotheses(["AAPL"])[0]
    registry.register(new)
    all_loaded = registry.load_all()
    assert len(all_loaded) == 2
    assert {h.hypothesis_id for h in all_loaded} == {"MOM-001", new.hypothesis_id}
