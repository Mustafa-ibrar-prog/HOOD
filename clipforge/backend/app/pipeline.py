"""End-to-end processing: URL -> metadata -> media -> transcript -> moments -> MP4 clips."""
from __future__ import annotations

import json
import logging
import time
import traceback
from pathlib import Path
from typing import Callable, Optional

from .analysis.audio_energy import loudness_curve
from .analysis.detector import detect_moments
from .analysis.sentences import Unit, build_units
from .config import MAX_CLIP_SECONDS, settings
from .ingest.base import IngestError
from .ingest.registry import provider_for
from .ingest.url_validation import UrlValidationError
from .jobs import store
from .models import CaptionLine, Clip, Job, JobStatus, Transcript
from .storage import storage
from .transcribe.providers import TranscriptionError
from .transcribe.service import obtain_transcript
from .video.captions import build_caption_lines
from .video.ffmpeg import FFmpegError, extract_audio, extract_frame, probe
from .video.render import RenderError, render_clip

log = logging.getLogger(__name__)

# overall progress range for each stage
STAGE_RANGES = {
    "validating": (0, 2),
    "fetching_metadata": (2, 6),
    "downloading": (6, 35),
    "transcribing": (35, 58),
    "analyzing": (58, 66),
    "rendering": (66, 100),
}


class Cancelled(Exception):
    pass


class JobContext:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.dir = store.dir(job_id)
        self._last_save = 0.0

    def stage(self, stage: str, frac: float = 0.0, message: str = "") -> None:
        if store.is_cancelled(self.job_id):
            raise Cancelled()
        lo, hi = STAGE_RANGES.get(stage, (0, 100))
        pct = round(lo + (hi - lo) * max(0.0, min(frac, 1.0)), 1)
        now = time.time()
        # throttle disk writes for chatty progress callbacks
        if frac not in (0.0, 1.0) and now - self._last_save < 0.7:
            return
        self._last_save = now

        def upd(j: Job) -> None:
            j.stage, j.progress, j.status = stage, max(pct, j.progress if j.stage == stage else pct), JobStatus.running
            if message:
                j.message = message

        store.update(self.job_id, upd)

    def progress_fn(self, stage: str) -> Callable[[float, str], None]:
        return lambda f, m="": self.stage(stage, f, m)

    def warn(self, msg: str) -> None:
        store.update(self.job_id, lambda j: j.warnings.append(msg) if msg not in j.warnings else None)


def _retry(fn, attempts: int = 3, base_delay: float = 2.0):
    for i in range(attempts):
        try:
            return fn()
        except IngestError as e:
            if not e.retryable or i == attempts - 1:
                raise
            time.sleep(base_delay * (2 ** i))


def captions_for(units: list[Unit], start: float, end: float, words_per_caption: int) -> list[CaptionLine]:
    words = [w for u in units for w in u.words if w.end > start and w.start < end]
    return build_caption_lines(words, start, end, words_per_caption)


def save_transcript(ctx: JobContext, transcript: Transcript) -> None:
    (ctx.dir / "transcript.json").write_text(transcript.model_dump_json())


def load_units(job_id: str) -> list[Unit]:
    p = store.dir(job_id) / "transcript.json"
    if not p.exists():
        return []
    return build_units(Transcript.model_validate_json(p.read_text()))


def source_video_path(job_id: str) -> Optional[Path]:
    d = store.dir(job_id)
    meta = d / "media.json"
    if meta.exists():
        p = Path(json.loads(meta.read_text())["video"])
        if p.exists():
            return p
    return None


def _unlink_quietly(p: Path) -> None:
    """Delete a file, tolerating Windows' refusal to delete files another process
    (e.g. a browser streaming the old preview) still has open."""
    try:
        p.unlink(missing_ok=True)
    except OSError as e:
        log.warning("could not delete %s (%s); it will be removed by cleanup", p, e)


