"""Find, score, deduplicate and rank the best moments in a transcript."""
from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Callable, Optional

from ..models import Clip, JobOptions
from .candidates import Window, generate_windows, window_bounds
from .copywriter import heuristic_copy
from .heuristic import HeuristicScorer, ScoredWindow, explain
from .llm import AnalysisError, LLMAnalyzer, LLMMoment, get_llm_analyzer
from .scoring import blend, weighted_total
from .selection import select_diverse
from .sentences import Unit

log = logging.getLogger(__name__)

LLM_WEIGHT = 0.7  # final breakdown = 0.7 * LLM judgement + 0.3 * transparent heuristic signals
MIN_HEURISTIC_SCORE = 35.0


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", s.lower())).strip()


def clip_text(units: list[Unit], w: Window) -> str:
    return " ".join(u.text for u in units[w.first : w.last + 1])


def fit_unit_range(units: list[Unit], first: int, last: int, min_s: float, max_s: float,
                   media_duration: Optional[float]) -> Optional[Window]:
    """Clamp an arbitrary unit range (e.g. from an LLM) to valid ids and duration limits."""
    n = len(units)
    if n == 0:
        return None
    first, last = max(0, min(first, n - 1)), max(0, min(last, n - 1))
    if last < first:
        first, last = last, first
    # too long -> drop trailing units, then leading ones
    while last > first and units[last].end - units[first].start > max_s - 0.5:
        last -= 1
    if units[last].end - units[first].start > max_s - 0.5:
        return None  # a single unit longer than the limit
    # too short -> extend forward, then backward
    while units[last].end - units[first].start < min_s and last + 1 < n and units[last + 1].end - units[first].start <= max_s - 0.5:
        last += 1
    while units[last].end - units[first].start < min_s and first > 0 and units[last].end - units[first - 1].start <= max_s - 0.5:
        first -= 1
    start, end = window_bounds(units, first, last, max_s, media_duration)
    if end - start < min(min_s, 5.0):
        return None
    return Window(first, last, start, end)


def _verbatim_hook(quote: str, units: list[Unit], w: Window) -> str:
    """Use the model's hook quote only if it really appears at the start of the clip."""
    opening = " ".join(u.text for u in units[w.first : min(w.first + 2, w.last + 1)])
    if quote and _norm(quote) and _norm(quote) in _norm(opening):
        return quote
    return units[w.first].text


def _make_clip(units: list[Unit], sw: ScoredWindow, *, explanation: str, reason: str, hook: str,
               platforms: dict, analyzer: str, options: JobOptions, source_title: str) -> Clip:
    text = clip_text(units, sw.window)
    return Clip(
        id=uuid.uuid4().hex[:10],
        start=sw.window.start,
        end=sw.window.end,
        score=sw.total,
        breakdown=sw.breakdown,
        content_type=sw.content_type,
        hook=hook,
        explanation=explanation,
        selection_reason=reason,
        transcript=text,
        platforms=platforms or heuristic_copy(hook, text, sw.content_type, source_title),
        render=options.render.model_copy(deep=True),
        analyzer=analyzer,
    )


def detect_moments(
    units: list[Unit],
    *,
    options: JobOptions,
    title: str,
    media_duration: Optional[float],
    energy: Optional[list[float]] = None,
    warnings: list[str],
    analyzer: Optional[LLMAnalyzer] = None,
    use_llm: bool = True,
    progress: Callable[[float, str], None] = lambda f, m: None,
) -> tuple[list[Clip], str]:
    min_s, max_s = options.min_clip_seconds, min(options.max_clip_seconds, 60.0)
    scorer = HeuristicScorer(units, energy)

    # ---------------- LLM path
    if use_llm:
        try:
            analyzer = analyzer or get_llm_analyzer()
        except AnalysisError as e:
            warnings.append(f"AI analysis unavailable ({e}); used built-in heuristics.")
            analyzer = None
    else:
        analyzer = None
    if analyzer is not None:
        progress(0.1, f"Asking {analyzer.name} ({analyzer.model}) to find the strongest moments…")
        moments: list[LLMMoment] = []
        for attempt in range(3):
            try:
                moments = analyzer.find_moments(units, title=title, duration=media_duration,
                                                n_wanted=options.max_clips, min_s=min_s, max_s=max_s)
                break
            except AnalysisError as e:
                if e.retryable and attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue
                warnings.append(f"AI analysis failed ({e}); used built-in heuristics instead.")
                moments = []
                break
        scored: list[tuple[ScoredWindow, LLMMoment]] = []
        for m in moments:
            w = fit_unit_range(units, m.start_id, m.end_id, min_s, max_s, media_duration)
            if not w:
                continue
            h = scorer.score(w)
            b = blend(m.scores, h.breakdown, LLM_WEIGHT)
            sw = ScoredWindow(w, b, weighted_total(b), m.content_type, h.reasons, h.penalties)
            scored.append((sw, m))
        chosen = select_diverse(
            scored, score=lambda x: x[0].total, span=lambda x: (x[0].window.start, x[0].window.end),
            text=lambda x: clip_text(units, x[0].window), max_items=options.max_clips,
        )
        if chosen:
            clips = []
            for sw, m in chosen:
                _, h_reason = explain(sw)
                clips.append(_make_clip(
                    units, sw,
                    explanation=m.explanation or explain(sw)[0],
                    reason=m.selection_reason or h_reason,
                    hook=_verbatim_hook(m.hook_quote, units, sw.window),
                    platforms=m.platforms, analyzer=f"{analyzer.name}:{analyzer.model}",
                    options=options, source_title=title,
                ))
            return _rank(clips), f"{analyzer.name}:{analyzer.model}"
        if moments:
            warnings.append("The AI's suggested moments didn't fit the clip constraints; used built-in heuristics.")

    # ---------------- heuristic path
    progress(0.3, "Scoring candidate moments…")
    windows = generate_windows(units, min_s, max_s, media_duration=media_duration)
    if not windows:
        return [], "heuristic"
    scored_h = [scorer.score(w) for w in windows]
    chosen_h = select_diverse(
        scored_h, score=lambda s: s.total, span=lambda s: (s.window.start, s.window.end),
        text=lambda s: clip_text(units, s.window), max_items=options.max_clips, min_score=MIN_HEURISTIC_SCORE,
    )
    clips = []
    for sw in chosen_h:
        expl, reason = explain(sw)
        clips.append(_make_clip(units, sw, explanation=expl, reason=reason, hook=units[sw.window.first].text,
                                platforms={}, analyzer="heuristic", options=options, source_title=title))
    return _rank(clips), "heuristic"


def _rank(clips: list[Clip]) -> list[Clip]:
    clips.sort(key=lambda c: c.score, reverse=True)
    for i, c in enumerate(clips, 1):
        c.rank = i
    return clips
