"""The editor's five tools (docs/EDITOR.md §4, D31): four read-only views and write_edl.

Our code does every action; Claude only decides. Each tool's input is a Pydantic model; its JSON
schema is sent with `strict: true`, stripped of what strict schemas reject (numeric and length
bounds, maxItems, defaults: F11, F208), and the bounds are checked here instead. A tool never
raises into the loop: a bad call comes back as `is_error` with a message that names the valid
values. Every image is shrunk to the F08 limit before it is sent.
"""

import base64
import io
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import BaseModel, ConfigDict, ValidationError

from reel_studio.core.config import Limits
from reel_studio.core.errors import MediaError
from reel_studio.core.media_config import Media
from reel_studio.editor.media import edl, grade, grade_preview, strip
from reel_studio.editor.media.edl_models import Edl
from reel_studio.editor.media.sheets import LEGEND
from reel_studio.editor.media.shots import Clip, Shots

type Block = dict[str, Any]  # Any: an Anthropic content block

STRIPS, JPEG = "strips", "image/jpeg"
UNSUPPORTED = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "maxItems",
    "default",
)  # strict schemas reject these (F208)


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadSheet(_Input):
    """Look at one contact sheet: 4x4 tiles of frames, with a legend from tile to clip and time."""

    sheet_id: str


class ReadStrip(_Input):
    """Frames of one clip between two times, to pick exact cut points (at most 6 s; at most 12
    strips per edit)."""

    clip: str
    start_s: float
    end_s: float


class ReadGradePreview(_Input):
    """The colour looks side by side on a few frames (at most 2 per edit). Frames as "clip:time"
    (e.g. "c03:2.5"); null picks the most colourful sharp frames."""

    frames: list[str] | None


class ReadTranscript(_Input):
    """Word-level transcript of one clip with gaps marked (only when the order keeps the voice)."""

    clip: str


@dataclass(frozen=True)
class Context:
    work: Path
    input_dir: Path | None
    shots: Shots
    media: Media
    limits: Limits
    order_style: str | None
    voice: bool


@dataclass
class Result:
    content: list[Block]
    is_error: bool = False

    def text(self) -> str:
        return "\n".join(b["text"] for b in self.content if b["type"] == "text")


def _text(message: str, is_error: bool = False) -> Result:
    return Result([{"type": "text", "text": message}], is_error)


def strict_schema(schema: Any) -> Any:  # Any: JSON Schema
    """Drop what strict tool schemas reject and close every object (F11, F208)."""
    if isinstance(schema, dict):
        out = {
            k: strict_schema(v) for k, v in schema.items() if k not in UNSUPPORTED and k != "title"
        }
        if out.get("type") == "object":
            out["additionalProperties"] = False
        return out
    if isinstance(schema, list):
        return [strict_schema(v) for v in schema]
    return schema


def image_block(image: Image.Image, max_side: int, quality: int) -> Block:
    """A JPEG content block no larger than the F08 limit on its longest side."""
    picture = image.convert("RGB")
    picture.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    picture.save(buffer, format="JPEG", quality=quality)
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": JPEG, "data": data}}


def _render_strip(work: Path, request: strip.Request, media: Media, max_side: int) -> Path:
    return strip.strip(work, request, work / STRIPS, media, max_side)


def _render_preview(
    work: Path, shots: Shots, frames: list[tuple[str, float]] | None, ctx: Context
) -> Image.Image:
    media, cfg = ctx.media, ctx.media.grade
    choice = grade.Choice(cfg.default_look, cfg.default_strength, cfg.default_match)
    ref = grade.reference_of(shots, ctx.input_dir, media)
    return grade_preview.preview(
        work, shots, grade_preview.PreviewRequest(choice, ref, frames), media
    )


