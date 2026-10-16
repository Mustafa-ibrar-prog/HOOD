"""YouTube ingestion via yt-dlp.

Compliance notes:
  * Only publicly accessible videos are supported. No cookies / logins are
    passed, so private, members-only, age-gated-behind-login and region-locked
    videos fail with a clear error rather than being worked around.
  * yt-dlp does not decrypt DRM-protected formats, and we never ask it to.
  * The user must confirm they own or are authorised to process the content
    (enforced at the API layer).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from ..config import settings
from ..models import SourceInfo, Transcript
from ..transcribe.captions import parse_json3, parse_vtt
from .base import IngestError, ProgressFn, VideoProvider
from .url_validation import UrlValidationError, parse_youtube_url

log = logging.getLogger(__name__)

# (regex on yt-dlp error text, user-facing message, code, retryable)
_JS_HELP = ("Install Deno (Windows: winget install DenoLand.Deno · macOS: brew install deno · Linux: see deno.com), "
            "run  pip install -U \"yt-dlp[default]\"  and restart the ClipForge server.")

_ERROR_MAP: list[tuple[str, str, str, bool]] = [
    (r"no supported javascript runtime|signature solving failed|n challenge solving failed|challenge solver|\bejs\b",
     "yt-dlp could not solve YouTube's player challenge because no JavaScript runtime is available. " + _JS_HELP,
     "ytdlp_js_runtime", False),
    (r"requested format is not available|no video formats found",
     "YouTube offered no downloadable video format. This usually means yt-dlp couldn't solve YouTube's player "
     "challenge (" + _JS_HELP + ") or that yt-dlp is out of date (pip install -U \"yt-dlp[default]\").",
     "no_formats", False),
    (r"private video", "This video is private. Only public videos can be processed.", "video_private", False),
    (r"members[- ]only|join this channel", "This video is restricted to channel members.", "video_members_only", False),
    (r"sign in to confirm your age|age[- ]restricted|inappropriate for some users",
     "This video is age-restricted and requires sign-in, so it can't be processed.", "video_age_restricted", False),
    (r"available in your country|geo.?restrict|blocked it in your country",
     "This video isn't available in the server's region.", "video_geo_blocked", False),
    (r"sign in to confirm you.re not a bot|confirm you are not a robot",
     "YouTube is asking this server to prove it isn't a bot. Try again later or from a different network.",
     "platform_bot_check", True),
    (r"copyright|removed by the uploader|account .* terminated|has been removed",
     "This video has been removed or is unavailable.", "video_removed", False),
    (r"this live event will begin|premieres in|is upcoming",
     "This live stream or premiere hasn't started yet.", "video_upcoming", False),
    (r"drm", "This video is DRM-protected and can't be processed.", "video_drm", False),
    (r"video unavailable|does not exist|incomplete youtube id|unable to extract",
     "This video is unavailable (it may be deleted, private, or the link is wrong).", "video_unavailable", False),
    (r"http error 429|too many requests", "YouTube is rate-limiting requests. Please retry in a few minutes.", "rate_limited", True),
    (r"timed out|connection|network is unreachable|tunnel|proxy|name or service not known|temporary failure",
     "Couldn't reach YouTube from the server (network error).", "network_error", True),
]


def map_ytdlp_error(text: str) -> IngestError:
    low = text.lower()
    detail = text.strip()[-1500:]
    for pattern, message, code, retryable in _ERROR_MAP:
        if re.search(pattern, low):
            return IngestError(message, code, retryable, detail)
    return IngestError(f"Could not access this video: {text.strip()[:300]}", "ingest_failed", False, detail)


class _CollectingLogger:
    """Keeps yt-dlp's warnings (they explain *why* an extraction failed) without printing them."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def debug(self, msg: str) -> None:
        pass

    info = debug

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def error(self, msg: str) -> None:
        self.warnings.append(msg)


def _ingest_error(e: Exception, logger: "_CollectingLogger") -> IngestError:
    # Warnings first: "no JavaScript runtime" is only ever a warning, followed by a generic error.
    return map_ytdlp_error("\n".join(logger.warnings[-5:] + [str(e)]))


def _ydl_base_opts() -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": settings.download_retries,
        "fragment_retries": settings.download_retries,
        "socket_timeout": 30,
        "noprogress": True,
        # Never pass cookies / credentials: public content only.
        "cookiefile": None,
    }


