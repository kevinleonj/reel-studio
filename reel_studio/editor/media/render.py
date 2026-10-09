"""Render the one cut twice, with text and clean (port of kit render.py:166-376).

Each segment becomes an intermediate file (crop or blurred fit, per-clip LUT, speed, per-shot
level, click-free fades); the parts are concatenated and loudness-normalised in two passes to
-14 LUFS (D42) into 1080x1920, 30 fps, H.264 and AAC (D43). Text is overlaid from PNG cards.
No music is ever added (D02): the natural sound stays, music is picked inside Instagram.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from reel_studio.core.errors import RenderError
from reel_studio.core.logging import get_logger
from reel_studio.core.media_config import Media
from reel_studio.editor.media import grade, textcards
from reel_studio.editor.media.edl_models import Edl, resolve, speed_of
from reel_studio.editor.media.render_filters import (
    TextEvent,
    atempo_chain,
    crop_filter,
    text_events,
)
from reel_studio.editor.media.render_steps import Steps
from reel_studio.editor.media.shots import Shots
from reel_studio.editor.media.tools import Ffmpeg

__all__ = ["Job", "Timeline", "atempo_chain", "crop_filter", "render", "resolve", "text_events"]

log = get_logger(__name__)

STAGE = "render"
TEXT, CLEAN, TIMELINE = "text.mp4", "clean.mp4", "timeline.json"


@dataclass(frozen=True)
class Job:
    work: Path  # holds clips/ and receives review/ and render_tmp/
    input_dir: Path | None  # read for style photos only (D02)
    out_dir: Path  # receives text.mp4 and clean.mp4
    ffmpeg: Ffmpeg
    media: Media


class PlacedSegment(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    i: int
    clip: str
    in_: float = Field(alias="in")
    out: float
    speed: float
    role: str
    kind: str
    start: float  # seconds into the Reel
    end: float
    note: str


class PlacedText(TextEvent):
    x0: int
    y0: int
    x1: int
    y1: int
    font_px: int
    lines: int
    inside_safe_zone: bool


class Timeline(BaseModel):
    """Where every segment and text landed (kit render.py:365-372); qa.py reads it."""

    files: dict[str, str]
    duration: float
    planned_duration: float
    segments: list[PlacedSegment]
    text: list[PlacedText]


def _luts(job: Job, shots: Shots, edl: Edl, folder: Path) -> dict[str, Path]:
    if not any(c.color_stats is not None for c in shots.clips):
        return {}
    g, cfg = edl.grade, job.media.grade
    choice = grade.Choice(
        look=g.look if g is not None and g.look is not None else cfg.default_look,
        strength=g.strength if g is not None and g.strength is not None else cfg.default_strength,
        match=g.match if g is not None and g.match is not None else cfg.default_match,
    )
    return grade.build_luts(
        shots, choice, grade.reference_of(shots, job.input_dir, job.media), folder, cfg
    )


def render(job: Job, shots: Shots, edl: Edl) -> Timeline:
    """Render text.mp4 and clean.mp4 from a checked EDL; returns the timeline."""
    if edl.audio.music is not None:
        raise RenderError("music is not supported: music is chosen inside Instagram (D02)")
    version = edl.versions[0]
    tmp = job.work / "render_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        luts = _luts(job, shots, edl, tmp / "luts")
        events, starts, total = text_events(version, job.media)
        overlays: list[tuple[TextEvent, Path]] = []
        boxes: list[PlacedText] = []
        for k, ev in enumerate(events):
            png = tmp / f"text{k:02d}.png"
            box = textcards.render_card(
                textcards.Card(ev.text, ev.kind, ev.position), png, edl.text_style, job.media
            )
            overlays.append((ev, png))
            boxes.append(PlacedText(**ev.model_dump(), **box.__dict__))
        r = Steps(job.work, job.ffmpeg, shots, edl, job.media)
        parts = []
        for i, seg in enumerate(version.segments):
            clip = shots.clip(seg.clip)
            if clip is None:
                raise RenderError(f"segment {i}: unknown clip {seg.clip}")
            part = tmp / f"seg{i:03d}.mkv"
            r.segment(clip, seg, part, luts.get(seg.clip))
            parts.append(part)
        loud = r.loudness(parts)
        job.out_dir.mkdir(parents=True, exist_ok=True)
        clean, texted = job.out_dir / CLEAN, job.out_dir / TEXT
        r.finalize(parts, loud, [], clean)
        r.finalize(parts, loud, overlays, texted)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    kinds = {c.id: c.kind for c in shots.clips}
    timeline = Timeline(
        files={"text": str(texted), "clean": str(clean)},
        duration=round(job.ffmpeg.probe(texted).duration, 2),
        planned_duration=round(total, 2),
        segments=[
            PlacedSegment(
                i=i,
                clip=seg.clip,
                in_=seg.in_,
                out=seg.out,
                speed=speed_of(seg, job.media),
                role=seg.role,
                kind=kinds[seg.clip],
                start=round(a, 2),
                end=round(b, 2),
                note=seg.note,
            )
            for i, (seg, (a, b)) in enumerate(zip(version.segments, starts, strict=True))
        ],
        text=boxes,
    )
    review = job.work / "review"
    review.mkdir(parents=True, exist_ok=True)
    (review / TIMELINE).write_text(timeline.model_dump_json(indent=1), encoding="utf-8")
    log.info(
        "rendered %d segments, %.1fs",
        len(parts),
        total,
        extra={"stage": STAGE, "event": "render", "outcome": "ok"},
    )
    return timeline
