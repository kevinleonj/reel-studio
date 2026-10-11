"""`make ab-pick` (STEP-04 task 3) and the A/B report (task 4).

Each fixture's two text versions are shown as X and Y in a random order (a local HTML page with
both videos, and their paths in the terminal). Kevin types x, y or tie and one line of reason;
only then is the mapping revealed. The picks turn ab-runs.json into ab.json, the file the step04
gate reads, and eval/AB-RESULT.md is rewritten with the table and the verdict.
"""

import json
import random
import secrets
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from jinja2 import Environment

from reel_studio.core import config, constants
from reel_studio.core.config import Ab
from reel_studio.editor import ab, evaluate

AB_JSON = "ab.json"
REPORT = Path("eval") / "AB-RESULT.md"
PAGE = "pick.html"
CHOICES = ("x", "y", "tie")
SIDES = ("new", "old")
PAGE_TEMPLATE = """<!doctype html><meta charset=utf-8><title>A/B blind pick</title>
{% for name, x, y in pairs %}<h2>{{ name }}</h2>
{% for label, src in (("X", x), ("Y", y)) %}<figure style="display:inline-block">
<figcaption>{{ label }}</figcaption><video src="{{ src }}" controls height=640></video>
</figure>{% endfor %}
{% endfor %}"""

type Row = dict[str, Any]  # Any: one fixture of ab-runs.json

_html = Environment(autoescape=True)  # an HTML page: names and paths are escaped


def _page(pairs: list[tuple[str, Path, Path]], target: Path) -> Path:
    uris = [(name, x.resolve().as_uri(), y.resolve().as_uri()) for name, x, y in pairs]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_html.from_string(PAGE_TEMPLATE).render(pairs=uris), encoding="utf-8")
    return target


def _video(row: Row, side: str, root: Path) -> Path:
    path = Path(row[side]["outputs"]["text"])
    return path if path.is_absolute() else root / path


def _ask_pick(name: str, ask: Callable[[str], str], say: Callable[[str], None]) -> str:
    while True:
        answer = ask(f"{name}: which is better? (x, y or tie) ").strip().lower()
        if answer in CHOICES:
            return answer
        say(f"Type x, y or tie, not {answer!r}.")


def verdict(rows: list[Row], cfg: Ab) -> list[str]:
    """EDITOR §11 in words, for the report (the step04 gate recomputes it from ab.json)."""
    n = len(rows)
    picks = [r.get("pick") for r in rows]
    new_or_tie = picks.count("new") + picks.count("tie")
    new_mean = sum(Decimal(str(r["new"]["critic_total"])) for r in rows) / n
    old_mean = sum(Decimal(str(r["old"]["critic_total"])) for r in rows) / n
    lost = [r["name"] for r in rows if r["old"]["passed"] and not r["new"]["passed"]]
    cost = sum(Decimal(str(r["new"]["cost_usd"])) for r in rows) / n
    checks = [
        (new_or_tie >= cfg.min_new_or_tie, f"new picked or tied in {new_or_tie} of {n}"),
        (
            new_mean >= old_mean - cfg.critic_margin,
            f"mean critic new {new_mean:.1f}, old {old_mean:.1f}",
        ),
        (not lost, f"gates lost by new: {', '.join(lost) if lost else 'none'}"),
        (cost <= cfg.max_mean_cost_usd, f"mean new cost ${cost:.2f}"),
    ]
    return [("ok    " if ok else "FAIL  ") + text for ok, text in checks]


def report(rows: list[Row], cfg: Ab, root: Path, source: Path) -> Path:
    lines = [
        "# A/B result: new engine vs the old kit (STEP-04)",
        "",
        f"Source: `{source.relative_to(root)}`.",
        "Same files to both engines; our critic judges both.",
        "",
        "| fixture | pick | reason | new critic | old critic | new $ | old $ | new s | old s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        new, old = r["new"], r.get("old") or {}
        lines.append(
            f"| {r['name']} | {r.get('pick', 'pending')} | {r.get('reason', '')} "
            f"| {new['critic_total']} | {old.get('critic_total', '-')} "
            f"| {new['cost_usd']:.2f} | {old.get('cost_usd', 0):.2f} "
            f"| {new['wall_s']:.0f} | {old.get('wall_s', 0):.0f} |"
        )
    complete = bool(rows) and all("pick" in r and r.get("old") for r in rows)
    lines += ["", "Verdict:" if complete else "Verdict: pending Kevin's blind picks (make ab-pick)"]
    if complete:
        lines += ["", *(f"- `{line}`" for line in verdict(rows, cfg))]
    target = root / REPORT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def pick(
    runs: Path, root: Path, ask: Callable[[str], str], seed: int, say: Callable[[str], None]
) -> Path:
    """Blind picks for every fixture of `runs`; writes ab.json beside it and the report."""
    data: dict[str, Any] = json.loads(runs.read_text(encoding="utf-8"))  # Any: JSON
    rows: list[Row] = [r for r in data["fixtures"] if r.get("new") and r.get("old")]
    rng = random.Random(seed)  # noqa: S311 - an order for a blind test, not a secret
    orders = {r["name"]: rng.sample(SIDES, len(SIDES)) for r in rows}
    pairs = [
        (r["name"], _video(r, orders[r["name"]][0], root), _video(r, orders[r["name"]][1], root))
        for r in rows
    ]
    page = _page(pairs, root / ab.OUT / runs.parent.name / PAGE)
    say(f"Open {page} in a browser; X and Y are in a random order per fixture.")
    for (name, x, y), row in zip(pairs, rows, strict=True):
        say(f"{name}: X = {x}  Y = {y}")
        answer = _ask_pick(name, ask, say)
        row["reason"] = ask(f"{name}: one line on why: ").strip()
        x_side, y_side = orders[name]
        row["pick"] = {"x": x_side, "y": y_side, "tie": "tie"}[answer]
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

    target = pick(runs[-1], evaluate.ROOT, input, secrets.randbits(constants.SEED_BITS), say)
    say(f"Picks recorded: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
