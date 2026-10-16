"""Pick the best non-redundant set of moments from scored candidates."""
from __future__ import annotations

import re
from typing import Callable, Iterable, Sequence, TypeVar

from .lexicon import STOPWORDS

T = TypeVar("T")
_WORD = re.compile(r"[a-z0-9']+")


def overlap_seconds(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def temporal_iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    inter = overlap_seconds(a, b)
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def select_diverse(
    items: Sequence[T],
    *,
    score: Callable[[T], float],
    span: Callable[[T], tuple[float, float]],
    text: Callable[[T], str],
    max_items: int,
    max_overlap_seconds: float = 2.0,
    max_text_similarity: float = 0.5,
    min_score: float = 0.0,
) -> list[T]:
    """Greedy non-maximum suppression over time *and* content.

    Highest score first; a candidate is skipped if it overlaps an already-chosen
    clip by more than ``max_overlap_seconds`` or repeats the same idea
    (content-word Jaccard above ``max_text_similarity``).
    """
    chosen: list[T] = []
    chosen_words: list[set[str]] = []
    for it in sorted(items, key=score, reverse=True):
        if len(chosen) >= max_items:
            break
        if score(it) < min_score and chosen:
            break
        sp = span(it)
        if any(overlap_seconds(sp, span(c)) > max_overlap_seconds for c in chosen):
            continue
        words = content_words(text(it))
        if any(jaccard(words, cw) > max_text_similarity for cw in chosen_words):
            continue
        chosen.append(it)
        chosen_words.append(words)
    return chosen


def flatten(xs: Iterable[Iterable[T]]) -> list[T]:
    return [x for sub in xs for x in sub]
