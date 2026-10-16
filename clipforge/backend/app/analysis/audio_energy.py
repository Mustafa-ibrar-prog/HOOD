"""Per-second loudness curve via ffmpeg's astats filter (streams; no full decode into RAM)."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from ..config import settings
from ..video.ffmpeg import FFmpegError, run

log = logging.getLogger(__name__)
_RMS = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?[\d.]+|-inf|inf|nan)")


def parse_astats(text: str) -> list[float]:
    out: list[float] = []
    for m in _RMS.finditer(text):
        v = m.group(1)
        out.append(-100.0 if v in {"-inf", "nan", "inf"} else max(float(v), -100.0))
    return out


def loudness_curve(audio: Path, sample_rate: int = 16000) -> list[float]:
    """Return RMS level in dBFS for each 1-second window. Empty list on failure."""
    try:
        proc = run(
            [
                settings.ffmpeg_bin, "-v", "error", "-i", str(audio), "-vn",
                "-af", f"aresample={sample_rate},asetnsamples=n={sample_rate}:p=0,astats=metadata=1:reset=1,"
                "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-",
                "-f", "null", "-",
            ],
        )
    except FFmpegError as e:
        log.warning("loudness analysis failed: %s %s", e, e.stderr[-300:])
        return []
    return parse_astats(proc.stdout.decode("utf-8", "replace"))
