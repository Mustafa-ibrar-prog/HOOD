import pytest

from app.ingest.url_validation import UrlValidationError, parse_youtube_url
from app.ingest.youtube import map_ytdlp_error

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url,kind",
    [
        (f"https://www.youtube.com/watch?v={VID}", "watch"),
        (f"https://youtube.com/watch?v={VID}&t=42s", "watch"),
        (f"http://m.youtube.com/watch?feature=share&v={VID}", "watch"),
        (f"youtube.com/watch?v={VID}", "watch"),
        (f"https://youtu.be/{VID}", "shortlink"),
        (f"https://youtu.be/{VID}?si=abcdef&t=10", "shortlink"),
        (f"https://www.youtube.com/shorts/{VID}", "short"),
        (f"https://youtube.com/shorts/{VID}?feature=share", "short"),
        (f"https://www.youtube.com/live/{VID}", "live"),
        (f"https://www.youtube.com/embed/{VID}", "embed"),
        (f"https://music.youtube.com/watch?v={VID}", "watch"),
        (f"  https://www.youtube.com/watch?v={VID}  ", "watch"),
    ],
)
def test_valid_urls(url, kind):
    p = parse_youtube_url(url)
    assert p.video_id == VID
    assert p.kind == kind
    assert p.canonical_url == f"https://www.youtube.com/watch?v={VID}"


def test_timestamp_parsing():
    assert parse_youtube_url(f"https://youtu.be/{VID}?t=1m30s").start_seconds == 90
    assert parse_youtube_url(f"https://youtube.com/watch?v={VID}&t=75").start_seconds == 75


@pytest.mark.parametrize(
    "url,code",
    [
        ("", "empty_url"),
        ("   ", "empty_url"),
        ("https://vimeo.com/12345", "unsupported_source"),
        ("https://example.com/watch?v=dQw4w9WgXcQ", "unsupported_source"),
        ("https://www.youtube.com/playlist?list=PL123", "playlist_url"),
        ("https://www.youtube.com/@somechannel", "channel_url"),
        ("https://www.youtube.com/watch?v=short", "invalid_url"),
        ("https://www.youtube.com/watch", "invalid_url"),
        ("https://youtu.be/", "invalid_url"),
        ("ftp://youtube.com/watch?v=dQw4w9WgXcQ", "invalid_url"),
        ("javascript:alert(1)", "unsupported_source"),
        ("https://www.youtube.com/watch?v=" + "a" * 3000, "invalid_url"),
    ],
)
def test_invalid_urls(url, code):
    with pytest.raises(UrlValidationError) as e:
        parse_youtube_url(url)
    assert e.value.code == code


@pytest.mark.parametrize(
    "text,code,retryable",
    [
        ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", "video_private", False),
        ("ERROR: [youtube] abc: Sign in to confirm your age.", "video_age_restricted", False),
        ("ERROR: [youtube] abc: Join this channel to get access to members-only content", "video_members_only", False),
        ("ERROR: [youtube] abc: Video unavailable", "video_unavailable", False),
        ("ERROR: The uploader has not made this video available in your country", "video_geo_blocked", False),
        ("ERROR: [youtube] abc: This live event will begin in 3 hours.", "video_upcoming", False),
        ("ERROR: HTTP Error 429: Too Many Requests", "rate_limited", True),
        ("ERROR: Unable to download webpage: <urlopen error Tunnel connection failed: 403>", "network_error", True),
        ("ERROR: Sign in to confirm you're not a bot", "platform_bot_check", True),
        ("ERROR: something entirely new", "ingest_failed", False),
    ],
)
def test_ytdlp_error_mapping(text, code, retryable):
    err = map_ytdlp_error(text)
    assert err.code == code
    assert err.retryable is retryable
