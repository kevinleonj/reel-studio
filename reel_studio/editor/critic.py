"""The critic (D36, docs/EDITOR.md §6): a fresh call that scores a render; the gates live here.

The critic sees only what a viewer would: the three review sheets, the QA lines, the timeline
and the order. Never the editor's conversation. Its scores come back through the strict tool
`submit_review`; the score bound is stripped from the schema (F208) and checked on the way in.
A failed render goes back to the editor once with the issues; after `max_renders` the higher
total ships and the failed gate is named.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from reel_studio.core import constants
from reel_studio.core.config import Gates
from reel_studio.core.errors import ModelRefusal
from reel_studio.editor.loop import Session, call_claude
from reel_studio.editor.tools import image_block, strict_schema

TOOL = "submit_review"
NUDGE = f"Call {TOOL} with your scores."
CATEGORIES = ("hook", "retention", "story", "peak", "craft", "share", "colour")  # qa-rubric.md


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Score(_Model):
    score: int = Field(ge=constants.CRITIC_SCORE_MIN, le=constants.CRITIC_SCORE_MAX)
    evidence: str = Field(description="The tile or timestamp that shows it, e.g. 'hook 0.50s'.")


class Issue(_Model):
    where: str = Field(description="Sheet and tile or timestamp.")
    problem: str
    fix: str = Field(description="A change the editor can make: clip, in/out, text or order.")


class Review(_Model):
    hook: Score
    retention: Score
    story: Score
    peak: Score
    craft: Score
    share: Score
    colour: Score
    major: list[Issue]
    minor: list[Issue]
    works: list[str]
    verdict: str

    @property
    def total(self) -> int:
        return sum(self.scores().values())

    def scores(self) -> dict[str, int]:
        return {name: getattr(self, name).score for name in CATEGORIES}


@dataclass(frozen=True)
class Material:
    sheets: list[Path]  # hook, cuts, overview
    qa_lines: list[str]
    timeline: str
    order: str


@dataclass(frozen=True)
class Final[R]:
    render: R
    review: Review
    passed: bool
    weakness: str | None  # the failed gates of the shipped render


def passes(review: Review, gates: Gates) -> tuple[bool, str]:
    """D36 in code: hook >= hook_min, no category below category_min, total >= total_min."""
    failed = []
    scores = review.scores()
    if scores["hook"] < gates.hook_min:
        failed.append(f"hook {scores['hook']} < {gates.hook_min}")
    failed += [
        f"{name} {value} < {gates.category_min}"
        for name, value in scores.items()
        if value < gates.category_min and name != "hook"
    ]
    if review.total < gates.total_min:
        failed.append(f"total {review.total} < {gates.total_min}")
    return not failed, "; ".join(failed)


def feedback(review: Review, why: str) -> str:
    """What goes back to the editor after a failed render: the failed gates and every issue."""
    lines = [f"The critic failed this render: {why}."]
    for label, issues in (("Major", review.major), ("Minor", review.minor)):
        lines += [f"{label}: {i.where}: {i.problem} Fix: {i.fix}" for i in issues]
    lines.append("Revise the edit list and call write_edl.")
    return "\n".join(lines)


def review_cycle[E, R](
    plan: Callable[[str | None], E],
    render: Callable[[E, int], R],
    judge: Callable[[R], Review],
    gates: Gates,
    max_renders: int,
) -> Final[R]:
    """Plan, render, judge; revise on a fail until `max_renders`; ship the higher total."""
    tried: list[tuple[R, Review, str]] = []
    note: str | None = None
    for number in range(1, max_renders + 1):
        rendered = render(plan(note), number)
        review = judge(rendered)
        ok, why = passes(review, gates)
        if ok:
            return Final(rendered, review, True, None)
        tried.append((rendered, review, why))
        note = feedback(review, why)
    best = max(tried, key=lambda t: t[1].total)  # max keeps the first on a tie
    return Final(best[0], best[1], False, best[2])


def tool_definition() -> dict[str, Any]:  # Any: JSON Schema
    return {
        "name": TOOL,
        "description": "Submit the scores, issues and verdict for this render.",
        "input_schema": strict_schema(Review.model_json_schema()),
        "strict": True,
    }


def _content(material: Material, max_side: int, quality: int) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []  # Any: content blocks
    for sheet in material.sheets:
        with Image.open(sheet) as image:
            blocks.append(image_block(image, max_side, quality))
        blocks.append({"type": "text", "text": f"Sheet: {sheet.stem}"})
    facts = [
        "Order: " + material.order,
        "Timeline:\n" + material.timeline,
        "QA:\n" + "\n".join(material.qa_lines),
        f"Score the render and call {TOOL}.",
    ]
    blocks.append({"type": "text", "text": "\n\n".join(facts)})
    return blocks


def critique(
    session: Session, system: str, material: Material, max_side: int, quality: int
) -> Review:
    """One fresh conversation that must end in a valid review.

    `tool_choice` stays `auto` (forcing a tool is a 400 on Sonnet 5.5: D35, F10), so a reply in
    plain text gets one nudge; a second one, or any other stop, fails the order.
    """
    editor = session.editor
    messages: list[dict[str, Any]] = [  # Any: content blocks
        {"role": "user", "content": _content(material, max_side, quality)}
    ]
    for turn in (1, 2):
        request = {
            "model": editor.critic_model,
            "max_tokens": editor.max_tokens,
            "system": system,
            "messages": messages,
            "tools": [tool_definition()],
            "tool_choice": {"type": "auto"},
            "cache_control": {"type": "ephemeral"},  # D34, F07
            "output_config": {"effort": editor.effort},  # D33
        }
        reply = call_claude(session, request, turn)
        uses = [b for b in reply.get("content", []) if b.get("type") == "tool_use"]
        if uses:
            try:
                return Review.model_validate(uses[0].get("input"))
            except ValidationError as exc:
                raise ModelRefusal(f"critic review invalid: {exc.error_count()} errors") from exc
        if reply.get("stop_reason") != "end_turn":
            raise ModelRefusal(f"critic stopped with {reply.get('stop_reason')}")
        messages = [
            *messages,
            {"role": "assistant", "content": reply.get("content", [])},
            {"role": "user", "content": NUDGE},
        ]
    raise ModelRefusal("critic gave no review after a nudge")
