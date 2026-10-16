"""Pluggable speech-to-text providers.

* ``faster_whisper`` — local, free, runs on CPU/GPU. ``pip install faster-whisper``.
  Downloads model weights from Hugging Face on first use.
* ``openai`` — OpenAI's /audio/transcriptions endpoint (or any compatible server
  via OPENAI_BASE_URL). Paid: whisper-1 is $0.006 per audio minute at time of writing.

Platform captions (YouTube) are handled in ``app.ingest`` and chosen by
``app.transcribe.service``.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

from ..config import settings
from ..models import Segment, Transcript, Word
from ..video.ffmpeg import split_audio

log = logging.getLogger(__name__)


class TranscriptionError(Exception):
    def __init__(self, message: str, code: str = "transcription_failed"):
        super().__init__(message)
        self.code = code


class SpeechToText(ABC):
    name: str

    @abstractmethod
    def available(self) -> tuple[bool, str]: ...

    @abstractmethod
    def transcribe(self, audio: Path, language: str, progress) -> Transcript: ...


class FasterWhisperSTT(SpeechToText):
    name = "faster_whisper"

    def available(self) -> tuple[bool, str]:
        import importlib.util

        if importlib.util.find_spec("faster_whisper") is None:
            return False, "faster-whisper is not installed (pip install faster-whisper)"
        return True, ""

    def transcribe(self, audio: Path, language: str, progress) -> Transcript:
        from faster_whisper import WhisperModel

        device = settings.whisper_device
        try:
            model = WhisperModel(settings.whisper_model, device=device, compute_type="auto")
        except Exception as e:
            raise TranscriptionError(f"Could not load Whisper model '{settings.whisper_model}': {e}", "stt_model_load_failed") from e
        segments_iter, info = model.transcribe(
            str(audio),
            language=(language or None) if language != "auto" else None,
            word_timestamps=True,
            vad_filter=True,
        )
        total = info.duration or 1.0
        segments: list[Segment] = []
        for s in segments_iter:  # generator: streams through the file
            words = [Word(start=w.start, end=w.end, text=w.word.strip()) for w in (s.words or []) if w.word.strip()]
            segments.append(Segment(start=s.start, end=s.end, text=s.text.strip(), words=words))
            progress(min(s.end / total, 1.0), f"Transcribing… {s.end/60:.1f} / {total/60:.1f} min")
        return Transcript(source=f"faster_whisper:{settings.whisper_model}", language=info.language or language,
                          segments=segments, has_word_timing=True)


class OpenAISTT(SpeechToText):
    name = "openai"

    def available(self) -> tuple[bool, str]:
        if not settings.openai_api_key:
            return False, "OPENAI_API_KEY is not set"
        return True, ""

    def _post(self, path: Path, language: str) -> dict:
        import httpx

        last: Exception | None = None
        for attempt in range(4):
            try:
                with path.open("rb") as fh:
                    r = httpx.post(
                        f"{settings.openai_base_url.rstrip('/')}/audio/transcriptions",
                        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                        data={
                            "model": settings.openai_transcribe_model,
                            "response_format": "verbose_json",
                            "timestamp_granularities[]": ["word", "segment"],
                            **({"language": language} if language and language != "auto" else {}),
                        },
                        files={"file": (path.name, fh, "audio/mpeg")},
                        timeout=600,
                    )
                if r.status_code == 429 or r.status_code >= 500:
                    raise TranscriptionError(f"OpenAI transcription HTTP {r.status_code}", "stt_api_retryable")
                if r.status_code >= 400:
                    raise TranscriptionError(f"OpenAI transcription failed: HTTP {r.status_code} {r.text[:300]}", "stt_api_error")
                return r.json()
            except TranscriptionError as e:
                if e.code != "stt_api_retryable":
                    raise
                last = e
            except httpx.HTTPError as e:
                last = e
            time.sleep(2 ** attempt)
        raise TranscriptionError(f"OpenAI transcription failed after retries: {last}", "stt_api_error")

    def transcribe(self, audio: Path, language: str, progress) -> Transcript:
        chunks = split_audio(audio, audio.parent / "stt_chunks", chunk_seconds=600)
        segments: list[Segment] = []
        for i, (chunk, offset) in enumerate(chunks):
            data = self._post(chunk, language)
            words = [Word(start=w["start"] + offset, end=w["end"] + offset, text=w["word"].strip()) for w in data.get("words", [])]
            for s in data.get("segments", []):
                s_start, s_end = s["start"] + offset, s["end"] + offset
                seg_words = [w for w in words if w.start >= s_start - 0.01 and w.start < s_end]
                segments.append(Segment(start=s_start, end=s_end, text=s["text"].strip(), words=seg_words))
            progress((i + 1) / len(chunks), f"Transcribing chunk {i+1}/{len(chunks)}")
        return Transcript(source=f"openai:{settings.openai_transcribe_model}", language=language,
                          segments=segments, has_word_timing=any(s.words for s in segments))


STT_PROVIDERS: dict[str, SpeechToText] = {p.name: p for p in (FasterWhisperSTT(), OpenAISTT())}
