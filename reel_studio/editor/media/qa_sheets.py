"""QA's eyes: frame grabs, per-frame stats and the review grids (kit qa.py:37-94).

The grids are capped at the F08 image size because the critic (STEP-03) reads them; the kit
never capped them, and a long Reel's cuts sheet would pass 2000 px.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

from reel_studio.core import constants
from reel_studio.core.media_config import Media, Qa
from reel_studio.editor.media.colour import Image as Frame
from reel_studio.editor.media.colour import colourfulness, grey_thumb
from reel_studio.editor.media.fonts import bold
from reel_studio.editor.media.measure import frame_at


@dataclass(frozen=True)
class FrameStats:
    gray: NDArray[np.uint8]
    luma: float
    lab: NDArray[np.float64]
    sharp: float
    colourful: float
    hsv_hist: NDArray[np.float32]


@dataclass(frozen=True)
class Layout:
    cols: int
    tile: tuple[int, int]  # width, height
    safe: bool  # draw the text safe zone in red


def grab(cap: cv2.VideoCapture, t: float) -> Frame | None:
    return frame_at(cap, max(0.0, t))


def stats(frame: Frame, cfg: Qa) -> FrameStats:
    """Kit qa.py:54-63."""
    small = cv2.resize(frame, (cfg.thumb_w_px, cfg.thumb_h_px)).astype(np.uint8)
    gray = grey_thumb(small, (cfg.thumb_w_px, cfg.thumb_h_px))
    scaled = small.astype(np.float32) / constants.U8_MAX
    lab = cv2.cvtColor(scaled, cv2.COLOR_BGR2Lab).reshape(-1, constants.COLOUR_CHANNELS).mean(0)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    ranges = [*constants.HSV_HUE_RANGE, *constants.HSV_SAT_RANGE]
    hist = cv2.calcHist([hsv], [0, 1], None, list(cfg.hsv_bins), ranges).flatten()
    norm = float(np.linalg.norm(hist))  # cv2.normalize's default: unit L2 norm (kit qa.py:62)
    unit = (hist / norm if norm > 0 else hist).astype(np.float32)
    return FrameStats(
        gray=gray,
        luma=float(gray.mean()),
        lab=np.asarray(lab, dtype=np.float64),
        sharp=float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        colourful=colourfulness(small),
        hsv_hist=unit,
    )


def tile(frame: Frame, size: tuple[int, int]) -> Image.Image:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb).resize(size, Image.Resampling.LANCZOS)


def grid(
    items: Sequence[tuple[str, Image.Image]], layout: Layout, out: Path, media: Media, max_side: int
) -> None:
    """Labelled tiles in rows (kit qa.py:81-94), shrunk to `max_side`."""
    cfg, style = media.qa.sheets, media.sheet_style
    gap, label = cfg.gap_px, cfg.label_h_px
    (w, h), cols = layout.tile, layout.cols
    rows = max(1, (len(items) + cols - 1) // cols)
    size = (gap + cols * (w + gap), gap + rows * (h + label + gap))
    image = Image.new("RGB", size, style.background_rgb)
    draw, font = ImageDraw.Draw(image), bold(style.font_px)
    for k, (text, picture) in enumerate(items):
        x, y = gap + (k % cols) * (w + gap), gap + (k // cols) * (h + label + gap)
        draw.text((x + media.contact_sheet.label_pad_px, y), text, fill=style.label_rgb, font=font)
        image.paste(picture, (x, y + label))
        if layout.safe:
            box = [
                x + constants.SAFE_X0 * w // constants.OUT_W,
                y + label + constants.SAFE_Y0 * h // constants.OUT_H,
                x + constants.SAFE_X1 * w // constants.OUT_W,
                y + label + constants.SAFE_Y1 * h // constants.OUT_H,
            ]
            draw.rectangle(box, outline=style.safe_zone_outline_rgb)
    image.thumbnail((max_side, max_side))
    image.save(out, quality=cfg.jpeg_quality)
