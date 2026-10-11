"""One judge for both A/B arms (STEP-04 task 2): our QA sheets and our critic on any finished cut.

Both engines' outputs go through this same function with the same order line, so neither side is
scored by its own critic or on different material. Its calls are costed on their own meter.
"""

import shutil
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from reel_studio.core.config import Config
from reel_studio.core.media_config import Media
from reel_studio.editor import critic, loop, make, prompt
from reel_studio.editor.media import qa, render
from reel_studio.editor.media.tools import Ffmpeg
from reel_studio.editor.meter import Meter


@dataclass(frozen=True)
class Cut:
    """A finished Reel: its two files and where every segment and text landed."""

    text: Path
    clean: Path
    timeline: render.Timeline


@dataclass(frozen=True)
class Judged:
    total: int
    passed: bool
    cost_usd: Decimal
    weakness: str | None


@dataclass(frozen=True)
class CriticJudge:
    ports: make.Ports
    cfg: Config
    media: Media
    ffmpeg: Ffmpeg
    order: prompt.OrderSettings

    def __call__(self, cut: Cut, folder: Path) -> Judged:
        out = folder / "out"
        out.mkdir(parents=True, exist_ok=True)
        if cut.text.resolve() != (out / render.TEXT).resolve():
            shutil.copy2(cut.text, out / render.TEXT)
            shutil.copy2(cut.clean, out / render.CLEAN)
        job = render.Job(folder / make.WORK, None, out, self.ffmpeg, self.media)
        side = self.cfg.limits.sheets.max_image_side_px
        result = qa.run(job, cut.timeline, side)
        editor = self.cfg.limits.editor
        meter = Meter(self.cfg.prices, editor.cost_cap_usd)
        session = loop.Session(
            self.ports.claude, meter, self.ports.clock, folder / make.REQUESTS, editor, "critic"
        )
        material = critic.Material(
            sheets=[Path(s) for s in result.sheets],
            qa_lines=result.lines,
            timeline=make.timeline_lines(cut.timeline),
            order=make.order_line(self.order),
        )
        quality = self.media.contact_sheet.jpeg_quality
        review = critic.critique(session, prompt.critic_prompt(self.cfg), material, side, quality)
        ok, why = critic.passes(review, self.cfg.limits.gates)
        return Judged(review.total, ok, meter.spent, why if not ok else None)
