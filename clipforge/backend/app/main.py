"""ClipForge HTTP API (FastAPI)."""
from __future__ import annotations

import logging
import re
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import public_config, settings
from .ingest.url_validation import UrlValidationError, parse_youtube_url
from .jobs import executor, new_job_id, store
from .models import CreateJobRequest, Job, JobOptions, JobStatus, UpdateClipRequest
from .pipeline import _unlink_quietly, apply_clip_edit, captions_for, clip_bounds_valid, load_units, process_job, render_one
from .storage import storage
from .video.ffmpeg import ffmpeg_available

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("clipforge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not ffmpeg_available():
        log.error("FFmpeg/ffprobe not found on PATH — rendering will fail. Install FFmpeg.")
    removed = store.cleanup(settings.retention_hours)
    if removed:
        log.info("cleaned up %d expired jobs", len(removed))
    yield
    executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="ClipForge API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _job_or_404(job_id: str) -> Job:
    if not re.fullmatch(r"[a-f0-9]{6,32}", job_id):
        raise HTTPException(404, "Job not found")
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


def _safe_name(s: str, limit: int = 60) -> str:
    s = re.sub(r"[^\w\- ]+", "", s).strip().replace(" ", "_")
    return (s[:limit] or "clip").strip("_")


# ---------------------------------------------------------------------------- meta
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "ffmpeg": ffmpeg_available()}


@app.get("/api/config")
def config() -> dict:
    return public_config()


@app.get("/api/validate")
def validate(url: str = Query(..., max_length=2048)) -> dict:
    try:
        p = parse_youtube_url(url)
    except UrlValidationError as e:
        return {"valid": False, "error": str(e), "code": e.code}
    return {"valid": True, "provider": p.provider, "video_id": p.video_id, "canonical_url": p.canonical_url, "kind": p.kind}


# ---------------------------------------------------------------------------- jobs
@app.post("/api/jobs", status_code=201)
def create_job(req: CreateJobRequest) -> Job:
    if not req.authorized:
        raise HTTPException(400, "Please confirm you own this video or are authorised to process it.")
    try:
        parsed = parse_youtube_url(req.url)
    except UrlValidationError as e:
        raise HTTPException(422, {"message": str(e), "code": e.code})
    job = store.create(Job(id=new_job_id(), request_url=parsed.canonical_url, options=req.options))
    executor.submit(process_job, job.id)
    return job


@app.post("/api/demo", status_code=201)
def create_demo(options: JobOptions | None = None) -> Job:
    job = store.create(Job(id=new_job_id(), request_url="sample://demo", options=options or JobOptions(), is_demo=True,
                           message="Demo: generating the labelled sample video…"))
    executor.submit(process_job, job.id)
    return job


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return [
        {"id": j.id, "status": j.status, "progress": j.progress, "stage": j.stage, "created_at": j.created_at,
         "title": (j.source.title if j.source else j.request_url), "clips": len(j.clips), "is_demo": j.is_demo}
        for j in store.list()
    ]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> Job:
    return _job_or_404(job_id)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> Job:
    job = _job_or_404(job_id)
    if job.status in {JobStatus.queued, JobStatus.running}:
        store.request_cancel(job_id)
    return job


@app.post("/api/jobs/{job_id}/retry", status_code=201)
def retry_job(job_id: str) -> Job:
    old = _job_or_404(job_id)
    if old.status not in {JobStatus.failed, JobStatus.cancelled}:
        raise HTTPException(409, "Only failed or cancelled jobs can be retried.")
    job = store.create(Job(id=new_job_id(), request_url=old.request_url, options=old.options, is_demo=old.is_demo))
    executor.submit(process_job, job.id)
    return job


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str) -> None:
    job = _job_or_404(job_id)
    store.request_cancel(job.id)
    store.delete(job.id)


@app.post("/api/cleanup")
def cleanup(older_than_hours: float = Query(settings.retention_hours, ge=0)) -> dict:
    removed = store.cleanup(older_than_hours)
    return {"removed": removed, "disk_usage_bytes": store.disk_usage_bytes()}


# ---------------------------------------------------------------------------- clips
def _clip_or_404(job: Job, clip_id: str):
    clip = next((c for c in job.clips if c.id == clip_id), None)
    if not clip:
        raise HTTPException(404, "Clip not found")
    return clip


