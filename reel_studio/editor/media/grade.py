"""Colour: shot match plus a creative look, rendered as one 3D LUT per clip (kit grade.py).

The colourist's order happens in CIE Lab: each clip's exposure and white balance are pulled
toward the set's median (saturated food colour protected), then a named look or the statistics
of the customer's style photo, blended in by `strength`. The preview and the render use the same
maths: render applies the .cube files written here.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from reel_studio.core import constants
from reel_studio.core.media_config import Grade, GradeMatch, Media
from reel_studio.editor.media.colour import ColourStats, merge, reference_stats
from reel_studio.editor.media.shots import Shots

type Rgb = NDArray[np.float32]

LOOKS = ("natural", "warm", "moody", "fresh", "clean", "reference")  # kit grade.py:31


@dataclass(frozen=True)
class Choice:
    """The EDL's grade block (kit grade.py:184-187)."""

    look: str
    strength: float
    match: float


@dataclass(frozen=True)
class Reference:
    """The style photo's statistics and the whole set's, for the `reference` look."""

    ref: ColourStats | None
    set_stats: ColourStats | None


@dataclass(frozen=True)
class Correction:
    p50: float
    t50: float
    k: float
    shift: tuple[float, float]
    m: float


def correction(clip: ColourStats, target: ColourStats, match: float, cfg: GradeMatch) -> Correction:
    """Exposure stretch and white-balance shift toward the set (kit grade.py:85-93)."""
    rng_c = max(clip.p98 - clip.p2, cfg.min_clip_range_l)
    rng_t = min(target.p98, cfg.set_p98_cap_l) - target.p2
    k = float(np.clip(rng_t / rng_c, cfg.contrast_k_min, cfg.contrast_k_max))
    shift = (0.0, 0.0)
    usable = clip.neutral_ab is not None and clip.neutral_frac >= cfg.neutral_frac_min
    if usable and clip.neutral_ab is not None and target.neutral_ab is not None:
        aim = (
            cfg.set_warmth_kept * target.neutral_ab[0],
            cfg.set_warmth_kept * target.neutral_ab[1],
        )
        shift = (aim[0] - clip.neutral_ab[0], aim[1] - clip.neutral_ab[1])
    return Correction(clip.p50, target.p50, k, shift, match)


def _to_lab(rgb: Rgb) -> NDArray[np.float32]:
    lab = cv2.cvtColor(
        rgb.reshape(-1, 1, constants.COLOUR_CHANNELS).astype(np.float32), cv2.COLOR_RGB2Lab
    )
    return lab.reshape(-1, constants.COLOUR_CHANNELS).astype(np.float32)


def _to_rgb(lab: NDArray[np.float32]) -> Rgb:
    rgb = cv2.cvtColor(
        lab.reshape(-1, 1, constants.COLOUR_CHANNELS).astype(np.float32), cv2.COLOR_Lab2RGB
    )
    return np.clip(rgb.reshape(-1, constants.COLOUR_CHANNELS), 0, 1).astype(np.float32)


def _match(lab: NDArray[np.float32], corr: Correction, cfg: GradeMatch) -> NDArray[np.float32]:
    """Kit grade.py:102-108; the shift fades with chroma so saturated food keeps its colour."""
    out = lab.copy()
    lum, a, b = out[:, 0], out[:, 1], out[:, 2]
    target = corr.t50 + (lum - corr.p50) * corr.k
    weight = np.clip(1 - np.hypot(a, b) / cfg.protect_chroma, cfg.protect_weight_min, 1.0)
    out[:, 0] = lum + corr.m * (target - lum)
    out[:, 1] = a + corr.m * corr.shift[0] * weight
    out[:, 2] = b + corr.m * corr.shift[1] * weight
    return out


def _transfer(
    channels: list[NDArray[np.float32]], ref: ColourStats, set_stats: ColourStats, cfg: Grade
) -> list[NDArray[np.float32]]:
    """Reinhard-style transfer at set level, clamped so an odd photo cannot wreck the footage
    (kit grade.py:146-156)."""
    r = cfg.looks.reference
    out = []
    for i, arr in enumerate(channels):
        mu_s, sd_s = set_stats.mean[i], max(set_stats.std[i], r.min_std)
        ratio = float(np.clip(ref.std[i] / sd_s, r.std_ratio_min[i], r.std_ratio_max[i]))
        shift = float(np.clip(ref.mean[i] - mu_s, -r.max_mean_shift[i], r.max_mean_shift[i]))
        out.append(np.asarray((arr - mu_s) * ratio + mu_s + shift, dtype=np.float32))
    return out


