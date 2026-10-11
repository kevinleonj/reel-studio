"""`make ab-pick` (STEP-04 task 3) and the A/B report (task 4).

Each fixture's two text versions are copied to neutral names (x.mp4, y.mp4) in a random order and
shown on a local HTML page; nothing printed or embedded before the last pick says which engine
made which. Kevin types x, y or tie and one line of reason; then the mapping is revealed, ab.json
(the file the step04 gate reads) is written and eval/AB-RESULT.md is rewritten.
"""

import json
import random
import secrets
import shutil
import sys
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from jinja2 import Environment

from reel_studio.core import config, constants
from reel_studio.core.config import Ab
from reel_studio.editor import ab, evaluate

AB_JSON = "ab.json"
REPORT = Path("eval") / "AB-RESULT.md"
PICK = "pick"
PAGE = "pick.html"
CHOICES = ("x", "y", "tie")
LABELS = ("x", "y")
CELL_BAR, CELL_SAFE = "|", "/"  # a reason must not break the table
PAGE_TEMPLATE = """<!doctype html><meta charset=utf-8><title>A/B blind pick</title>
{% for name, x, y in pairs %}<h2>{{ name }}</h2>
{% for label, src in (("X", x), ("Y", y)) %}<figure style="display:inline-block">
<figcaption>{{ label }}</figcaption><video src="{{ src }}" controls height=640></video>
</figure>{% endfor %}
{% endfor %}"""

type Row = dict[str, Any]  # Any: one fixture of ab-runs.json

_html = Environment(autoescape=True)  # an HTML page: names and paths are escaped


class Incomplete(RuntimeError):
    """A fixture has no finished arm on one side: rerun it before picking."""


def order_of(seed: int, names: Sequence[str]) -> dict[str, list[str]]:
    """Per fixture, which engine is X and which is Y."""
    rng = random.Random(seed)  # noqa: S311 - an order for a blind test, not a secret
    return {name: rng.sample(ab.SIDES, len(ab.SIDES)) for name in names}


def _complete(row: Row) -> bool:
    return all(side in row and row[side]["error"] is None for side in ab.SIDES)


def _neutral(
    rows: list[Row], orders: dict[str, list[str]], root: Path, folder: Path
) -> list[tuple[str, Path, Path]]:
    pairs = []
    for row in rows:
        name = row["name"]
        target = folder / name
        target.mkdir(parents=True, exist_ok=True)
        copies = []
        for label, side in zip(LABELS, orders[name], strict=True):
            copy = target / f"{label}.mp4"
            shutil.copy2(root / row[side]["outputs"]["text"], copy)
            copies.append(copy)
        pairs.append((name, copies[0], copies[1]))
    return pairs


def _ask_pick(name: str, ask: Callable[[str], str], say: Callable[[str], None]) -> str:
    while True:
        answer = ask(f"{name}: which is better? (x, y or tie) ").strip().lower()
        if answer in CHOICES:
            return answer
        say(f"Type x, y or tie, not {answer!r}.")


def verdict(rows: list[Row], cfg: Ab) -> list[tuple[bool, str]]:
    """EDITOR §11 for the report (the step04 gate recomputes it from ab.json)."""
    n = len(rows)
    picks = [r.get("pick") for r in rows]
    new_or_tie = picks.count("new") + picks.count("tie")
    new_mean = sum(Decimal(str(r["new"]["critic_total"])) for r in rows) / n
    old_mean = sum(Decimal(str(r["old"]["critic_total"])) for r in rows) / n
    lost = [r["name"] for r in rows if r["old"]["passed"] and not r["new"]["passed"]]
    new_cost = sum(Decimal(str(r["new"]["cost_usd"])) for r in rows)
    spent = new_cost + sum(Decimal(str(r["old"]["cost_usd"])) for r in rows)
    return [
        (new_or_tie >= cfg.min_new_or_tie, f"new picked or tied in {new_or_tie} of {n}"),
        (
            new_mean >= old_mean - cfg.critic_margin,
            f"mean critic new {new_mean:.1f}, old {old_mean:.1f}",
        ),
        (not lost, f"gates lost by new: {', '.join(lost) if lost else 'none'}"),
        (new_cost / n <= cfg.max_mean_cost_usd, f"mean new cost ${new_cost / n:.2f}"),
        (spent <= cfg.budget_usd, f"budget: ${spent:.2f} of ${cfg.budget_usd}"),
    ]


