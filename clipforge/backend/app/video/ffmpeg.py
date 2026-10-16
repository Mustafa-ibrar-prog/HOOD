"""Thin, testable wrappers around the ffmpeg / ffprobe binaries.

All media work streams from disk via subprocesses — we never load a whole
video into Python memory.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from ..config import settings

log = logging.getLogger(__name__)


class FFmpegError(RuntimeError):
    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


def ffmpeg_available() -> bool:
    return shutil.which(settings.ffmpeg_bin) is not None and shutil.which(settings.ffprobe_bin) is not None


def run(args: Sequence[str], timeout: Optional[int] = None, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """Run a command, raising FFmpegError with the tail of stderr on failure."""
    log.debug("exec: %s", " ".join(map(str, args)))
    try:
        proc = subprocess.run(
            list(map(str, args)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout or settings.ffmpeg_timeout_seconds,
            check=False,
            cwd=str(cwd) if cwd else None,
        )
    except subprocess.TimeoutExpired as e:
        raise FFmpegError(f"{Path(str(args[0])).name} timed out after {e.timeout}s") from e
    except FileNotFoundError as e:
        raise FFmpegError(f"{args[0]} not found — is FFmpeg installed and on PATH?") from e
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace")[-1500:]
        raise FFmpegError(f"{Path(str(args[0])).name} failed (exit {proc.returncode})", tail)
    return proc


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    has_video: bool


def probe(path: Path) -> MediaInfo:
    proc = run(
        [settings.ffprobe_bin, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        timeout=120,
    )
    data = json.loads(proc.stdout or b"{}")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or (v or {}).get("duration") or 0.0)
    fps = 30.0
    if v and v.get("avg_frame_rate") and v["avg_frame_rate"] != "0/0":
        num, _, den = v["avg_frame_rate"].partition("/")
        try:
            fps = float(num) / float(den or 1)
        except (ValueError, ZeroDivisionError):
            pass
    width, height = int((v or {}).get("width") or 0), int((v or {}).get("height") or 0)
    # Respect rotation metadata (phone footage)
    rotation = 0
    for sd in (v or {}).get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = abs(int(sd["rotation"]))
    if rotation in (90, 270):
        width, height = height, width
    return MediaInfo(duration=duration, width=width, height=height, fps=fps or 30.0, has_audio=a is not None, has_video=v is not None)


def extract_audio(src: Path, dst: Path, sample_rate: int = 16000) -> Path:
    """Mono 16 kHz FLAC — what speech recognisers want, ~10x smaller than WAV."""
    run([settings.ffmpeg_bin, "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "flac", str(dst)])
    return dst


def split_audio(src: Path, out_dir: Path, chunk_seconds: int = 600, bitrate: str = "48k") -> list[tuple[Path, float]]:
    """Split audio into MP3 chunks (for size-limited STT APIs). Returns (path, offset)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    info = probe(src)
    chunks: list[tuple[Path, float]] = []
    offset = 0.0
    idx = 0
    while offset < info.duration - 0.05:
        dst = out_dir / f"chunk_{idx:04d}.mp3"
        run([
            settings.ffmpeg_bin, "-y", "-v", "error", "-ss", f"{offset:.3f}", "-t", str(chunk_seconds), "-i", str(src),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", bitrate, str(dst),
        ])
        chunks.append((dst, offset))
        offset += chunk_seconds
        idx += 1
    return chunks


def extract_frame(src: Path, at: float, dst: Path, width: int = 640) -> Path:
    run([
        settings.ffmpeg_bin, "-y", "-v", "error", "-ss", f"{max(at, 0):.3f}", "-i", str(src),
        "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(dst),
    ], timeout=120)
    return dst
