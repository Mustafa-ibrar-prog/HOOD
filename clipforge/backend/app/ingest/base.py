"""Provider interface for video ingestion.

A provider knows how to (1) recognise its URLs, (2) fetch metadata, (3) fetch
any platform-provided captions, and (4) download the media to a local file.
Add a new authorised source by implementing ``VideoProvider`` and registering it
in ``app.ingest.registry``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Optional

from ..models import SourceInfo, Transcript

ProgressFn = Callable[[float, str], None]  # (fraction 0..1, message)


class IngestError(Exception):
    """User-facing ingestion failure with a stable machine code."""

    def __init__(self, message: str, code: str = "ingest_failed", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class VideoProvider(ABC):
    name: str

    @abstractmethod
    def matches(self, url: str) -> bool: ...

    @abstractmethod
    def fetch_metadata(self, url: str) -> SourceInfo: ...

    def fetch_captions(self, source: SourceInfo, workdir: Path, language: str) -> Optional[tuple[Transcript, bool]]:
        """Return (transcript, is_manual) if the platform offers captions, else None."""
        return None

    @abstractmethod
    def download(self, source: SourceInfo, workdir: Path, progress: ProgressFn) -> Path: ...
