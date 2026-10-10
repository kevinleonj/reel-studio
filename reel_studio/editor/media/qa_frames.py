"""QA from the pictures: motion and exposure per segment, every cut compared (kit qa.py:120-189).

Each finding is a FLAG (a craft risk to look at on the sheets), never a hard failure.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel

from reel_studio.core.media_config import Qa
from reel_studio.editor.media.colour import ssim
from reel_studio.editor.media.qa_sheets import FrameStats, grab, stats, tile
from reel_studio.editor.media.render import PlacedSegment

EXCUSED = frozenset({"payoff", "reveal", "verdict", "reaction"})  # may be still (kit qa.py:142)


class SegmentStats(BaseModel):
    i: int
    motion: float
    sharp: float
    luma: float
    colourful: float
    clip_hi: float
    crush: float


class Cut(BaseModel):
    cut: str
    t: float
    ssim: float
    hist: float
    dluma: float
    dE: float


@dataclass
class Frames:
    cfg: Qa
    flag: Callable[[str], None]
    median_motion: float = 0.0
    median_sharpness: float = 0.0
    tiles: list[tuple[str, Image.Image]] = field(default_factory=list)

    def segments(
        self, cap: cv2.VideoCapture, placed: Sequence[PlacedSegment]
    ) -> list[SegmentStats]:
        s, cfg = self.cfg.sampling, self.cfg
        rows: list[tuple[PlacedSegment, SegmentStats]] = []
        for seg in placed:
            mid = (seg.start + seg.end) / 2
            f0 = grab(cap, max(seg.start, mid - s.segment_half_span_s))
            f1 = grab(cap, min(seg.end - s.segment_end_inset_s, mid + s.segment_half_span_s))
            if f0 is None or f1 is None:
                continue
            a, b = stats(f0, cfg), stats(f1, cfg)
            rows.append(
                (
                    seg,
                    SegmentStats(
                        i=seg.i,
                        motion=float(np.mean(cv2.absdiff(a.gray, b.gray))),
                        sharp=(a.sharp + b.sharp) / 2,
                        luma=a.luma,
                        colourful=a.colourful,
                        clip_hi=float((a.gray >= cfg.blown_pixel).mean()),
                        crush=float((a.gray <= cfg.crushed_pixel).mean()),
                    ),
                )
            )
        found = [r for _, r in rows]
        self.median_motion = float(np.median([r.motion for r in found])) if found else 0.0
        self.median_sharpness = float(np.median([r.sharp for r in found])) if found else 0.0
        for seg, r in rows:
            self._segment_flags(seg, r)
        return found

    def _segment_flags(self, seg: PlacedSegment, r: SegmentStats) -> None:
        cfg, tag = self.cfg, f"seg {seg.i} ({seg.clip}"
        still = r.motion < cfg.dead_ratio * self.median_motion
        if (
            seg.kind != "photo"
            and seg.role not in EXCUSED
            and self.median_motion
            and still
            and seg.end - seg.start > cfg.dead_min_s
        ):
            self.flag(f"{tag}, {seg.start:.1f}-{seg.end:.1f}s): little motion — dead air?")
        if r.clip_hi > cfg.blown_frac:
            self.flag(
                f"{tag}): {r.clip_hi:.0%} of the frame is blown-out white"
                " — lower the look strength or pick another shot"
            )
        if r.crush > cfg.crushed_frac:
            self.flag(f"{tag}): {r.crush:.0%} crushed to black — moody look too strong?")
        if self.median_sharpness and r.sharp < cfg.blur_ratio * self.median_sharpness:
            self.flag(f"{tag}): blurrier than half the Reel median — check it on the sheet")

    def cuts(self, cap: cv2.VideoCapture, placed: Sequence[PlacedSegment]) -> list[Cut]:
        cfg, s, size = self.cfg, self.cfg.sampling, self.cfg.sheets.cuts_tile_px
        found = []
        for index in range(1, len(placed)):
            p, q = placed[index - 1], placed[index]
            fa, fb = grab(cap, p.end - s.cut_before_s), grab(cap, q.start + s.cut_after_s)
            if fa is None or fb is None:
                continue
            sa, sb = stats(fa, cfg), stats(fb, cfg)
            c = Cut(
                cut=f"{p.i}->{q.i}",
                t=q.start,
                ssim=round(ssim(sa.gray, sb.gray, cfg.ssim_window, cfg.ssim_sigma), 2),
                hist=round(float(cv2.compareHist(sa.hsv_hist, sb.hsv_hist, cv2.HISTCMP_CORREL)), 2),
                dluma=round(sb.luma - sa.luma),
                dE=round(float(np.linalg.norm(sa.lab - sb.lab)), 1),
            )
            found.append(c)
            self._cut_flags(c, p, q)
            self.tiles += [
                (f"{c.cut} end", tile(fa, size)),
                (f"ssim{c.ssim} dL{c.dluma:+.0f}", tile(fb, size)),
            ]
        return found

    def _cut_flags(self, c: Cut, p: PlacedSegment, q: PlacedSegment) -> None:
        cfg, same = self.cfg, p.clip == q.clip
        where = f"cut {c.cut} at {c.t:.1f}s"
        # A fixed overhead camera makes steps look alike: flag only same-clip identical framing.
        if (
            same and c.ssim > cfg.jump_ssim and c.hist > cfg.jump_hist
        ) or c.ssim > cfg.near_same_ssim:
            clip = ", same clip" if same else ""
            self.flag(
                f"{where}: near-identical framing (ssim {c.ssim}, hist {c.hist}{clip}) — jump cut?"
            )
        if abs(c.dluma) > cfg.luma_jump:
            self.flag(f"{where}: brightness jump {c.dluma:+.0f} — intended?")
        if same and c.dE > cfg.colour_shift_de and abs(q.in_ - p.out) < cfg.colour_shift_gap_s:
            self.flag(f"{where}: colour shift dE {c.dE} inside one clip — check grade/exposure")

    def first_frame(self, first: FrameStats) -> None:
        cfg = self.cfg
        if (
            self.median_sharpness
            and first.sharp < cfg.first_frame_soft_ratio * self.median_sharpness
        ):
            self.flag(
                "frame 1 is soft compared with the rest"
                " — the first frame must be the sharpest, most appetising image"
            )
        if first.luma < cfg.first_frame_dark_luma:
            self.flag(f"frame 1 is dark (luma {first.luma:.0f})")
