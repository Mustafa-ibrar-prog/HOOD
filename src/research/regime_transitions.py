"""Phase 10, Part 9: volatility regime transition/persistence/duration
analysis — a NEW, generic module (operates on any discrete state-label
sequence, not volatility-specific machinery, though this phase is its
only caller). Nothing here duplicates src.research.regime, which buckets
panel rows/trades BY a regime label; this module instead characterizes
the regime-label SEQUENCE ITSELF: how often does state X follow state X
(persistence), what's state X's typical episode length (duration), and
what's the full transition matrix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from src.research.analysis import mean

STATES_LOW_NORMAL_HIGH_EXTREME = ("LOW", "NORMAL", "HIGH", "EXTREME")


@dataclass(frozen=True)
class RegimeTransitionReport:
    states: tuple[str, ...]
    transition_counts: dict[str, dict[str, int]]
    transition_probabilities: dict[str, dict[str, float]]  # row-normalized: P(next=col | current=row)
    persistence_probability: dict[str, float | None]  # P(next==same state | current=state) == transition_probabilities[s][s]
    episode_durations: dict[str, list[int]] = field(repr=False)
    mean_duration: dict[str, float | None] = field(default_factory=dict)
    median_duration: dict[str, float | None] = field(default_factory=dict)
    n_episodes: dict[str, int] = field(default_factory=dict)
    n_transitions_observed: int = 0


def _episodes(labels: Sequence[str | None]) -> list[tuple[str, int]]:
    """Run-length encodes a label sequence, dropping None entries as gaps
    (a None never starts, extends, or ends an episode of a real state —
    it simply isn't observed)."""
    episodes: list[tuple[str, int]] = []
    current: str | None = None
    length = 0
    for label in labels:
        if label is None:
            if current is not None:
                episodes.append((current, length))
            current, length = None, 0
            continue
        if label == current:
            length += 1
        else:
            if current is not None:
                episodes.append((current, length))
            current, length = label, 1
    if current is not None:
        episodes.append((current, length))
    return episodes


def analyze_regime_transitions(labels: Sequence[str | None], *, states: Sequence[str] | None = None) -> RegimeTransitionReport:
    """`labels` is a single chronologically-ordered state sequence (e.g.
    one symbol's own regime-label series, or several symbols'
    concatenated with a None gap between them so no spurious
    cross-symbol transition is counted). Transitions are counted between
    ADJACENT non-None entries only."""
    observed_states = sorted({s for s in labels if s is not None})
    all_states = tuple(states) if states is not None else tuple(observed_states)

    counts: dict[str, dict[str, int]] = {s: {t: 0 for t in all_states} for s in all_states}
    n_transitions = 0
    prev: str | None = None
    for label in labels:
        if label is None:
            prev = None
            continue
        if prev is not None and prev in counts and label in counts[prev]:
            counts[prev][label] += 1
            n_transitions += 1
        prev = label

    probabilities: dict[str, dict[str, float]] = {}
    persistence: dict[str, float | None] = {}
    for s in all_states:
        row_total = sum(counts[s].values())
        if row_total == 0:
            probabilities[s] = {t: None for t in all_states}  # type: ignore[dict-item]
            persistence[s] = None
        else:
            probabilities[s] = {t: counts[s][t] / row_total for t in all_states}
            persistence[s] = probabilities[s][s]

    episodes = _episodes(labels)
    durations_by_state: dict[str, list[int]] = {s: [] for s in all_states}
    for state, length in episodes:
        if state in durations_by_state:
            durations_by_state[state].append(length)

    mean_dur: dict[str, float | None] = {}
    median_dur: dict[str, float | None] = {}
    n_episodes: dict[str, int] = {}
    for s in all_states:
        durs = durations_by_state[s]
        n_episodes[s] = len(durs)
        mean_dur[s] = mean(durs) if durs else None
        median_dur[s] = _median(durs) if durs else None

    return RegimeTransitionReport(
        states=all_states, transition_counts=counts, transition_probabilities=probabilities,
        persistence_probability=persistence, episode_durations=durations_by_state,
        mean_duration=mean_dur, median_duration=median_dur, n_episodes=n_episodes,
        n_transitions_observed=n_transitions,
    )


def _median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0
