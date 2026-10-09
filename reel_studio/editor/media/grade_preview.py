"""The looks preview: rows = hero frames, columns = original then each look (kit grade.py:207-271).

The preview and the render use the same maths (grade.apply_transform), so what the editor picks
here is what the LUTs produce.
"""

from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from reel_studio.core import constants
from reel_studio.core.media_config import Grade, Media
from reel_studio.editor.media.fonts import bold
from reel_studio.editor.media.grade import LOOKS, Choice, Reference, apply_transform, correction
from reel_studio.editor.media.measure import frame_at
from reel_studio.editor.media.shots import Shots


def hero_frames(shots: Shots, cfg: Grade) -> list[tuple[str, float]]:
    """Colourful, sharp windows from different clips plus the darkest (grade.py:208-222)."""
    count, exponent = cfg.preview.hero_frames, cfg.preview.sharpness_exponent
    best: dict[str, tuple[float, float]] = {}
    for w in shots.windows:
        clip = shots.clip(w.clip)
        median = clip.median_sharpness if clip is not None and clip.median_sharpness > 1 else 1.0
        score = w.colourful * (w.sharpness / median) ** exponent
        if w.clip not in best or score > best[w.clip][0]:
            best[w.clip] = (score, (w.start + w.end) / 2)
    ranked = sorted(best.items(), key=lambda kv: -kv[1][0])
    picks = [(cid, t) for cid, (_, t) in ranked[: count - 1]]
    darkest = min(
        shots.clips,
        key=lambda c: c.color_stats.p50 if c.color_stats is not None else constants.LAB_L_MAX,
    )
    if darkest.id not in {p[0] for p in picks} and darkest.id in best:
        picks.append((darkest.id, best[darkest.id][1]))
    return picks[:count]


def preview(work: Path, shots: Shots, choice: Choice, ref: Reference, media: Media) -> Image.Image:
    """Rows = hero frames, columns = original then each look (kit grade.py:225-271)."""
    cfg, style = media.grade.preview, media.sheet_style
    looks = [look for look in LOOKS if look != "reference" or ref.ref is not None]
    columns: Sequence[str] = ["original", *looks]
    frames = hero_frames(shots, media.grade)
    tw, th, gap = cfg.tile_w_px, cfg.tile_h_px, cfg.gap_px
    size = (
        gap + len(columns) * (tw + gap),
        cfg.header_h_px + len(frames) * (th + cfg.caption_h_px),
    )
    sheet = Image.new("RGB", size, style.background_rgb)
    draw, font = ImageDraw.Draw(sheet), bold(style.font_px)
    for j, column in enumerate(columns):
        label = column if column == "original" else f"{column} {choice.strength:g}"
        draw.text(
            (gap + j * (tw + gap) + cfg.text_inset_px, cfg.header_text_y_px),
            label,
            fill=style.label_rgb,
            font=font,
        )
    for i, (cid, t) in enumerate(frames):
        clip = shots.clip(cid)
        if clip is None:
            continue
        cap = cv2.VideoCapture(str(work / clip.proxy))
        frame = frame_at(cap, t)
        cap.release()
        if frame is None:
            continue
        height, width = frame.shape[:2]
        aspect = constants.OUT_W / constants.OUT_H
        if width / height > aspect:  # centre-crop to 9:16 like the render default
            keep = int(height * aspect)
            frame = frame[:, (width - keep) // 2 : (width - keep) // 2 + keep]
        small = cv2.cvtColor(cv2.resize(frame, (tw, th)), cv2.COLOR_BGR2RGB)
        rgb = (small.astype(np.float32) / constants.U8_MAX).astype(np.float32)
        corr = None
        if clip.color_stats is not None and ref.set_stats is not None:
            corr = correction(clip.color_stats, ref.set_stats, choice.match, media.grade.match)
        y = cfg.header_h_px + i * (th + cfg.caption_h_px)
        draw.text(
            (cfg.caption_x_px, y + th + cfg.text_inset_px),
            f"{cid} @ {t:.1f}s",
            fill=cfg.caption_rgb,
            font=font,
        )
        for j, column in enumerate(columns):
            look = Choice(column, choice.strength, choice.match)
            img = (
                rgb if column == "original" else apply_transform(rgb, corr, look, ref, media.grade)
            )
            sheet.paste(
                Image.fromarray((img * constants.U8_MAX).astype(np.uint8)),
                (gap + j * (tw + gap), y),
            )
    return sheet
