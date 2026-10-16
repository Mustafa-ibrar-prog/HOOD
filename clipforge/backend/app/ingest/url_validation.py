"""URL parsing / validation for supported video sources.

Pure functions, no network — easy to unit test.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_YT_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}


class UrlValidationError(ValueError):
    def __init__(self, message: str, code: str = "invalid_url"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ParsedVideoUrl:
    provider: str
    video_id: str
    canonical_url: str
    kind: str  # watch | short | live | embed | shortlink
    start_seconds: Optional[int] = None


def _parse_t(value: str) -> Optional[int]:
    """Parse YouTube's t= parameter: '90', '90s', '1m30s', '1h2m3s'."""
    value = value.strip().lower()
    if value.isdigit():
        return int(value)
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", value)
    if not m or not any(m.groups()):
        return None
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mi * 60 + s


def parse_youtube_url(raw: str) -> ParsedVideoUrl:
    if not raw or not raw.strip():
        raise UrlValidationError("Please paste a video URL.", "empty_url")
    raw = raw.strip()
    if len(raw) > 2048:
        raise UrlValidationError("That URL is too long.")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = "https://" + raw  # tolerate "youtube.com/watch?v=..." without a scheme
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise UrlValidationError("Only http(s) URLs are supported.")
    host = (parsed.hostname or "").lower()
    query = parse_qs(parsed.query)
    path_parts = [p for p in parsed.path.split("/") if p]

    video_id: Optional[str] = None
    kind = "watch"
    if host in _YT_SHORT_HOSTS:
        kind = "shortlink"
        video_id = path_parts[0] if path_parts else None
    elif host in _YT_HOSTS:
        if path_parts[:1] == ["watch"]:
            video_id = (query.get("v") or [None])[0]
        elif path_parts[:1] in (["shorts"], ["live"], ["embed"], ["v"], ["e"]):
            kind = {"shorts": "short", "live": "live", "embed": "embed", "v": "embed", "e": "embed"}[path_parts[0]]
            video_id = path_parts[1] if len(path_parts) > 1 else None
        elif path_parts[:1] == ["playlist"]:
            raise UrlValidationError(
                "Playlist URLs aren't supported — paste the URL of a single video.", "playlist_url"
            )
        elif path_parts and (path_parts[0].startswith("@") or path_parts[0] in {"channel", "c", "user"}):
            raise UrlValidationError(
                "That's a channel URL — paste the URL of a single video.", "channel_url"
            )
    else:
        raise UrlValidationError(
            "Unsupported source. Paste a YouTube video URL (youtube.com/watch, youtu.be, or /shorts).",
            "unsupported_source",
        )

    if not video_id or not _YT_ID.match(video_id):
        raise UrlValidationError("This doesn't look like a valid YouTube video link (missing or malformed video ID).")

    start = None
    t = (query.get("t") or query.get("start") or [None])[0]
    if t:
        start = _parse_t(t)

    return ParsedVideoUrl(
        provider="youtube",
        video_id=video_id,
        canonical_url=f"https://www.youtube.com/watch?v={video_id}",
        kind=kind,
        start_seconds=start,
    )
