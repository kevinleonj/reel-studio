"""Render the one cut twice, with text and clean (port of kit render.py:166-376).

Each segment becomes an intermediate file (crop or blurred fit, per-clip LUT, speed, per-shot
level, click-free fades); the parts are concatenated and loudness-normalised in two passes to
-14 LUFS (D42) into 1080x1920, 30 fps, H.264 and AAC (D43). Text is overlaid from PNG cards.
No music is ever added (D02): the natural sound stays, music is picked inside Instagram.
"""

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from reel_studio.core import constants
from reel_studio.core.errors import RenderError
from reel_studio.core.logging import get_logger
from reel_studio.core.media_config import Media
from reel_studio.core.media_config import Segment as SegmentConfig
from reel_studio.editor.media import grade, textcards
from reel_studio.editor.media.edl import Resolved, resolve, seg_dur, speed_of
from reel_studio.editor.media.edl_models import Edl, GradeBlock, Segment, Version
from reel_studio.editor.media.shots import Clip, Shots
from reel_studio.editor.media.tools import Ffmpeg

__all__ = ["Job", "Timeline", "atempo_chain", "crop_filter", "render", "resolve", "text_events"]

log = get_logger(__name__)

STAGE = "render"
TEXT, CLEAN, TIMELINE = "text.mp4", "clean.mp4", "timeline.json"
LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)  # kit render.py:259


@dataclass(frozen=True)
class Job:
    work: Path  # holds clips/ and receives review/ and render_tmp/
    input_dir: Path | None  # read for style photos only (D02)
    out_dir: Path  # receives text.mp4 and clean.mp4
    ffmpeg: Ffmpeg
    media: Media


class TextEvent(BaseModel):
    text: str
    kind: str
    position: str
    start: float
    end: float


class Timeline(BaseModel):
    """Where every segment and text landed (kit render.py:365-372); qa.py reads it."""

    files: dict[str, str]
    duration: float
    planned_duration: float
    segments: list[dict[str, object]]
    text: list[dict[str, object]]


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


def _flip(frame: Resolved) -> str:
    return ",hflip,vflip" if frame.rotate == constants.HALF_TURN_DEG else ""


def crop_filter(clip: Clip, frame: Resolved) -> str:
    """Fill 9:16 by cropping around the focus point, zoomed (kit render.py:167-176)."""
    pw, ph = clip.proxy_w, clip.proxy_h
    scale = max(constants.OUT_W / pw, constants.OUT_H / ph)
    cw = min(pw, round(constants.OUT_W / scale / frame.zoom / 2) * 2)
    ch = min(ph, round(constants.OUT_H / scale / frame.zoom / 2) * 2)
    x, y = int((pw - cw) * frame.focus_x), int((ph - ch) * frame.focus_y)
    out = f"{constants.OUT_W}:{constants.OUT_H}"
    return f"crop={cw}:{ch}:{x}:{y},scale={out}:flags=lanczos,setsar=1{_flip(frame)}"


def grade_filter(block: GradeBlock | None, lut: Path | None, media: Media) -> str:
    """Per-clip LUT then an optional eq fine-tune (kit render.py:179-186)."""
    out = ""
    if lut is not None:
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