@app.patch("/api/jobs/{job_id}/clips/{clip_id}")
def update_clip(job_id: str, clip_id: str, req: UpdateClipRequest) -> Job:
    job = _job_or_404(job_id)
    clip = _clip_or_404(job, clip_id)
    if clip.status == "rendering":
        raise HTTPException(409, "This clip is currently rendering; try again in a moment.")
    start = req.start if req.start is not None else clip.start
    end = req.end if req.end is not None else clip.end
    if err := clip_bounds_valid(start, end, job.source.duration if job.source else None):
        raise HTTPException(422, err)

    def upd(j: Job) -> None:
        c = next(c for c in j.clips if c.id == clip_id)
        regroup = req.render is not None and req.render.captions.words_per_caption != c.render.captions.words_per_caption
        if req.render is not None:
            c.render = req.render
        apply_clip_edit(j, c, req.start, req.end, req.captions)
        if regroup and req.captions is None:
            c.captions = captions_for(load_units(j.id), c.start, c.end, c.render.captions.words_per_caption)
        c.status = "pending"

    job = store.update(job_id, upd)  # type: ignore[assignment]
    executor.submit(render_one, job_id, clip_id)
    return job


@app.post("/api/jobs/{job_id}/clips/{clip_id}/regenerate")
def regenerate_clip(job_id: str, clip_id: str) -> Job:
    job = _job_or_404(job_id)
    clip = _clip_or_404(job, clip_id)
    if clip.status == "rendering":
        raise HTTPException(409, "This clip is already rendering.")
    store.update(job_id, lambda j: setattr(_clip_or_404(j, clip_id), "status", "pending"))
    executor.submit(render_one, job_id, clip_id)
    return store.get(job_id)  # type: ignore[return-value]


@app.delete("/api/jobs/{job_id}/clips/{clip_id}")
def delete_clip(job_id: str, clip_id: str) -> Job:
    job = _job_or_404(job_id)
    clip = _clip_or_404(job, clip_id)
    clips_dir = store.dir(job_id) / "clips"
    for f in (clip.file, clip.thumbnail):
        if f:
            _unlink_quietly(clips_dir / f)

    def upd(j: Job) -> None:
        j.clips = [c for c in j.clips if c.id != clip_id]
    return store.update(job_id, upd)  # type: ignore[return-value]


def _clip_file(job_id: str, name: str | None) -> Path:
    if not name or "/" in name or ".." in name:
        raise HTTPException(404, "File not ready")
    p = store.dir(job_id) / "clips" / name
    if not p.exists():
        raise HTTPException(404, "File not found")
    return p


@app.get("/api/jobs/{job_id}/clips/{clip_id}/video")
def clip_video(job_id: str, clip_id: str, download: bool = False):
    job = _job_or_404(job_id)
    clip = _clip_or_404(job, clip_id)
    p = _clip_file(job_id, clip.file)
    name = f"{clip.rank:02d}_{_safe_name(clip.hook, 50)}.mp4"
    if url := storage.url_for(job_id, p, name if download else None):
        return RedirectResponse(url)
    return FileResponse(p, media_type="video/mp4", filename=name if download else None,
                        content_disposition_type="attachment" if download else "inline")


@app.get("/api/jobs/{job_id}/clips/{clip_id}/thumbnail")
def clip_thumbnail(job_id: str, clip_id: str):
    job = _job_or_404(job_id)
    clip = _clip_or_404(job, clip_id)
    p = _clip_file(job_id, clip.thumbnail)
    return FileResponse(p, media_type="image/jpeg")


@app.get("/api/jobs/{job_id}/thumbnail")
def source_thumbnail(job_id: str):
    _job_or_404(job_id)
    p = store.dir(job_id) / "source_thumb.jpg"
    if not p.exists():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(p, media_type="image/jpeg")


@app.get("/api/jobs/{job_id}/download.zip")
def download_zip(job_id: str, background: BackgroundTasks):
    job = _job_or_404(job_id)
    ready = [c for c in job.clips if c.status == "ready" and c.file]
    if not ready:
        raise HTTPException(404, "No rendered clips to download yet.")
    zpath = store.dir(job_id) / f"clips_{job_id}.zip"
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_STORED) as zf:  # MP4 is already compressed
        lines = []
        for c in sorted(ready, key=lambda c: c.rank):
            name = f"{c.rank:02d}_{_safe_name(c.hook, 50)}.mp4"
            zf.write(store.dir(job_id) / "clips" / c.file, name)  # type: ignore[operator]
            yt = c.platforms.get("youtube_shorts")
            lines.append(
                f"{name}\n  score: {c.score:.0f}/100 ({c.content_type})\n  source: {c.start:.1f}s - {c.end:.1f}s\n"
                f"  hook: {c.hook}\n  why: {c.explanation}\n"
                + (f"  title: {yt.title}\n  hashtags: {' '.join(yt.hashtags)}\n" if yt else "")
            )
        title = job.source.title if job.source else job.request_url
        zf.writestr("clips.txt", f"{title}\n{job.request_url}\n\n" + "\n".join(lines))
    background.add_task(_unlink_quietly, zpath)
    return FileResponse(zpath, media_type="application/zip", filename=f"clips_{_safe_name(title, 40)}.zip")


# ---------------------------------------------------------------------------- frontend
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
