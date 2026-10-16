"""The real (non-demo) URL path, end to end, with YouTube replaced by a local stand-in provider.

Covers what the demo cannot: provider -> platform captions (json3 parsed like real
YouTube auto-captions) -> transcript strategy -> analysis -> render -> verification
done by scripts/doctor.py. Network access to YouTube itself is NOT exercised here.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.ingest import registry
from app.ingest.base import IngestError, VideoProvider
from app.ingest.youtube import map_ytdlp_error
from app.models import SourceInfo
from app.transcribe.captions import parse_json3
from app.models import Transcript

from .conftest import needs_ffmpeg

LINES = [
    "Here's the thing nobody tells you about public speaking.",
    "Everyone is nervous, even the professionals.",
    "I remember my first talk, my hands were shaking so badly I dropped the microphone.",
    "The whole room went silent!",
    "But that's why I tell people to practice out loud at least ten times.",
    "Unpopular opinion: slides are overrated.",
    "No, I disagree, slides help people follow along.",
    "Hear me out, most slides are just the speaker reading text.",
    "So the answer is: use slides for pictures, not for paragraphs.",
]


def _json3(lines, start=1.0, wps=2.7):
    """Build YouTube json3 auto-caption events with per-word offsets."""
    events, t = [], start
    for line in lines:
        words = line.split()
        segs = [{"utf8": words[0]}] + [{"utf8": " " + w, "tOffsetMs": int(i * 1000 / wps)} for i, w in enumerate(words[1:], 1)]
        dur = len(words) / wps
        events.append({"tStartMs": int(t * 1000), "dDurationMs": int(dur * 1000), "segs": segs})
        t += dur + 0.4
    return {"events": events}, t + 1.0


class LocalStandInProvider(VideoProvider):
    """Behaves like YouTubeProvider but serves a local file + json3 captions."""

    name = "youtube"

    def __init__(self, video: Path, captions: dict, duration: float):
        self.video, self.captions, self.duration = video, captions, duration

    def matches(self, url):  # claim YouTube URLs, exactly like the real provider
        return "youtu" in url

    def fetch_metadata(self, url):
        return SourceInfo(provider="youtube", url=url, video_id="aaaaaaaaaaa", title="Stand-in public talk",
                          channel="Test", duration=self.duration)

    def fetch_captions(self, source, workdir, language):
        segs = parse_json3(self.captions)
        return Transcript(source="youtube_auto_captions", segments=segs, has_word_timing=True), False

    def download(self, source, workdir, progress):
        dst = workdir / "source.mp4"
        shutil.copy(self.video, dst)
        progress(1.0, "copied")
        return dst


@pytest.fixture
def stand_in(tmp_path, monkeypatch):
    captions, duration = _json3(LINES)
    video = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=25:duration={duration:.1f}",
                    "-f", "lavfi", "-i", f"sine=f=220:d={duration:.1f}", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(video)], check=True)
    provider = LocalStandInProvider(video, captions, duration)
    monkeypatch.setattr(registry, "_PROVIDERS", [provider])
    return provider


@needs_ffmpeg
@pytest.mark.slow
def test_url_job_through_doctor_e2e(stand_in, tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import doctor

    assert doctor.run_e2e("https://youtu.be/aaaaaaaaaaa", max_clips=2) is True
    e2e = doctor.REPORT["e2e"]
    assert e2e["status"] == "completed"
    assert e2e["transcript_source"] == "youtube_auto_captions"
    assert e2e["analyzer"] == "heuristic"
    assert any("auto-generated captions" in w for w in e2e["warnings"])  # honest about caption quality
    assert e2e["clips"] and all(not c["problems"] for c in e2e["clips"])
    assert all(c["size"] == "1080x1920" for c in e2e["clips"])  # 1080p source -> full-res vertical
    json.dumps(doctor.REPORT, default=str)  # report is serialisable


@pytest.mark.parametrize("text,code", [
    ("WARNING: [youtube] No supported JavaScript runtime could be found. Only deno is enabled by default\n"
     "ERROR: [youtube] x: Requested format is not available", "ytdlp_js_runtime"),
    ("WARNING: [youtube] x: Signature solving failed: Some formats may be missing.", "ytdlp_js_runtime"),
    ("ERROR: [youtube] x: Requested format is not available. Use --list-formats", "no_formats"),
])
def test_js_runtime_failures_are_diagnosed(text, code):
    err = map_ytdlp_error(text)
    assert err.code == code
    assert "Deno" in str(err) and "yt-dlp[default]" in str(err)
    assert err.detail.endswith(text.strip()[-50:])


def test_ingest_error_keeps_raw_detail():
    e = map_ytdlp_error("ERROR: Unable to download API page: Tunnel connection failed: 403 Forbidden")
    assert e.code == "network_error" and "403 Forbidden" in e.detail
    assert isinstance(e, IngestError)
