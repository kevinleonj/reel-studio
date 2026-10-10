"""Pure parts of render: ffmpeg filter strings and when each text shows (kit render.py:167-223)."""

from pathlib import Path

from pydantic import BaseModel

from reel_studio.core import constants
from reel_studio.core.errors import RenderError
from reel_studio.core.media_config import Media
from reel_studio.core.media_config import Segment as SegmentConfig
from reel_studio.editor.media.edl_models import GradeBlock, Resolved, Version, seg_dur
from reel_studio.editor.media.shots import Clip

# Characters that end or escape a quoted filter argument in an ffmpeg filtergraph (F206);
# reproduced in the phase B review with ' : and \.
FILTERGRAPH_SPECIALS = ("'", ":", "\\")


class TextEvent(BaseModel):
    text: str
    kind: str
    position: str
    start: float
    end: float


def atempo_chain(speed: float, cfg: SegmentConfig) -> str:
    """ffmpeg's atempo takes 0.5-2.0 per stage, so chain stages (kit render.py:189-198)."""
    parts, rest = [], speed
    while rest > cfg.atempo_max:
        parts.append(f"atempo={cfg.atempo_max}")
        rest /= cfg.atempo_max
    while rest < cfg.atempo_min:
        parts.append(f"atempo={cfg.atempo_min}")
        rest /= cfg.atempo_min
    parts.append(f"atempo={rest:.4f}")
    return ",".join(parts)


def flip(frame: Resolved) -> str:
    return ",hflip,vflip" if frame.rotate == constants.HALF_TURN_DEG else ""


def crop_filter(clip: Clip, frame: Resolved) -> str:
    """Fill 9:16 by cropping around the focus point, zoomed (kit render.py:167-176)."""
    pw, ph = clip.proxy_w, clip.proxy_h
    scale = max(constants.OUT_W / pw, constants.OUT_H / ph)
    cw = min(pw, round(constants.OUT_W / scale / frame.zoom / 2) * 2)
    ch = min(ph, round(constants.OUT_H / scale / frame.zoom / 2) * 2)
    x, y = int((pw - cw) * frame.focus_x), int((ph - ch) * frame.focus_y)
    out = f"{constants.OUT_W}:{constants.OUT_H}"
    return f"crop={cw}:{ch}:{x}:{y},scale={out}:flags=lanczos,setsar=1{flip(frame)}"


def grade_filter(block: GradeBlock | None, lut: Path | None, media: Media) -> str:
    """Per-clip LUT then an optional eq fine-tune (kit render.py:179-186)."""
    out = ""
    if lut is not None:
        if any(ch in str(lut) for ch in FILTERGRAPH_SPECIALS):
            raise RenderError(f"LUT path {lut} holds a character ffmpeg's filtergraph cannot take")
        out = f",format=rgb24,lut3d=file='{lut}':interp={media.grade.lut_interp},format=yuv420p"
    if block is not None and any(
        v is not None for v in (block.brightness, block.contrast, block.saturation)
    ):
        b = block.brightness if block.brightness is not None else 0.0
        c = block.contrast if block.contrast is not None else 1.0
        s = block.saturation if block.saturation is not None else 1.0
        out += f",eq=brightness={b:.3f}:contrast={c:.3f}:saturation={s:.3f}"
    return out


def text_events(
    version: Version, media: Media
) -> tuple[list[TextEvent], list[tuple[float, float]], float]:
    """Hook and labels with their on-screen times (kit render.py:201-223)."""
    starts, t = [], 0.0
    for seg in version.segments:
        d = seg_dur(seg, media)
        starts.append((t, t + d))
        t += d
    total, events = t, []
    hook_s = (
        version.title_seconds
        if version.title_seconds is not None
        else media.edl.defaults.title_seconds
    )
    hook = (
        TextEvent(
            text=version.hook_text,
            kind="title",
            position=version.title_position,
            start=0.0,
            end=min(hook_s, total),
        )
        if version.hook_text
        else None
    )
    if hook is not None:
        events.append(hook)
    segs = version.segments
    for i, seg in enumerate(segs):
        if not seg.text:
            continue
        span = seg.text_span if seg.text_span is not None else media.edl.defaults.text_span
        j = min(len(segs) - 1, i + max(1, span) - 1)
        start, end = starts[i][0], starts[j][1]
        if hook is not None and seg.text_position == hook.position and start < hook.end:
            start = hook.end
        if end - start >= media.render.text_timing.min_event_s:
            events.append(
                TextEvent(
                    text=seg.text, kind="step", position=seg.text_position, start=start, end=end
                )
            )
    return events, starts, total
