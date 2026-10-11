"""One order, end to end (docs/EDITOR.md §3, §6): prepare, plan, render, judge, revise, ship.

Everything outside this process comes in through `Ports` (the model, the clock) and `Steps` (the
media pipeline), so the whole flow runs in tests with fakes. The editor and the critic share one
meter, so the cost cap covers every call of the order (D37). Each render goes to its own folder
under work/renders/; only the shipped one is copied to the top of `out`.
"""

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from reel_studio.core import config, ports
from reel_studio.core.config import Config
from reel_studio.core.errors import ModelRefusal
from reel_studio.core.logging import get_logger
from reel_studio.core.media_config import Media
from reel_studio.editor import critic, loop, prompt
from reel_studio.editor.media import pipeline, qa, render
from reel_studio.editor.media.edl_models import Edl
from reel_studio.editor.media.shots import Shots
from reel_studio.editor.media.tools import Ffmpeg
from reel_studio.editor.meter import Meter
from reel_studio.editor.tools import Context, Toolbox

log = get_logger(__name__)

STAGE = "make"
WORK, RENDERS, REVIEW = "work", "renders", "review"
EDL_JSON, RESULT_JSON, REQUESTS = "edl.json", "result.json", "requests.jsonl"


@dataclass(frozen=True)
class Rendered:
    folder: Path  # holds text.mp4, clean.mp4, qa.json and review/ of this render
    timeline: render.Timeline
    qa: qa.QaResult


@dataclass(frozen=True)
class Steps:
    prepare: Callable[[Path, Path], Shots]  # (input folder, work) -> shots
    render: Callable[[Path, Shots, Edl], Rendered]  # (render folder, shots, edl) -> files + QA


@dataclass(frozen=True)
class Ports:
    claude: ports.Claude
    clock: ports.Clock


@dataclass(frozen=True)
class Request:
    folder: Path  # only read (D02)
    out: Path
    order: prompt.OrderSettings


@dataclass(frozen=True)
class Made:
    out: Path
    final: critic.Final[Rendered]
    renders: int
    cost: Decimal
    edl: Edl
    warnings: list[str]  # write_edl's craft warnings for the shipped edit list
    reviews: list[dict[str, Any]]  # Any: JSON; every render's review, shipped or not


def media_steps(folder: Path, ffmpeg: Ffmpeg, media: Media, cfg: Config) -> Steps:
    """The real pipeline from STEP-02."""
    max_side = cfg.limits.sheets.max_image_side_px

    def _render(out_dir: Path, shots: Shots, edl: Edl) -> Rendered:
        work = out_dir.parent.parent
        job = render.Job(work=work, input_dir=folder, out_dir=out_dir, ffmpeg=ffmpeg, media=media)
        timeline = render.render(job, shots, edl)
        return Rendered(out_dir, timeline, qa.run(job, timeline, max_side))

    return Steps(
        prepare=lambda src, work: pipeline.build_shots(src, work, ffmpeg, media, cfg.limits.sheets),
        render=_render,
    )


def _keep_sheets(rendered: Rendered) -> list[Path]:
    """QA writes every render's sheets to one review/ folder: copy them beside their render."""
    kept = rendered.folder / REVIEW
    kept.mkdir(parents=True, exist_ok=True)
    out = []
    for sheet in rendered.qa.sheets:
        source = Path(sheet) if Path(sheet).is_absolute() else rendered.folder / sheet
        out.append(Path(shutil.copy2(source, kept / source.name)))
    return out


def _timeline_lines(timeline: render.Timeline) -> str:
    rows = [
        f"seg {s.i} {s.role} {s.start:.2f}-{s.end:.2f}s clip {s.clip} {s.in_:.2f}-{s.out:.2f}"
        f" x{s.speed:g} {s.note}".rstrip()
        for s in timeline.segments
    ]
    rows += [
        f"text {t.kind} {t.start:.2f}-{t.end:.2f}s {t.position}: {t.text}" for t in timeline.text
    ]
    return "\n".join(rows)


def _order_line(order: prompt.OrderSettings) -> str:
    voice = "kept" if order.voice else "off"
    return f"style {order.style}, {order.length_s} s, text {order.text_lang}, voice {voice}"