class YouTubeProvider(VideoProvider):
    name = "youtube"

    def __init__(self) -> None:
        self._info_cache: dict[str, dict] = {}

    def matches(self, url: str) -> bool:
        try:
            parse_youtube_url(url)
            return True
        except UrlValidationError:
            return False

    # ------------------------------------------------------------------ metadata
    def _extract(self, url: str) -> dict:
        import yt_dlp  # imported lazily so tests don't need it

        logger = _CollectingLogger()
        try:
            with yt_dlp.YoutubeDL({**_ydl_base_opts(), "skip_download": True, "logger": logger}) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:  # DownloadError and anything unexpected
            raise _ingest_error(e, logger) from e
        if not info:
            raise IngestError("YouTube returned no information for this video.", "video_unavailable")
        return info

    def fetch_metadata(self, url: str) -> SourceInfo:
        parsed = parse_youtube_url(url)
        info = self._extract(parsed.canonical_url)
        self._info_cache[parsed.video_id] = info

        if info.get("is_live") or info.get("live_status") == "is_live":
            raise IngestError(
                "This is a live stream that's still in progress. Try again once the broadcast has ended and the recording is available.",
                "video_live",
            )
        if info.get("live_status") in {"is_upcoming"}:
            raise IngestError("This premiere / live stream hasn't started yet.", "video_upcoming")
        if info.get("availability") in {"private", "premium_only", "subscriber_only", "needs_auth"}:
            raise IngestError(
                f"This video isn't publicly available ({info.get('availability')}).", "video_not_public"
            )
        if info.get("has_drm"):
            raise IngestError("This video is DRM-protected and can't be processed.", "video_drm")

        duration = info.get("duration")
        if settings.max_video_seconds and duration and duration > settings.max_video_seconds:
            raise IngestError(
                f"This video is {duration/60:.0f} min long; this server is configured for at most "
                f"{settings.max_video_seconds/60:.0f} min (MAX_VIDEO_SECONDS).",
                "video_too_long",
            )
        return SourceInfo(
            provider=self.name,
            url=parsed.canonical_url,
            video_id=parsed.video_id,
            title=info.get("title") or parsed.video_id,
            channel=info.get("channel") or info.get("uploader"),
            duration=float(duration) if duration else None,
            thumbnail_url=info.get("thumbnail"),
            width=info.get("width"),
            height=info.get("height"),
        )

    # ------------------------------------------------------------------ captions
    def fetch_captions(self, source: SourceInfo, workdir: Path, language: str) -> Optional[tuple[Transcript, bool]]:
        """Download platform captions (manual preferred, auto as fallback).

        Returns None when no captions in a matching language exist.
        """
        import yt_dlp

        info = self._info_cache.get(source.video_id or "") or self._extract(source.url)
        lang_prefix = (language or "en").split("-")[0].lower()

        def pick(tracks: dict) -> Optional[str]:
            if not tracks:
                return None
            for key in tracks:
                if key.lower() == lang_prefix:
                    return key
            for key in tracks:
                if key.lower().startswith(lang_prefix) and "translated" not in key.lower():
                    return key
            return None

        manual = info.get("subtitles") or {}
        auto = info.get("automatic_captions") or {}
        choice: Optional[tuple[str, bool]] = None
        if (k := pick(manual)):
            choice = (k, True)
        elif (k := pick(auto)):
            # auto captions: the "orig" track is the real ASR, others are machine translations
            orig = next((x for x in auto if x.endswith("-orig") and x.startswith(lang_prefix)), None)
            choice = (orig or k, False)
        if not choice:
            return None
        lang_key, is_manual = choice
        sub_dir = workdir / "subs"
        sub_dir.mkdir(parents=True, exist_ok=True)
        opts = {
            **_ydl_base_opts(),
            "skip_download": True,
            "writesubtitles": is_manual,
            "writeautomaticsub": not is_manual,
            "subtitleslangs": [lang_key],
            "subtitlesformat": "json3/vtt/best",
            "outtmpl": str(sub_dir / "captions.%(ext)s"),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([source.url])
        except Exception as e:
            log.warning("caption download failed: %s", e)
            return None
        files = sorted(sub_dir.glob("captions*"))
        for f in files:
            text = f.read_text(encoding="utf-8", errors="replace")
            try:
                if f.suffix == ".json3":
                    segs = parse_json3(json.loads(text))
                elif f.suffix == ".vtt":
                    segs = parse_vtt(text)
                else:
                    continue
            except Exception as e:  # malformed file — try the next one
                log.warning("could not parse captions %s: %s", f, e)
                continue
            if segs:
                return (
                    Transcript(
                        source="youtube_manual_captions" if is_manual else "youtube_auto_captions",
                        language=lang_key,
                        segments=segs,
                        has_word_timing=any(s.words for s in segs),
                    ),
                    is_manual,
                )
        return None

    # ------------------------------------------------------------------ download
    def download(self, source: SourceInfo, workdir: Path, progress: ProgressFn) -> Path:
        import yt_dlp

        h = settings.max_download_height
        fmt = (
            f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/"
            f"bv*[height<={h}]+ba/"
            f"b[height<={h}]/bv*+ba/b"
        )

        def hook(d: dict) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                if total:
                    progress(min(done / total, 1.0), f"Downloading… {done/1e6:.0f} / {total/1e6:.0f} MB")
            elif d.get("status") == "finished":
                progress(1.0, "Download finished, merging streams…")

        opts = {
            **_ydl_base_opts(),
            "format": fmt,
            "merge_output_format": "mp4",
            "outtmpl": str(workdir / "source.%(ext)s"),
            "progress_hooks": [hook],
            "ffmpeg_location": None if settings.ffmpeg_bin == "ffmpeg" else str(Path(settings.ffmpeg_bin).parent),
            "concurrent_fragment_downloads": 4,
        }
        logger = _CollectingLogger()
        opts["logger"] = logger
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([source.url])
        except Exception as e:
            raise _ingest_error(e, logger) from e
        candidates = [p for p in workdir.glob("source.*") if p.suffix in {".mp4", ".mkv", ".webm", ".mov"}]
        if not candidates:
            raise IngestError("The download finished but no video file was produced.", "download_failed", True)
        return max(candidates, key=lambda p: p.stat().st_size)
