"""Turn a transcript into sentence-like units with precise timings.

Clip boundaries are only ever placed on these unit boundaries, which is what
keeps clips from starting or ending mid-sentence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Transcript, Word

_TERMINAL = re.compile(r"[.!?…]+[\"')\]]*$")
_MARKER = re.compile(r"^\[(.+?)\]$|^\((.+?)\)$")


@dataclass
class Unit:
    id: int
    start: float
    end: float
    text: str
    words: list[Word]
    markers: list[str] = field(default_factory=list)  # e.g. ["laughter", "applause", "music"]
    gap_before: float = 0.0
    terminal: bool = False  # ends with sentence punctuation

    @property
    def duration(self) -> float:
        return self.end - self.start


def _synth_words(start: float, end: float, text: str) -> list[Word]:
    """Distribute a segment's time over its tokens by character length."""
    tokens = text.split()
    if not tokens:
        return []
    total_chars = sum(len(t) + 1 for t in tokens)
    span = max(end - start, 0.05 * len(tokens))
    out, t = [], start
    for tok in tokens:
        d = span * (len(tok) + 1) / total_chars
        out.append(Word(start=round(t, 3), end=round(t + d, 3), text=tok))
        t += d
    return out


def flatten_words(transcript: Transcript) -> list[Word]:
    words: list[Word] = []
    for seg in transcript.segments:
        ws = seg.words or _synth_words(seg.start, seg.end, seg.text)
        for w in ws:
            txt = w.text.strip()
            if not txt:
                continue
            if words and w.start < words[-1].start:  # out-of-order guard
                continue
            words.append(Word(start=w.start, end=max(w.end, w.start + 0.05), text=txt))
    return words


def build_units(transcript: Transcript, max_unit_seconds: float = 15.0) -> list[Unit]:
    words = flatten_words(transcript)
    if not words:
        return []
    punct_ratio = sum(1 for w in words if _TERMINAL.search(w.text)) / max(len(words), 1)
    punctuated = punct_ratio > 0.02
    pause_split = 0.9 if punctuated else 0.55
    soft_max = max_unit_seconds * (0.8 if punctuated else 0.6)

    units: list[Unit] = []
    cur: list[Word] = []
    markers: list[str] = []

    def flush(terminal: bool) -> None:
        nonlocal cur, markers
        spoken = [w for w in cur if not _MARKER.match(w.text)]
        if spoken:
            prev_end = units[-1].end if units else 0.0
            units.append(
                Unit(
                    id=len(units),
                    start=spoken[0].start,
                    end=spoken[-1].end,
                    text=" ".join(w.text for w in spoken),
                    words=spoken,
                    markers=markers,
                    gap_before=max(0.0, spoken[0].start - prev_end),
                    terminal=terminal,
                )
            )
        elif markers and units:
            units[-1].markers.extend(markers)
        cur, markers = [], []

    for i, w in enumerate(words):
        m = _MARKER.match(w.text)
        if m:
            markers.append((m.group(1) or m.group(2)).strip().lower())
            continue
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt.start - w.end) if nxt else 99.0
        dur = w.end - cur[0].start
        is_terminal = bool(_TERMINAL.search(w.text))
        if is_terminal or gap >= pause_split:
            flush(is_terminal)
        elif dur >= soft_max and (w.text.endswith(",") or gap >= 0.25):
            flush(False)
        elif dur >= max_unit_seconds:
            flush(False)
    if cur or markers:
        flush(bool(cur and _TERMINAL.search(cur[-1].text)))
    return units