def _look(lab: NDArray[np.float32], look: str, ref: Reference, cfg: Grade) -> NDArray[np.float32]:
    """The named look on a matched image (kit grade.py:109-160)."""
    common, looks = cfg.look_common, cfg.looks
    lum, a, b = lab[:, 0].copy(), lab[:, 1].copy(), lab[:, 2].copy()
    chroma = np.hypot(a, b)
    hue = (np.degrees(np.arctan2(b, a)) + constants.FULL_TURN_DEG) % constants.FULL_TURN_DEG
    warm = (hue < common.warm_hue_below_deg) | (hue > common.warm_hue_above_deg)

    def vib(amount: float) -> NDArray[np.float32]:
        return np.asarray(1 + amount * (1 - np.minimum(chroma / common.vibrance_chroma, 1)))

    def contrast(x: NDArray[np.float32], k: float) -> NDArray[np.float32]:
        return np.asarray(common.contrast_pivot_l + (x - common.contrast_pivot_l) * k)

    def highlights(x: NDArray[np.float32]) -> NDArray[np.float32]:
        return np.asarray(np.clip((x - common.highlight_start_l) / common.highlight_span_l, 0, 1))

    if look == "natural":
        gain = vib(looks.natural.vibrance)
        lum = contrast(lum, looks.natural.contrast)
    elif look == "warm":
        w = looks.warm
        gain = vib(w.vibrance) * np.where(warm, w.warm_hue_gain, 1.0)
        lum = contrast(lum, w.contrast)
        b = b + w.b_lift * (lum / constants.LAB_L_MAX)
        a = a + w.a_lift
    elif look == "moody":
        m = looks.moody
        gain = np.where(warm, m.warm_hue_gain, m.other_hue_gain)
        curved = constants.LAB_L_MAX * np.power(
            np.clip(lum, 0, constants.LAB_L_MAX) / constants.LAB_L_MAX, m.gamma
        )
        lum = contrast(curved, m.contrast)
        b = b + m.b_lift * np.clip((lum - m.b_lift_start_l) / m.b_lift_span_l, 0, 1)
    elif look == "fresh":
        f = looks.fresh
        green = (hue > f.green_hue_min_deg) & (hue < f.green_hue_max_deg)
        gain = vib(f.vibrance) * np.where(green, f.green_hue_gain, 1.0)
        lum = lum + f.l_lift
        fade = 1 - f.highlight_desat * highlights(lum)
        a, b = a * fade, b * fade
    elif look == "clean":
        c = looks.clean
        gain = vib(c.vibrance)
        lum = contrast(lum + c.l_lift, c.contrast)
        fade = 1 - c.highlight_desat * highlights(lum)
        a, b = a * fade, b * fade
    elif look == "reference":
        r = looks.reference
        if ref.ref is None or ref.set_stats is None:
            gain = vib(r.fallback_vibrance)
        else:
            lum, a, b = _transfer([lum, a, b], ref.ref, ref.set_stats, cfg)
            gain = np.ones_like(chroma)
    else:
        raise ValueError(f"Unknown look {look!r}; use one of {LOOKS}")
    return np.stack([np.clip(lum, 0, constants.LAB_L_MAX), a * gain, b * gain], 1).astype(
        np.float32
    )


def apply_transform(
    rgb: Rgb, corr: Correction | None, choice: Choice, ref: Reference, cfg: Grade
) -> Rgb:
    """RGB floats 0..1 (any shape ending in 3) -> graded RGB (kit grade.py:96-162)."""
    shape = rgb.shape
    base = _to_lab(rgb)
    if corr is not None and corr.m > 0:
        base = _match(base, corr, cfg.match)
    looked = _look(base, choice.look, ref, cfg)
    out = base + choice.strength * (looked - base)
    return _to_rgb(out).reshape(shape)


def write_cube(
    path: Path, corr: Correction | None, choice: Choice, ref: Reference, cfg: Grade
) -> None:
    """A .cube LUT; red changes fastest, as the format requires (kit grade.py:166-173)."""
    grid = np.linspace(0, 1, cfg.lut_size, dtype=np.float32)
    bb, gg, rr = np.meshgrid(grid, grid, grid, indexing="ij")
    rgb = np.stack([rr, gg, bb], -1).reshape(-1, constants.COLOUR_CHANNELS)
    out = apply_transform(rgb, corr, choice, ref, cfg)
    header = (
        f'TITLE "reel-studio {choice.look}"\nLUT_3D_SIZE {cfg.lut_size}\n'
        "DOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n"
    )
    rows = "".join(f"{r:.6f} {g:.6f} {b:.6f}\n" for r, g, b in out)
    path.write_text(header + rows, encoding="utf-8")


def set_stats_of(shots: Shots) -> ColourStats:
    """The set's colour: video clips if any, else every clip (kit grade.py:176-181)."""
    videos = [c.color_stats for c in shots.clips if c.color_stats is not None and c.kind == "video"]
    every = [c.color_stats for c in shots.clips if c.color_stats is not None]
    stats = videos if videos else every
    if not stats:
        raise ValueError("No colour statistics in shots.json")
    return merge(stats)


def reference_of(shots: Shots, input_dir: Path | None, media: Media) -> Reference:
    ref = None
    if input_dir is not None and input_dir.is_dir():
        grade = media.grade
        ref, _ = reference_stats(
            input_dir, grade.reference_words, grade.stats, media.prepare.max_pixels
        )
    return Reference(ref, set_stats_of(shots))


def build_luts(
    shots: Shots, choice: Choice, ref: Reference, out_dir: Path, cfg: Grade
) -> dict[str, Path]:
    """One .cube per clip: its own match, then the shared look (kit grade.py:190-204)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    luts = {}
    for clip in shots.clips:
        corr = None
        if clip.color_stats is not None and clip.kind == "video" and ref.set_stats is not None:
            corr = correction(clip.color_stats, ref.set_stats, choice.match, cfg.match)
        path = out_dir / f"{clip.id}.cube"
        write_cube(path, corr, choice, ref, cfg)
        luts[clip.id] = path
    return luts
