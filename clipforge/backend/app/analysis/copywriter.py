"""Platform titles / descriptions / hashtags without an LLM.

Built only from verbatim transcript text and the source title, so nothing is invented.
"""
from __future__ import annotations

import re
from collections import Counter

from ..models import PlatformCopy
from .lexicon import COMMON_WORDS, STOPWORDS

_TYPE_TAGS = {
    "funny": ["#funny", "#comedy"],
    "debate": ["#debate", "#hottake"],
    "emotional": ["#emotional", "#story"],
    "educational": ["#learnontiktok", "#tips"],
    "gaming": ["#gaming", "#gamer"],
    "surprising": ["#mindblown", "#didyouknow"],
    "story": ["#storytime", "#story"],
    "suspense": ["#wait", "#storytime"],
    "conversation": ["#podcast", "#conversation"],
}
_PLATFORM_TAGS = {
    "youtube_shorts": ["#shorts"],
    "tiktok": ["#fyp", "#foryou"],
    "instagram_reels": ["#reels", "#explore"],
}


def shorten(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:-")
    return cut + "…"


def keywords(text: str, n: int = 3) -> list[str]:
    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z']{3,}", text.lower()) if w not in STOPWORDS and w not in COMMON_WORDS and "'" not in w]
    return [w for w, _ in Counter(words).most_common(n)]


def heuristic_copy(hook: str, clip_text: str, content_type: str, source_title: str) -> dict[str, PlatformCopy]:
    title = shorten(hook.strip().strip('"'), 68)
    kw_tags = ["#" + k for k in keywords(clip_text)]
    base = _TYPE_TAGS.get(content_type, _TYPE_TAGS["conversation"])
    src = shorten(source_title, 80) if source_title else ""
    out: dict[str, PlatformCopy] = {}
    for platform, ptags in _PLATFORM_TAGS.items():
        tags: list[str] = []
        for t in ptags + base + kw_tags:
            if t.lower() not in {x.lower() for x in tags}:
                tags.append(t)
        desc = f"“{shorten(hook, 140)}”" + (f" — from “{src}”." if src else "")
        out[platform] = PlatformCopy(title=title, description=desc, hashtags=tags[:8])
    return out
