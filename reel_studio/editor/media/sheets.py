"""Contact sheets: how Claude sees the footage (D38).

Each sheet is a grid of `cols` x `rows` tiles of `tile_w` x `tile_h` (4 x 4 of 384 x 216 =
1536 x 864, under the 2000 px rule of F08). A clip gives 2-6 frames, one from the middle of each
scene PySceneDetect found, spread evenly when there are fewer scenes than the minimum; frames
nearly identical to one already kept are dropped while the clip keeps its minimum. A legend maps
each tile to its clip and time.

This replaces the kit's flow layout (kit prep.py:167-221); the drawing style (label colours,
JPEG quality, label box) is the kit's.
"""

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from reel_studio.core.config import Sheets
from reel_studio.core.media_config import Media, Qa
from reel_studio.editor.media.colour import Image as Frame
from reel_studio.editor.media.colour import grey_thumb, ssim
from reel_studio.editor.media.fonts import bold
from reel_studio.editor.media.measure import frame_at
from reel_studio.editor.media.prepare import Proxy

LEGEND = "legend.json"


@dataclass(frozen=True)
class Shot:
    """One frame chosen for a sheet."""

    clip: str
    t: float
    frame: Frame


@dataclass(frozen=True)
class Tile:
    """Legend row: tile `tile` (1-based, row by row) of sheet `sheet` shows `clip` at `t` s."""

    sheet: int
    tile: int
    clip: str
    t: float


def frame_times(
    scenes: Sequence[tuple[float, float]], duration: float, limits: Sheets
) -> list[float]:
    """One time per scene (its middle), at least the minimum, at most the maximum."""
    if len(scenes) < limits.frames_per_clip_min:
        count = limits.frames_per_clip_min
        return [duration * (2 * i + 1) / (2 * count) for i in range(count)]  # slot middles
    picks = np.linspace(0, len(scenes) - 1, min(len(scenes), limits.frames_per_clip_max))
    chosen = sorted({round(float(i)) for i in picks})
    return [(scenes[i][0] + scenes[i][1]) / 2 for i in chosen]


def drop_near_duplicates(
    candidates: Sequence[tuple[float, Frame]], limits: Sheets, qa: Qa
) -> list[tuple[float, Frame]]:
    """Drop a frame whose SSIM with any kept frame reaches the threshold, keeping the minimum."""
    size = (qa.thumb_w_px, qa.thumb_h_px)
    kept: list[tuple[float, Frame]] = []
    thumbs: list[np.ndarray] = []
    for index, (t, frame) in enumerate(candidates):
        thumb = grey_thumb(frame, size)
        remaining = len(candidates) - index - 1
        duplicate = any(
            ssim(thumb, other, qa.ssim_window, qa.ssim_sigma) >= limits.near_duplicate_ssim
            for other in thumbs
        )
        if duplicate and len(kept) + remaining >= limits.frames_per_clip_min:
            continue
        kept.append((t, frame))
        thumbs.append(thumb)
    return kept


def _tile(shot: Shot, limits: Sheets, media: Media) -> Image.Image:
    style, box = media.sheet_style, media.contact_sheet
    tile = Image.new("RGB", (limits.tile_w, limits.tile_h), style.background_rgb)
    rgb = cv2.cvtColor(shot.frame, cv2.COLOR_BGR2RGB)
    picture = Image.fromarray(rgb)
    scale = min(limits.tile_w / picture.width, limits.tile_h / picture.height)
    size = (max(1, round(picture.width * scale)), max(1, round(picture.height * scale)))
    picture = picture.resize(size, Image.Resampling.LANCZOS)
    tile.paste(picture, ((limits.tile_w - size[0]) // 2, (limits.tile_h - size[1]) // 2))
    draw = ImageDraw.Draw(tile)
    font = bold(style.font_px)
    label = f"{shot.clip} {shot.t:.1f}s"
    width = round(draw.textlength(label, font=font)) + 2 * box.label_pad_px
    draw.rectangle([0, 0, width, box.label_h_px], fill=(0, 0, 0))
    draw.text((box.label_pad_px, 0), label, fill=style.label_rgb, font=font)
    return tile


def draw(
    shots: Sequence[Shot], limits: Sheets, media: Media
) -> tuple[list[Image.Image], list[Tile]]:
    """Shots in order -> full-size sheets and their legend."""
    per_sheet = limits.cols * limits.rows
    size = (limits.cols * limits.tile_w, limits.rows * limits.tile_h)
    images: list[Image.Image] = []
    legend: list[Tile] = []
    for index, shot in enumerate(shots):
        slot = index % per_sheet
        if slot == 0:
            images.append(Image.new("RGB", size, media.sheet_style.background_rgb))
        col, row = slot % limits.cols, slot // limits.cols
        images[-1].paste(_tile(shot, limits, media), (col * limits.tile_w, row * limits.tile_h))
        legend.append(Tile(len(images), slot + 1, shot.clip, round(shot.t, 2)))
    return images, legend


def build(
    work: Path,
    clips: Sequence[tuple[Proxy, Sequence[tuple[float, float]]]],
    out_dir: Path,
    limits: Sheets,
    media: Media,
) -> tuple[list[Path], list[Tile]]:
    """(proxy, its scenes) pairs -> chosen frames, sheets and legend written to `out_dir`."""
    shots: list[Shot] = []
    for proxy, scenes in clips:
        clip_scenes = scenes if scenes else [(0.0, proxy.duration)]
        cap = cv2.VideoCapture(str(work / proxy.path))
        try:
            frames = [
                (t, frame_at(cap, t)) for t in frame_times(clip_scenes, proxy.duration, limits)
            ]
        finally:
            cap.release()
        readable = [(t, f) for t, f in frames if f is not None]
        shots += [Shot(proxy.id, t, f) for t, f in drop_near_duplicates(readable, limits, media.qa)]
    images, legend = draw(shots, limits, media)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("sheet*.jpg"):  # a rerun with fewer clips (kit prep.py:170-171)
        old.unlink()
    paths = []
    for number, image in enumerate(images, start=1):
        path = out_dir / f"sheet{number:02d}.jpg"
        image.save(path, quality=media.contact_sheet.jpeg_quality)
        paths.append(path)
    (out_dir / LEGEND).write_text(
        json.dumps([asdict(t) for t in legend], indent=1), encoding="utf-8"
    )
    return paths, legend
