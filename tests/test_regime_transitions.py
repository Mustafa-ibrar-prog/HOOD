"""Phase 10, Part 9 & 28: regime transition/persistence/duration tests
(src/research/regime_transitions.py), using synthetic label sequences
with KNOWN transition/duration structure.
"""

from __future__ import annotations

from src.research.regime_transitions import analyze_regime_transitions


def test_perfectly_persistent_regime_has_persistence_probability_one():
    labels = ["LOW"] * 10
    report = analyze_regime_transitions(labels, states=("LOW", "HIGH"))
    assert report.persistence_probability["LOW"] == 1.0
    assert report.n_episodes["LOW"] == 1
    assert report.mean_duration["LOW"] == 10


def test_alternating_regime_has_zero_persistence_probability():
    labels = ["LOW", "HIGH"] * 5
    report = analyze_regime_transitions(labels, states=("LOW", "HIGH"))
    assert report.persistence_probability["LOW"] == 0.0
    assert report.persistence_probability["HIGH"] == 0.0
    assert report.n_episodes["LOW"] == 5
    assert all(d == 1 for d in report.episode_durations["LOW"])


def test_known_episode_durations_are_computed_correctly():
    labels = ["LOW"] * 3 + ["HIGH"] * 5 + ["LOW"] * 2
    report = analyze_regime_transitions(labels, states=("LOW", "HIGH"))
    assert report.episode_durations["LOW"] == [3, 2]
    assert report.episode_durations["HIGH"] == [5]
    assert report.mean_duration["LOW"] == 2.5
    assert report.median_duration["HIGH"] == 5


def test_none_entries_are_gaps_not_transitions():
    labels = ["LOW", "LOW", None, "HIGH", "HIGH"]
    report = analyze_regime_transitions(labels, states=("LOW", "HIGH"))
    # the LOW->HIGH transition across the None gap must NOT be counted
    assert report.transition_counts["LOW"]["HIGH"] == 0
    assert report.transition_counts["LOW"]["LOW"] == 1
    assert report.transition_counts["HIGH"]["HIGH"] == 1
    assert report.n_transitions_observed == 2


def test_transition_probabilities_sum_to_one_per_row():
    labels = ["LOW", "NORMAL", "HIGH", "NORMAL", "LOW", "NORMAL", "HIGH", "EXTREME", "HIGH", "NORMAL"]
    report = analyze_regime_transitions(labels)
    for state, row in report.transition_probabilities.items():
        total = sum(v for v in row.values() if v is not None)
        if report.n_episodes[state] > 0 or any(row.values()):
            assert abs(total - 1.0) < 1e-9 or total == 0.0


def test_state_never_observed_has_none_persistence():
    labels = ["LOW", "LOW", "LOW"]
    report = analyze_regime_transitions(labels, states=("LOW", "EXTREME"))
    assert report.persistence_probability["EXTREME"] is None
    assert report.n_episodes["EXTREME"] == 0


def test_empty_sequence_handled_gracefully():
    report = analyze_regime_transitions([], states=("LOW", "HIGH"))
    assert report.n_transitions_observed == 0
    assert report.persistence_probability["LOW"] is None
