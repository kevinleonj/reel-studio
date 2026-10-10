"""What Claude reads (docs/EDITOR.md §2, §6): the system prompts and the first user message.

The editor's system prompt is the same bytes for every call of a run, so it is cached (D34): it
is built only from files in `prompts/` and from config, never from the order. The order goes in
the brief. Sources: `system/editor.md` is the kit's `make-reel/SKILL.md` rewritten for tools;
`references/` are the kit's references with script steps replaced by tools; `critic.md` is the
kit's `agents/reel-critic.md`.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from string import Template

from jinja2 import Environment, PackageLoader, StrictUndefined

from reel_studio.core.config import Config
from reel_studio.editor.critic import TOTAL_MAX
from reel_studio.editor.media.shots import Shots

PROMPTS = Path(__file__).parent / "prompts"
REFERENCES = ("creator-mindset", "formats", "craft", "colour", "edl-schema", "qa-rubric")
CRITIC_REFERENCES = ("qa-rubric", "colour")
NO_VALUE = "-"
FENCE_ESCAPES = {"<": "&lt;", ">": "&gt;"}  # the note can never close <customer_preferences>

_templates = Environment(
    loader=PackageLoader("reel_studio.editor", "prompts"),
    undefined=StrictUndefined,  # a missing field is a bug, not an empty line
    # Markdown for a model, never served as HTML; customer text is fenced by _fenced instead.
    autoescape=False,  # noqa: S701
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


@dataclass(frozen=True)
class OrderSettings:
    style: str
    length_s: int
    text_lang: str  # a code from styles.toml [text_languages]
    voice: bool
    chips: tuple[str, ...] = ()
    note: str | None = None


def _read(*parts: str) -> str:
    return (PROMPTS.joinpath(*parts)).read_text(encoding="utf-8").strip()


def _reference(name: str, cfg: Config) -> str:
    text = _read("references", f"{name}.md")
    if name != "qa-rubric":
        return text
    gates, editor = cfg.limits.gates, cfg.limits.editor
    return Template(text).substitute(
        hook_min=gates.hook_min,
        category_min=gates.category_min,
        total_min=gates.total_min,
        total_max=TOTAL_MAX,
        max_renders=editor.max_renders,
    )


def _files(style: str, cfg: Config) -> tuple[Path, Path]:
    chosen = cfg.styles.styles.get(style)
    if chosen is None:
        raise ValueError(f"unknown style {style!r}")
    return (
        PROMPTS / "styles" / f"{chosen.skill}.md",
        PROMPTS / "structures" / f"{chosen.structure}.md",
    )


def available_styles(cfg: Config) -> list[str]:
    """Styles whose prompt files exist; the others arrive with their own step."""
    return [s for s in cfg.styles.styles if all(p.is_file() for p in _files(s, cfg))]


def system_prompt(style: str, cfg: Config) -> str:
    if style not in available_styles(cfg):
        raise ValueError(f"no prompt for style {style!r}; available: {available_styles(cfg)}")
    skill, structure = _files(style, cfg)
    parts = [_read("system", "editor.md"), _read("styles", skill.name)]
    parts += [_read("structures", structure.name)]
    parts += [_reference(name, cfg) for name in REFERENCES]
    return "\n\n".join(parts) + "\n"


def critic_prompt(cfg: Config) -> str:
    parts = [_read("critic.md")] + [_reference(name, cfg) for name in CRITIC_REFERENCES]
    return "\n\n".join(parts) + "\n"


def _fenced(text: str) -> str:
    for raw, safe in FENCE_ESCAPES.items():
        text = text.replace(raw, safe)
    return text


def _clip_rows(shots: Shots) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for clip in shots.clips:
        windows = [w for w in shots.windows if w.clip == clip.id]
        best = max(windows, key=lambda w: w.sharpness) if windows else None
        rows.append(
            {
                "id": clip.id,
                "kind": clip.kind,
                "duration": clip.duration,
                "fps": clip.proxy_fps,
                "orientation": clip.orientation,
                "sharpest": f"{best.start:.2f}-{best.end:.2f}" if best else NO_VALUE,
                "motion": f"{fmean(w.motion for w in windows):.1f}" if windows else NO_VALUE,
            }
        )
    return rows


def brief(order: OrderSettings, cfg: Config, shots: Shots, transcripts: dict[str, str]) -> str:
    """The first user message: the order, the inventory, the sheets, and the fenced wishes."""
    languages = {lang.code: lang.label for lang in cfg.styles.text_languages.items}
    return _templates.get_template("brief.md.j2").render(
        style=order.style,
        style_label=cfg.styles.styles[order.style].label,
        length_s=order.length_s,
        text_lang=languages[order.text_lang],
        voice=order.voice,
        clips=_clip_rows(shots),
        total_s=shots.total_raw_seconds,
        sheets=[Path(s).stem for s in shots.sheets],
        transcripts=transcripts,
        chips=[_fenced(c) for c in order.chips],
        note=json.dumps(_fenced(order.note), ensure_ascii=False) if order.note else None,
    )
