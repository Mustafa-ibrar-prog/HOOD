"""Generate overlapping, sentence-aligned candidate windows."""
from __future__ import annotations

from dataclasses import dataclass

from .sentences import Unit

# Lead-in/out padding around speech so cuts don't clip the first/last syllable.
PAD_BEFORE = 0.20
PAD_AFTER = 0.45


@dataclass(frozen=True)
class Window:
    first: int  # unit index (inclusive)
    last: int  # unit index (inclusive)
    start: float  # seconds, padded
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def window_bounds(units: list[Unit], first: int, last: int, max_seconds: float, media_duration: float | None = None) -> tuple[float, float]:
    """Padded [start, end] for a unit range, never cutting into neighbouring speech, never exceeding max_seconds."""
    u0, u1 = units[first], units[last]
    prev_end = units[first - 1].end if first > 0 else 0.0
    next_start = units[last + 1].start if last + 1 < len(units) else (media_duration or u1.end + PAD_AFTER)
    start = max(u0.start - PAD_BEFORE, (prev_end + u0.start) / 2 if first > 0 else 0.0, 0.0)
    end = min(u1.end + PAD_AFTER, (u1.end + next_start) / 2 if last + 1 < len(units) else u1.end + PAD_AFTER)
    if media_duration:
        end = min(end, media_duration)
    if end - start > max_seconds:
        # trim padding first, symmetric-ish, then hard cap
        start = max(start, u0.start - 0.05)
        end = min(end, start + max_seconds)
    return round(start, 3), round(end, 3)


def generate_windows(
    units: list[Unit],
    min_seconds: float = 15.0,
    max_seconds: float = 60.0,
    media_duration: float | None = None,
    max_internal_gap: float = 4.0,
    max_windows: int = 60_000,
) -> list[Window]:
    """Overlapping, sentence-aligned candidates.

    Every unit may start a window; every later unit that *finishes a sentence*
    (terminal punctuation, or followed by a clear pause) may end it, as long as the
    duration is within [min_seconds, max_seconds]. Windows never span a silence
    longer than ``max_internal_gap``. For very long transcripts, start positions
    are strided so the candidate count stays bounded.
    """
    n = len(units)
    out: list[Window] = []
    limit = max_seconds - 0.5  # leave room for padding
    stride = 1
    if n > 0:
        avg_ends = max(1.0, (max_seconds - min_seconds) / max(sum(u.duration for u in units) / n, 0.5))
        stride = max(1, int(n * avg_ends / max_windows) + 1) if n * avg_ends > max_windows else 1
    for i in range(0, n, stride):
        for j in range(i, n):
            if j > i and units[j].gap_before > max_internal_gap:
                break
            span = units[j].end - units[i].start
            if span > limit:
                break
            if span < min_seconds - 0.6:
                continue
            ends_sentence = units[j].terminal or (j + 1 < n and units[j + 1].gap_before >= 0.6) or j + 1 == n
            if not ends_sentence:
                continue
            start, end = window_bounds(units, i, j, max_seconds, media_duration)
            if min_seconds <= end - start <= max_seconds:
                out.append(Window(i, j, start, end))
    return out
