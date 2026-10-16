"""Face tracking / speaker-centred reframing for 9:16 output.

Approach (CPU-only, no model downloads):
  * Sample frames at a few fps with OpenCV, detect faces with the Haar cascade
    bundled in opencv-python(-headless) < 5.
  * Approximate the *active speaker* among several faces with mouth-region
    motion (frame difference in the lower part of each face box) weighted with
    face size, plus hysteresis so the camera doesn't ping-pong.
    This is a lightweight heuristic, not an audio-visual ASD model.
  * Smooth the target path with a median filter and a dead-zone, then emit
    piecewise-linear keyframes that ffmpeg's crop filter evaluates per frame.
  * Detect a small, persistent face in a frame corner as a gaming "facecam".
If anything fails, callers fall back to a clean centre crop or blurred background.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class FaceBox:
    x: float  # all normalised 0..1 relative to frame
    y: float
    w: float
    h: float
    motion: float = 0.0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def area(self) -> float:
        return self.w * self.h


@dataclass
class FaceSample:
    t: float  # seconds relative to clip start
    faces: list[FaceBox] = field(default_factory=list)


@dataclass
class FaceAnalysis:
    samples: list[FaceSample]
    coverage: float  # fraction of samples with at least one face
    median_face_h: float
    aspect: float = 16 / 9  # source frame width / height


def detect_faces(src: Path, start: float, end: float, sample_fps: float = 3.0, max_width: int = 480) -> Optional[FaceAnalysis]:
    try:
        import cv2
    except ImportError:
        log.info("OpenCV not installed; face tracking disabled")
        return None
    cascade_path = getattr(cv2, "data", None)
    cascade_file = (cascade_path.haarcascades + "haarcascade_frontalface_default.xml") if cascade_path else ""
    cascade = cv2.CascadeClassifier(cascade_file) if cascade_file else None
    if cascade is None or cascade.empty():
        log.warning("Haar cascade unavailable (opencv>=5 removed bundled cascades; install opencv-python-headless<5)")
        return None
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        return None
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)
        step = max(int(round(fps / sample_fps)), 1)
        total_frames = int((end - start) * fps)
        samples: list[FaceSample] = []
        prev_gray = None
        for i in range(total_frames):
            if i % step != 0 and (i + 1) % step != 0:
                if not cap.grab():
                    break
                continue
            ok, frame = cap.read()
            if not ok:
                break
            h0, w0 = frame.shape[:2]
            scale = min(1.0, max_width / w0)
            small = cv2.resize(frame, (int(w0 * scale), int(h0 * scale))) if scale < 1 else frame
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            if (i + 1) % step == 0 and i % step != 0:
                prev_gray = gray  # frame just before a sample, for motion
                continue
            sh, sw = gray.shape[:2]
            rects = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(max(int(sh * 0.06), 20),) * 2)
            faces: list[FaceBox] = []
            for (x, y, w, h) in rects:
                motion = 0.0
                if prev_gray is not None and prev_gray.shape == gray.shape:
                    y0 = int(y + h * 0.6)
                    roi_a = gray[y0 : y + h, x : x + w]
                    roi_b = prev_gray[y0 : y + h, x : x + w]
                    if roi_a.size:
                        motion = float(cv2.absdiff(roi_a, roi_b).mean())
                faces.append(FaceBox(x / sw, y / sh, w / sw, h / sh, motion))
            samples.append(FaceSample(t=i / fps, faces=faces))
            prev_gray = None
    finally:
        cap.release()
    if not samples:
        return None
    with_faces = [s for s in samples if s.faces]
    hs = [max(f.h for f in s.faces) for s in with_faces]
    return FaceAnalysis(samples=samples, coverage=len(with_faces) / len(samples),
                        median_face_h=median(hs) if hs else 0.0, aspect=(w0 / h0) if h0 else 16 / 9)


def choose_targets(analysis: FaceAnalysis, switch_margin: float = 1.35, hold_samples: int = 2) -> list[Optional[float]]:
    """Per-sample horizontal target (normalised centre x) following the likely speaker."""
    targets: list[Optional[float]] = []
    current: Optional[float] = None
    challenger: Optional[float] = None
    challenger_count = 0
    for s in analysis.samples:
        if not s.faces:
            targets.append(None)
            continue
        max_area = max(f.area for f in s.faces) or 1e-6
        max_motion = max(f.motion for f in s.faces) or 1e-6
        scored = sorted(((0.5 * f.area / max_area + 0.5 * f.motion / max_motion, f.cx) for f in s.faces), reverse=True)
        best_score, best_x = scored[0]
        if current is None:
            current = best_x
        else:
            # score of the face closest to where we are now
            cur_face = min(s.faces, key=lambda f: abs(f.cx - current))
            cur_score = 0.5 * cur_face.area / max_area + 0.5 * cur_face.motion / max_motion
            if abs(cur_face.cx - current) >= 0.15:
                # The person we followed is gone (or moved far): go to the best candidate now.
                current, challenger, challenger_count = best_x, None, 0
                targets.append(current)
                continue
            current = cur_face.cx  # follow small movements of the same person
            if abs(best_x - current) > 0.12 and best_score > cur_score * switch_margin:
                if challenger is not None and abs(challenger - best_x) < 0.1:
                    challenger_count += 1
                else:
                    challenger, challenger_count = best_x, 1
                if challenger_count >= hold_samples:
                    current, challenger, challenger_count = best_x, None, 0
            else:
                challenger, challenger_count = None, 0
        targets.append(current)
    return targets


def fill_gaps(values: list[Optional[float]]) -> Optional[list[float]]:
    known = [(i, v) for i, v in enumerate(values) if v is not None]
    if not known:
        return None
    out: list[float] = []
    for i in range(len(values)):
        if values[i] is not None:
            out.append(values[i])  # type: ignore[arg-type]
            continue
        before = next(((j, v) for j, v in reversed(known) if j < i), None)
        after = next(((j, v) for j, v in known if j > i), None)
        if before and after:
            (j0, v0), (j1, v1) = before, after
            out.append(v0 + (v1 - v0) * (i - j0) / (j1 - j0))
        else:
            out.append((before or after)[1])  # type: ignore[index]
    return out


def smooth(values: list[float], k: int = 5) -> list[float]:
    if len(values) < 3:
        return values
    half = k // 2
    return [median(values[max(0, i - half) : i + half + 1]) for i in range(len(values))]


def keyframes(times: list[float], centers: list[float], deadzone: float = 0.07, move_time: float = 0.45,
              max_keys: int = 40) -> list[tuple[float, float]]:
    """Camera keyframes (t, centre_x): hold still inside a dead-zone, glide when the subject moves."""
    if not centers:
        return [(0.0, 0.5)]
    cam = centers[0]
    keys: list[tuple[float, float]] = [(0.0, cam)]
    for t, c in zip(times, centers):
        if abs(c - cam) > deadzone and t > keys[-1][0] + 0.05:
            keys.append((t, cam))
            keys.append((t + move_time, c))
            cam = c
    if len(keys) > max_keys:  # keep it tractable for the ffmpeg expression
        stride = len(keys) / max_keys
        keys = [keys[int(i * stride)] for i in range(max_keys)]
    # ensure strictly increasing times
    clean: list[tuple[float, float]] = []
    for t, x in keys:
        if clean and t <= clean[-1][0]:
            continue
        clean.append((round(t, 3), round(x, 4)))
    return clean


def crop_x_expression(keys: list[tuple[float, float]], src_w: int, crop_w: int) -> str:
    """Piecewise-linear ffmpeg expression for the crop's left edge (pixels), evaluated at time t."""
    max_x = max(src_w - crop_w, 0)

    def px(cx: float) -> float:
        return float(round(min(max(cx * src_w - crop_w / 2, 0.0), max_x), 1))

    if len(keys) == 1:
        return str(px(keys[0][1]))
    expr = str(px(keys[-1][1]))
    for (t0, x0), (t1, x1) in reversed(list(zip(keys, keys[1:]))):
        p0, p1 = px(x0), px(x1)
        seg = f"{p0}+({p1 - p0})*(t-{t0})/{round(t1 - t0, 3)}" if p0 != p1 else f"{p0}"
        expr = f"if(lt(t,{t1}),{seg},{expr})"
    return expr