class _Renderer:
    def __init__(self, job: Job, shots: Shots, edl: Edl) -> None:
        self.job, self.shots, self.edl, self.media = job, shots, edl, job.media
        self.rate, self.channels = str(constants.AUDIO_RATE_HZ), str(constants.AUDIO_CHANNELS)

    def segment(self, clip: Clip, seg: Segment, out: Path, lut: Path | None) -> None:
        """Kit render.py:226-247."""
        cfg = self.media.render.segment
        sp, d = speed_of(seg, self.media), seg_dur(seg, self.media)
        frame = resolve(seg, self.edl.defaults, self.media)
        vol = cfg.mute_db if seg.mute else seg.audio_db
        look = grade_filter(self.edl.grade, lut, self.media)
        tail = f"{look},setpts=(PTS-STARTPTS)/{sp},fps={constants.OUT_FPS}[v]"
        size = f"{constants.OUT_W}:{constants.OUT_H}"
        if frame.fit == "blur":  # whole frame visible, a blurred zoomed copy fills the canvas
            blur = self.media.render.blur_fit
            vchain = (
                f"[0:v]split[bgs][fgs];[bgs]scale={size}:force_original_aspect_ratio=increase,"
                f"crop={size},boxblur={blur.boxblur},eq=brightness={blur.background_brightness}[bg];"
                f"[fgs]scale={constants.OUT_W}:-2:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,"
                f"setsar=1{_flip(frame)}{tail}"
            )
        else:
            vchain = f"[0:v]{crop_filter(clip, frame)}{tail}"
        fade_out = max(0.0, d - cfg.fade_s)
        achain = (
            f"[0:a]asetpts=PTS-STARTPTS,{atempo_chain(sp, cfg)},volume={vol}dB,"
            f"aresample={self.rate},apad,atrim=0:{d:.4f},afade=t=in:d={cfg.fade_s},"
            f"afade=t=out:st={fade_out:.4f}:d={cfg.fade_s}[a]"
        )
        args = [
            "-y",
            "-v",
            "error",
            "-ss",
            f"{seg.in_:.3f}",
            "-t",
            f"{seg.out - seg.in_:.3f}",
            "-i",
            str(self.job.work / clip.proxy),
            "-filter_complex",
            f"{vchain};{achain}",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            f"{d:.4f}",
            "-c:v",
            "libx264",
            "-crf",
            str(cfg.crf),
            "-preset",
            cfg.preset,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            cfg.audio_codec,
            "-ar",
            self.rate,
            "-ac",
            self.channels,
            str(out),
        ]
        self.job.ffmpeg.run(args, f"Rendering segment {out.name}")

    def loudness(self, parts: list[Path]) -> dict[str, str] | None:
        """Pass 1 of two-pass loudnorm, audio only (kit render.py:250-268)."""
        cfg = self.media.render.loudness
        args = ["-hide_banner", "-nostats"]
        for p in parts:
            args += ["-i", str(p)]
        inputs = "".join(f"[{i}:a]" for i in range(len(parts)))
        norm = (
            f"loudnorm=I={constants.TARGET_LUFS:g}:TP={cfg.true_peak_db:g}:LRA={cfg.lra}"
            ":print_format=json"
        )
        args += [
            "-filter_complex",
            f"{inputs}concat=n={len(parts)}:v=0:a=1,{norm}[a]",
            "-map",
            "[a]",
            "-f",
            "null",
            "-",
        ]
        found = LOUDNORM_JSON.search(self.job.ffmpeg.measure(args, "Measuring loudness"))
        if found is None:
            return None
        data: dict[str, str] = json.loads(found.group(0))
        try:
            if float(data["input_i"]) < cfg.silence_below_lufs:  # silence: nothing to normalise
                return None
        except ValueError:
            return None
        return data

    def loud_filter(self, loud: dict[str, str] | None) -> str:
        """Linear loudnorm when it can reach the target under the peak cap, else gain + limiter."""
        cfg = self.media.render.loudness
        if loud is None:
            return "anull"
        gain = constants.TARGET_LUFS - float(loud["input_i"])
        if float(loud["input_tp"]) + gain <= cfg.true_peak_db:
            return (
                f"loudnorm=I={constants.TARGET_LUFS:g}:TP={cfg.true_peak_db:g}:LRA={cfg.lra}:"
                f"measured_I={loud['input_i']}:measured_TP={loud['input_tp']}:"
                f"measured_LRA={loud['input_lra']}:measured_thresh={loud['input_thresh']}:"
                f"offset={loud['target_offset']}:linear=true"
            )
        boost = min(
            gain + cfg.limiter_headroom_db, cfg.max_gain_db
        )  # the limiter eats some loudness
        return (
            f"volume={boost:.2f}dB,aresample={cfg.limiter_oversample_hz},"
            f"alimiter=limit={cfg.limiter_limit}:attack={cfg.limiter_attack_ms}:"
            f"release={cfg.limiter_release_ms}:level=false,aresample={self.rate}"
        )

    def finalize(
        self,
        parts: list[Path],
        loud: dict[str, str] | None,
        overlays: list[tuple[TextEvent, Path]],
        out: Path,
    ) -> None:
        """Concatenate, overlay text, normalise, encode (kit render.py:271-303)."""
        cfg = self.media.render.final
        args, n = ["-y", "-v", "error"], len(parts)
        for p in parts:
            args += ["-i", str(p)]
        for _, png in overlays:
            args += ["-loop", "1", "-i", str(png)]
        chain = ["".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v0][nat]"]
        last = "v0"
        for k, (ev, _) in enumerate(overlays):
            nxt = f"v{k + 1}"
            chain.append(
                f"[{last}][{n + k}:v]overlay=0:0:shortest=1:"
                f"enable='between(t,{ev.start:.3f},{ev.end:.3f})'[{nxt}]"
            )
            last = nxt
        chain.append(
            f"[nat]volume={self.edl.audio.natural_db}dB,{self.loud_filter(loud)},aresample={self.rate}[aout]"
        )
        fps = constants.OUT_FPS
        args += [
            "-filter_complex",
            ";".join(chain),
            "-map",
            f"[{last}]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            cfg.preset,
            "-crf",
            str(cfg.crf),
            "-profile:v",
            cfg.profile,
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-g",
            str(fps * cfg.gop_seconds),
            "-maxrate",
            cfg.maxrate,
            "-bufsize",
            cfg.bufsize,
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-c:a",
            "aac",
            "-b:a",
            f"{cfg.audio_bitrate_kbps}k",
            "-ar",
            self.rate,
            "-ac",
            self.channels,
            "-movflags",
            "+faststart",
            str(out),
        ]
        self.job.ffmpeg.run(args, f"Final encode {out.name}")


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
        overlays, boxes = [], []
        for k, ev in enumerate(events):
            png = tmp / f"text{k:02d}.png"
            box = textcards.render_card(
                textcards.Card(ev.text, ev.kind, ev.position), png, edl.text_style, job.media
            )
            overlays.append((ev, png))
            boxes.append({**ev.model_dump(), **box.__dict__})
        r = _Renderer(job, shots, edl)
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
    timeline = Timeline(
        files={"text": str(texted), "clean": str(clean)},
        duration=round(job.ffmpeg.probe(texted).duration, 2),
        planned_duration=round(total, 2),
        segments=[
            {
                "i": i,
                "clip": s.clip,
                "in": s.in_,
                "out": s.out,
                "speed": speed_of(s, job.media),
                "role": s.role,
                "kind": (shots.clip(s.clip) or shots.clips[0]).kind,
                "start": round(a, 2),
                "end": round(b, 2),
                "note": s.note,
            }
            for i, (s, (a, b)) in enumerate(zip(version.segments, starts, strict=True))
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
