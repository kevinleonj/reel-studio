"""Quality checks on a rendered Reel: hard numbers and three review sheets (port of kit qa.py).

PASS/FAIL lines are the spec; they become `hard_checks` in qa.json, whose values are booleans
(the STEP-02 gate requires every one true). FLAG lines are craft risks, from heuristics the kit
calls rules of thumb. The sheets are hook (first 3 s), cuts (both sides of every cut) and
overview (24 frames), in the work folder's review/.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel

from reel_studio.core import constants
from reel_studio.core.errors import RenderError
from reel_studio.core.media_config import Qa
from reel_studio.editor.media.colour import ssim
from reel_studio.editor.media.qa_frames import Cut, Frames, SegmentStats
from reel_studio.editor.media.qa_sheets import Layout, grab, grid, stats, tile
from reel_studio.editor.media.render import CLEAN, TEXT, Job, PlacedText, Timeline
from reel_studio.editor.media.tools import Ffmpeg

QA_JSON = "qa.json"
REVIEW = "review"
LUFS = re.compile(r"I: +(-?[\d.]+) LUFS")  # kit qa.py:71 (ffmpeg pads with spaces)
BLACK = re.compile(r"black_start:([\d.]+) black_end:([\d.]+)")  # kit qa.py:73
FREEZE = re.compile(r"freeze_start: ([\d.]+)")  # kit qa.py:74


class AudioResult(BaseModel):
    lufs: float | None
    black: list[tuple[float, float]]
    freeze: list[float]


class HardChecks(BaseModel):
    """The kit's PASS/FAIL lines, one boolean each (docs/handoff/engine.md plan, row 10)."""

    spec_text: bool
    spec_clean: bool
    size_duration_text: bool
    size_duration_clean: bool
    no_black_frames: bool
    text_in_safe_zone: bool


class QaResult(BaseModel):
    hard_checks: HardChecks
    lines: list[str]
    audio: AudioResult
    cuts: list[Cut]
    segments: list[SegmentStats]
    median_motion: float
    median_sharpness: float
    loop: dict[str, float] | None
    sheets: list[str]


def measure_audio(ffmpeg: Ffmpeg, path: Path, cfg: Qa) -> AudioResult:
    """Loudness, black frames and frozen picture in one pass (kit qa.py:66-74)."""
    video = (
        f"blackdetect=d={cfg.black_min_s}:pix_th={cfg.black_pixel_threshold},"
        f"freezedetect=n={cfg.freeze_noise}:d={cfg.freeze_min_s}"
    )
    args = [
        "-hide_banner",
        "-nostats",
        "-i",
        str(path),
        "-filter_complex",
        f"[0:a]ebur128=peak=true[a];[0:v]{video}[v]",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-f",
        "null",
        "-",
    ]
    err = ffmpeg.measure(args, f"QA measure {path.name}")
    lufs = LUFS.findall(err)
    if not lufs:  # fail closed: no measurement must never read as clean (phase B review W5)
        last = err.strip().rpartition("\n")[2]
        raise RenderError(f"QA could not measure loudness of {path.name}: {last}")
    return AudioResult(
        lufs=float(lufs[-1]) if lufs else None,
        black=[(float(a), float(b)) for a, b in BLACK.findall(err)],
        freeze=[float(f) for f in FREEZE.findall(err)],
    )


def _beside(path: Path, base: Path) -> str:
    """`path` relative to `base` when inside it, so qa.json never depends on the cwd."""
    return str(path.relative_to(base)) if path.is_relative_to(base) else str(path)


def all_inside(boxes: list[PlacedText]) -> bool:
    """Every text box inside the safe zone; a Reel without text passes."""
    return all(b.inside_safe_zone for b in boxes)


@dataclass
class _Lines:
    lines: list[str] = field(default_factory=list)

    def res(self, ok: bool, msg: str) -> bool:
        self.lines.append(f"{'PASS' if ok else 'FAIL'}  {msg}")
        return ok

    def flag(self, msg: str) -> None:
        self.lines.append(f"FLAG  {msg}")


def _spec(job: Job, path: Path, out: _Lines) -> tuple[bool, bool]:
    """Codec, size, frame rate and audio; then file size and length (kit qa.py:104-110)."""
    cfg, edl = job.media.qa, job.media.edl
    info, size = job.ffmpeg.probe(path), path.stat().st_size
    form = (
        info.codec == "h264"
        and (info.width, info.height) == (constants.OUT_W, constants.OUT_H)
        and abs(info.fps - constants.OUT_FPS) < cfg.fps_tolerance
        and info.has_audio
    )
    a = out.res(
        form,
        f"{path.name}: {info.codec} {info.width}x{info.height} {info.fps:.0f}fps "
        f"{info.duration:.1f}s {size / constants.BYTES_PER_MB:.1f}MB",
    )
    fits = (
        size <= cfg.max_file_mb * constants.BYTES_PER_MB
        and edl.total_min_s <= info.duration <= edl.total_max_s
    )
    b = out.res(
        fits,
        f"{path.name}: within {edl.total_min_s:g}-{edl.total_max_s:g} s and {cfg.max_file_mb:g} MB",
    )
    return a, b