def _tune(checks: list[tuple[bool, str]]) -> list[str]:
    if all(ok for ok, _ in checks):
        return []
    return [
        "",
        "What to tune: read each lost fixture's weakness in ab-runs.json, change the prompts",
        "for it, and rerun only those fixtures (`make ab REDO=<names>`; a plain `make ab`",
        "resumes a run that stopped).",
    ]


def report(rows: list[Row], cfg: Ab, root: Path, source: Path) -> Path:
    lines = [
        "# A/B result: new engine vs the old kit (STEP-04)",
        "",
        f"Source: `{source.relative_to(root)}`. Same files and order to both engines;",
        "our critic judges both finished cuts.",
        "",
        "| fixture | pick | reason | new critic | old critic | new $ | old $ | new s | old s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        new, old = r["new"], r["old"]
        reason = str(r.get("reason", "")).replace(CELL_BAR, CELL_SAFE)
        lines.append(
            f"| {r['name']} | {r.get('pick', 'pending')} | {reason} "
            f"| {new['critic_total']} | {old['critic_total']} "
            f"| {new['cost_usd']:.2f} | {old['cost_usd']:.2f} "
            f"| {new['wall_s']:.0f} | {old['wall_s']:.0f} |"
        )
    checks = verdict(rows, cfg)
    passed = all(ok for ok, _ in checks)
    lines += ["", f"Verdict: {'PASS' if passed else 'FAIL'}", ""]
    lines += [f"- `{'ok  ' if ok else 'FAIL'}  {text}`" for ok, text in checks]
    lines += _tune(checks)
    target = root / REPORT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def pick(
    runs: Path, root: Path, ask: Callable[[str], str], seed: int, say: Callable[[str], None]
) -> Path:
    """Blind picks for every fixture of `runs`; writes ab.json beside it and the report."""
    data: dict[str, Any] = json.loads(runs.read_text(encoding="utf-8"))  # Any: JSON
    rows: list[Row] = data["fixtures"]
    by_name = {r["name"]: r for r in rows}
    wanted = config.load().limits.eval.ab.fixtures  # all of them, not only the rows written
    unfinished = [n for n in wanted if n not in by_name or not _complete(by_name[n])]
    if unfinished:
        raise Incomplete(
            f"no finished pair for {unfinished}: run make ab ONLY={','.join(unfinished)}"
        )
    orders = order_of(seed, [r["name"] for r in rows])
    folder = root / ab.OUT / runs.parent.name / PICK
    pairs = _neutral(rows, orders, root, folder)
    uris = [(name, x.resolve().as_uri(), y.resolve().as_uri()) for name, x, y in pairs]
    page = folder / PAGE
    page.write_text(_html.from_string(PAGE_TEMPLATE).render(pairs=uris), encoding="utf-8")
    say(f"Open {page} in a browser; X and Y are in a random order per fixture.")
    for (name, _x, _y), row in zip(pairs, rows, strict=True):
        answer = _ask_pick(name, ask, say)
        row["reason"] = ask(f"{name}: one line on why: ").strip()
        row["pick"] = "tie" if answer == "tie" else orders[name][LABELS.index(answer)]
    for name, (x_side, y_side) in orders.items():
        say(f"{name}: X was {x_side}, Y was {y_side}")
    target = runs.with_name(AB_JSON)
    target.write_text(json.dumps({**data, "fixtures": rows}, indent=1) + "\n", encoding="utf-8")
    report(rows, config.load().limits.eval.ab, root, target)
    return target


def main() -> int:
    runs = sorted((evaluate.ROOT / evaluate.RESULTS).glob(f"*/{ab.RUNS_JSON}"))
    if not runs:
        sys.stderr.write("no ab-runs.json yet: run make ab first\n")
        return 1

    def say(line: str) -> None:
        sys.stdout.write(line + "\n")

    seed = secrets.randbits(constants.SEED_BITS)
    try:
        target = pick(runs[-1], evaluate.ROOT, input, seed, say)
    except Incomplete as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    say(f"Picks recorded: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
