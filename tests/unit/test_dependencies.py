"""A dependency lands in pyproject.toml with its first import (CLAUDE.md, code rules)."""

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "reel_studio"
REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()  # PEP 503 name normalisation


def _declared(extra: str | None = None) -> set[str]:
    """Distribution names in the base dependencies and every extra, or in one extra."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    groups: dict[str, list[str]] = project["optional-dependencies"]
    if extra is not None:
        lines = groups[extra]
    else:
        lines = [*project["dependencies"], *(line for group in groups.values() for line in group)]
    names = set()
    for line in lines:
        match = REQUIREMENT_NAME.match(line)
        assert match is not None, line
        names.add(_normalise(match.group(0)))
    return names


def _third_party_imports() -> dict[str, str]:
    """Top-level module -> one file importing it, for every non-stdlib, non-first-party import."""
    found: dict[str, str] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                top = module.split(".")[0]
                if top not in sys.stdlib_module_names and top != PACKAGE.name:
                    found.setdefault(top, str(path.relative_to(ROOT)))
    return found


def test_every_third_party_import_is_declared() -> None:
    declared = _declared()
    providers = packages_distributions()

    undeclared = {
        module: where
        for module, where in _third_party_imports().items()
        if not {_normalise(d) for d in providers.get(module, [])} & declared
    }

    assert undeclared == {}


def test_editor_extra_declares_the_sdk_http_layer() -> None:
    # adapters/claude/client.py on the engine lane catches httpx2.TransportError, which the
    # anthropic SDK does not wrap mid-stream (docs/handoff/engine.md, Needs Kevin 21).
    assert "httpx2" in _declared("editor")
