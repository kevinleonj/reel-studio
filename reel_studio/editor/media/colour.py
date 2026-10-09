"""Colour statistics in CIE Lab: per frame, per clip, and of style photos.

Port of kit grade.py:37-73 and prep.py:137-141. The grade (shot match and looks) reads these;
measure stores one merged summary per clip in shots.json.
"""

from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict

from reel_studio.core import constants
from reel_studio.core.media_config import GradeStats

type Image = NDArray[np.uint8]


class ColourStats(BaseModel):
    """Lab summary of one frame or one clip (kit grade.py:43-48)."""

    model_config = ConfigDict(frozen=True)

    p2: float
    p50: float
    p98: float
    mean: tuple[float, float, float]
    std: tuple[float, float, float]
    neutral_frac: float
    neutral_ab: tuple[float, float] | None
    clip_hi: float
    crush: float


def _lab(bgr: Image, width: int) -> NDArray[np.float32]:
    height = max(1, int(width * bgr.shape[0] / bgr.shape[1]))
    small = cv2.resize(bgr, (width, height))
    scaled = small.astype(np.float32) / constants.U8_MAX
    lab = cv2.cvtColor(scaled, cv2.COLOR_BGR2Lab)
    return lab.reshape(-1, constants.COLOUR_CHANNELS).astype(np.float32)


def frame_stats(bgr: Image, cfg: GradeStats) -> ColourStats:
    """One BGR frame -> exposure percentiles, mean and spread, and the cast of its neutrals."""
    lab = _lab(bgr, cfg.thumb_w_px)
    lum, a, b = lab[:, 0], lab[:, 1], lab[:, 2]
    chroma = np.hypot(a, b)
    neutral = (
        (chroma < cfg.neutral_chroma_max) & (lum > cfg.neutral_l_min) & (lum < cfg.neutral_l_max)
    )
    low, mid, high = (float(np.percentile(lum, q)) for q in cfg.percentiles)
    neutral_ab = None
    if int(neutral.sum()) > cfg.neutral_min_pixels:
        neutral_ab = (float(a[neutral].mean()), float(b[neutral].mean()))
    return ColourStats(
        p2=low,
        p50=mid,
        p98=high,
        mean=(float(lum.mean()), float(a.mean()), float(b.mean())),
        std=(float(lum.std()), float(a.std()), float(b.std())),
        neutral_frac=float(neutral.mean()),
        neutral_ab=neutral_ab,
        clip_hi=float((lum > cfg.clip_hi_l).mean()),
        crush=float((lum < cfg.crush_l).mean()),
    )


def _median3(rows: Sequence[tuple[float, float, float]]) -> tuple[float, float, float]:
    m = np.median(np.array(rows, dtype=np.float64), axis=0)
    return float(m[0]), float(m[1]), float(m[2])


def merge(stats: Sequence[ColourStats]) -> ColourStats:
    """Median of several frames' stats: one clip-level summary (kit grade.py:51-58)."""
    if not stats:
        raise ValueError("no frames to merge")
    neutrals = [s.neutral_ab for s in stats if s.neutral_ab is not None]
    neutral_ab = None
    if neutrals:
        m = np.median(np.array(neutrals, dtype=np.float64), axis=0)
        neutral_ab = (float(m[0]), float(m[1]))
    return ColourStats(
        p2=float(np.median([s.p2 for s in stats])),
        p50=float(np.median([s.p50 for s in stats])),
        p98=float(np.median([s.p98 for s in stats])),
        mean=_median3([s.mean for s in stats]),
        std=_median3([s.std for s in stats]),
        neutral_frac=float(np.median([s.neutral_frac for s in stats])),
        neutral_ab=neutral_ab,
        clip_hi=float(np.median([s.clip_hi for s in stats])),
        crush=float(np.median([s.crush for s in stats])),
    )


def reference_stats(
    folder: Path, words: Sequence[str], cfg: GradeStats
) -> tuple[ColourStats | None, list[str]]:
    """Style photos in the input folder (name contains vsco, look or ref) -> one summary.

    Kit grade.py:61-73; the kit also read assets/looks/, which the product does not ship.
    """
    files = sorted(
        p
        for p in folder.iterdir()
        if p.suffix.lower() in constants.IMAGE_EXT and any(w in p.stem.lower() for w in words)
    )
    stats = []
    for path in files:
        image = cv2.imread(str(path))
        if image is not None:
            stats.append(frame_stats(image.astype(np.uint8), cfg))
    return (merge(stats) if stats else None), [p.name for p in files]


def colourfulness(bgr: Image) -> float:
    """Hasler & Suesstrunk (2003) colourfulness (kit prep.py:137-141)."""
    b, g, r = (c.astype(np.float32) for c in cv2.split(bgr))
    rg, yb = r - g, (r + g) / 2 - b
    spread = np.hypot(rg.std(), yb.std())
    centre = np.hypot(rg.mean(), yb.mean())
    return float(spread + constants.COLOURFULNESS_MEAN_WEIGHT * centre)


def ssim(a: NDArray[np.uint8], b: NDArray[np.uint8], window: int, sigma: float) -> float:
    """Mean structural similarity of two grey images (kit qa.py:43-51, Wang et al. 2004)."""
    x, y = a.astype(np.float64), b.astype(np.float64)
    c1 = (constants.SSIM_K1 * constants.U8_MAX) ** 2
    c2 = (constants.SSIM_K2 * constants.U8_MAX) ** 2
    kernel = (window, window)
    mu_x, mu_y = cv2.GaussianBlur(x, kernel, sigma), cv2.GaussianBlur(y, kernel, sigma)
    var_x = cv2.GaussianBlur(x * x, kernel, sigma) - mu_x**2
    var_y = cv2.GaussianBlur(y * y, kernel, sigma) - mu_y**2
    cov = cv2.GaussianBlur(x * y, kernel, sigma) - mu_x * mu_y
    num = (2 * mu_x * mu_y + c1) * (2 * cov + c2)
    den = (mu_x**2 + mu_y**2 + c1) * (var_x + var_y + c2)
    return float((num / den).mean())


def grey_thumb(bgr: Image, size: tuple[int, int]) -> NDArray[np.uint8]:
    """Small grey copy for comparisons (kit qa.py:55-56); `size` is (width, height)."""
    return cv2.cvtColor(cv2.resize(bgr, size), cv2.COLOR_BGR2GRAY).astype(np.uint8)
