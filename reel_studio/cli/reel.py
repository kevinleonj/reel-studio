"""`reel`: the command line (render arrives in STEP-02, make in STEP-03).

    reel render --edl <edl.json> <folder> [--out <dir>]

Prepares the folder's clips, checks the hand-written edit list against them, renders text.mp4
and clean.mp4 and writes qa.json, all into --out. The folder is only read (D02); proxies, sheets
and review images go to <out>/work. Exit codes: 0 rendered and every hard check passed,
1 rendered but a hard check failed, or ffmpeg failed; 2 bad arguments, an EDL with errors, or a
folder with nothing usable in it.
"""

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from reel_studio.core import config
from reel_studio.core.errors import NoUsableInput, ReelError
from reel_studio.core.logging import configure, get_logger
from reel_studio.editor.media import edl, pipeline, qa, render
from reel_studio.editor.media.tools import Ffmpeg
from reel_studio.settings import EditorSettings

log = get_logger(__name__)

STAGE = "cli"
OK, FAILED, BAD_INPUT = 0, 1, 2
WORK = "work"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reel", description="Turn a folder of food clips into an Instagram Reel."
    )
    commands = parser.add_subparsers(dest="command")
    cmd = commands.add_parser("render", help="render a Reel from a hand-written edit list")
    cmd.add_argument("--edl", required=True, type=Path, help="edit list (JSON)")
    cmd.add_argument("folder", type=Path, help="folder of clips and photos; only read")
    cmd.add_argument("--out", type=Path, help="output folder (default: <folder>-reel beside it)")
    return parser


def default_out(folder: Path) -> Path:
    """Beside the input folder, never inside it (D02); `.` is named after the real folder."""
    real = folder.resolve()
    return real.with_name(f"{real.name}-reel")


def _same(a: Path, b: Path) -> bool:
    return os.path.exists(a) and os.path.exists(b) and os.path.samefile(a, b)


def _overlaps(folder: Path, out: Path) -> bool:
    """True when the run would write into `folder` (D02): `out/work` is the folder, inside it,
    or holds it (a previous run's clips/ used as input). Compares files, not spellings
    (`os.path.samefile`), since a case-insensitive volume lets `IN/out` past `in`. A path that
    cannot be checked counts as overlapping.
    """
    work = out / WORK
    try:
        upward = any(_same(c, folder) for c in (work, *work.parents))
        downward = any(_same(work, c) for c in (folder, *folder.parents))
    except OSError:  # an ancestor we may not search: refuse rather than guess
        return True
    return upward or downward


def _bad(message: str) -> int:
    log.error("%s", message, extra={"stage": STAGE, "event": "bad_input", "outcome": "refused"})
    return BAD_INPUT


def _edl_errors(errors: list[str]) -> int:
    for error in errors:
        log.error("EDL: %s", error, extra={"stage": STAGE, "event": "edl_error"})
    return BAD_INPUT


def render_command(args: argparse.Namespace, settings: EditorSettings) -> int:
    folder: Path = args.folder.resolve()
    if not folder.is_dir():
        return _bad(f"input folder not found: {folder}")
    out: Path = (args.out if args.out is not None else default_out(folder)).resolve()
    if _overlaps(folder, out):
        return _bad(f"--out {out} is inside the input folder; the folder is only read (D02)")
    try:
        raw = json.loads(args.edl.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # ValueError: bad JSON or not UTF-8
        return _bad(f"edit list unreadable: {exc}")
    media, limits = config.load_media(), config.load().limits.sheets
    early = edl.precheck(raw, media)  # before minutes of ffmpeg work
    if early:
        return _edl_errors(early)
    ffmpeg = Ffmpeg(settings.ffmpeg_path, settings.ffprobe_path, media.tools)
    work = out / WORK
    shots = pipeline.build_shots(folder, work, ffmpeg, media, limits)
    report = edl.validate(raw, shots, media)
    for warning in report.warnings:
        log.warning("EDL: %s", warning, extra={"stage": STAGE, "event": "edl_warning"})
    if report.errors or report.edl is None:
        return _edl_errors(report.errors)
    job = render.Job(work=work, input_dir=folder, out_dir=out, ffmpeg=ffmpeg, media=media)
    timeline = render.render(job, shots, report.edl)
    result = qa.run(job, timeline, limits.max_image_side_px)
    for line in result.lines:
        log.info("QA %s", line, extra={"stage": STAGE, "event": "qa"})
    passed = all(result.hard_checks.model_dump().values())
    log.info(
        "wrote %s",
        out,
        extra={"stage": STAGE, "event": "done", "outcome": "ok" if passed else "qa_failed"},
    )
    return OK if passed else FAILED


def main(argv: Sequence[str] | None = None, settings: EditorSettings | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "render":
        parser.print_help()
        return OK
    configure()
    try:
        return render_command(args, settings if settings is not None else EditorSettings())
    except NoUsableInput as exc:  # nothing in the folder could be read: the input is the problem
        log.error("%s", exc, extra={"stage": STAGE, "event": "failed", "outcome": exc.code})
        return BAD_INPUT
    except ReelError as exc:
        log.exception(
            "%s", type(exc).__name__, extra={"stage": STAGE, "event": "failed", "outcome": exc.code}
        )
        return FAILED
