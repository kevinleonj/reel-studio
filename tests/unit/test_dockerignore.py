"""The Docker build context never carries secrets or local state, and never drops what an image
copies (web.md, For MAIN: REVIEW-FIXES MAIN item 2)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERIGNORE = ROOT / ".dockerignore"
COPY_SOURCES = re.compile(r"^\s*COPY\s+(?!--from)(?:--\S+\s+)*(.+?)\s+\S+\s*$", re.MULTILINE)
MUST_IGNORE = (".env", ".git", ".venv", "data", ".claude", "web/node_modules")


def _patterns() -> list[str]:
    lines = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
    return [line.strip().rstrip("/") for line in lines if line.strip() and not line.startswith("#")]


def _ignored(path: str, patterns: list[str]) -> bool:
    """Docker's rule for the cases used here: the last matching pattern wins, `!` re-includes,
    a pattern also covers everything below it."""
    verdict = False
    for pattern in patterns:
        keep = pattern.startswith("!")
        body = pattern.removeprefix("!").removeprefix("/")
        if Path(path).full_match(body) or any(Path(p).full_match(body) for p in Path(path).parents):
            verdict = not keep
    return verdict


def test_secrets_and_local_state_stay_out_of_the_build_context() -> None:
    patterns = _patterns()

    assert [path for path in MUST_IGNORE if not _ignored(path, patterns)] == []
    assert not _ignored(".env.example", patterns)


def test_nothing_an_image_copies_is_ignored() -> None:
    patterns = _patterns()
    sources = [
        source
        for dockerfile in sorted((ROOT / "docker").glob("*.Dockerfile"))
        for match in COPY_SOURCES.finditer(dockerfile.read_text(encoding="utf-8"))
        for source in match.group(1).split()
    ]

    assert sources
    assert [s for s in sources if _ignored(s.rstrip("/"), patterns)] == []
