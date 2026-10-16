"""Runtime configuration, read from environment variables (and an optional .env file).

Secrets (API keys) are only ever read here, on the server. They are never
serialised into API responses — see ``public_config()``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional convenience; production deployments set real env vars
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:  # pragma: no cover
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name, "1" if default else "0").lower()
    return raw in {"1", "true", "yes", "on"}


# Hard product limit. Every clip that leaves the renderer is checked against it.
MAX_CLIP_SECONDS = 60.0


@dataclass
class Settings:
    # Resolved to an absolute path: ffmpeg is run with cwd set to job folders, so relative paths would break.
    data_dir: Path = field(default_factory=lambda: Path(_env("CLIPFORGE_DATA_DIR", str(Path(__file__).resolve().parents[1] / "data"))).resolve())
    storage_backend: str = field(default_factory=lambda: _env("STORAGE_BACKEND", "local"))  # local | s3
    s3_bucket: str = field(default_factory=lambda: _env("S3_BUCKET"))
    s3_prefix: str = field(default_factory=lambda: _env("S3_PREFIX", "clipforge/"))

    # Ingestion
    max_video_seconds: int = field(default_factory=lambda: _env_int("MAX_VIDEO_SECONDS", 0))  # 0 = unlimited
    max_download_height: int = field(default_factory=lambda: _env_int("MAX_DOWNLOAD_HEIGHT", 1080))
    download_retries: int = field(default_factory=lambda: _env_int("DOWNLOAD_RETRIES", 3))

    # Transcription: auto | youtube_captions | faster_whisper | openai
    transcription_provider: str = field(default_factory=lambda: _env("TRANSCRIPTION_PROVIDER", "auto"))
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "small"))
    whisper_device: str = field(default_factory=lambda: _env("WHISPER_DEVICE", "auto"))
    transcript_language: str = field(default_factory=lambda: _env("TRANSCRIPT_LANGUAGE", "en"))

    # Moment analysis: auto | anthropic | openai | heuristic
    analysis_provider: str = field(default_factory=lambda: _env("ANALYSIS_PROVIDER", "auto"))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-opus-5-5"))
    anthropic_effort: str = field(default_factory=lambda: _env("ANTHROPIC_EFFORT", "medium"))
    anthropic_fallbacks: bool = field(default_factory=lambda: _env_bool("ANTHROPIC_FALLBACKS", True))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    openai_base_url: str = field(default_factory=lambda: _env("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL", "gpt-4o-mini"))
    openai_transcribe_model: str = field(default_factory=lambda: _env("OPENAI_TRANSCRIBE_MODEL", "whisper-1"))
    llm_timeout_seconds: float = field(default_factory=lambda: _env_float("LLM_TIMEOUT_SECONDS", 300.0))

    # Rendering
    ffmpeg_bin: str = field(default_factory=lambda: _env("FFMPEG_BIN", "ffmpeg"))
    ffprobe_bin: str = field(default_factory=lambda: _env("FFPROBE_BIN", "ffprobe"))
    x264_preset: str = field(default_factory=lambda: _env("X264_PRESET", "veryfast"))
    x264_crf: int = field(default_factory=lambda: _env_int("X264_CRF", 20))
    ffmpeg_timeout_seconds: int = field(default_factory=lambda: _env_int("FFMPEG_TIMEOUT_SECONDS", 900))
    default_max_clips: int = field(default_factory=lambda: _env_int("DEFAULT_MAX_CLIPS", 8))

    # Jobs
    worker_threads: int = field(default_factory=lambda: _env_int("WORKER_THREADS", 2))
    retention_hours: float = field(default_factory=lambda: _env_float("RETENTION_HOURS", 48.0))
    cors_origins: str = field(default_factory=lambda: _env("CORS_ORIGINS", "http://localhost:5173"))

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    def resolved_analysis_provider(self) -> str:
        p = self.analysis_provider.lower()
        if p != "auto":
            return p
        if self.anthropic_api_key:
            return "anthropic"
        if self.openai_api_key:
            return "openai"
        return "heuristic"


settings = Settings()


def public_config() -> dict:
    """What the browser may know. Never include keys."""
    return {
        "analysis_provider": settings.resolved_analysis_provider(),
        "analysis_model": {
            "anthropic": settings.anthropic_model,
            "openai": settings.openai_model,
        }.get(settings.resolved_analysis_provider(), "built-in heuristics"),
        "transcription_provider": settings.transcription_provider,
        "has_anthropic_key": bool(settings.anthropic_api_key),
        "has_openai_key": bool(settings.openai_api_key),
        "max_clip_seconds": MAX_CLIP_SECONDS,
        "max_video_seconds": settings.max_video_seconds,
        "default_max_clips": settings.default_max_clips,
        "storage_backend": settings.storage_backend,
    }
