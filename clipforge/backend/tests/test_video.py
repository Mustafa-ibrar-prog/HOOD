"""FFmpeg utilities, captions/ASS, reframing maths and real renders (needs ffmpeg)."""
import subprocess

import pytest

from app.analysis.audio_energy import loudness_curve, parse_astats
from app.models import CaptionLine, CaptionStyle, RenderOptions, Word
from app.video import reframe
from app.video.captions import _ass_time, build_caption_lines, line_words, write_ass
from app.video.ffmpeg import FFmpegError, extract_audio, probe, run, split_audio
from app.video.render import output_size, render_clip

from .conftest import needs_ffmpeg


# ---------------------------------------------------------------- captions
def _words(n, start=10.0, step=0.4):
    return [Word(start=start + i * step, end=start + i * step + 0.35, text=f"w{i}") for i in range(n)]


def test_caption_lines_relative_and_grouped():
    lines = build_caption_lines(_words(10), clip_start=10.0, clip_end=15.0, words_per_caption=3)
    assert lines[0].start == 0.0
    assert all(len(ln.text.split()) <= 3 for ln in lines)
    assert all(0 <= ln.start < ln.end <= 5.0 for ln in lines)
    assert " ".join(ln.text for ln in lines) == " ".join(f"w{i}" for i in range(10))


def test_caption_lines_break_on_pause_and_drop_markers():
    ws = [Word(start=0, end=0.3, text="Hi."), Word(start=0.35, end=0.6, text="[Laughter]"),
          Word(start=2.0, end=2.3, text="later"), Word(start=2.3, end=2.6, text="words")]
    lines = build_caption_lines(ws, 0, 5, words_per_caption=4)
    assert [ln.text for ln in lines] == ["Hi.", "later words"]


def test_edited_caption_text_redistributes_timing():
    ln = CaptionLine(start=1.0, end=2.0, text="new edited text here", words=_words(2, 1.0))
    ws = line_words(ln)
    assert [w.text for w in ws] == ["new", "edited", "text", "here"]
    assert ws[0].start == 1.0 and ws[-1].end == pytest.approx(2.0)


def test_ass_file(tmp_path):
    lines = [CaptionLine(start=0, end=1.2, text="Hello {world}", words=[Word(start=0, end=0.5, text="Hello"), Word(start=0.5, end=1.2, text="{world}")])]
    style = CaptionStyle(primary_color="#FFFFFF", highlight_color="#00FF00", position="middle", uppercase=True)
    p = write_ass(lines, style, 1080, 1920, tmp_path / "c.ass")
    txt = p.read_text()
    assert "PlayResX: 1080" in txt and "PlayResY: 1920" in txt
    assert "&H0000FF00" in txt  # BGR-encoded highlight
    assert "HELLO" in txt and "{world}" not in txt  # escaped braces, uppercase
    assert txt.count("Dialogue:") == 2  # one event per highlighted word
    assert _ass_time(3725.5) == "1:02:05.50"


def test_caption_style_validation():
    with pytest.raises(ValueError):
        CaptionStyle(primary_color="red")
    with pytest.raises(ValueError):
        CaptionStyle(font_size=500)


# ---------------------------------------------------------------- reframing maths
def test_output_size():
    assert output_size(2160) == (1080, 1920)
    assert output_size(1080) == (1080, 1920)
    assert output_size(720) == (720, 1280)
    assert output_size(480) == (540, 960)


def _analysis(xs):
    return reframe.FaceAnalysis(
        samples=[reframe.FaceSample(t=i / 3, faces=[reframe.FaceBox(x - 0.05, 0.3, 0.1, 0.2)] if x is not None else []) for i, x in enumerate(xs)],
        coverage=sum(x is not None for x in xs) / len(xs), median_face_h=0.2)


def test_face_track_follows_subject_with_deadzone():
    xs = [0.3] * 10 + [0.32] * 5 + [0.7] * 10
    keys = reframe.plan_face_track(_analysis(xs))
    assert keys[0] == (0.0, pytest.approx(0.3, abs=0.03))
    assert keys[-1][1] == pytest.approx(0.7, abs=0.03)
    # small jitter (0.30 -> 0.32) must not move the camera: only one move
    assert len(keys) == 3


def test_face_track_none_when_no_faces():
    assert reframe.plan_face_track(_analysis([None] * 10)) is None


def test_fill_gaps_interpolates():
    assert reframe.fill_gaps([None, 0.2, None, 0.4, None]) == pytest.approx([0.2, 0.2, 0.3, 0.4, 0.4])


