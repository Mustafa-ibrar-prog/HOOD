"""Render a vertical 9:16 MP4 clip with burned-in captions using FFmpeg."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import MAX_CLIP_SECONDS, settings
from ..models import CaptionLine, RenderOptions
from . import reframe
from .captions import windows_font_dirs, write_ass
from .ffmpeg import FFmpegError, MediaInfo, extract_frame, probe, run

log = logging.getLogger(__name__)


class RenderError(Exception):
    pass


@dataclass
class RenderResult:
    path: Path
    thumbnail: Path
    width: int
    height: int
    duration: float
    layout: str
    notes: list[str]


def output_size(src_h: int) -> tuple[int, int]:
    """1080x1920 when the source has the resolution for it; never upscale wildly."""
    if src_h >= 1080:
        return 1080, 1920
    if src_h >= 720:
        return 720, 1280
    return 540, 960


def _even(v: float) -> int:
    return max(2, int(v) // 2 * 2)


def _blur_bg(w: int, h: int, label_in: str, label_out: str) -> str:
    # Blur at quarter resolution then upscale: visually identical, ~10x cheaper.
    qw, qh = _even(w / 4), _even(h / 4)
    return (
        f"[{label_in}]scale={qw}:{qh}:force_original_aspect_ratio=increase,crop={qw}:{qh},"
        f"boxblur=luma_radius=12:luma_power=2,eq=brightness=-0.08:saturation=1.1,"
        f"scale={w}:{h}:flags=bilinear[{label_out}]"
    )


def build_video_graph(layout: str, info: MediaInfo, out_w: int, out_h: int, *, crop_x: float = 0.5,
                      track_keys: Optional[list[tuple[float, float]]] = None,
                      facecam: Optional[reframe.Facecam] = None) -> str:
    """Return a filter_complex fragment reading [0:v] and producing [vbase]."""
    sw, sh = info.width, info.height
    crop_w = _even(min(sw, sh * 9 / 16))
    crop_h = _even(min(sh, sw * 16 / 9)) if sw < sh * 9 / 16 else _even(sh)
    if layout == "face_track" and track_keys:
        x_expr = reframe.crop_x_expression(track_keys, sw, crop_w)
        return f"[0:v]crop=w={crop_w}:h={crop_h}:x='{x_expr}':y=(ih-{crop_h})/2,scale={out_w}:{out_h}:flags=lanczos,setsar=1[vbase]"
    if layout == "center" or (layout == "face_track" and not track_keys):
        x = round(min(max(crop_x * sw - crop_w / 2, 0), sw - crop_w))
        return f"[0:v]crop=w={crop_w}:h={crop_h}:x={x}:y=(ih-{crop_h})/2,scale={out_w}:{out_h}:flags=lanczos,setsar=1[vbase]"
    if layout == "gaming":
        gp_h = _even(out_w * sh / sw) if sw else _even(out_h / 3)
        parts = [f"[0:v]split={3 if facecam else 2}[bgsrc][gp]{'[fcsrc]' if facecam else ''}", _blur_bg(out_w, out_h, "bgsrc", "bg"),
                 f"[gp]scale={out_w}:{gp_h}:flags=lanczos,setsar=1[gps]"]
        gp_y = _even((out_h - gp_h) / 2 + out_h * 0.08)
        if facecam:
            fx, fy = _even(facecam.x * sw), _even(facecam.y * sh)
            fw, fh = _even(facecam.w * sw), _even(facecam.h * sh)
            fc_w = _even(out_w * 0.62)
            fc_h = _even(fc_w * fh / max(fw, 1))
            fc_h = min(fc_h, _even(gp_y - out_h * 0.04))
            parts.append(f"[fcsrc]crop={fw}:{fh}:{fx}:{fy},scale={fc_w}:{fc_h}:force_original_aspect_ratio=increase,crop={fc_w}:{fc_h},setsar=1[fc]")
            parts.append(f"[bg][gps]overlay=0:{gp_y}[tmp]")
            parts.append(f"[tmp][fc]overlay=(W-w)/2:{_even(max(gp_y - fc_h - out_h * 0.02, out_h * 0.03))}[vbase]")
        else:
            parts.append(f"[bg][gps]overlay=0:{_even((out_h - gp_h) / 2)}[vbase]")
        return ";".join(parts)
    # blur (default fallback): whole frame, letterboxed over a blurred copy of itself
    fg_h = _even(min(out_w * sh / sw, out_h)) if sw else out_h
    return ";".join([
        "[0:v]split=2[bgsrc][fg]",
        _blur_bg(out_w, out_h, "bgsrc", "bg"),
        f"[fg]scale={out_w}:{fg_h}:flags=lanczos,setsar=1[fgs]",
        "[bg][fgs]overlay=0:(H-h)/2[vbase]",
    ])


def _escape_filter_path(p: Path) -> str:
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def decide_layout(requested: str, src: Path, start: float, end: float, info: MediaInfo, notes: list[str]
                  ) -> tuple[str, Optional[list[tuple[float, float]]], Optional[reframe.Facecam]]:
    if info.width and info.height and info.width / info.height <= 9 / 16 + 0.02:
        return "center", None, None  # already vertical: nothing to track
    if requested in {"center", "blur"}:
        return requested, None, None
    analysis = None
    try:
        analysis = reframe.detect_faces(src, start, end)
    except Exception as e:  # tracking must never break rendering
        log.warning("face detection failed: %s", e)
        notes.append("Face detection failed; used fallback framing.")
    if requested == "gaming":
        return "gaming", None, reframe.detect_facecam(analysis)
    if requested == "face_track":
        keys = reframe.plan_face_track(analysis, min_coverage=0.25)
        if not keys:
            notes.append("No consistent face found for tracking; used blurred-background framing.")
            return "blur", None, None
        return "face_track", keys, None
    # auto
    if analysis and analysis.coverage >= 0.5 and analysis.median_face_h >= 0.12:
        keys = reframe.plan_face_track(analysis)
        if keys:
            return "face_track", keys, None
    facecam = reframe.detect_facecam(analysis)
    if facecam:
        return "gaming", None, facecam
    return "blur", None, None


def render_clip(src: Path, start: float, end: float, captions: list[CaptionLine], options: RenderOptions,
                out_path: Path, info: Optional[MediaInfo] = None) -> RenderResult:
    info = info or probe(src)
    if not info.has_video:
        raise RenderError("Source has no video stream.")
    start = max(0.0, start)
    if info.duration:
        end = min(end, info.duration)
    duration = round(min(end - start, MAX_CLIP_SECONDS), 3)
    if duration < 1.0:
        raise RenderError(f"Clip too short to render ({duration:.2f}s).")

    notes: list[str] = []
    out_w, out_h = output_size(info.height)
    layout, keys, facecam = decide_layout(options.layout, src, start, start + duration, info, notes)
    work = out_path.parent
    graph = [build_video_graph(layout, info, out_w, out_h, crop_x=options.crop_x, track_keys=keys, facecam=facecam)]
    v_label = "vbase"
    if options.captions.enabled and captions:
        ass = write_ass(captions, options.captions, out_w, out_h, out_path.with_suffix(".ass"))
        # Relative filename (ffmpeg runs with cwd=work) avoids Windows drive-letter escaping issues.
        fontsdir = ""
        if os.name == "nt" and windows_font_dirs():  # let libass load Windows fonts directly
            fontsdir = f":fontsdir='{_escape_filter_path(windows_font_dirs()[0])}'"
        graph.append(f"[vbase]subtitles=filename='{_escape_filter_path(Path(ass.name))}'{fontsdir}[vsub]")
        v_label = "vsub"
    graph.append(f"[{v_label}]format=yuv420p[vout]")
    if info.has_audio:
        fade_out = max(duration - 0.25, 0)
        graph.append(
            f"[0:a]aresample=48000,afade=t=in:st=0:d=0.06,afade=t=out:st={fade_out:.3f}:d=0.25,"
            f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]"
        )
    fps = min(info.fps or 30.0, 60.0)
    tmp_out = out_path.with_name(out_path.stem + ".tmp.mp4")
    cmd = [
        settings.ffmpeg_bin, "-y", "-v", "error",
        "-ss", f"{start:.3f}", "-i", str(src.resolve()), "-t", f"{duration:.3f}",
        # Passed inline: -filter_complex_script is deprecated in FFmpeg 7.1+.
        "-filter_complex", ";".join(graph),
        "-map", "[vout]",
        *(["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"] if info.has_audio else []),
        "-c:v", "libx264", "-preset", settings.x264_preset, "-crf", str(settings.x264_crf),
        "-profile:v", "high", "-r", f"{fps:.3f}",
        "-movflags", "+faststart", "-t", f"{duration:.3f}", str(tmp_out.resolve()),
    ]
    try:
        run(cmd, cwd=work)
    except FFmpegError as e:
        tmp_out.unlink(missing_ok=True)
        raise RenderError(f"{e}: {e.stderr[-600:]}") from e
    tmp_out.replace(out_path)
    out_info = probe(out_path)
    if out_info.duration > MAX_CLIP_SECONDS + 0.1:
        out_path.unlink(missing_ok=True)
        raise RenderError(f"Rendered clip is {out_info.duration:.2f}s, above the {MAX_CLIP_SECONDS:.0f}s limit.")
    thumb = extract_frame(out_path, min(1.0, out_info.duration / 3), out_path.with_suffix(".jpg"), width=360)
    return RenderResult(out_path, thumb, out_info.width, out_info.height, round(out_info.duration, 2), layout, notes)
