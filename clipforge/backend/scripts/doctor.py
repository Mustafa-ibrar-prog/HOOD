"""ClipForge doctor: check the local setup, probe a YouTube URL, and run a verified end-to-end job.

    python scripts/doctor.py                                  # environment checks only
    python scripts/doctor.py --url URL                        # + can this server reach/download this video?
    python scripts/doctor.py --url URL --e2e --authorized     # + full pipeline, verifying every output file

Prints [OK]/[WARN]/[FAIL] lines and writes a JSON report you can share when asking for help.
API keys are never printed — only whether they are set.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:  # Windows consoles default to a legacy code page
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

REPORT: dict = {"checks": [], "probe": None, "e2e": None}


def line(status: str, name: str, detail: str = "") -> None:
    REPORT["checks"].append({"status": status, "name": name, "detail": detail})
    print(f"[{status:<4}] {name}" + (f" - {detail}" if detail else ""))


def cmd_out(args: list[str]) -> str:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return (p.stdout or p.stderr).strip()
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------- environment
def check_environment() -> bool:
    from app.config import settings

    ok = True
    print("\n== Environment ==")
    line("OK" if sys.version_info >= (3, 10) else "FAIL", "Python", f"{platform.python_version()} on {platform.system()} {platform.release()}")

    for binary in (settings.ffmpeg_bin, settings.ffprobe_bin):
        path = shutil.which(binary)
        if not path:
            line("FAIL", binary, "not found on PATH (Windows: winget install Gyan.FFmpeg, then open a NEW terminal)")
            ok = False
        else:
            line("OK", binary, cmd_out([binary, "-version"]).splitlines()[0][:90])
    if shutil.which(settings.ffmpeg_bin):
        filters = cmd_out([settings.ffmpeg_bin, "-hide_banner", "-filters"])
        encoders = cmd_out([settings.ffmpeg_bin, "-hide_banner", "-encoders"])
        for name, present, why in [
            ("ffmpeg subtitles filter (libass)", " subtitles " in filters, "needed for burned-in captions"),
            ("ffmpeg libx264 encoder", "libx264" in encoders, "needed for MP4 output"),
            ("ffmpeg loudnorm filter", " loudnorm " in filters, "needed for audio levelling"),
        ]:
            line("OK" if present else "FAIL", name, "" if present else why + " - install a full build (e.g. Gyan.FFmpeg)")
            ok &= present

    try:
        import yt_dlp.version

        line("OK", "yt-dlp", yt_dlp.version.__version__)
    except ImportError:
        line("FAIL", "yt-dlp", "pip install -r requirements.txt")
        ok = False
    ejs = importlib.util.find_spec("yt_dlp_ejs") is not None
    line("OK" if ejs else "WARN", "yt-dlp-ejs (YouTube challenge solver)",
         "" if ejs else 'missing - pip install -U "yt-dlp[default]"')
    deno = shutil.which("deno")
    if not deno:
        line("WARN", "Deno JavaScript runtime",
             "missing - YouTube downloads may fail. Windows: winget install DenoLand.Deno (then open a NEW terminal)")
    else:
        ver = cmd_out(["deno", "--version"]).splitlines()[0]
        m = re.search(r"deno (\d+)\.(\d+)", ver)
        new_enough = bool(m) and (int(m.group(1)), int(m.group(2))) >= (2, 3)  # yt-dlp's minimum
        line("OK" if new_enough else "WARN", "Deno JavaScript runtime",
             ver if new_enough else f"{ver} is too old; yt-dlp needs >= 2.3 (deno upgrade)")

    try:
        import cv2

        cascade = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        line("OK" if cascade.exists() else "WARN", "OpenCV face detection", cv2.__version__ if cascade.exists()
             else "cascade missing (use opencv-python-headless<5); face tracking falls back to blurred framing")
    except Exception as e:
        line("WARN", "OpenCV face detection", f"unavailable ({e}); face tracking falls back to blurred framing")

    stt = importlib.util.find_spec("faster_whisper") is not None
    line("OK" if stt else "WARN", "faster-whisper (local speech-to-text)", "installed" if stt else
         "not installed - videos without YouTube captions will need it (pip install faster-whisper) or OPENAI_API_KEY")
    provider = settings.resolved_analysis_provider()
    line("OK", "Moment analysis", f"{provider}" + (f" ({settings.anthropic_model})" if provider == "anthropic" else
                                                    f" ({settings.openai_model})" if provider == "openai" else
                                                    " (free, offline; set ANTHROPIC_API_KEY for LLM analysis)"))
    line("OK", "API keys set", f"anthropic={bool(settings.anthropic_api_key)} openai={bool(settings.openai_api_key)}")

    try:
        settings.jobs_dir.mkdir(parents=True, exist_ok=True)
        probe = settings.jobs_dir / ".write_test"
        probe.write_text("x")
        probe.unlink()
        line("OK", "Data directory writable", str(settings.data_dir))
    except OSError as e:
        line("FAIL", "Data directory writable", f"{settings.data_dir}: {e}")
        ok = False
    dist = ROOT.parent / "frontend" / "dist" / "index.html"
    line("OK" if dist.exists() else "WARN", "Built web UI", "served at http://localhost:8000" if dist.exists()
         else "not built - run `npm run build` in clipforge/frontend, or use `npm run dev` on :5173")
    return ok


# ---------------------------------------------------------------------------- URL probe
def probe_url(url: str) -> bool:
    import yt_dlp

    from app.config import settings
    from app.ingest.base import IngestError
    from app.ingest.url_validation import UrlValidationError, parse_youtube_url
    from app.ingest.youtube import YouTubeProvider, _CollectingLogger, _ydl_base_opts, map_ytdlp_error

    print("\n== URL probe (no download) ==")
    result: dict = {"url": url}
    REPORT["probe"] = result
    try:
        parsed = parse_youtube_url(url)
        line("OK", "URL format", f"{parsed.kind} video id={parsed.video_id}")
    except UrlValidationError as e:
        line("FAIL", "URL format", str(e))
        return False

    t = time.time()
    try:
        src = YouTubeProvider().fetch_metadata(url)
        result["metadata"] = src.model_dump()
        line("OK", "Metadata", f"\"{src.title[:60]}\" by {src.channel} - {src.duration or 0:.0f}s ({time.time() - t:.1f}s)")
    except IngestError as e:
        result["error"] = {"code": e.code, "message": str(e), "detail": e.detail}
        line("FAIL", "Metadata", f"[{e.code}] {e}")
        if e.detail:
            print("       yt-dlp raw error: " + e.detail.replace("\n", "\n       ")[-800:])
        return False

    # Format resolution exactly as the downloader will do it, plus yt-dlp's own warnings.
    logger = _CollectingLogger()
    info: dict = {}
    h = settings.max_download_height
    fmt = f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"
    try:
        with yt_dlp.YoutubeDL({**_ydl_base_opts(), "logger": logger, "format": fmt, "simulate": True}) as ydl:
            info = ydl.extract_info(parsed.canonical_url, download=False)
        chosen = info.get("requested_formats") or [info]
        desc = " + ".join(f"{f.get('format_id')}:{f.get('ext')}:{f.get('height') or 'audio'}" for f in chosen)
        heights = [f.get("height") for f in chosen if f.get("height")]
        line("OK", "Downloadable formats", f"{len(info.get('formats') or [])} offered; will use {desc}")
        if heights and max(heights) < 720:
            line("WARN", "Resolution", f"best available is {max(heights)}p - often a sign the JS challenge failed (see warnings)")
        result["chosen_formats"] = desc
    except Exception as e:
        err = map_ytdlp_error("\n".join(logger.warnings[-5:] + [str(e)]))
        result["error"] = {"code": err.code, "message": str(err), "detail": err.detail}
        line("FAIL", "Downloadable formats", f"[{err.code}] {err}")
        print("       yt-dlp raw error: " + err.detail.replace("\n", "\n       ")[-800:])
    lang = settings.transcript_language
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    has_manual = any(k.split("-")[0] == lang for k in manual)
    has_auto = any(k.split("-")[0] == lang for k in auto)
    line("OK" if (has_manual or has_auto) else "WARN", "Captions",
         f"manual[{lang}]={has_manual} auto={has_auto}" + ("" if (has_manual or has_auto) else
                                                         " - transcription will need faster-whisper or OPENAI_API_KEY"))
    for w in logger.warnings[-6:]:
        line("WARN", "yt-dlp says", w[:300])
    result["ytdlp_warnings"] = logger.warnings
    return "error" not in result


# ---------------------------------------------------------------------------- end to end
def run_e2e(url: str, max_clips: int) -> bool:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.video.ffmpeg import probe

    print("\n== End-to-end run (real download, transcript, analysis, render) ==")
    e2e: dict = {"url": url}
    REPORT["e2e"] = e2e
    ok = True
    with TestClient(app) as c:
        r = c.post("/api/jobs", json={"url": url, "authorized": True, "options": {"max_clips": max_clips}})
        if r.status_code != 201:
            line("FAIL", "Create job", r.text[:300])
            return False
        job_id = r.json()["id"]
        e2e["job_id"] = job_id
        line("OK", "Create job", job_id)
        last = None
        t0 = time.time()
        while True:
            j = c.get(f"/api/jobs/{job_id}").json()
            msg = f"{j['stage']:<18} {j['progress']:5.1f}%  {j['message']}"
            if msg != last:
                print(f"       {time.time() - t0:6.0f}s  {msg}")
                last = msg
            if j["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(2)
        e2e["status"], e2e["error"], e2e["error_code"] = j["status"], j["error"], j["error_code"]
        e2e["transcript_source"], e2e["analyzer"], e2e["warnings"] = j["transcript_source"], j["analyzer"], j["warnings"]
        for w in j["warnings"]:
            line("WARN", "Job warning", w)
        if j["status"] != "completed":
            line("FAIL", "Job", f"{j['status']}: [{j['error_code']}] {j['error']}")
            return False
        line("OK", "Ingestion + download", f"{j['source']['width']}x{j['source']['height']}, {j['source']['duration']:.0f}s")
        line("OK", "Transcript", j["transcript_source"])
        line("OK", "Moment detection", f"{j['analyzer']} -> {len(j['clips'])} clips")

        from app.jobs import store

        jdir = store.dir(job_id) / "clips"
        e2e["clips"] = []
        for clip in sorted(j["clips"], key=lambda x: x["rank"]):
            rec = {"rank": clip["rank"], "score": clip["score"], "start": clip["start"], "end": clip["end"],
                   "hook": clip["hook"], "content_type": clip["content_type"], "status": clip["status"]}
            problems = []
            if clip["status"] != "ready":
                problems.append(f"status={clip['status']} {clip['error']}")
            else:
                f = jdir / clip["file"]
                info = probe(f)
                ass = f.with_suffix(".ass")
                dialogue = ass.read_text(encoding="utf-8").count("Dialogue:") if ass.exists() else 0
                rec.update(file=str(f), duration=round(info.duration, 2), size=f"{info.width}x{info.height}",
                           audio=info.has_audio, caption_events=dialogue, layout=clip["layout_used"])
                if info.duration > 60.1:
                    problems.append(f"duration {info.duration:.1f}s > 60s")
                if abs(info.width / info.height - 9 / 16) > 0.01:
                    problems.append(f"not 9:16 ({info.width}x{info.height})")
                if not info.has_audio:
                    problems.append("no audio")
                if clip["render"]["captions"]["enabled"] and dialogue == 0:
                    problems.append("no caption events")
                if not 0 <= clip["score"] <= 100 or not clip["explanation"]:
                    problems.append("missing score/explanation")
                if clip["hook"] not in " ".join(x["transcript"] for x in j["clips"]) and clip["hook"] not in clip["transcript"]:
                    problems.append("hook not found in transcript")
                v = c.get(f"/api/jobs/{job_id}/clips/{clip['id']}/video", headers={"Range": "bytes=0-1023"})
                if v.status_code != 206:
                    problems.append(f"preview stream HTTP {v.status_code}")
                d = c.get(f"/api/jobs/{job_id}/clips/{clip['id']}/video", params={"download": True})
                if d.status_code != 200 or "attachment" not in d.headers.get("content-disposition", ""):
                    problems.append("download endpoint failed")
            rec["problems"] = problems
            e2e["clips"].append(rec)
            ok &= not problems
            line("OK" if not problems else "FAIL", f"Clip #{clip['rank']}",
                 f"score {clip['score']:.0f} {clip['content_type']} {clip['start']:.1f}-{clip['end']:.1f}s "
                 f"{rec.get('size', '')} {rec.get('duration', '')}s layout={rec.get('layout')} captions={rec.get('caption_events')}"
                 + (f" PROBLEMS: {problems}" if problems else f" | \"{clip['hook'][:60]}\""))
        z = c.get(f"/api/jobs/{job_id}/download.zip")
        ready = sum(1 for x in j["clips"] if x["status"] == "ready")
        zip_ok = z.status_code == 200 and len(z.content) > 1000
        line("OK" if zip_ok else "FAIL", "ZIP download", f"{len(z.content) / 1e6:.1f} MB, {ready} clips")
        ok &= zip_ok
        e2e["clips_dir"] = str(jdir)
        print(f"\n       Clips are in: {jdir}")
        print(f"       Open the dashboard: http://localhost:8000/#/jobs/{job_id}  (with the server running)")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="public YouTube URL to probe")
    ap.add_argument("--e2e", action="store_true", help="run the full pipeline on --url")
    ap.add_argument("--authorized", action="store_true", help="confirm you own / may process the video (required for --e2e)")
    ap.add_argument("--max-clips", type=int, default=3)
    ap.add_argument("--report", default="doctor_report.json")
    a = ap.parse_args()

    ok = check_environment()
    if a.url:
        ok = probe_url(a.url) and ok
        if a.e2e:
            if not a.authorized:
                line("FAIL", "End-to-end", "add --authorized to confirm you own or may process this video")
                ok = False
            elif ok:
                ok = run_e2e(a.url, a.max_clips)
            else:
                line("FAIL", "End-to-end", "skipped because earlier checks failed")
    Path(a.report).write_text(json.dumps(REPORT, indent=2, default=str), encoding="utf-8")
    print(f"\n{'ALL CHECKS PASSED' if ok else 'SOME CHECKS FAILED'} - report written to {os.path.abspath(a.report)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