def test_speaker_switch_requires_persistence():
    # two faces; the right one becomes the active (moving-mouth) speaker for one sample only -> no switch
    def sample(t, motion_right):
        return reframe.FaceSample(t=t, faces=[reframe.FaceBox(0.15, 0.3, 0.1, 0.2, motion=1.0),
                                             reframe.FaceBox(0.75, 0.3, 0.1, 0.2, motion=motion_right)])
    a = reframe.FaceAnalysis(samples=[sample(0, 0.1), sample(0.3, 5.0), sample(0.6, 0.1)], coverage=1, median_face_h=0.2)
    assert all(abs(x - 0.2) < 0.01 for x in reframe.choose_targets(a))
    b = reframe.FaceAnalysis(samples=[sample(0, 0.1)] + [sample(0.3 * i, 5.0) for i in range(1, 5)], coverage=1, median_face_h=0.2)
    assert abs(reframe.choose_targets(b)[-1] - 0.8) < 0.01


def test_crop_expression_is_clamped_and_piecewise():
    expr = reframe.crop_x_expression([(0, 0.0), (1, 0.5), (2, 1.0)], src_w=1920, crop_w=608)
    assert expr.startswith("if(lt(t,1)")
    assert "0.0" in expr and "1312.0" in expr  # clamped to [0, src_w - crop_w]


def test_facecam_detection():
    samples = [reframe.FaceSample(t=i, faces=[reframe.FaceBox(0.85, 0.05, 0.06, 0.1)]) for i in range(10)]
    fc = reframe.detect_facecam(reframe.FaceAnalysis(samples=samples, coverage=1, median_face_h=0.1))
    assert fc and fc.x > 0.6 and fc.y < 0.2
    center = [reframe.FaceSample(t=i, faces=[reframe.FaceBox(0.45, 0.3, 0.1, 0.3)]) for i in range(10)]
    assert reframe.detect_facecam(reframe.FaceAnalysis(samples=center, coverage=1, median_face_h=0.3)) is None


def test_parse_astats():
    txt = "frame:0 pts:0\nlavfi.astats.Overall.RMS_level=-23.5\nframe:1\nlavfi.astats.Overall.RMS_level=-inf\n"
    assert parse_astats(txt) == [-23.5, -100.0]


# ---------------------------------------------------------------- real ffmpeg
@needs_ffmpeg
def test_probe_and_audio(sample_video, tmp_path):
    info = probe(sample_video)
    assert info.width == 1280 and info.height == 720 and info.has_audio
    assert 74 < info.duration < 76
    audio = extract_audio(sample_video, tmp_path / "a.flac")
    assert probe(audio).has_audio
    curve = loudness_curve(audio)
    assert 70 <= len(curve) <= 76 and all(-60 < v < 0 for v in curve[:-1])  # last window may be partial
    chunks = split_audio(audio, tmp_path / "chunks", chunk_seconds=30)
    assert [round(o) for _, o in chunks] == [0, 30, 60]


@needs_ffmpeg
def test_run_raises_on_failure(tmp_path):
    with pytest.raises(FFmpegError):
        run(["ffmpeg", "-v", "error", "-i", str(tmp_path / "missing.mp4"), str(tmp_path / "x.mp4")])
    with pytest.raises(FFmpegError):
        run(["definitely-not-a-binary-xyz"])


@needs_ffmpeg
@pytest.mark.parametrize("layout", ["center", "blur", "gaming", "auto"])
def test_render_vertical_clip(sample_video, tmp_path, layout):
    caps = [CaptionLine(start=0.2, end=2.0, text="Hello there", words=[])]
    res = render_clip(sample_video, 10.0, 22.0, caps, RenderOptions(layout=layout), tmp_path / "c.mp4")
    info = probe(res.path)
    assert (info.width, info.height) == (720, 1280)  # 720p source -> 720x1280
    assert abs(info.duration - 12.0) < 0.2
    assert info.has_audio
    assert res.thumbnail.exists()


@needs_ffmpeg
def test_render_never_exceeds_60_seconds(sample_video, tmp_path):
    res = render_clip(sample_video, 0.0, 75.0, [], RenderOptions(layout="center"), tmp_path / "long.mp4")
    assert res.duration <= 60.1
    assert probe(res.path).duration <= 60.1


@needs_ffmpeg
def test_render_face_track_expression_executes(sample_video, tmp_path, monkeypatch):
    import app.video.render as R

    monkeypatch.setattr(R, "decide_layout", lambda *a, **k: ("face_track", [(0, 0.2), (1, 0.2), (1.5, 0.8), (4, 0.8)], None))
    res = render_clip(sample_video, 5.0, 10.0, [], RenderOptions(), tmp_path / "t.mp4")
    assert res.layout == "face_track" and abs(res.duration - 5.0) < 0.2


@needs_ffmpeg
def test_render_video_without_audio(tmp_path):
    src = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=6",
                    "-c:v", "libx264", "-preset", "ultrafast", str(src)], check=True)
    res = render_clip(src, 0, 5, [], RenderOptions(layout="blur"), tmp_path / "o.mp4")
    assert not probe(res.path).has_audio and res.duration <= 5.1