def plan_face_track(analysis: Optional[FaceAnalysis], min_coverage: float = 0.5) -> Optional[list[tuple[float, float]]]:
    if not analysis or analysis.coverage < min_coverage:
        return None
    targets = fill_gaps(choose_targets(analysis))
    if not targets:
        return None
    times = [s.t for s in analysis.samples]
    return keyframes(times, smooth(targets))


@dataclass
class Facecam:
    x: float
    y: float
    w: float
    h: float


def detect_facecam(analysis: Optional[FaceAnalysis], min_presence: float = 0.4) -> Optional[Facecam]:
    """A small face that stays in one corner region -> likely a streamer's facecam overlay."""
    if not analysis:
        return None
    small = [f for s in analysis.samples for f in s.faces if f.h < 0.28 and (f.cx < 0.35 or f.cx > 0.65)]
    if len(small) < min_presence * len(analysis.samples):
        return None
    cx = median(f.cx for f in small)
    cy = median(f.y + f.h / 2 for f in small)
    stable = [f for f in small if abs(f.cx - cx) < 0.06 and abs(f.y + f.h / 2 - cy) < 0.06]
    if len(stable) < min_presence * len(analysis.samples):
        return None
    fh = median(f.h for f in stable)
    # A facecam overlay is typically ~2.4x the face height with a 4:3 pixel aspect.
    box_h = min(fh * 2.4, 0.5)
    box_w = min(box_h * (4 / 3) / analysis.aspect, 0.45)  # convert pixel aspect to normalised width
    x = min(max(cx - box_w / 2, 0.0), 1.0 - box_w)
    y = min(max(cy - box_h / 2, 0.0), 1.0 - box_h)
    return Facecam(x, y, box_w, box_h)
