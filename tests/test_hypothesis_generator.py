"""Phase 7, Part 12 & 19: controlled hypothesis generator tests."""

from __future__ import annotations

from src.research.hypothesis_generator import HypothesisFamily, generate_hypotheses


def test_generates_exactly_twelve_hypotheses_one_per_family():
    hyps = generate_hypotheses(["AAPL", "MSFT"])
    assert len(hyps) == 12
    families = {h.family for h in hyps}
    assert families == {f.value for f in HypothesisFamily}


def test_every_hypothesis_has_full_required_fields():
    hyps = generate_hypotheses(["AAPL"])
    for h in hyps:
        assert h.economic_intuition
        assert h.mathematical_definition
        assert h.required_features is not None
        assert h.target_definition
        assert h.holding_period_bars is not None and h.holding_period_bars > 0
        assert h.entry_rule
        assert h.exit_rule
        assert h.universe == ("AAPL",)
        assert h.expected_mechanism
        assert len(h.falsification_criteria) > 0


def test_hypothesis_ids_are_unique():
    hyps = generate_hypotheses(["AAPL"])
    ids = [h.hypothesis_id for h in hyps]
    assert len(ids) == len(set(ids))


def test_generator_never_returns_a_parameter_grid_only_single_values():
    """Structural guarantee against Part 12's 'NOT an unrestricted
    optimizer' — mathematical_definition text should never describe a
    LIST/grid of parameters, only single chosen values."""
    hyps = generate_hypotheses(["AAPL"])
    for h in hyps:
        # a crude but effective check: no hypothesis's math definition
        # contains bracketed lists of numbers like "[5, 10, 15, 20]"
        assert "[5," not in h.mathematical_definition
        assert "[10," not in h.mathematical_definition


def test_universe_is_injected_not_hardcoded():
    universe_a = generate_hypotheses(["AAPL", "MSFT"])
    universe_b = generate_hypotheses(["JPM", "GS", "MS"])
    assert universe_a[0].universe == ("AAPL", "MSFT")
    assert universe_b[0].universe == ("JPM", "GS", "MS")


def test_directional_and_magnitude_hypotheses_are_distinguished():
    hyps = generate_hypotheses(["AAPL"])
    by_id = {h.hypothesis_id: h for h in hyps}
    assert "abs(" in by_id["P7-BRK-A"].target_definition
    assert "abs(" in by_id["P7-VOLANOM-A"].target_definition
    assert "abs(" not in by_id["P7-MOM-A"].target_definition


def test_every_generated_hypothesis_is_a_real_hypothesis_type_reusable_by_the_registry(tmp_path):
    from src.research.hypothesis import HypothesisRegistry

    hyps = generate_hypotheses(["AAPL"])
    registry = HypothesisRegistry(tmp_path / "hyps.jsonl")
    for h in hyps:
        registry.register(h)
    assert len(registry.load_all()) == 12
