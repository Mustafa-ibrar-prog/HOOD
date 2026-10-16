"""Caption cue building and ASS (Advanced SubStation Alpha) subtitle generation.

ASS lets libass render bold, outlined, word-highlighted captions directly in
the ffmpeg filter graph — no extra dependencies.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..models import CaptionLine, CaptionStyle, Word

_MARKER = re.compile(r"^\[.*\]$|^\(.*\)$")
_SENT_END = re.compile(r"[.!?…]$")


def build_caption_lines(words: list[Word], clip_start: float, clip_end: float, words_per_caption: int = 3,
                        max_chars: int = 26) -> list[CaptionLine]:
    """Group words into short caption cues with times relative to the clip start."""
    ws = [w for w in words if w.end > clip_start and w.start < clip_end and not _MARKER.match(w.text.strip())]
    lines: list[CaptionLine] = []
    cur: list[Word] = []

    def flush() -> None:
        if not cur:
            return
        rel = [Word(start=round(max(w.start - clip_start, 0.0), 3), end=round(min(w.end, clip_end) - clip_start, 3), text=w.text) for w in cur]
        lines.append(CaptionLine(start=rel[0].start, end=rel[-1].end, text=" ".join(w.text for w in rel), words=rel))
        cur.clear()

    for i, w in enumerate(ws):
        if cur:
            gap = w.start - cur[-1].end
            chars = len(" ".join(x.text for x in cur)) + 1 + len(w.text)
            if len(cur) >= words_per_caption or gap > 0.6 or chars > max_chars or _SENT_END.search(cur[-1].text):
                flush()
        cur.append(w)
    flush()
    # Extend each cue to the next one (no flicker between words), capped.
    dur = clip_end - clip_start
    for i, ln in enumerate(lines):
        nxt = lines[i + 1].start if i + 1 < len(lines) else dur
        ln.end = round(min(max(ln.end, ln.start + 0.3), nxt if nxt - ln.end < 0.8 else ln.end + 0.3, dur), 3)
    return lines


def _ass_color(hex_rgb: str, alpha: int = 0) -> str:
    r, g, b = hex_rgb[1:3], hex_rgb[3:5], hex_rgb[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ass_time(t: float) -> str:
    t = max(t, 0.0)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    cs = int(round((s - int(s)) * 100))
    if cs == 100:
        cs = 99
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def line_words(line: CaptionLine) -> list[Word]:
    """Word timings for a cue. If the user edited the text so tokens no longer
    match the stored words, spread the new tokens evenly across the cue."""
    tokens = line.text.split()
    if line.words and len(line.words) == len(tokens):
        return [Word(start=w.start, end=w.end, text=t) for w, t in zip(line.words, tokens)]
    if not tokens:
        return []
    span = max(line.end - line.start, 0.1)
    step = span / len(tokens)
    return [Word(start=line.start + i * step, end=line.start + (i + 1) * step, text=t) for i, t in enumerate(tokens)]


def write_ass(lines: list[CaptionLine], style: CaptionStyle, width: int, height: int, path: Path) -> Path:
    scale = height / 1920.0
    font_size = int(style.font_size * scale)
    outline = round(style.outline_width * scale, 1)
    align = {"bottom": 2, "middle": 5, "top": 8}[style.position]
    margin_v = int({"bottom": 0.22, "middle": 0.0, "top": 0.12}[style.position] * height)
    margin_lr = int(70 * scale)
    primary = _ass_color(style.primary_color)
    highlight = _ass_color(style.highlight_color)
    outline_c = _ass_color(style.outline_color)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{style.font},{font_size},{primary},{highlight},{outline_c},&H80000000,-1,0,0,0,100,100,0,0,1,{outline},{round(2*scale,1)},{align},{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    for ln in lines:
        text = ln.text.upper() if style.uppercase else ln.text
        if not text.strip():
            continue
        if style.highlight_active_word:
            ws = line_words(CaptionLine(start=ln.start, end=ln.end, text=text, words=ln.words))
            for i, w in enumerate(ws):
                seg_start = ln.start if i == 0 else w.start
                seg_end = ws[i + 1].start if i + 1 < len(ws) else ln.end
                if seg_end <= seg_start:
                    continue
                parts = []
                for j, x in enumerate(ws):
                    t = _escape(x.text)
                    parts.append(f"{{\\c{highlight}}}{t}{{\\c{primary}}}" if j == i else t)
                events.append(f"Dialogue: 0,{_ass_time(seg_start)},{_ass_time(seg_end)},Cap,,0,0,0,,{' '.join(parts)}")
        else:
            events.append(f"Dialogue: 0,{_ass_time(ln.start)},{_ass_time(ln.end)},Cap,,0,0,0,,{_escape(text)}")
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return path
