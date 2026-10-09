"""shots.json: every clip and measured window of an order (kit prep.py:288-297, shots.py).

prepare, measure and sheets fill it; the grade, the EDL checks, render and the loop read it.
"""

from pydantic import BaseModel, ConfigDict

from reel_studio.editor.media.colour import ColourStats
from reel_studio.editor.media.measure import Window
from reel_studio.editor.media.prepare import Proxy

SHOTS = "shots.json"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Clip(_Frozen):
    """One proxy with its colour summary; `proxy` is relative to the work folder."""

    id: str
    source: str
    proxy: str
    duration: float
    orientation: str
    proxy_w: int
    proxy_h: int
    proxy_fps: int
    color: str
    kind: str
    color_stats: ColourStats | None
    median_sharpness: float

    @classmethod
    def of(cls, proxy: Proxy, stats: ColourStats | None, median_sharpness: float) -> "Clip":
        return cls(
            id=proxy.id,
            source=proxy.source,
            proxy=proxy.path,
            duration=proxy.duration,
            orientation=proxy.orientation,
            proxy_w=proxy.width,
            proxy_h=proxy.height,
            proxy_fps=proxy.fps,
            color=proxy.color,
            kind=proxy.kind,
            color_stats=stats,
            median_sharpness=median_sharpness,
        )


class Shots(_Frozen):
    name: str
    clips: list[Clip]
    windows: list[Window]
    sheets: list[str]
    total_raw_seconds: float

    def clip(self, clip_id: str) -> Clip | None:
        return next((c for c in self.clips if c.id == clip_id), None)


def format_table(shots: Shots) -> str:
    """Compact clip and window table for the editor (kit shots.py:26-36)."""
    median = {c.id: c.median_sharpness if c.median_sharpness > 0 else 1.0 for c in shots.clips}
    lines = [
        f"{shots.name}: {len(shots.clips)} clips, {shots.total_raw_seconds}s raw",
        "clip  source                    dur   fps  orient     kind   colour",
    ]
    lines += [
        f"{c.id:<5} {c.source:<24.24} {c.duration:>5.1f}  {c.proxy_fps:>3}  "
        f"{c.orientation:<10} {c.kind:<6} {c.color}"
        for c in shots.clips
    ]
    lines += ["", "win   clip  start   end   motion sharp  luma colour  warm"]
    lines += [
        f"{w.id:<5} {w.clip:<5} {w.start:>5.1f} {w.end:>5.1f}  {w.motion:>6.1f} "
        f"{w.sharpness / median[w.clip]:>5.2f} {w.luma:>5.0f} {w.colourful:>6.0f} {w.warmth:>5.1f}"
        for w in shots.windows
    ]
    lines += ["", "sheets: " + " ".join(shots.sheets)]
    return "\n".join(lines)
