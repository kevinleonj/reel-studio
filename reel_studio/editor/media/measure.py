"""Scene cuts and measured windows per clip (port of kit prep.py:119-163, 276-290).

A window is a slice of one shot, at most `window_s` long, with motion, sharpness, brightness,
colourfulness and warmth measured on a few sampled frames. The editor reads them to find the
liveliest, sharpest moments; render's checks compare a segment with its clip's medians.
"""

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict
from scenedetect import AdaptiveDetector, detect

from reel_studio.core import constants
from reel_studio.core.media_config import Measure, Media
from reel_studio.editor.media.colour import ColourStats, Image, colourfulness, frame_stats, merge
from reel_studio.editor.media.prepare import Proxy


class Window(BaseModel):
    """One measured slice of a clip; `id` is numbered across the whole order (w001...)."""

    model_config = ConfigDict(frozen=True)

    id: str
    clip: str
    start: float
    end: float
    motion: float
    sharpness: float
    luma: float
    colourful: float
    warmth: float  # Lab b*: higher = warmer, yellower


@dataclass(frozen=True)
class MeasuredClip:
    windows: list[Window]
    color_stats: ColourStats | None
    median_sharpness: float
    cuts: list[tuple[float, float]]  # scenes PySceneDetect found; empty for a photo or one shot


def detect_cuts(path: Path, cfg: Measure) -> list[tuple[float, float]]:
    """Hard cuts inside one proxy, as (start, end) seconds (kit prep.py:119-122)."""
    scenes = detect(str(path), AdaptiveDetector(min_scene_len=f"{cfg.scene_min_len_s}s"))
    return [(float(a.seconds), float(b.seconds)) for a, b in scenes]


def split_windows(start: float, end: float, cfg: Measure) -> list[tuple[float, float]]:
    """A shot -> equal windows of at most window_s, capped per clip (kit prep.py:125-128)."""
    count = max(1, min(cfg.max_windows_per_clip, math.ceil((end - start) / cfg.window_s)))
    step = (end - start) / count
    return [(start + i * step, start + (i + 1) * step) for i in range(count)]


def frame_at(cap: cv2.VideoCapture, t: float) -> Image | None:
    cap.set(cv2.CAP_PROP_POS_MSEC, max(t, 0.0) * constants.MS_PER_S)
    ok, frame = cap.read()
    return frame.astype(np.uint8) if ok else None


def _measure(cap: cv2.VideoCapture, start: float, end: float, cfg: Measure) -> dict[str, float]:
    """Kit prep.py:144-163: motion is the mean frame difference, sharpness the Laplacian var."""
    count = max(cfg.samples_min, min(cfg.samples_max, int((end - start) / cfg.sample_spacing_s)))
    grays, colours, labs = [], [], []
    for t in np.linspace(start + cfg.edge_inset_s, end - cfg.edge_inset_s, count):
        frame = frame_at(cap, float(t))
        if frame is None:
            continue
        portrait = frame.shape[0] > frame.shape[1]
        size = (
            (cfg.thumb_short_px, cfg.thumb_long_px)
            if portrait
            else (cfg.thumb_long_px, cfg.thumb_short_px)
        )
        small = cv2.resize(frame, size).astype(np.uint8)
        grays.append(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
        colours.append(colourfulness(small))
        scaled = small.astype(np.float32) / constants.U8_MAX
        labs.append(
            cv2.cvtColor(scaled, cv2.COLOR_BGR2Lab).reshape(-1, constants.COLOUR_CHANNELS).mean(0)
        )
    if not grays:
        return {"motion": 0.0, "sharpness": 0.0, "luma": 0.0, "colourful": 0.0, "warmth": 0.0}
    diffs = [float(np.mean(cv2.absdiff(grays[i], grays[i + 1]))) for i in range(len(grays) - 1)]
    lab = np.mean(labs, axis=0)
    return {
        "motion": round(float(np.mean(diffs)) if diffs else 0.0, 1),
        "sharpness": round(float(np.median([cv2.Laplacian(g, cv2.CV_64F).var() for g in grays]))),
        "luma": round(float(np.mean([g.mean() for g in grays]))),
        "colourful": round(float(np.mean(colours))),
        "warmth": round(float(lab[2]), 1),
    }


def _colour_stats(cap: cv2.VideoCapture, duration: float, media: Media) -> ColourStats | None:
    cfg = media.measure
    last = max(cfg.colour_min_end_s, duration - cfg.colour_edge_s)
    samples = [
        frame_at(cap, float(t)) for t in np.linspace(cfg.colour_edge_s, last, cfg.colour_samples)
    ]
    frames = [f for f in samples if f is not None]
    return merge([frame_stats(f, media.grade.stats) for f in frames]) if frames else None


def measure_clip(work: Path, proxy: Proxy, media: Media) -> MeasuredClip:
    """Cuts, windows, colour statistics and the median sharpness of one proxy."""
    cfg = media.measure
    path = work / proxy.path
    cuts = detect_cuts(path, cfg) if proxy.kind == "video" else []
    cap = cv2.VideoCapture(str(path))
    try:
        stats = _colour_stats(cap, proxy.duration, media)
        windows = []
        for shot_start, shot_end in cuts if cuts else [(0.0, proxy.duration)]:
            for start, end in split_windows(shot_start, shot_end, cfg):
                if end - start < cfg.min_window_s:
                    continue
                values = _measure(cap, start, end, cfg)
                windows.append(
                    Window(id="", clip=proxy.id, start=round(start, 2), end=round(end, 2), **values)
                )
    finally:
        cap.release()
    sharp = float(np.median([w.sharpness for w in windows])) if windows else 0.0
    return MeasuredClip(windows, stats, sharp, cuts)
