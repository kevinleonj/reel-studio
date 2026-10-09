"""EDL shape: the kit schema unchanged (D46, kit edl-schema.md) plus the v1 fields (EDITOR.md §7).

The models check types only; ranges and cross-references live in edl.py so that every problem
is reported at once. Fields a segment may inherit (`zoom`, `focus_x`, ...) stay None when
omitted and are resolved against `defaults`, then media.toml, at use (kit render.py:42-43).
Unknown fields are refused: a typo must not silently fall back to a default.
"""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reel_studio.core import constants
from reel_studio.core.media_config import Media

ROLES = frozenset(
    {
        "hook",
        "setup",
        "ingredient",
        "process",
        "mix",
        "assembly",
        "cook",
        "bake",
        "reveal",
        "payoff",
        "reaction",
        "detail",
        "ambience",
        "verdict",
        "other",
    }
)  # kit render.py:30-31
LONG_OK = frozenset({"hook", "reveal", "payoff", "verdict", "reaction"})  # kit render.py:32
STILL_OK = frozenset({"payoff", "reveal", "verdict"})  # may be static (kit render.py:135)
ENDINGS = frozenset({"payoff", "verdict", "reveal"})  # a strong last shot (kit render.py:150)
FITS = frozenset({"crop", "blur"})  # kit render.py:120
ROTATIONS = frozenset({0, constants.HALF_TURN_DEG})  # kit render.py:122
type Position = Literal["top", "center", "low"]  # kit textcards.py:57-64


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Framing(_Model):
    """Fields a segment may set and `defaults` may supply (kit edl-schema.md:58)."""

    zoom: float | None = None
    focus_x: float | None = None
    focus_y: float | None = None
    rotate: int | None = None
    fit: str | None = None


class Segment(Framing):
    clip: str
    in_: float = Field(alias="in")
    out: float
    speed: float | None = None
    role: str = "other"
    text: str | None = None
    text_span: int | None = None
    text_position: Position = "top"
    audio_db: float = 0.0
    mute: bool = False
    allow_long: bool = False
    note: str = ""
    # v1 (EDITOR.md §7)
    beat: str | None = None
    quote: str | None = None
    visual_check: bool | None = None


class Version(_Model):
    name: str | None = None
    hook_text: str | None = None
    title_seconds: float | None = None
    title_position: Position = "top"
    segments: list[Segment] = []

    @model_validator(mode="before")
    @classmethod
    def _title_is_hook_text(cls, data: Any) -> Any:  # Any: raw JSON before validation
        """The kit accepted `title` for `hook_text` (render.py:152, 208)."""
        if isinstance(data, dict) and "title" in data:
            data = dict(data)
            title = data.pop("title")
            data.setdefault("hook_text", title)
        return data


class GradeBlock(_Model):
    look: str | None = None
    strength: float | None = None
    match: float | None = None
    brightness: float | None = None
    contrast: float | None = None
    saturation: float | None = None


class AudioBlock(_Model):
    natural_db: float = 0.0
    music: Any = None  # Any: present at all is the error (D02, D42); its shape is irrelevant


class Dropped(_Model):
    clip: str
    reason: str


class Preference(_Model):
    text: str
    applied: bool
    why: str


class Edl(_Model):
    format: str = "other"
    text_style: str = "outline"
    defaults: Framing = Framing()
    grade: GradeBlock | None = None
    audio: AudioBlock = AudioBlock()
    versions: list[Version] = []
    # v1 (EDITOR.md §7)
    style: str | None = None
    dropped: list[Dropped] = []
    preferences: list[Preference] = []
    caption: str | None = None
    music_hint: str | None = None
    assumptions: list[str] = []
    check_by_eye: list[str] = []


@dataclass(frozen=True)
class Resolved:
    """A segment's framing after `defaults` and media.toml fill the gaps (kit render.py:42-43)."""

    zoom: float
    focus_x: float
    focus_y: float
    rotate: int
    fit: str


def resolve(seg: Segment, defaults: Framing, media: Media) -> Resolved:
    d = media.edl.defaults

    def pick(name: str, fallback: Any) -> Any:  # Any: one of the Framing field types
        own = getattr(seg, name)
        if own is not None:
            return own
        inherited = getattr(defaults, name)
        return inherited if inherited is not None else fallback

    return Resolved(
        pick("zoom", d.zoom),
        pick("focus_x", d.focus),
        pick("focus_y", d.focus),
        pick("rotate", 0),
        pick("fit", "crop"),
    )


def speed_of(seg: Segment, media: Media) -> float:
    return seg.speed if seg.speed is not None else media.edl.defaults.speed


def seg_dur(seg: Segment, media: Media) -> float:
    """On-screen seconds: (out - in) / speed (kit render.py:46-47)."""
    return (seg.out - seg.in_) / speed_of(seg, media)
