"""Parsers for platform caption formats (YouTube json3 and WebVTT).

Both return a list of ``Segment`` with word-level timing when the source has it
(YouTube auto-captions include per-word offsets).
"""
from __future__ import annotations

import html
import re

from ..models import Segment, Word

_TS = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})"


def _ts_to_s(h: str | None, m: str, s: str, ms: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _clean(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_json3(data: dict) -> list[Segment]:
    segments: list[Segment] = []
    events = [e for e in data.get("events", []) if e.get("segs")]
    for idx, ev in enumerate(events):
        start = ev.get("tStartMs", 0) / 1000.0
        end = start + ev.get("dDurationMs", 0) / 1000.0
        # Auto-caption events overlap the following event; clamp to it.
        if idx + 1 < len(events):
            nxt = events[idx + 1].get("tStartMs", 0) / 1000.0
            if start < nxt < end:
                end = nxt
        segs = ev["segs"]
        texts = [s.get("utf8", "") for s in segs]
        joined = _clean("".join(texts))
        if not joined:
            continue
        words: list[Word] = []
        has_offsets = len(segs) > 1 or any("tOffsetMs" in s for s in segs)
        if has_offsets:
            starts = [start + s.get("tOffsetMs", 0) / 1000.0 for s in segs]
            for i, s in enumerate(segs):
                w = _clean(s.get("utf8", ""))
                if not w:
                    continue
                w_end = starts[i + 1] if i + 1 < len(segs) else end
                w_end = max(w_end, starts[i] + 0.15)
                words.append(Word(start=round(starts[i], 3), end=round(w_end, 3), text=w))
            if words:
                end = max(end, words[-1].end)
        segments.append(Segment(start=round(start, 3), end=round(max(end, start + 0.1), 3), text=joined, words=words))
    return segments


_CUE_RE = re.compile(rf"^{_TS}\s+-->\s+{_TS}")
_INLINE_TS = re.compile(rf"<{_TS}>")


def parse_vtt(text: str) -> list[Segment]:
    lines = text.replace("\r\n", "\n").split("\n")
    segments: list[Segment] = []
    i = 0
    last_text = ""
    while i < len(lines):
        m = _CUE_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        start = _ts_to_s(*m.groups()[0:4])
        end = _ts_to_s(*m.groups()[4:8])
        i += 1
        body: list[str] = []
        # a cue ends at a truly empty line (YouTube auto-captions use " " lines inside cues)
        while i < len(lines) and lines[i] != "":
            body.append(lines[i])
            i += 1
        tagged = [b for b in body if _INLINE_TS.search(b)]
        if tagged:
            # YouTube auto-caption style: words with inline timestamps.
            line = tagged[-1]
            # first word has the cue start time
            parts = _INLINE_TS.split(line)
            # split yields: [text0, h,m,s,ms, text1, h,m,s,ms, text2, ...]
            words: list[Word] = []
            first = _clean(parts[0])
            pending: list[tuple[float, str]] = []
            if first:
                pending.append((start, first))
            for j in range(1, len(parts) - 4, 5):
                t = _ts_to_s(parts[j], parts[j + 1], parts[j + 2], parts[j + 3])
                w = _clean(parts[j + 4])
                if w:
                    pending.append((t, w))
            for k, (t, w) in enumerate(pending):
                t_end = pending[k + 1][0] if k + 1 < len(pending) else end
                for token in w.split():
                    words.append(Word(start=round(t, 3), end=round(max(t_end, t + 0.1), 3), text=token))
            if words:
                seg_text = " ".join(w.text for w in words)
                segments.append(Segment(start=words[0].start, end=round(end, 3), text=seg_text, words=words))
                last_text = seg_text
            continue
        cue_text = _clean(" ".join(body))
        if not cue_text:
            continue
        # Rolling auto captions repeat the previous line; drop exact repeats.
        if cue_text == last_text or (segments and end - start < 0.05):
            continue
        if last_text and cue_text.startswith(last_text):
            cue_text = cue_text[len(last_text):].strip()
            if not cue_text:
                continue
        segments.append(Segment(start=round(start, 3), end=round(end, 3), text=cue_text))
        last_text = cue_text
    return segments
