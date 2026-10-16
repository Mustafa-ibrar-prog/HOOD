"""Pydantic models shared by the API, the job store and the pipeline."""
from __future__ import annotations

import time
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Word(BaseModel):
    start: float
    end: float
    text: str


class Segment(BaseModel):
    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)


class Transcript(BaseModel):
    source: str  # e.g. "youtube_manual_captions", "faster_whisper:small", "sample_script"
    language: str = "en"
    segments: list[Segment]
    has_word_timing: bool = False


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


STAGES = [
    "validating",
    "fetching_metadata",
    "downloading",
    "transcribing",
    "analyzing",
    "rendering",
    "done",
]


class CaptionStyle(BaseModel):
    enabled: bool = True
    font: str = "Inter"
    font_size: int = Field(78, ge=24, le=160)
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFD400"
    outline_color: str = "#000000"
    outline_width: float = Field(5.0, ge=0, le=12)
    position: Literal["bottom", "middle", "top"] = "bottom"
    uppercase: bool = False
    words_per_caption: int = Field(3, ge=1, le=8)
    highlight_active_word: bool = True

    @field_validator("primary_color", "highlight_color", "outline_color")
    @classmethod
    def _hex(cls, v: str) -> str:
        v = v.strip()
        if not (len(v) == 7 and v.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in v[1:])):
            raise ValueError("colour must be #RRGGBB")
        return v.upper()


LayoutMode = Literal["auto", "face_track", "center", "blur", "gaming"]


class RenderOptions(BaseModel):
    layout: LayoutMode = "auto"
    # Manual horizontal crop anchor 0..1 used by "center" (0.5 = middle)
    crop_x: float = Field(0.5, ge=0.0, le=1.0)
    captions: CaptionStyle = Field(default_factory=CaptionStyle)


class JobOptions(BaseModel):
    max_clips: int = Field(8, ge=1, le=20)
    min_clip_seconds: float = Field(15.0, ge=5.0, le=55.0)
    max_clip_seconds: float = Field(60.0, ge=10.0, le=60.0)
    render: RenderOptions = Field(default_factory=RenderOptions)


class CreateJobRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    authorized: bool = Field(..., description="User confirms they may process this video")
    options: JobOptions = Field(default_factory=JobOptions)


class ScoreBreakdown(BaseModel):
    hook: float = Field(0, ge=0, le=100)
    emotion: float = Field(0, ge=0, le=100)
    clarity: float = Field(0, ge=0, le=100)
    payoff: float = Field(0, ge=0, le=100)
    pacing: float = Field(0, ge=0, le=100)
    shareability: float = Field(0, ge=0, le=100)


class PlatformCopy(BaseModel):
    title: str
    description: str
    hashtags: list[str]


class CaptionLine(BaseModel):
    """A caption cue, times relative to the *clip* start."""
    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)


class Clip(BaseModel):
    id: str
    rank: int = 0
    start: float  # seconds in source
    end: float
    score: float
    breakdown: ScoreBreakdown
    content_type: str
    hook: str  # verbatim opening line from the transcript
    explanation: str
    selection_reason: str
    transcript: str  # verbatim transcript of the clip
    captions: list[CaptionLine] = Field(default_factory=list)
    platforms: dict[str, PlatformCopy] = Field(default_factory=dict)
    render: RenderOptions = Field(default_factory=RenderOptions)
    status: Literal["pending", "rendering", "ready", "failed"] = "pending"
    error: Optional[str] = None
    layout_used: Optional[str] = None
    file: Optional[str] = None
    thumbnail: Optional[str] = None
    output_width: Optional[int] = None
    output_height: Optional[int] = None
    rendered_duration: Optional[float] = None
    analyzer: str = "heuristic"
    version: int = 0

    @property
    def duration(self) -> float:
        return self.end - self.start


class SourceInfo(BaseModel):
    provider: str
    url: str
    video_id: Optional[str] = None
    title: str = ""
    channel: Optional[str] = None
    duration: Optional[float] = None
    thumbnail_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    is_sample: bool = False


class Job(BaseModel):
    id: str
    status: JobStatus = JobStatus.queued
    stage: str = "validating"
    progress: float = 0.0  # 0..100
    message: str = "Queued"
    error: Optional[str] = None
    error_code: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    request_url: str
    options: JobOptions = Field(default_factory=JobOptions)
    source: Optional[SourceInfo] = None
    transcript_source: Optional[str] = None
    analyzer: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    clips: list[Clip] = Field(default_factory=list)
    is_demo: bool = False


class UpdateClipRequest(BaseModel):
    start: Optional[float] = None
    end: Optional[float] = None
    captions: Optional[list[CaptionLine]] = None
    render: Optional[RenderOptions] = None
