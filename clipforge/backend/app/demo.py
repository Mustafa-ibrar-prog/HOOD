"""Demo mode: a clearly-labelled synthetic sample so the UI can be tried without
network access or API keys.

The sample "video" is generated locally with FFmpeg (a labelled test card, no
real footage) and paired with a scripted, hand-written transcript. Nothing about
it pretends to be a real processed video: the job is flagged ``is_demo`` and the
source title says SAMPLE.
"""
from __future__ import annotations

import os
from pathlib import Path

from .config import settings
from .models import Segment, SourceInfo, Transcript
from .video.ffmpeg import run

SAMPLE_TITLE = "SAMPLE — Synthetic demo video with scripted transcript (not a real source)"

# A scripted conversation used only for demo mode.
SAMPLE_SCRIPT: list[str] = [
    "Welcome back to the show.",
    "Today we're talking about learning to code as an adult.",
    "So let's just get into it.",
    "Here's the thing nobody tells you about learning to code.",
    "It's not the syntax that stops people.",
    "It's the feeling of being stupid for six months straight.",
    "I remember my first week, I spent nine hours on a missing semicolon.",
    "Nine hours!",
    "[Laughter]",
    "And when I finally found it, I didn't feel smart, I felt furious.",
    "But that's why most people quit in the first month.",
    "The lesson is simple: the confusion is the learning.",
    "Okay, so, um, anyway.",
    "Let's talk about bootcamps for a second.",
    "Unpopular opinion: most coding bootcamps are overrated.",
    "No, I disagree, that's not true at all.",
    "Hear me out, you're paying fifteen thousand dollars for a curriculum that's free online.",
    "But you're not paying for the curriculum, you're paying for the structure and the deadlines.",
    "That's actually a fair point, most people need someone to hold them accountable.",
    "So the answer is: if you're disciplined, skip it; if you're not, the structure is worth the money.",
    "Alright, quick break.",
    "Did you know that seventy percent of developers say they're mostly self-taught?",
    "That's a real number from a big developer survey.",
    "Which means the degree matters way less than people think.",
    "What matters is that you can show your work.",
    "Here's how to do that: build three small projects that solve a real problem you actually have.",
    "Not a to-do app, everyone has a to-do app.",
    "[Laughter]",
    "Build the thing your friends would actually use.",
    "That's the secret to getting hired without a degree.",
    "My dad was a truck driver for thirty years.",
    "When I told him I was quitting my job to learn programming at thirty-five, he went quiet.",
    "Then he said: I always wished I had tried something like that.",
    "I still think about that conversation every single day.",
    "It changed my life, honestly.",
    "Anyway, that's all for today.",
    "Thanks for listening, see you next week.",
]


def drawtext_font_arg(path: Path) -> str:
    """``fontfile='C\\:/Windows/Fonts/arial.ttf':`` — drive-letter colon escaped for ffmpeg's option parser."""
    return "fontfile='" + path.as_posix().replace(":", "\\:") + "':"


def _scripted_transcript() -> Transcript:
    segments: list[Segment] = []
    t = 1.0
    for line in SAMPLE_SCRIPT:
        if line.startswith("["):
            segments.append(Segment(start=round(t, 2), end=round(t + 1.5, 2), text=line))
            t += 1.8
            continue
        n = len(line.split())
        dur = max(n / 2.9, 0.9)
        segments.append(Segment(start=round(t, 2), end=round(t + dur, 2), text=line))
        t += dur + (0.9 if line.endswith(("?", "!")) else 0.35)
    return Transcript(source="sample_script", language="en", segments=segments, has_word_timing=False)


def sample_assets() -> tuple[Path, Transcript, SourceInfo]:
    transcript = _scripted_transcript()
    duration = transcript.segments[-1].end + 2.0
    out_dir = settings.data_dir / "sample"
    out_dir.mkdir(parents=True, exist_ok=True)
    video = out_dir / "sample_v1.mp4"
    if not video.exists():
        tmp = out_dir / "sample_v1.tmp.mp4"
        label = "SAMPLE VIDEO  -  synthetic demo  -  no real footage"
        # Windows FFmpeg builds often can't resolve a default font for drawtext; point at Arial explicitly.
        win_font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf"
        font = drawtext_font_arg(win_font) if os.name == "nt" and win_font.exists() else ""
        vf = (
            f"drawtext={font}text='{label}':fontcolor=white:fontsize=34:x=(w-text_w)/2:y=h*0.12:box=1:boxcolor=black@0.5:boxborderw=14,"
            f"drawtext={font}text='%{{pts\\:hms}}':fontcolor=white:fontsize=56:x=(w-text_w)/2:y=h*0.45"
        )
        run([
            settings.ffmpeg_bin, "-y", "-v", "error",
            "-f", "lavfi", "-i", f"gradients=s=1280x720:r=25:d={duration:.2f}:speed=0.01:c0=0x1f2a6b:c1=0x7b2a6b",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-vf", vf, "-t", f"{duration:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(tmp),
        ], timeout=600)
        tmp.replace(video)
    source = SourceInfo(provider="sample", url="sample://demo", title=SAMPLE_TITLE, channel="ClipForge demo",
                        duration=round(duration, 2), width=1280, height=720, is_sample=True)
    return video, transcript, source
