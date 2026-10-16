"""Choose how to obtain a timestamped transcript for a job.

Strategy for ``TRANSCRIPTION_PROVIDER=auto``:
  1. Human-made platform captions (most accurate text).
  2. A configured speech-to-text provider (faster-whisper if installed, else OpenAI if keyed).
  3. Platform auto-generated captions (have word timing, less accurate text).
  4. Otherwise fail with an actionable error.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from ..config import settings
from ..models import Transcript
from .providers import STT_PROVIDERS, TranscriptionError

log = logging.getLogger(__name__)


def _usable(t: Optional[Transcript]) -> bool:
    return bool(t and len([s for s in t.segments if s.text.strip()]) >= 3)


def obtain_transcript(
    *,
    captions: Optional[tuple[Transcript, bool]],
    audio_path_fn: Callable[[], Path],
    language: str,
    progress: Callable[[float, str], None],
    warnings: list[str],
) -> Transcript:
    """``captions`` is what the ingest provider found; ``audio_path_fn`` lazily extracts audio."""
    mode = settings.transcription_provider.lower()
    manual = captions[0] if captions and captions[1] else None
    auto = captions[0] if captions and not captions[1] else None

    def run_stt(name: str) -> Transcript:
        provider = STT_PROVIDERS[name]
        ok, why = provider.available()
        if not ok:
            raise TranscriptionError(f"Speech-to-text provider '{name}' unavailable: {why}", "stt_unavailable")
        return provider.transcribe(audio_path_fn(), language, progress)

    if mode == "youtube_captions":
        if _usable(manual):
            return manual  # type: ignore[return-value]
        if _usable(auto):
            return auto  # type: ignore[return-value]
        raise TranscriptionError(
            "This video has no captions in the requested language, and TRANSCRIPTION_PROVIDER=youtube_captions "
            "disables speech recognition. Set TRANSCRIPTION_PROVIDER=auto and install faster-whisper or set OPENAI_API_KEY.",
            "no_transcript",
        )
    if mode in STT_PROVIDERS:
        return run_stt(mode)

    # auto
    if _usable(manual):
        return manual  # type: ignore[return-value]
    errors: list[str] = []
    for name in ("faster_whisper", "openai"):
        ok, why = STT_PROVIDERS[name].available()
        if not ok:
            errors.append(f"{name}: {why}")
            continue
        try:
            return run_stt(name)
        except TranscriptionError as e:
            log.warning("STT provider %s failed: %s", name, e)
            errors.append(f"{name}: {e}")
            warnings.append(f"Speech recognition with {name} failed ({e}); falling back.")
    if _usable(auto):
        warnings.append("Using YouTube auto-generated captions as the transcript (no speech-to-text provider configured). Accuracy depends on YouTube's ASR.")
        return auto  # type: ignore[return-value]
    raise TranscriptionError(
        "No transcript could be obtained: the video has no usable captions and no speech-to-text provider is available ("
        + "; ".join(errors) + ").",
        "no_transcript",
    )
