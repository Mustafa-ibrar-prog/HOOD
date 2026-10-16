import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Isolate test data from any real data dir *before* app modules import settings.
_TMP = Path(tempfile.mkdtemp(prefix="clipforge-test-"))
os.environ["CLIPFORGE_DATA_DIR"] = str(_TMP)
os.environ["ANALYSIS_PROVIDER"] = "heuristic"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Segment, Transcript, Word  # noqa: E402

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


def make_transcript(lines: list[str], wps: float = 2.8, gap: float = 0.35, start: float = 0.5) -> Transcript:
    """Build a transcript with word-level timings from plain sentences."""
    segs = []
    t = start
    for line in lines:
        words = []
        for tok in line.split():
            d = 1.0 / wps
            words.append(Word(start=round(t, 3), end=round(t + d * 0.9, 3), text=tok))
            t += d
        segs.append(Segment(start=words[0].start, end=words[-1].end, text=line, words=words))
        t += gap
    return Transcript(source="test", segments=segs, has_word_timing=True)


@pytest.fixture(scope="session")
def tmp_media_dir():
    d = _TMP / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(scope="session")
def sample_video(tmp_media_dir):
    """A 1280x720, 75 s synthetic video with a tone track."""
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    import subprocess

    out = tmp_media_dir / "src.mp4"
    if not out.exists():
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=75",
             "-f", "lavfi", "-i", "sine=f=300:d=75", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
             "-shortest", str(out)],
            check=True,
        )
    return out