# ---------------------------------------------------------------------------- rendering
def render_one(job_id: str, clip_id: str) -> None:
    """Render (or re-render) a single clip, with a safe-layout retry on failure."""
    job = store.get(job_id)
    src = source_video_path(job_id)
    if not job or not src:
        return
    clip = next((c for c in job.clips if c.id == clip_id), None)
    if not clip:
        return

    def set_status(status: str, **kw) -> None:
        def upd(j: Job) -> None:
            for c in j.clips:
                if c.id == clip_id:
                    c.status = status  # type: ignore[assignment]
                    for k, v in kw.items():
                        setattr(c, k, v)
        store.update(job_id, upd)

    set_status("rendering", error=None)
    clips_dir = store.dir(job_id) / "clips"
    clips_dir.mkdir(exist_ok=True)
    version = clip.version + 1
    out = clips_dir / f"clip_{clip.id}_v{version}.mp4"
    try:
        info = probe(src)
        try:
            res = render_clip(src, clip.start, clip.end, clip.captions, clip.render, out, info)
        except RenderError as e:
            if clip.render.layout in {"blur", "center"}:
                raise
            log.warning("render failed for %s with layout %s, retrying with blur: %s", clip_id, clip.render.layout, e)
            safe = clip.render.model_copy(update={"layout": "blur"})
            res = render_clip(src, clip.start, clip.end, clip.captions, safe, out, info)
            res.notes.append(f"Smart framing failed; rendered with blurred background ({str(e)[:120]}).")
        assert res.duration <= MAX_CLIP_SECONDS + 0.1
        for p in (res.path, res.thumbnail):
            storage.publish(job_id, p)
        old_files = [clip.file, clip.thumbnail]
        set_status("ready", file=res.path.name, thumbnail=res.thumbnail.name, output_width=res.width,
                   output_height=res.height, rendered_duration=res.duration, layout_used=res.layout,
                   version=version, error=("; ".join(res.notes) or None))
        for f in old_files:  # remove superseded renders
            if f and f != res.path.name and f != res.thumbnail.name:
                _unlink_quietly(clips_dir / f)
    except (RenderError, FFmpegError, OSError) as e:
        log.exception("render failed")
        set_status("failed", error=f"Rendering failed: {str(e)[:400]}")


