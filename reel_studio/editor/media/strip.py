"""A timestamped filmstrip of one clip, for choosing exact in/out points (port of kit strip.py).

Frames every `frame_step_s` between `min_frames` and `max_frames`, `cols` per row, each labelled
with its time in the clip. The image is shrunk to `max_side` px per side (F08: above 20 images
in a request, every image must be at most 2000 px per side).
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from reel_studio.core.media_config import Media
from reel_studio.core.media_config import Strip as StripConfig
from reel_studio.editor.media.fonts import bold
from reel_studio.editor.media.measure import frame_at
from reel_studio.editor.media.prepare import Proxy


@dataclass(frozen=True)
class Request:
    """A clip and an optional range in seconds; None means the clip's start or end."""

    proxy: Proxy
    start: float | None
    end: float | None


def frame_times(start: float, end: float, cfg: StripConfig) -> list[float]:
    """Kit strip.py:40-41: one frame per step, clamped to [min_frames, max_frames]."""
    count = int(min(cfg.max_frames, max(cfg.min_frames, (end - start) / cfg.frame_step_s)))
    return [float(t) for t in np.linspace(start, max(start, end - cfg.end_inset_s), count)]


def _range(request: Request) -> tuple[float, float]:
    duration = request.proxy.duration
    start = request.start if request.start is not None else 0.0
    end = min(request.end, duration) if request.end is not None else duration  # clamp, don't fail
    if not 0 <= start < end:
        raise ValueError(f"Range must be inside 0-{duration:.2f}")
    return start, end


def strip(work: Path, request: Request, out_dir: Path, media: Media, max_side: int) -> Path:
    """Write `<clip>_<start>-<end>.jpg` into `out_dir` and return its path."""
    cfg, style = media.strip, media.sheet_style
    start, end = _range(request)
    clip = request.proxy.id
    cap = cv2.VideoCapture(str(work / request.proxy.path))
    thumbs: list[tuple[float, Image.Image]] = []
    try:
        for t in frame_times(start, end, cfg):
            frame = frame_at(cap, t)
            if frame is None:
                continue
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            height = int(cfg.thumb_w_px * image.height / image.width)
            thumbs.append((t, image.resize((cfg.thumb_w_px, height), Image.Resampling.LANCZOS)))
    finally:
        cap.release()
    if not thumbs:
        raise ValueError(f"Could not read frames from {clip}")
    tile_h = thumbs[0][1].height
    rows = (len(thumbs) + cfg.cols - 1) // cfg.cols
    width = cfg.gap_px + cfg.cols * (cfg.thumb_w_px + cfg.gap_px)
    height = cfg.gap_px + rows * (tile_h + cfg.label_h_px + cfg.gap_px)
    sheet = Image.new("RGB", (width, height), style.background_rgb)
    draw = ImageDraw.Draw(sheet)
    font = bold(style.font_px)
    for index, (t, thumb) in enumerate(thumbs):
        x = cfg.gap_px + (index % cfg.cols) * (cfg.thumb_w_px + cfg.gap_px)
        y = cfg.gap_px + (index // cfg.cols) * (tile_h + cfg.label_h_px + cfg.gap_px)
        draw.text((x + cfg.gap_px, y), f"{clip} {t:.2f}s", fill=style.label_rgb, font=font)
        sheet.paste(thumb, (x, y + cfg.label_h_px))
    sheet.thumbnail((max_side, max_side))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{clip}_{start:.1f}-{end:.1f}.jpg"
    sheet.save(path, quality=cfg.jpeg_quality)
    return path