@dataclass
class Toolbox:
    ctx: Context
    strips: int = 0
    previews: int = 0
    accepted: Edl | None = None
    warnings: list[str] = field(default_factory=list)

    def definitions(self) -> list[Block]:
        specs: list[tuple[str, type[BaseModel], str]] = [
            ("read_sheet", ReadSheet, ReadSheet.__doc__ or ""),
            ("read_strip", ReadStrip, ReadStrip.__doc__ or ""),
            ("read_grade_preview", ReadGradePreview, ReadGradePreview.__doc__ or ""),
            ("read_transcript", ReadTranscript, ReadTranscript.__doc__ or ""),
            (
                "write_edl",
                Edl,
                "Hand back the finished edit list. Rejected with every problem listed, "
                "or accepted with craft warnings to fix or justify.",
            ),
        ]
        return [
            {
                "name": name,
                "description": " ".join(desc.split()),
                "strict": True,
                "input_schema": strict_schema(model.model_json_schema(by_alias=True)),
            }
            for name, model, desc in specs
        ]

    def run(self, name: str, raw: Any) -> Result:  # Any: tool input JSON from the model
        handlers: dict[str, Callable[[Any], Result]] = {
            "read_sheet": self._read_sheet,
            "read_strip": self._read_strip,
            "read_grade_preview": self._read_grade_preview,
            "read_transcript": self._read_transcript,
            "write_edl": self._write_edl,
        }
        handler = handlers.get(name)
        if handler is None:
            return _text(f"unknown tool {name!r}; the tools are {', '.join(handlers)}", True)
        try:
            return handler(raw)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            return _text(f"{name}: bad input: {problems}", True)
        except (MediaError, OSError, ValueError) as exc:  # a tool never raises into the loop
            return _text(f"{name} failed: {exc}", True)

    # ------------------------------------------------------------ images
    def _image(self, image: Image.Image, caption: str) -> Result:
        side, quality = (
            self.ctx.limits.sheets.max_image_side_px,
            self.ctx.media.contact_sheet.jpeg_quality,
        )
        return Result([image_block(image, side, quality), {"type": "text", "text": caption}])

    # ------------------------------------------------------------ handlers
    def _read_sheet(self, raw: Any) -> Result:  # Any: tool input JSON
        args = ReadSheet.model_validate(raw)
        ids = [Path(s).stem for s in self.ctx.shots.sheets]
        if args.sheet_id not in ids:
            return _text(f"unknown sheet_id {args.sheet_id!r}; valid ids: {', '.join(ids)}", True)
        number = ids.index(args.sheet_id) + 1
        legend = json.loads(
            (self.ctx.work / Path(self.ctx.shots.sheets[0]).parent / LEGEND).read_text(
                encoding="utf-8"
            )
        )
        lines = [
            f"tile {t['tile']}: {t['clip']} at {t['t']:.1f}s"
            for t in legend
            if t["sheet"] == number
        ]
        with Image.open(self.ctx.work / self.ctx.shots.sheets[number - 1]) as image:
            return self._image(image, f"{args.sheet_id}\n" + "\n".join(lines))

    def _clip(self, cid: str) -> Clip | Result:
        clip = self.ctx.shots.clip(cid)
        if clip is None:
            ids = ", ".join(c.id for c in self.ctx.shots.clips)
            return _text(f"unknown clip {cid!r}; valid clips: {ids}", True)
        return clip

    def _read_strip(self, raw: Any) -> Result:  # Any: tool input JSON
        args, limits = ReadStrip.model_validate(raw), self.ctx.limits.editor
        clip = self._clip(args.clip)
        if isinstance(clip, Result):
            return clip
        if not 0 <= args.start_s < args.end_s <= clip.duration + self.ctx.media.edl.out_tolerance_s:
            return _text(f"need 0 <= start_s < end_s <= {clip.duration:.2f} for {clip.id}", True)
        if args.end_s - args.start_s > limits.strip_max_seconds:
            return _text(
                f"a strip covers at most {limits.strip_max_seconds} s; ask for a shorter range",
                True,
            )
        if self.strips >= limits.max_strips:
            return _text(
                f"all {limits.max_strips} strips of this edit are used; decide from what you have",
                True,
            )
        self.strips += 1
        request = strip.Request(clip.as_proxy(), args.start_s, args.end_s)
        path = _render_strip(
            self.ctx.work, request, self.ctx.media, self.ctx.limits.sheets.max_image_side_px
        )
        with Image.open(path) as image:
            return self._image(image, f"{clip.id} {args.start_s:.2f}-{args.end_s:.2f}s")

    def _read_grade_preview(self, raw: Any) -> Result:  # Any: tool input JSON
        args, most = ReadGradePreview.model_validate(raw), self.ctx.limits.editor.max_grade_previews
        frames = None
        if args.frames is not None:
            frames = []
            for ref in args.frames:
                cid, sep, at = ref.partition(":")
                if not sep or self.ctx.shots.clip(cid) is None:
                    return _text(
                        f"frame {ref!r}: write frames as clip:time with a known clip, e.g. c01:2.5",
                        True,
                    )
                frames.append((cid, float(at)))
        if self.previews >= most:
            return _text(
                f"all {most} grade previews of this edit are used; pick a look from what you saw",
                True,
            )
        self.previews += 1
        image = _render_preview(self.ctx.work, self.ctx.shots, frames, self.ctx)
        return self._image(image, "columns: original, then each look at the default strength")

    def _read_transcript(self, raw: Any) -> Result:  # Any: tool input JSON
        args = ReadTranscript.model_validate(raw)
        if not self.ctx.voice:
            return _text("no transcript for this order: the voice is off", True)
        clip = self._clip(args.clip)
        if isinstance(clip, Result):
            return clip
        path = self.ctx.work / "transcript" / f"{clip.id}.txt"
        if not path.exists():
            return _text(f"no transcript for {clip.id}: it has no speech", True)
        return _text(path.read_text(encoding="utf-8"))

    def _write_edl(self, raw: Any) -> Result:  # Any: tool input JSON
        report = edl.validate(raw, self.ctx.shots, self.ctx.media, self.ctx.order_style)
        if report.errors or report.edl is None:
            return _text(
                "edit list rejected; fix every problem and call write_edl again:\n- "
                + "\n- ".join(report.errors),
                True,
            )
        self.accepted, self.warnings = report.edl, report.warnings
        notes = "\n- ".join(report.warnings)
        return _text(
            "accepted" + (f" with warnings (fix or justify in note):\n- {notes}" if notes else "")
        )