# ---------------------------------------------------------------------------- main job
def process_job(job_id: str) -> None:
    ctx = JobContext(job_id)
    job = store.get(job_id)
    if not job:
        return
    warnings: list[str] = []
    captions = None
    try:
        if job.is_demo:
            from .demo import sample_assets

            ctx.stage("fetching_metadata", 0.0, "Preparing the labelled sample video…")
            video, transcript, source = sample_assets()
            store.update(job_id, lambda j: setattr(j, "source", source))
            ctx.stage("downloading", 1.0, "Sample video ready (generated locally).")
        else:
            ctx.stage("validating", 0.0, "Validating URL…")
            provider = provider_for(job.request_url)
            ctx.stage("fetching_metadata", 0.0, "Fetching video information…")
            source = _retry(lambda: provider.fetch_metadata(job.request_url))
            store.update(job_id, lambda j: setattr(j, "source", source))
            ctx.stage("fetching_metadata", 0.6, "Checking for captions…")
            captions = None
            try:
                captions = provider.fetch_captions(source, ctx.dir, settings.transcript_language)
            except Exception as e:
                log.warning("caption fetch failed: %s", e)
            ctx.stage("downloading", 0.0, "Downloading video…")
            video = _retry(lambda: provider.download(source, ctx.dir, ctx.progress_fn("downloading")))
            transcript = None

        (ctx.dir / "media.json").write_text(json.dumps({"video": str(video)}))
        info = probe(video)
        if not info.has_video:
            raise IngestError("The downloaded file has no video stream.", "no_video")
        if not job.is_demo:
            source.duration = source.duration or info.duration
            source.width, source.height = info.width, info.height
            store.update(job_id, lambda j: setattr(j, "source", source))
        try:
            extract_frame(video, min(info.duration * 0.1, 30), ctx.dir / "source_thumb.jpg", width=480)
        except FFmpegError:
            pass

        # ---- audio + transcript
        ctx.stage("transcribing", 0.0, "Extracting audio…")
        audio_path: Optional[Path] = None
        if info.has_audio:
            audio_path = extract_audio(video, ctx.dir / "audio.flac")
        if transcript is None:
            if not info.has_audio and not captions:
                raise TranscriptionError("This video has no audio track and no captions, so there is nothing to analyse.", "no_audio")

            def need_audio() -> Path:
                if not audio_path:
                    raise TranscriptionError("This video has no audio track.", "no_audio")
                return audio_path

            ctx.stage("transcribing", 0.05, "Getting a timestamped transcript…")
            transcript = obtain_transcript(captions=captions, audio_path_fn=need_audio, language=settings.transcript_language,
                                           progress=ctx.progress_fn("transcribing"), warnings=warnings)
        save_transcript(ctx, transcript)
        store.update(job_id, lambda j: setattr(j, "transcript_source", transcript.source))
        units = build_units(transcript)
        if len(units) < 3 or units[-1].end - units[0].start < job.options.min_clip_seconds:
            raise TranscriptionError("There isn't enough speech in this video to build clips from.", "not_enough_speech")

        energy = loudness_curve(audio_path) if audio_path else []
        ctx.stage("analyzing", 0.0, "Finding the most engaging moments…")
        clips, analyzer = detect_moments(
            units, options=job.options, title=source.title, media_duration=info.duration, energy=energy or None,
            warnings=warnings, use_llm=not job.is_demo, progress=ctx.progress_fn("analyzing"),
        )
        if not clips:
            raise TranscriptionError(
                "No moments met the quality bar for a standalone clip (try lowering the minimum clip length).", "no_moments"
            )
        for c in clips:
            c.captions = captions_for(units, c.start, c.end, c.render.captions.words_per_caption)

        def set_clips(j: Job) -> None:
            j.clips, j.analyzer = clips, analyzer
            for w in warnings:
                if w not in j.warnings:
                    j.warnings.append(w)
        store.update(job_id, set_clips)

        # ---- render
        for i, c in enumerate(clips):
            ctx.stage("rendering", i / len(clips), f"Rendering clip {i + 1} of {len(clips)}…")
            render_one(job_id, c.id)
        final = store.get(job_id)
        ok = [c for c in (final.clips if final else []) if c.status == "ready"]
        if not ok:
            raise RenderError("Every clip failed to render. See the clip errors for details.")
        if audio_path:
            _unlink_quietly(audio_path)  # transcript is saved; audio no longer needed

        def done(j: Job) -> None:
            j.status, j.stage, j.progress = JobStatus.completed, "done", 100.0
            j.message = f"{len(ok)} clip{'s' if len(ok) != 1 else ''} ready"
        store.update(job_id, done)
    except Cancelled:
        store.update(job_id, lambda j: (setattr(j, "status", JobStatus.cancelled), setattr(j, "message", "Cancelled")))
    except Exception as e:
        if isinstance(e, (IngestError, UrlValidationError, TranscriptionError)):
            msg, code = str(e), getattr(e, "code", "failed")
        elif isinstance(e, (RenderError, FFmpegError)):
            msg, code = f"Video processing failed: {e}", "ffmpeg_failed"
        else:
            log.error("unexpected pipeline error: %s", traceback.format_exc())
            msg, code = f"Unexpected error: {e.__class__.__name__}: {e}", "internal_error"

        def fail(j: Job) -> None:
            j.status, j.error, j.error_code, j.message = JobStatus.failed, msg, code, "Failed"
            for w in warnings:
                if w not in j.warnings:
                    j.warnings.append(w)
        store.update(job_id, fail)


def clip_bounds_valid(start: float, end: float, media_duration: Optional[float]) -> Optional[str]:
    if start < 0:
        return "Start must be ≥ 0."
    if end - start < 1.0:
        return "Clips must be at least 1 second long."
    if end - start > MAX_CLIP_SECONDS:
        return f"Clips can be at most {MAX_CLIP_SECONDS:.0f} seconds long."
    if media_duration and end > media_duration + 0.05:
        return "End is past the end of the video."
    return None


def apply_clip_edit(job: Job, clip: Clip, start: Optional[float], end: Optional[float],
                    captions: Optional[list[CaptionLine]]) -> None:
    """Update timings (rebuilding captions from the transcript if bounds moved) or captions."""
    moved = (start is not None and abs(start - clip.start) > 1e-3) or (end is not None and abs(end - clip.end) > 1e-3)
    if start is not None:
        clip.start = round(start, 3)
    if end is not None:
        clip.end = round(end, 3)
    if captions is not None and not moved:
        dur = clip.end - clip.start
        clip.captions = [
            CaptionLine(start=max(0.0, c.start), end=min(c.end, dur), text=c.text.strip(), words=c.words)
            for c in captions if c.text.strip() and c.end > c.start and c.start < dur
        ]
    elif moved:
        units = load_units(job.id)
        clip.captions = captions_for(units, clip.start, clip.end, clip.render.captions.words_per_caption)
        clip.transcript = " ".join(w.text for u in units for w in u.words if clip.start <= w.start < clip.end)
