"""`make eval FIX=<name> [MODEL=haiku]` (STEP-03 task 8): one fixture through `make`, on record.

The result goes to eval/results/<date>/<fixture>-<model>.json, which is committed and read by
the step gates (scripts/gates/_gate.py `eval_evidence`). Its cost and token counts come from the
run's requests.jsonl, so a run that fails half-way still records what it spent. The fixture
folder is only read (D02); the Reel and its work files go to out/eval/<date>/, which git ignores.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from reel_studio.core import config
from reel_studio.core.config import Config
from reel_studio.core.errors import ReelError
from reel_studio.core.logging import configure, get_logger
from reel_studio.editor import make, prompt
from reel_studio.editor.media import render
from reel_studio.editor.media.tools import Ffmpeg
from reel_studio.settings import BuildSettings, EditorSettings

log = get_logger(__name__)

STAGE = "eval"
ROOT = Path(__file__).resolve().parents[2]
RESULTS = Path("eval") / "results"
OUT = Path("out") / "eval"
OK, FAILED = 0, 1
MODELS = ("sonnet", "haiku")  # the gate's file names: <fixture>-<model>.json
DEFAULT_STYLE = "montage"
USAGE_FIELDS = {  # requests.jsonl field -> the result's field (the API's usage names)
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_read": "cache_read_input_tokens",
    "cache_write": "cache_creation_input_tokens",
}


@dataclass(frozen=True)
class Job:
    fixture: str
    model: str  # sonnet | haiku
    fixtures: Path  # REEL_FIXTURES_DIR
    root: Path  # the repository: results and outputs are written under it
    style: str


def for_eval(cfg: Config, model: str) -> Config:
    """`haiku` runs the editor and the critic on the cheap model (plumbing, D32); `sonnet` keeps
    limits.toml's models. Either way the order's cap drops to the eval run cap."""
    if model not in MODELS:
        raise ValueError(f"unknown model {model!r}; choose one of {MODELS}")
    editor = cfg.limits.editor
    cap = min(editor.cost_cap_usd, cfg.limits.eval.run_cap_usd)
    change: dict[str, object] = {"cost_cap_usd": cap}
    if model == "haiku":
        change.update(model=editor.cheap_model, critic_model=editor.cheap_model)
    limits = cfg.limits.model_copy(update={"editor": editor.model_copy(update=change)})
    return cfg.model_copy(update={"limits": limits})


def _calls(requests: Path) -> tuple[list[dict[str, int]], list[dict[str, int]], Decimal]:
    """Editor calls, critic calls and the total cost, from the run's requests.jsonl."""
    editor: list[dict[str, int]] = []
    critic: list[dict[str, int]] = []
    cost = Decimal(0)
    lines = requests.read_text(encoding="utf-8").splitlines() if requests.is_file() else []
    for line in lines:
        call: dict[str, Any] = json.loads(line)  # Any: one requests.jsonl record
        cost += Decimal(call["cost_usd"])
        usage = {name: int(call[field]) for field, name in USAGE_FIELDS.items()}
        (critic if call["call"] == "critic" else editor).append(usage)
    return editor, critic, cost


def _record(
    job: Job, out: Path, made: make.Made | None, error: str | None, now: datetime
) -> dict[str, Any]:
    editor, critic_calls, cost = _calls(out / make.REQUESTS)
    scores: dict[str, int] = {}
    if made is not None:
        final = made.final
        critic = {"total": final.review.total, "passed": final.passed, "weakness": final.weakness}
        scores = final.review.scores()
    else:
        critic = {"total": 0, "passed": False, "weakness": None}
    relative = out.relative_to(job.root)
    return {
        "fixture": job.fixture,
        "started": now.isoformat(),
        "model": job.model,
        "style": job.style,
        "cost_usd": float(cost),  # exact: every call's cost has far fewer than 15 digits
        "critic": critic,
        "scores": scores,
        "renders": made.renders if made is not None else 0,
        "error": error,
        "requests": editor,
        "critic_requests": critic_calls,
        "outputs": {
            "text": str(relative / render.TEXT),
            "clean": str(relative / render.CLEAN),
        },
    }