def _audio(job: Job, clean: Path, out: _Lines) -> AudioResult:
    cfg = job.media.qa
    a = measure_audio(job.ffmpeg, clean, cfg)
    if a.lufs is not None:
        if cfg.lufs_min <= a.lufs <= cfg.lufs_max:
            out.lines.append(f"PASS  loudness {a.lufs} LUFS (target {constants.TARGET_LUFS:g})")
        else:
            out.flag(f"loudness {a.lufs} LUFS, outside {cfg.lufs_min:g}..{cfg.lufs_max:g}")
    if a.freeze:
        out.flag(
            f"frozen picture >= {cfg.freeze_min_s:g} s at {a.freeze} s (static shot or stuck frame)"
        )
    return a


def _text(timeline: Timeline, cfg: Qa, out: _Lines) -> bool:
    for b in timeline.text:
        out.res(b.inside_safe_zone, f"text '{b.text}' {b.start:.1f}-{b.end:.1f}s {b.font_px}px")
        need = max(cfg.read_min_s, len(b.text) / cfg.read_chars_per_s)
        if b.end - b.start + cfg.read_tolerance_s < need:
            out.flag(
                f"text '{b.text}' on screen {b.end - b.start:.2f}s; needs >= {need:.2f}s to be read"
            )
    return all_inside(timeline.text)


def _hook_and_overview(
    tcap: cv2.VideoCapture, timeline: Timeline, cfg: Qa
) -> tuple[list[tuple[str, Image.Image]], list[tuple[str, Image.Image]]]:
    s, sh, dur = cfg.sampling, cfg.sheets, timeline.duration
    hook = []
    for t in np.arange(0.0, min(sh.hook_seconds, dur), sh.hook_step_s):
        frame = grab(tcap, float(t) + s.hook_offset_s)
        if frame is not None:
            hook.append((f"{t:.2f}s", tile(frame, sh.hook_tile_px)))
    over = []
    last = max(dur - s.overview_edge_s, 2 * s.overview_edge_s)
    for t in np.linspace(s.overview_edge_s, last, sh.overview_frames):
        frame = grab(tcap, float(t))
        seg = next((x.i for x in timeline.segments if x.start <= t < x.end), "?")
        if frame is not None:
            over.append((f"{t:.1f}s seg{seg}", tile(frame, sh.overview_tile_px)))
    return hook, over


def run(job: Job, timeline: Timeline, max_side: int) -> QaResult:
    """Check text.mp4 and clean.mp4, draw the review sheets, write qa.json into out_dir."""
    cfg, s, sh, out = job.media.qa, job.media.qa.sampling, job.media.qa.sheets, _Lines()
    text_p, clean_p = job.out_dir / TEXT, job.out_dir / CLEAN
    spec_text, size_text = _spec(job, text_p, out)
    spec_clean, size_clean = _spec(job, clean_p, out)
    audio = _audio(job, clean_p, out)
    no_black = out.res(not audio.black, f"black frames: {audio.black if audio.black else 'none'}")
    frames = Frames(cfg, out.flag)
    cap, tcap = cv2.VideoCapture(str(clean_p)), cv2.VideoCapture(str(text_p))
    try:
        segments = frames.segments(cap, timeline.segments)
        cuts = frames.cuts(cap, timeline.segments)
        hook, over = _hook_and_overview(tcap, timeline, cfg)
        first, last = (
            grab(cap, s.first_frame_s),
            grab(cap, timeline.duration - s.last_frame_inset_s),
        )
    finally:
        cap.release()
        tcap.release()
    if first is not None and segments:
        frames.first_frame(stats(first, cfg))
    safe = _text(timeline, cfg, out)
    loop = None
    if last is not None and first is not None:
        a, b = stats(last, cfg), stats(first, cfg)
        loop = {
            "ssim": round(ssim(a.gray, b.gray, cfg.ssim_window, cfg.ssim_sigma), 2),
            "hist": round(float(cv2.compareHist(a.hsv_hist, b.hsv_hist, cv2.HISTCMP_CORREL)), 2),
        }
        out.lines.append(
            f"INFO  loop match last->first: ssim {loop['ssim']}, colour hist {loop['hist']}"
            " (higher = smoother replay)"
        )
    review = job.work / REVIEW
    review.mkdir(parents=True, exist_ok=True)
    sheets = [review / "hook.jpg", review / "cuts.jpg", review / "overview.jpg"]
    cut_tiles = frames.tiles if frames.tiles else [("no cuts", Image.new("RGB", sh.cuts_tile_px))]
    grid(hook, Layout(sh.hook_cols, sh.hook_tile_px, safe=True), sheets[0], job.media, max_side)
    grid(
        cut_tiles, Layout(sh.cuts_cols, sh.cuts_tile_px, safe=False), sheets[1], job.media, max_side
    )
    grid(
        over,
        Layout(sh.overview_cols, sh.overview_tile_px, safe=True),
        sheets[2],
        job.media,
        max_side,
    )
    result = QaResult(
        hard_checks=HardChecks(
            spec_text=spec_text,
            spec_clean=spec_clean,
            size_duration_text=size_text,
            size_duration_clean=size_clean,
            no_black_frames=no_black,
            text_in_safe_zone=safe,
        ),
        lines=out.lines,
        audio=audio,
        cuts=cuts,
        segments=segments,
        median_motion=frames.median_motion,
        median_sharpness=frames.median_sharpness,
        loop=loop,
        sheets=[_beside(p, job.out_dir) for p in sheets],
    )
    (job.out_dir / QA_JSON).write_text(result.model_dump_json(indent=1), encoding="utf-8")
    return result
