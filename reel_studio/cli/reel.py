"""`reel`: the command line (render arrives in STEP-02, make in STEP-03).

    reel render --edl <edl.json> <folder> [--out <dir>]
    reel make <folder> --style <style> [--length <s>] [--text-lang <code>] [--voice on|off]
              [--out <dir>]

`render` prepares the folder's clips, checks the hand-written edit list against them, renders
text.mp4 and clean.mp4 and writes qa.json, all into --out. `make` has Claude write the edit list
on your own key, renders, has the critic judge it, and writes ./out/<name>/ (or --out). The folder
is only read (D02); proxies, sheets and review images go to <out>/work. Exit codes: 0 rendered and
every hard check passed, 1 rendered but a hard check failed, ffmpeg failed or the model stopped;
2 bad arguments, an EDL with errors, a folder with nothing usable in it, or a style whose prompts
are not written yet.
"""

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from reel_studio.core import config
from reel_studio.core.errors import NoUsableInput, ProviderError, ReelError
from reel_studio.core.logging import configure, get_logger
from reel_studio.editor import critic, make, prompt
from reel_studio.editor.media import edl, pipeline, qa, render
from reel_studio.editor.media.tools import Ffmpeg
from reel_studio.settings import EditorSettings

log = get_logger(__name__)

STAGE = "cli"
OK, FAILED, BAD_INPUT = 0, 1, 2
WORK = "work"
OUT = "out"  # `reel make` writes ./out/<name>/ by default (STEP-03 task 7)
VOICE = {"on": True, "off": False}
NO_KEY_NOTICE = "No Gemini key: natural sound only, no transcription."  # EDITOR.md §5, D14


@dataclass(frozen=True)
class Deps:
    """What `make` reaches outside the process; tests pass fakes, a real run the defaults."""

    ports: Callable[[EditorSettings], make.Ports]
    steps: Callable[[Path, EditorSettings], make.Steps]
    on_request: Callable[[make.Request], None] = lambda request: None


def real_deps() -> Deps:
    def ports(settings: EditorSettings) -> make.Ports:
        # Imported here so `reel render` and `--help` never load the SDK.
        from reel_studio.adapters.claude import client  # noqa: PLC0415
        from reel_studio.adapters.clock import SystemClock  # noqa: PLC0415

        editor = config.load().limits.editor
        claude = client.connect(settings.anthropic_api_key, config.load_claude(), editor)
        return make.Ports(claude, SystemClock())

    def steps(folder: Path, settings: EditorSettings) -> make.Steps:
        media = config.load_media()
        ffmpeg = Ffmpeg(settings.ffmpeg_path, settings.ffprobe_path, media.tools)
        return make.media_steps(folder, ffmpeg, media, config.load())

    return Deps(ports=ports, steps=steps)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reel", description="Turn a folder of food clips into an Instagram Reel."
    )
    commands = parser.add_subparsers(dest="command")
    cmd = commands.add_parser("render", help="render a Reel from a hand-written edit list")
    cmd.add_argument("--edl", required=True, type=Path, help="edit list (JSON)")
    cmd.add_argument("folder", type=Path, help="folder of clips and photos; only read")
    cmd.add_argument("--out", type=Path, help="output folder (default: <folder>-reel beside it)")
    cfg = config.load()
    order = cfg.limits.order
    languages = [lang.code for lang in cfg.styles.text_languages.items]
    commands.add_parser("job", help="run one order on Cloud Run (the reel-editor job)")
    cmd = commands.add_parser("make", help="edit a Reel with Claude on your own key")
    cmd.add_argument("folder", type=Path, help="folder of clips and photos; only read")
    cmd.add_argument("--style", required=True, choices=list(cfg.styles.styles))
    cmd.add_argument("--length", type=int, choices=order.lengths_s, default=order.default_length_s)
    cmd.add_argument("--text-lang", choices=languages, default=languages[0])
    cmd.add_argument("--voice", choices=list(VOICE), help="default: the style's own")
    cmd.add_argument("--out", type=Path, help=f"output folder (default: ./{OUT}/<folder name>)")
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
    (`os.path.samefile`), since a case-insensitive volume lets `IN/out` past `in`.
    """
    work = out / WORK
    upward = any(_same(c, folder) for c in (work, *work.parents))
    downward = any(_same(work, c) for c in (folder, *folder.parents))
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
        return _bad(
            f"--out {out} and the input folder {folder} overlap (one holds the other's work/); "
            "the input folder is only read (D02): pick an --out beside it"
        )
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


def _say(line: str) -> None:
    """The person's summary on stdout; log lines stay machine-readable JSON."""
    sys.stdout.write(line + "\n")


def _voice(args: argparse.Namespace, settings: EditorSettings) -> bool:
    style = config.load().styles.styles[args.style]
    wanted = VOICE[args.voice] if args.voice is not None else style.voice_default
    if settings.gemini_api_key is None:  # one Claude key is enough to run Reel Studio (D14)
        _say(NO_KEY_NOTICE)
        return False
    return wanted


def make_command(args: argparse.Namespace, settings: EditorSettings, deps: Deps) -> int:
    cfg = config.load()
    folder: Path = args.folder.resolve()
    if not folder.is_dir():
        return _bad(f"input folder not found: {folder}")
    if args.style not in prompt.available_styles(cfg):
        return _bad(f"style {args.style} is not available yet: {prompt.available_styles(cfg)}")
    out: Path = (args.out if args.out is not None else Path.cwd() / OUT / folder.name).resolve()
    if _overlaps(folder, out):
        return _bad(f"--out {out} overlaps the input folder {folder}; it is only read (D02)")
    order = prompt.OrderSettings(args.style, args.length, args.text_lang, _voice(args, settings))
    request = make.Request(folder=folder, out=out, order=order)
    deps.on_request(request)
    made = make.make(request, deps.ports(settings), deps.steps(folder, settings), cfg)
    final = made.final
    verdict = "passed" if final.passed else f"not passed: {final.weakness}"
    total = final.review.total if final.review is not None else "-"
    _say(f"Reel: {out / render.TEXT} | {out / render.CLEAN}")
    _say(f"Critic: {total}/{critic.TOTAL_MAX}, {verdict} ({made.renders} renders)")
    _say(f"Cost: ${made.cost}")
    return OK if all(final.render.qa.hard_checks.model_dump().values()) else FAILED


def _job_or_help(command: str | None, parser: argparse.ArgumentParser) -> int:
    if command == "job":
        from reel_studio.cli import job  # noqa: PLC0415 (Cloud Run only: the cloud clients)

        return job.main()
    parser.print_help()
    return OK


def main(
    argv: Sequence[str] | None = None,
    settings: EditorSettings | None = None,
    deps: Deps | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command not in ("render", "make"):
        return _job_or_help(args.command, parser)
    configure()
    settings = settings if settings is not None else EditorSettings()
    try:
        if args.command == "make":
            return make_command(args, settings, deps if deps is not None else real_deps())
        return render_command(args, settings)
    except NoUsableInput as exc:  # nothing in the folder could be read: the input is the problem
        log.error("%s", exc, extra={"stage": STAGE, "event": "failed", "outcome": exc.code})
        return BAD_INPUT
    except ProviderError as exc:  # the provider's own words say what to fix: no traceback
        log.error("%s", exc, extra={"stage": STAGE, "event": "failed", "outcome": exc.code})
        return FAILED
    except ReelError as exc:
        log.exception(
            "%s", type(exc).__name__, extra={"stage": STAGE, "event": "failed", "outcome": exc.code}
        )
        return FAILED
