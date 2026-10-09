"""EDL checks: the kit's `render.py --check` rules, reporting every problem, not the first.

Errors block the render; warnings are craft risks the editor fixes or justifies in `note`
(kit render.py:51-163). The v1 fields add their own rules (docs/EDITOR.md §7).
"""

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from reel_studio.core.media_config import Media
from reel_studio.editor.media.edl_models import (
    ENDINGS,
    FITS,
    LONG_OK,
    ROLES,
    ROTATIONS,
    STILL_OK,
    Edl,
    Segment,
    Version,
    resolve,
    seg_dur,
    speed_of,
)
from reel_studio.editor.media.grade import LOOKS
from reel_studio.editor.media.shots import Clip, Shots
from reel_studio.editor.media.textcards import STYLES

VERSION_NAME = re.compile(r"[A-Za-z0-9]+")  # kit render.py:76


@dataclass
class Report:
    edl: Edl | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse(raw: Any) -> Edl | list[str]:  # Any: JSON as written by Claude or a person
    try:
        return Edl.model_validate(raw)
    except ValidationError as exc:
        return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]


@dataclass
class _Checker:
    edl: Edl
    shots: Shots
    media: Media
    report: Report

    def err(self, message: str) -> None:
        self.report.errors.append(message)

    def warn(self, message: str) -> None:
        self.report.warnings.append(message)

    # ------------------------------------------------------------ whole EDL (render.py:55-77)
    def top_level(self) -> None:
        cfg, edl = self.media.edl, self.edl
        if edl.format not in cfg.format_target_s:
            self.err(f"format {edl.format!r} not one of {sorted(cfg.format_target_s)}")
        if edl.text_style not in STYLES:
            self.err(f"text_style must be one of {sorted(STYLES)}")
        if edl.audio.music:  # truthiness, as the kit (render.py:62): `false` is no music
            self.err("music is not supported: music is chosen inside Instagram. Remove audio.music")
        self.grade()
        if len(edl.versions) != 1:
            self.err(
                "need exactly 1 version (one cut; text and clean are rendered from it), "
                f"found {len(edl.versions)}"
            )
        names = [v.name for v in edl.versions]
        bad = any(n is None or not VERSION_NAME.fullmatch(n) for n in names)
        if len(set(names)) != len(names) or bad:
            self.err("version names must be unique letters/digits, e.g. A and B")

    def grade(self) -> None:
        cfg, g = self.media.edl, self.edl.grade
        if g is None:
            return
        b = g.brightness if g.brightness is not None else 0.0
        c = g.contrast if g.contrast is not None else 1.0
        s = g.saturation if g.saturation is not None else 1.0
        ok = (
            cfg.brightness_min <= b <= cfg.brightness_max
            and cfg.contrast_min <= c <= cfg.contrast_max
            and cfg.saturation_min <= s <= cfg.saturation_max
        )
        if not ok:
            self.err(
                "grade fine-tune out of range: "
                f"brightness {cfg.brightness_min}..{cfg.brightness_max}"
                f", contrast {cfg.contrast_min}..{cfg.contrast_max}"
                f", saturation {cfg.saturation_min}..{cfg.saturation_max}"
            )
        if g.look is not None and g.look not in LOOKS:
            self.err(f"grade.look must be one of {LOOKS}")
        if not all(0 <= v <= 1 for v in (g.strength, g.match) if v is not None):
            self.err("grade.strength and grade.match must be 0..1")

    # ------------------------------------------------------------ one segment (render.py:90-139)
    def timing(self, seg: Segment, tag: str, clip: Clip) -> float | None:
        """in/out, speed and length; the on-screen seconds, or None when unusable."""
        cfg = self.media.edl
        if not 0 <= seg.in_ < seg.out <= clip.duration + cfg.out_tolerance_s:
            self.err(f"{tag}: in/out must satisfy 0 <= in < out <= {clip.duration:.2f}")
            return None
        sp = speed_of(seg, self.media)
        if not cfg.min_speed <= sp <= cfg.max_speed:
            self.err(f"{tag}: speed {sp} outside {cfg.min_speed}-{cfg.max_speed}")
            return None
        if sp < cfg.slow_motion_below and clip.proxy_fps < cfg.slow_motion_min_fps:
            self.err(
                f"{tag}: slow motion {sp}x on a {clip.proxy_fps} fps clip stutters; use >= "
                f"{cfg.slow_motion_below} or a {self.media.prepare.proxy_fps_high} fps clip"
            )
        d = seg_dur(seg, self.media)
        if d < cfg.min_segment_s:
            self.err(f"{tag}: on screen {d:.2f}s, minimum {cfg.min_segment_s}s")
        if seg.role not in ROLES:
            self.err(f"{tag}: role {seg.role!r} not one of {sorted(ROLES)}")
        too_long = d > cfg.max_middle_s + cfg.max_middle_tolerance_s
        if seg.role not in LONG_OK and too_long and not seg.allow_long:
            self.err(
                f"{tag}: {d:.2f}s on screen; non-hook shots max {cfg.max_middle_s}s "
                "(speed up or trim, or set allow_long with the reason in note)"
            )
        return d

    def framing(self, seg: Segment, tag: str) -> None:
        cfg = self.media.edl
        frame = resolve(seg, self.edl.defaults, self.media)
        for name, value in (("focus_x", frame.focus_x), ("focus_y", frame.focus_y)):
            if not 0 <= value <= 1:
                self.err(f"{tag}: {name} must be 0..1")
        if not cfg.zoom_min <= frame.zoom <= cfg.zoom_max:
            self.err(f"{tag}: zoom must be {cfg.zoom_min}..{cfg.zoom_max}")
        if frame.fit not in FITS:
            self.err(f"{tag}: fit must be crop or blur")
        if frame.rotate not in ROTATIONS:
            self.err(f"{tag}: rotate must be 0 or 180")
        if seg.text is not None and not seg.text.strip():
            self.err(f"{tag}: label is blank")
        if seg.text and len(seg.text) > cfg.label_max_chars:
            self.err(f"{tag}: label over {cfg.label_max_chars} characters")

    def craft(self, seg: Segment, tag: str, clip: Clip, d: float) -> None:
        """Warnings from the measured windows (kit render.py:129-138)."""
        cfg = self.media.edl
        windows = [w for w in self.shots.windows if w.clip == clip.id]
        overlap = [w for w in windows if w.end > seg.in_ and w.start < seg.out]
        if not overlap or clip.kind != "video":
            return
        med_motion = sorted(w.motion for w in windows)[len(windows) // 2]
        motion = sum(w.motion for w in overlap) / len(overlap)
        sharp = min(w.sharpness for w in overlap)
        static = med_motion > 0 and motion < cfg.static_motion_ratio * med_motion
        if seg.role not in STILL_OK and static and d > cfg.static_min_s:
            self.warn(
                f"{tag}: nearly static ({motion:.1f} vs clip median {med_motion:.1f}) — dead air?"
            )
        if clip.median_sharpness and sharp < cfg.blur_ratio * clip.median_sharpness:
            self.warn(f"{tag}: blurrier than half the clip's median sharpness — check frames")

    # ------------------------------------------------------------ one version (render.py:83-162)
    def version(self, v: Version, index: int) -> None:
        cfg = self.media.edl
        vn = v.name if v.name is not None else f"#{index}"
        if not v.segments:
            self.err(f"version {vn}: no segments")
            return
        total = 0.0
        for i, seg in enumerate(v.segments):
            tag = f"{vn}[{i}] {seg.clip}"
            clip = self.shots.clip(seg.clip)
            if clip is None:
                self.err(f"{tag}: unknown clip id")
                continue
            d = self.timing(seg, tag, clip)
            if d is None:
                continue
            self.framing(seg, tag)
            self.craft(seg, tag, clip, d)
            total += d
        fmt = self.edl.format if self.edl.format in cfg.format_target_s else "other"
        lo, hi = cfg.format_target_s[fmt]
        if not lo <= total <= hi:
            self.warn(f"version {vn}: {total:.1f}s, {fmt} target {lo}-{hi}s")
        if not cfg.total_min_s <= total <= cfg.total_max_s:
            self.err(
                f"version {vn}: total {total:.1f}s outside {cfg.total_min_s:g}-{cfg.total_max_s:g}s"
            )
        self.shape(v, vn)

    def shape(self, v: Version, vn: str) -> None:
        """Hook, ending, clutter and jump-cut warnings (kit render.py:146-162)."""
        cfg, segs = self.media.edl, v.segments
        if v.hook_text is not None and not v.hook_text.strip():
            self.err(f"version {vn}: hook_text is blank")
        if segs[0].role != "hook":
            self.warn(f"version {vn}: first segment role is not hook")
        elif cfg.min_speed <= speed_of(segs[0], self.media) <= cfg.max_speed:  # else timing() erred
            hook_s = seg_dur(segs[0], self.media)
            if hook_s > cfg.hook_max_s:
                self.warn(
                    f"version {vn}: hook lasts {hook_s:.1f}s; payoff-first hooks work in under 3 s"
                )
        if segs[-1].role not in ENDINGS:
            self.warn(
                f"version {vn}: last segment is not a payoff/verdict/reveal (weak ending, no loop)"
            )
        words = len(v.hook_text.split()) if v.hook_text else 0
        if words > cfg.hook_max_words:
            self.warn(f"version {vn}: hook text has {words} words; aim for 6 or fewer")
        labels = sum(1 for s in segs if s.text)
        if labels > cfg.labels_max:
            self.warn(f"version {vn}: {labels} labels; more than {cfg.labels_max} reads as clutter")
        for i in range(1, len(segs)):
            p, q = segs[i - 1], segs[i]
            zoom = resolve(p, self.edl.defaults, self.media).zoom
            same_zoom = zoom == resolve(q, self.edl.defaults, self.media).zoom
            same = same_zoom and speed_of(p, self.media) == speed_of(q, self.media)
            if p.clip == q.clip and abs(q.in_ - p.out) < cfg.jump_cut_gap_s and same:
                self.warn(
                    f"version {vn}[{i}]: same clip, same framing as previous shot — jump cut risk "
                    "(change zoom by >= 0.2, insert another shot, or merge them)"
                )

    # ------------------------------------------------------------ v1 fields (EDITOR.md §7)
    def v1(self, order_style: str | None) -> None:
        """v1 rules that need no clips."""
        edl, cfg = self.edl, self.media.edl
        if order_style is not None and edl.style != order_style:
            self.err(f"style {edl.style!r} does not match the order's style {order_style!r}")
        if edl.caption is not None and len(edl.caption) > cfg.caption_max_chars:
            self.err(f"caption over {cfg.caption_max_chars} characters")
        if edl.music_hint is not None and len(edl.music_hint) > cfg.music_hint_max_chars:
            self.err(f"music_hint over {cfg.music_hint_max_chars} characters")

    def dropped(self) -> None:
        """Every dropped id is a clip, listed once; a v1 EDL accounts for every unused clip."""
        edl, seen = self.edl, set()
        for item in edl.dropped:
            if self.shots.clip(item.clip) is None:
                self.err(f"dropped: unknown clip id {item.clip}")
            if item.clip in seen:
                self.err(f"dropped: {item.clip} listed twice")
            seen.add(item.clip)
        if edl.style is None:  # a hand-written kit EDL has no dropped list (EDITOR.md §7 is v1)
            return
        used = {seg.clip for v in edl.versions for seg in v.segments}
        for clip in self.shots.clips:
            if clip.id not in used and clip.id not in seen:
                self.err(f"dropped: {clip.id} is not in any segment and not listed with a reason")


def validate(
    raw: Any, shots: Shots, media: Media, order_style: str | None = None
) -> Report:  # Any: JSON
    """Parse and check an EDL; `errors` empty means it can be rendered."""
    parsed = parse(raw)
    if not isinstance(parsed, Edl):
        return Report(None, errors=list(parsed))
    checker = _Checker(parsed, shots, media, Report(parsed))
    checker.top_level()
    for index, version in enumerate(parsed.versions):
        checker.version(version, index)
    checker.v1(order_style)
    checker.dropped()
    return checker.report


def precheck(raw: Any, media: Media) -> list[str]:  # Any: JSON
    """The errors that need no clips: shape, top-level rules, v1 lengths. Cheap; run it first."""
    parsed = parse(raw)
    if not isinstance(parsed, Edl):
        return list(parsed)
    none = Shots(name="", clips=[], windows=[], sheets=[], total_raw_seconds=0.0)
    checker = _Checker(parsed, none, media, Report(parsed))
    checker.top_level()
    checker.v1(None)
    return checker.report.errors