def _ship(request: Request, made: Made, meter: Meter) -> None:
    out, final = request.out, made.final
    for name in (render.TEXT, render.CLEAN, qa.QA_JSON):
        shutil.copy2(final.render.folder / name, out / name)
    shutil.copytree(final.render.folder / REVIEW, out / REVIEW, dirs_exist_ok=True)
    edl_json = made.edl.model_dump_json(by_alias=True, indent=1)
    (out / EDL_JSON).write_text(edl_json, encoding="utf-8")
    review = final.review
    record = {
        "style": request.order.style,
        "cost_usd": str(meter.spent),
        "cost_by_model": {k: str(v) for k, v in meter.by_model.items()},
        "critic": {
            "total": review.total if review is not None else None,
            "passed": final.passed,
            "scores": review.scores() if review is not None else {},
            "weakness": final.weakness,
            "verdict": review.verdict if review is not None else None,
            "major": [i.model_dump() for i in review.major] if review is not None else [],
        },
        "reviews": made.reviews,
        "hard_checks_passed": all(final.render.qa.hard_checks.model_dump().values()),
        "edl_warnings": made.warnings,
    }
    (out / RESULT_JSON).write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")


def make(request: Request, ports_: Ports, steps: Steps, cfg: Config) -> Made:
    """Run one order; raises CostCapReached, ModelRefusal or OutputTooLong as the loop does."""
    limits, media = cfg.limits, config.load_media()
    work = request.out / WORK
    request.out.mkdir(parents=True, exist_ok=True)
    shots = steps.prepare(request.folder, work)
    meter = Meter(cfg.prices, limits.editor.cost_cap_usd)
    session = loop.Session(
        ports_.claude, meter, ports_.clock, request.out / REQUESTS, limits.editor
    )
    critic_session = replace(session, call="critic")
    box = Toolbox(
        Context(
            work, request.folder, shots, media, limits, request.order.style, request.order.voice
        )
    )
    system = prompt.system_prompt(request.order.style, cfg)
    judge_system = prompt.critic_prompt(cfg)
    history: list[loop.Message] = []
    edls: list[Edl] = []
    warned: list[list[str]] = []
    reviews: list[dict[str, Any]] = []  # Any: JSON

    def plan(feedback: str | None) -> Edl:
        opening = (
            feedback if feedback is not None else prompt.brief(request.order, cfg, media, shots, {})
        )
        outcome = loop.run(session, box, system, opening, history if feedback is not None else None)
        if outcome.edl is None:
            raise ModelRefusal("the loop ended without an edit list")
        history[:] = outcome.messages
        edls.append(outcome.edl)
        warned.append(list(outcome.warnings))
        return outcome.edl

    def render_one(edl: Edl, number: int) -> Rendered:
        return steps.render(work / RENDERS / str(number), shots, edl)

    def judge(rendered: Rendered) -> critic.Review:
        material = critic.Material(
            sheets=_keep_sheets(rendered),
            qa_lines=rendered.qa.lines,
            timeline=_timeline_lines(rendered.timeline),
            order=_order_line(request.order),
        )
        quality = media.contact_sheet.jpeg_quality
        review = critic.critique(
            critic_session, judge_system, material, limits.sheets.max_image_side_px, quality
        )
        ok, why = critic.passes(review, limits.gates)
        reviews.append(
            {
                "render": int(rendered.folder.name),
                "total": review.total,
                "passed": ok,
                "scores": review.scores(),
                "weakness": why if not ok else None,
                "major": [i.model_dump() for i in review.major],
            }
        )
        return review

    final = critic.review_cycle(plan, render_one, judge, limits.gates, limits.editor.max_renders)
    number = int(final.render.folder.name) - 1
    made = Made(request.out, final, len(edls), meter.spent, edls[number], warned[number], reviews)
    _ship(request, made, meter)
    log.info(
        "shipped render %s, critic %s, cost %s",
        final.render.folder.name,
        final.review.total if final.review is not None else "not judged",
        meter.spent,
        extra={"stage": STAGE, "event": "shipped", "outcome": "passed" if final.passed else "weak"},
    )
    return made
