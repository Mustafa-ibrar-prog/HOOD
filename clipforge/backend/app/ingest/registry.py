from __future__ import annotations

from .base import VideoProvider
from .url_validation import UrlValidationError, parse_youtube_url
from .youtube import YouTubeProvider

_PROVIDERS: list[VideoProvider] = [YouTubeProvider()]


def register_provider(provider: VideoProvider) -> None:
    _PROVIDERS.insert(0, provider)


def provider_for(url: str) -> VideoProvider:
    for p in _PROVIDERS:
        if p.matches(url):
            return p
    # Re-run the YouTube parser to surface its specific error message.
    parse_youtube_url(url)
    raise UrlValidationError("Unsupported video source.", "unsupported_source")  # pragma: no cover