def _keep_earlier(target: Path) -> None:
    """Never overwrite a result: an earlier run's file keeps its cost under a stamped name, so
    the gate's branch budget check (results_budget) still sums it."""
    if not target.exists():
        return
    earlier = json.loads(target.read_text(encoding="utf-8"))
    stamp = datetime.fromisoformat(earlier["started"])
    target.rename(target.with_name(f"{target.stem}-{stamp:%H%M%S}{target.suffix}"))


def _write(job: Job, out: Path, made: make.Made | None, error: str | None, now: datetime) -> None:
    record = _record(job, out, made, error, now)
    target = job.root / RESULTS / now.date().isoformat() / f"{job.fixture}-{job.model}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    _keep_earlier(target)
    target.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    critic, scores = record["critic"], record["scores"]
    sys.stdout.write(
        f"{job.fixture} with {job.model}: cost ${record['cost_usd']}, critic {critic['total']}"
        f" passed={critic['passed']} {scores}, error={error}\nresult: {target}\nreel: {out}\n"
    )


def run(job: Job, ports: make.Ports, steps: make.Steps, cfg: Config) -> int:
    """Run `make` on the fixture and write the result file; 0 when a Reel was shipped.

    Any failure still writes the file with what was spent; one that is not a ReelError (a bug,
    a bad request) is raised after that."""
    chosen = for_eval(cfg, job.model)
    folder = job.fixtures / job.fixture
    if not folder.is_dir():
        raise ValueError(f"no fixture folder {folder}")
    now = ports.clock.now()
    out = job.root / OUT / now.date().isoformat() / f"{job.fixture}-{job.model}-{now:%H%M%S}"
    order = prompt.OrderSettings(
        style=job.style,
        length_s=cfg.limits.order.default_length_s,
        text_lang=cfg.styles.text_languages.items[0].code,
        voice=False,  # transcription arrives in STEP-05
    )
    made: make.Made | None = None
    error: str | None = None
    try:
        made = make.make(make.Request(folder=folder, out=out, order=order), ports, steps, chosen)
    except ReelError as exc:
        error = str(exc.code)
        log.error(
            "eval %s-%s failed: %s",
            job.fixture,
            job.model,
            exc,
            extra={"stage": STAGE, "event": "failed", "outcome": exc.code},
        )
    except Exception as exc:
        _write(job, out, None, type(exc).__name__, now)
        raise
    _write(job, out, made, error, now)
    return OK if made is not None else FAILED


def _ports(settings: EditorSettings, cfg: Config) -> make.Ports:
    # Imported here so the tests never load the SDK.
    from reel_studio.adapters.claude import client  # noqa: PLC0415
    from reel_studio.adapters.clock import SystemClock  # noqa: PLC0415

    claude = client.connect(settings.anthropic_api_key, config.load_claude(), cfg.limits.editor)
    return make.Ports(claude, SystemClock())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make eval", description=__doc__)
    parser.add_argument("--fixture", required=True, help="folder name under REEL_FIXTURES_DIR")
    parser.add_argument("--model", choices=MODELS, default=MODELS[0])
    parser.add_argument("--style", default=DEFAULT_STYLE)
    args = parser.parse_args(argv)
    configure()
    cfg, settings, build = config.load(), EditorSettings(), BuildSettings()
    media = config.load_media()
    ffmpeg = Ffmpeg(settings.ffmpeg_path, settings.ffprobe_path, media.tools)
    folder = build.reel_fixtures_dir / args.fixture
    steps = make.media_steps(folder, ffmpeg, media, cfg)
    job = Job(args.fixture, args.model, build.reel_fixtures_dir, ROOT, args.style)
    return run(job, _ports(settings, cfg), steps, cfg)


if __name__ == "__main__":
    sys.exit(main())
