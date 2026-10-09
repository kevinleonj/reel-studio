#!/usr/bin/env python3
"""Fail the build when a hard-coded value lands outside its home.

    python3 scripts/check_literals.py                  scan reel_studio/ and web/src/
    python3 scripts/check_literals.py FILE [FILE ...]  scan only these files
    python3 scripts/check_literals.py --self-test      prove every rule in a throwaway repository

Prints one sorted line per violation: path:line:col RULE message "value" (home: where it belongs).
The quoted value is what an allowlist entry needs. Exit 0 when clean, 1 on violations or stale
allowlist entries, 2 when the scanner itself fails. Exceptions live in tests/literal_allowlist.toml
and Kevin approves each one. Standard library only, Python 3.12 or newer.
"""

from __future__ import annotations

import argparse
import ast
import bisect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
import tomllib
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ALLOWLIST = "tests/literal_allowlist.toml"
SETTINGS = "reel_studio/settings.py"
CONSTANTS = "reel_studio/core/constants.py"
CLOCK = "reel_studio/adapters/clock.py"
WEB_SUFFIXES = {".ts", ".tsx", ".astro", ".css"}
# Home files hold these values on purpose, so the web rules never read them.
WEB_HOMES = {"web/src/styles/tokens.css", "web/src/lib/analytics.ts"}
MIN_REASON = 10
EXIT_CLEAN, EXIT_FOUND, EXIT_ERROR = 0, 1, 2
GIT_TIMEOUT_S = 10
CALL_SCAN_LIMIT = 200  # bounds the colour-function value so a missing ")" cannot swallow a file

RULES: dict[str, tuple[str, str]] = {
    "R1": ("number in code", "config/*.toml, or reel_studio/core/constants.py if a format value"),
    "R2": ("model id in code", "config/prices.toml"),
    "R3": ("URL in code", "reel_studio/settings.py, or core/constants.py with a FACTS id"),
    "R4": ("email address in code", "reel_studio/settings.py"),
    "R5": ("domain name in code", "reel_studio/settings.py"),
    "R6": ("cloud region in code", "reel_studio/settings.py"),
    "R7": ("currency code in code", "config/*.toml"),
    "R8": ("time zone in code", "reel_studio/settings.py"),
    "R9": ("machine path in code", "reel_studio/settings.py"),
    "R10": ("environment read outside settings.py", "read reel_studio.settings"),
    "R11": ("wall clock read outside adapters/clock.py", "use the Clock port"),
    "R12": ("falsy default with `or`", "use `x if x is not None else default`"),
    "R13": ("settings default without a reason", "add `# default-because: <why>` on the same line"),
    "C1": ("constant without a source comment", "a comment on the same line or the line above"),
    "W1": ("colour literal", "web/src/styles/tokens.css"),
    "W2": ("Tailwind arbitrary value", "use a theme token in tokens.css"),
    "W3": ("URL in web code", "runtime config from /api/config"),
    "W4": ("visible text in template", "text comes from web/src/copy/en.json"),
    "STALE": ("allowlist entry matched nothing", "delete the entry or fix its path, rule or value"),
}
ENTRY_RULES = set(RULES) - {"STALE"}
VALUE_RULES = {"R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"}
# A home may hold the values that belong there; every other rule still applies inside it.
SKIP: dict[str, set[str]] = {
    SETTINGS: {"R3", "R4", "R5", "R6", "R8", "R9", "R10"},
    CONSTANTS: VALUE_RULES,
    CLOCK: {"R11"},
}

MODEL_ID = re.compile(r"^(?:claude|gemini|gpt)-|\b(?:haiku|sonnet|opus|fable)[-_ ]?\d", re.I)
URL = re.compile(r"https?://", re.I)
URL_SPAN = re.compile(r"https?://[^\s\"'<>]*", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# A host must be a whole dotted token, so google.cloud.firestore, make_reel.py and
# api.app:app (module:attribute) stay code.
DOMAIN = re.compile(
    r"(?<!\w)(?<!\w\.)(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+"
    r"(?:com|app|dev|io|ai|net|org|es|eu|co|cloud|run)(?![\w-]|\.\w|:[A-Za-z_])"
)
REGION = re.compile(
    r"\b(?:europe|us|asia|africa|me|northamerica|southamerica|australia)-[a-z]+\d+(?:-[a-z])?\b"
)
CURRENCIES = {"eur", "usd", "gbp"}
TIME_ZONE = re.compile(r"[A-Z][A-Za-z_]+/[A-Z][A-Za-z_]+")
MACHINE_PATH = re.compile(r"/home/|/Users/|/tmp/|/mnt/|~/|[A-Za-z]:[\\/]")
# Qualified names; the bare forms catch modules whose import the scanner cannot see.
WALL_CLOCK = {
    "datetime.datetime.now", "datetime.datetime.utcnow", "datetime.datetime.today",
    "datetime.date.today", "time.time", "time.time_ns",
    "datetime.now", "datetime.utcnow", "datetime.today", "date.today",
}
ENV_NAMES = {"environ", "environb", "getenv", "getenvb", "putenv", "unsetenv"}
ENV_ATTRS = {f"os.{name}" for name in ENV_NAMES}
DEFAULT_BECAUSE = re.compile(r"#\s*default-because:")


class ScanError(Exception):
    """The scanner could not do its job; exit 2 instead of pretending the code is clean."""


@dataclass(frozen=True, order=True)
class Violation:
    path: str
    line: int
    col: int
    rule: str
    value: str
    message: str = ""

    def render(self) -> str:
        message, home = RULES[self.rule]
        shown = json.dumps(self.value, ensure_ascii=False)
        where = f"{self.path}:{self.line}:{self.col}"
        return f"{where} {self.rule} {self.message or message} {shown} (home: {home})"


# ---------------------------------------------------------------- Python rules (R1-R13, C1)


def docstring_ids(tree: ast.Module) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.partition(".")[0]
                aliases[alias.asname or top] = alias.name if alias.asname else top
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def dotted(node: ast.expr, aliases: dict[str, str]) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(aliases.get(node.id, node.id))
    return ".".join(reversed(parts))


def assigned_names(stmt: ast.Assign | ast.AnnAssign | ast.AugAssign | ast.TypeAlias) -> list[str]:
    if isinstance(stmt, ast.Assign):
        targets: list[ast.expr] = list(stmt.targets)
    else:
        targets = [stmt.name if isinstance(stmt, ast.TypeAlias) else stmt.target]
    return [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]


class PythonScan:
    """Runs the Python rules over one module's abstract syntax tree (AST)."""

    def __init__(self, rel: str, source: str) -> None:
        self.rel = rel
        self.source = source
        self.lines = source.split("\n")
        self.skip = SKIP.get(rel, set())
        self.found: list[Violation] = []
        self.comments: dict[int, str] = {}
        self.comment_only: set[int] = set()

    def run(self) -> list[Violation]:
        tree = ast.parse(self.source, filename=self.rel)
        docstrings = docstring_ids(tree)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        aliases = import_aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and id(node) not in docstrings:
                self.literal(node, parents.get(node))
            elif isinstance(node, ast.ImportFrom):
                self.env_import(node)
            elif isinstance(node, (ast.Attribute, ast.Name)):
                self.reference(node, aliases)
            elif isinstance(node, ast.BoolOp):
                self.falsy_default(node)
        if self.rel in (SETTINGS, CONSTANTS):
            self.load_comments()
        if self.rel == SETTINGS:
            self.settings_defaults(tree)
        if self.rel == CONSTANTS:
            self.constant_comments(tree)
        return self.found

    def add(self, rule: str, node: ast.expr | ast.stmt, value: str, message: str = "") -> None:
        if rule in self.skip:
            return
        # ast columns count UTF-8 bytes; editors count characters.
        head = self.lines[node.lineno - 1].encode()[: node.col_offset]
        col = len(head.decode(errors="replace")) + 1
        self.found.append(Violation(self.rel, node.lineno, col, rule, value, message))

    def segment(self, node: ast.AST) -> str:
        text = ast.get_source_segment(self.source, node)
        return " ".join((text if text is not None else ast.unparse(node)).split())

    def literal(self, node: ast.Constant, parent: ast.AST | None) -> None:
        value = node.value
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            target: ast.expr = node
            # Report -3 as written, so the allowlist value matches the source.
            if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, (ast.USub, ast.UAdd)):
                target = parent
            if abs(value) not in (0, 1, 2):
                self.add("R1", target, self.segment(target))
            return
        if isinstance(value, bytes):
            value = value.decode("latin-1")
        if isinstance(value, str):
            self.text(node, value)

    def text(self, node: ast.Constant, text: str) -> None:
        # A URL or an email already names its host, so the host rules read what is left.
        bare = EMAIL.sub(" ", URL_SPAN.sub(" ", text))
        hits = {
            "R2": MODEL_ID.search(text),
            "R3": URL.search(text),
            "R4": EMAIL.search(text),
            "R5": DOMAIN.search(bare),
            "R6": REGION.search(bare),
            "R7": text.lower() in CURRENCIES,
            "R8": TIME_ZONE.fullmatch(text),
            "R9": MACHINE_PATH.match(text),
        }
        for rule, hit in hits.items():
            if hit:
                self.add(rule, node, text)

    def env_import(self, node: ast.ImportFrom) -> None:
        if node.module == "os" and not node.level:
            for alias in node.names:
                if alias.name in ENV_NAMES:
                    self.add("R10", node, f"os.{alias.name}")

    def reference(self, node: ast.Attribute | ast.Name, aliases: dict[str, str]) -> None:
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            return
        name = dotted(node, aliases)
        # References count too: default_factory=time.time reads the clock later.
        if name in WALL_CLOCK:
            self.add("R11", node, self.segment(node))
        elif isinstance(node, ast.Attribute) and name in ENV_ATTRS:
            self.add("R10", node, self.segment(node))

    def falsy_default(self, node: ast.BoolOp) -> None:
        last = node.values[-1]
        if isinstance(last, ast.UnaryOp) and isinstance(last.op, (ast.USub, ast.UAdd)):
            last = last.operand
        if not isinstance(node.op, ast.Or) or not isinstance(last, ast.Constant):
            return
        # `x or ""` and `x or 0` cannot swap a real 0 or "" for another value, so they pass.
        if last.value is not None and not isinstance(last.value, bool) and last.value:
            self.add("R12", node, self.segment(node))

    def load_comments(self) -> None:
        for tok in tokenize.generate_tokens(io.StringIO(self.source).readline):
            if tok.type == tokenize.COMMENT:
                row, col = tok.start
                self.comments[row] = tok.string
                if not self.lines[row - 1][:col].strip():
                    self.comment_only.add(row)

    def commented(self, node: ast.stmt, pattern: re.Pattern[str] | None = None) -> bool:
        for row in range(node.lineno, (node.end_lineno or node.lineno) + 1):
            comment = self.comments.get(row)
            if comment is not None and (pattern is None or pattern.search(comment)):
                return True
        return False

    def settings_defaults(self, tree: ast.Module) -> None:
        for cls in ast.walk(tree):
            if isinstance(cls, ast.ClassDef):
                for stmt in cls.body:
                    if isinstance(stmt, ast.AnnAssign) and stmt.value is not None \
                            and not self.commented(stmt, DEFAULT_BECAUSE):
                        self.add("R13", stmt, self.segment(stmt.target))

    def constant_comments(self, tree: ast.Module) -> None:
        for stmt in tree.body:
            if isinstance(stmt, ast.AnnAssign) and stmt.value is None:
                continue
            if not isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.TypeAlias)):
                continue
            names = assigned_names(stmt)
            # __all__ and friends are module bookkeeping, not values with a source.
            if names and all(n.startswith("__") and n.endswith("__") for n in names):
                continue
            if self.commented(stmt) or stmt.lineno - 1 in self.comment_only:
                continue
            self.add("C1", stmt, ", ".join(names) or self.segment(stmt))


# ---------------------------------------------------------------- web rules (W1-W4)

JS_LEX = re.compile(
    r"""(?P<str>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`)"""
    r"|(?P<comment>/\*.*?\*/|(?<![:\\])//[^\n]*)",
    re.S,
)
CSS_LEX = re.compile(
    r"""(?P<str>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')|(?P<comment>/\*.*?\*/)""", re.S
)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
SCRIPT = re.compile(r"(<script\b[^>]*>)(.*?)(</script\s*>)", re.S | re.I)
STYLE = re.compile(r"(<style\b[^>]*>)(.*?)(</style\s*>)", re.S | re.I)
FRONTMATTER = re.compile(r"\A\s*---[ \t]*\n.*?^---[ \t]*$", re.S | re.M)
# &#8594; is an HTML character reference, not a colour.
COLOUR = re.compile(r"(?<!&)#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch)\(", re.I)
TAILWIND = re.compile(r"\b[a-z][a-z0-9:-]*-\[[^\]\s]+\]")
WEB_URL = re.compile(r"https?://[^\s\"'`<>)]*", re.I)
# Namespace identifiers (inline SVG, JSON-LD) look like URLs but are never fetched.
NAMESPACES = ("http://www.w3.org/", "https://www.w3.org/", "http://schema.org",
              "https://schema.org")
TAG = re.compile(r"""<(?:"[^"]*"|'[^']*'|[^'">])*>""")
TEXT_ATTR = re.compile(
    r"""(?<![\w:.-])(alt|title|placeholder|aria-label|content)\s*=\s*(?:"([^"]*)"|'([^']*)')"""
)
LETTERS = re.compile(r"[^\W\d_]{2,}")
ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]*|#\d+|#[xX][0-9A-Fa-f]+);")
# Viewport and http-equiv metas carry browser settings, not words a person reads.
META_SETTING = re.compile(r"""\bname\s*=\s*["']viewport["']|\bhttp-equiv\s*=""", re.I)


def blank(text: str) -> str:
    # Same length and same newlines keep every offset, so lines and columns stay true.
    return re.sub(r"[^\n]", " ", text)


def blank_all(pattern: re.Pattern[str], text: str) -> str:
    return pattern.sub(lambda m: blank(m[0]), text)


def mask_comments(text: str, lexer: re.Pattern[str]) -> str:
    # Comments may cite docs and colours; only code and markup carry runtime values.
    return lexer.sub(lambda m: blank(m[0]) if m["comment"] is not None else m[0], text)


def frontmatter_end(text: str) -> int:
    match = FRONTMATTER.match(text)
    return match.end() if match else 0


def mask_astro(text: str) -> str:
    start = frontmatter_end(text)
    body = blank_all(HTML_COMMENT, text[start:])
    body = SCRIPT.sub(lambda m: m[1] + mask_comments(m[2], JS_LEX) + m[3], body)
    body = STYLE.sub(lambda m: m[1] + mask_comments(m[2], CSS_LEX) + m[3], body)
    return mask_comments(text[:start], JS_LEX) + body


def blank_expressions(text: str) -> str:
    out = list(text)
    depth, start, quote, i = 0, 0, "", 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote or (ch == "\n" and quote != "`"):
                quote = ""
        elif depth and ch in "\"'`":
            quote = ch
        elif ch == "{":
            start = i if depth == 0 else start
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                out[start : i + 1] = blank(text[start : i + 1])
        i += 1
    if depth:  # an unclosed expression hides the rest rather than inventing text
        out[start:] = blank(text[start:])
    return "".join(out)


def template_hits(masked: str, start: int) -> list[tuple[int, str, str]]:
    body = blank_expressions(blank_all(STYLE, blank_all(SCRIPT, masked[start:])))
    hits: list[tuple[int, str, str]] = []

    def text_node(segment: str, offset: int) -> None:
        words = blank_all(ENTITY, segment)
        if LETTERS.search(words):
            lead = len(words) - len(words.lstrip())
            hits.append((start + offset + lead, " ".join(segment.split()), ""))

    pos = 0
    for tag in TAG.finditer(body):
        text_node(body[pos : tag.start()], pos)
        for attr in TEXT_ATTR.finditer(tag[0]):
            value = attr[2] if attr[2] is not None else attr[3]
            if attr[1] == "content" and META_SETTING.search(tag[0]):
                continue
            if LETTERS.search(blank_all(ENTITY, value)):
                hits.append((start + tag.start() + attr.start(1), value,
                             f"visible text in {attr[1]} attribute"))
        pos = tag.end()
    text_node(body[pos:], pos)
    return hits


def call_text(text: str, start: int, paren: int) -> str:
    depth = 0
    for i in range(paren, min(len(text), paren + CALL_SCAN_LIMIT)):
        if text[i] == "\n":
            break
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        if depth == 0:
            return text[start : i + 1]
    return text[start : paren + 1]


class LineIndex:
    def __init__(self, text: str) -> None:
        self.starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]

    def position(self, offset: int) -> tuple[int, int]:
        line = bisect.bisect_right(self.starts, offset)
        return line, offset - self.starts[line - 1] + 1


def scan_web(rel: str, text: str) -> list[Violation]:
    suffix = PurePosixPath(rel).suffix
    if suffix == ".astro":
        masked = mask_astro(text)
    else:
        masked = mask_comments(text, CSS_LEX if suffix == ".css" else JS_LEX)
    hits: list[tuple[int, str, str, str]] = []
    for m in COLOUR.finditer(masked):
        value = m[0] if m[0].startswith("#") else call_text(masked, m.start(), m.end() - 1)
        hits.append((m.start(), "W1", value, ""))
    hits += [(m.start(), "W2", m[0], "") for m in TAILWIND.finditer(masked)]
    hits += [(m.start(), "W3", m[0], "") for m in WEB_URL.finditer(masked)
             if not m[0].startswith(NAMESPACES)]
    if suffix == ".astro":
        hits += [(off, "W4", value, msg) for off, value, msg in
                 template_hits(masked, frontmatter_end(text))]
    index = LineIndex(text)
    return [Violation(rel, *index.position(off), rule, value, msg)
            for off, rule, value, msg in hits]


# ---------------------------------------------------------------- files, allowlist, command line


@dataclass(frozen=True)
class Entry:
    path: str
    rule: str
    value: str
    line: int


def kind_of(rel: str) -> str | None:
    path = PurePosixPath(rel)
    if path.parts[:1] == ("reel_studio",) and path.suffix == ".py":
        return "py"
    if path.parts[:2] == ("web", "src") and path.suffix in WEB_SUFFIXES and rel not in WEB_HOMES:
        return "web"
    return None


def find_root() -> Path:
    try:
        done = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                              text=True, check=True, timeout=GIT_TIMEOUT_S)
        if done.stdout.strip():
            return Path(done.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass  # no git or not a repository: the script's own checkout is the root
    return Path(__file__).resolve().parent.parent


def discover(root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for base in (root / "reel_studio", root / "web" / "src"):
        if base.is_dir():
            for path in base.rglob("*"):
                rel = path.relative_to(root).as_posix()
                if kind_of(rel) and path.is_file():
                    found[rel] = path
    return dict(sorted(found.items()))


def select(root: Path, names: list[str]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for name in names:
        path = Path(name) if Path(name).is_absolute() else Path.cwd() / name
        try:
            rel = path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue  # outside the repository, so outside every scanned area
        if kind_of(rel):
            found[rel] = path.resolve()
    return dict(sorted(found.items()))


def read_source(path: Path, rel: str) -> str:
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ScanError(f"cannot read {rel}: {exc}") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def scan_file(rel: str, path: Path) -> list[Violation]:
    text = read_source(path, rel)
    if kind_of(rel) == "web":
        return scan_web(rel, text)
    try:
        return PythonScan(rel, text).run()
    except (SyntaxError, ValueError, tokenize.TokenError) as exc:
        raise ScanError(f"cannot parse {rel}: {exc}") from exc


def load_allowlist(root: Path) -> list[Entry]:
    file = root / ALLOWLIST
    if not file.is_file():
        return []
    try:
        text = file.read_text(encoding="utf-8")
        data = tomllib.loads(text)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ScanError(f"{ALLOWLIST}: {exc}") from exc
    raw = data.get("allow", [])
    if set(data) - {"allow"} or not isinstance(raw, list):
        raise ScanError(f"{ALLOWLIST}: only [[allow]] tables are allowed")
    headers = [m.start() for m in re.finditer(r"^[ \t]*\[\[[ \t]*allow[ \t]*\]\]", text, re.M)]
    entries: list[Entry] = []
    for index, item in enumerate(raw):
        line = text.count("\n", 0, headers[index]) + 1 if len(headers) == len(raw) else 1
        where = f"{ALLOWLIST}:{line}"
        if not isinstance(item, dict) or set(item) - {"path", "rule", "value", "reason"}:
            raise ScanError(f"{where}: an entry has exactly path, rule, value and reason")
        for key in ("path", "rule", "value", "reason"):
            if not isinstance(item.get(key), str):
                raise ScanError(f"{where}: `{key}` is required and must be a quoted string")
        if len(item["reason"].strip()) < MIN_REASON:
            raise ScanError(f"{where}: `reason` needs at least {MIN_REASON} characters")
        if item["rule"] not in ENTRY_RULES:
            raise ScanError(f"{where}: unknown rule {item['rule']!r}")
        entry = Entry(item["path"], item["rule"], item["value"], line)
        if any((e.path, e.rule, e.value) == (entry.path, entry.rule, entry.value) for e in entries):
            raise ScanError(f"{where}: duplicate of an earlier entry")
        entries.append(entry)
    return entries


def run(files: list[str]) -> int:
    root = find_root()
    entries = load_allowlist(root)
    targets = select(root, files) if files else discover(root)
    found = {v for rel, path in targets.items() for v in scan_file(rel, path)}
    allowed = {(e.path, e.rule, e.value): e for e in entries}
    kept = [v for v in found if (v.path, v.rule, v.value) not in allowed]
    if not files:  # only a full scan sees every file, so only it can call an entry stale
        used = {(v.path, v.rule, v.value) for v in found}
        kept += [Violation(ALLOWLIST, e.line, 1, "STALE", e.value,
                           f"allowlist entry matched nothing: {e.path} {e.rule}")
                 for key, e in allowed.items() if key not in used]
    for violation in sorted(kept):
        print(violation.render())
    if kept:
        return EXIT_FOUND
    if not files:
        print(f"literal scan: 0 violations in {len(targets)} files")
    return EXIT_CLEAN


# ---------------------------------------------------------------- self-test

SELF_TEST_TIMEOUT_S = 60
MEDIA = "reel_studio/editor/media.py"
OUT_LINE = re.compile(r"(?P<path>\S+):(?P<line>\d+):(?P<col>\d+) (?P<rule>[A-Z]+\d*) ")


def lines(*rows: str) -> str:
    return "\n".join(rows) + "\n"


# (case, rule, path, content, line the rule must report): each file breaks exactly one rule.
PLANTS: list[tuple[str, str, str, str, int]] = [
    ("number literal", "R1", "reel_studio/r1_number.py", lines(
        '"""Small numbers are free and a docstring may say 48000."""',
        "SMALL = (0, 1, 2, -1, 2.0, True, None)",
        "TIMEOUT_S = 30",
    ), 3),
    ("negative number", "R1", "reel_studio/r1_negative.py", lines(
        '"""A negative literal is reported as written."""',
        "LOUDNESS_LUFS = -14",
    ), 2),
    ("model id", "R2", "reel_studio/r2_model.py", lines(
        '"""Model ids such as claude-sonnet-5-5 belong in config."""',
        'MODEL = "claude-sonnet-5-5"',
    ), 2),
    ("URL", "R3", "reel_studio/r3_url.py", lines(
        '"""URLs belong in settings, see https://example.org/docs."""',
        'BASE = "https://api.example.org/v1"',
    ), 2),
    ("URL in an f-string part", "R3", "reel_studio/r3_fstring.py", lines(
        '"""The constant parts of an f-string are checked as strings."""',
        "",
        "",
        "def endpoint(host: str) -> str:",
        '    return f"https://{host}/v1"',
    ), 5),
    ("email address", "R4", "reel_studio/r4_email.py", lines(
        '"""Email addresses."""',
        'SENDER = "reels@example.org"',
    ), 2),
    ("domain, but not import paths or file names", "R5", "reel_studio/r5_domain.py", lines(
        '"""Domains are flagged; import paths and file names are not."""',
        "import importlib",
        "",
        'FIRESTORE = importlib.import_module("google.cloud.firestore")',
        'FILES = ("edl.json", "make_reel.py", "reel_studio.api.app:app")',
        'HOST = "api.example.org"',
    ), 6),
    ("cloud region", "R6", "reel_studio/r6_region.py", lines(
        '"""Cloud regions."""', 'REGION = "europe-west1"'), 2),
    ("currency code", "R7", "reel_studio/r7_currency.py", lines(
        '"""Currency codes."""', 'CURRENCY = "EUR"'), 2),
    ("time zone", "R8", "reel_studio/r8_zone.py", lines(
        '"""Time zones."""', 'ZONE = "Europe/Madrid"'), 2),
    ("machine path", "R9", "reel_studio/r9_path.py", lines(
        '"""Machine paths."""', 'CACHE_DIR = "/tmp/reel-cache"'), 2),
    ("os.environ outside settings", "R10", "reel_studio/r10_environ.py", lines(
        '"""Environment reads."""',
        "import os",
        "",
        'PAYMENTS = os.environ["PAYMENTS"]',
    ), 4),
    ("from os import getenv", "R10", "reel_studio/r10_getenv.py", lines(
        '"""Importing getenv is an environment read too."""',
        "from os import getenv",
        "",
        'SITE = getenv("SITE_URL")',
    ), 2),
    ("datetime.now, monotonic timers allowed", "R11", "reel_studio/r11_clock.py", lines(
        '"""Wall-clock reads; monotonic timers measure durations and stay allowed."""',
        "import time",
        "from datetime import datetime",
        "",
        "",
        "def stamp() -> tuple[datetime, float]:",
        "    started = time.monotonic()",
        "    return datetime.now(), time.perf_counter() - started",
    ), 8),
    ("time.time handed on as a factory", "R11", "reel_studio/r11_reference.py", lines(
        '"""Handing the clock function on still reads the wall clock."""',
        "import time",
        "from dataclasses import dataclass, field",
        "",
        "",
        "@dataclass",
        "class Job:",
        "    started: float = field(default_factory=time.time)",
    ), 8),
    ("falsy default", "R12", "reel_studio/r12_default.py", lines(
        '"""Falsy defaults."""',
        "",
        "",
        "def pick(name: str | None) -> str:",
        '    return name or "fallback"',
    ), 5),
    ("settings default without a reason", "R13", SETTINGS, lines(
        '"""Env reads, URLs and regions live here; every default says why."""',
        "import os",
        "",
        "",
        "class Settings:",
        '    site_url: str = "http://localhost:8080"  # default-because: the laptop tier',
        '    region: str = "europe-west1"  # default-because: D50',
        '    payments: str = "off"',
        '    debug: str | None = os.environ.get("REEL_DEBUG")  # default-because: off unless set',
    ), 8),
    ("constant without a source comment", "C1", CONSTANTS, lines(
        '"""Format constants; each one says where it comes from."""',
        "# AAC sample rate Instagram accepts (FACTS F45)",
        "SAMPLE_RATE = 48000",
        "WIDTH = 1080  # Reel frame width (FACTS F46)",
        "HEIGHT = 1920",
    ), 5),
    ("colour literal", "W1", "web/src/components/Badge.tsx", lines(
        "// Colours come from tokens.css; #fff inside a comment is not a value.",
        'export const badge = { color: "#ff0000" };',
    ), 2),
    ("Tailwind arbitrary value", "W2", "web/src/components/Box.tsx", lines(
        "export function Box() {",
        '  return <div className="flex w-[372px]" />;',
        "}",
    ), 2),
    ("URL in web code", "W3", "web/src/lib/api.ts", lines(
        "// Docs: https://docs.astro.build/en/guides/endpoints/ (comments are not scanned)",
        'export const API_BASE = "https://api.example.org";',
    ), 2),
    ("text between tags", "W4", "web/src/pages/plain.astro", lines(
        "---",
        'const note = "frontmatter is code, covered by ESLint";',
        "---",
        "<h1>Hello world</h1>",
    ), 4),
    ("literal alt text", "W4", "web/src/pages/photo.astro", lines(
        '<img src="/dish.jpg" alt="A plated dish" />',
    ), 1),
]

# A clean repository: every home in use, one value approved by the allowlist, 0 violations.
CLEAN: dict[str, str] = {
    "reel_studio/__init__.py": lines('"""Reel Studio."""'),
    "reel_studio/editor/render.py": lines(
        '"""Values come from settings, config and constants.',
        "",
        "Docs: https://ffmpeg.org/ffmpeg.html (a docstring is never flagged).",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "import importlib",
        "import time",
        "from pathlib import Path",
        "",
        "from reel_studio.core.constants import SAMPLE_RATE",
        "",
        'FIRESTORE = "google.cloud.firestore"',
        'EDL_FILE = "edl.json"',
        "",
        "",
        "def audio_args(rate: int | None) -> list[str]:",
        "    chosen = rate if rate is not None else SAMPLE_RATE",
        '    return ["-ar", str(chosen), "-ac", "2", "-map", "0:a:0"]',
        "",
        "",
        "def output(folder: Path, name: str | None) -> Path:",
        "    return folder / (name if name is not None else EDL_FILE)",
        "",
        "",
        "def elapsed(started: float) -> float:",
        "    return time.monotonic() - started",
        "",
        "",
        "def duration(probe: dict[str, str], label: str | None) -> tuple[float, str]:",
        '    return float(probe.get("duration") or 0), label or ""',
        "",
        "",
        "def firestore() -> object:",
        "    return importlib.import_module(FIRESTORE)",
    ),
    MEDIA: lines(
        '"""Holds the one planted value the allowlist approves."""',
        "# AAC sample rate Instagram requires (FACTS F45), kept here to prove the allowlist",
        "AAC_RATE = 48000",
    ),
    CONSTANTS: lines(
        '"""Format and protocol constants; each says where it comes from."""',
        "# Frame size of a vertical Reel (FACTS F46)",
        "REEL_WIDTH = 1080",
        "REEL_HEIGHT = 1920  # FACTS F46",
        "SAMPLE_RATE = 48000  # AAC sample rate (FACTS F45)",
        'GRAPH_URL = "https://graph.example.org/v1"  # FACTS F12',
        '__all__ = ["GRAPH_URL", "REEL_HEIGHT", "REEL_WIDTH", "SAMPLE_RATE"]',
    ),
    SETTINGS: lines(
        '"""The only module that reads the environment."""',
        "import os",
        "",
        "",
        "class Settings:",
        '    site_url: str = "http://localhost:8080"  # default-because: the laptop tier',
        '    gcp_region: str = "europe-west1"  # default-because: D50',
        '    alert_email: str = "alerts@example.org"  # default-because: placeholder until STEP-08',
        '    zone: str = "Europe/Madrid"  # default-because: the scheduler runs in Madrid',
        '    home: str | None = os.environ.get("REEL_HOME")  # default-because: unset means none',
    ),
    CLOCK: lines(
        '"""The only module that reads the wall clock."""',
        "from datetime import UTC, datetime",
        "",
        "",
        "class SystemClock:",
        "    def now(self) -> datetime:",
        "        return datetime.now(tz=UTC)",
    ),
    "web/src/pages/index.astro": lines(
        "---",
        'import { t } from "../lib/i18n";',
        "// Frontmatter comments may cite https://docs.astro.build/ freely.",
        "---",
        "<!doctype html>",
        '<html lang="en">',
        "  <head>",
        '    <meta charset="utf-8" />',
        '    <meta name="viewport" content="width=device-width, initial-scale=1" />',
        '    <title>{t("meta.title")}</title>',
        "    <!-- Page copy lives in web/src/copy/en.json -->",
        "  </head>",
        "  <body>",
        '    <h1 class="text-ink">{t("hero.title")}</h1>',
        '    <img src="/hero.jpg" alt={t("hero.alt")} />',
        '    <p>{t("hero.body")}&nbsp;&rarr;&#8594;</p>',
        '    <svg xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        '<path d="M0 0h24v24H0z" /></svg>',
        "  </body>",
        "</html>",
        "<style>",
        "  h1 { color: var(--color-ink); }",
        "</style>",
        "<script>",
        "  // Analytics loads from web/src/lib/analytics.ts",
        '  const status = "never rendered as text";',
        "</script>",
    ),
    "web/src/components/Hero.tsx": lines(
        "// Copy comes from en.json; see https://react.dev/learn (comments are not scanned).",
        'import { t } from "../lib/i18n";',
        "",
        "export function Hero({ count }: { count: number }) {",
        "  return (",
        '    <section className="flex flex-col gap-4 text-ink">',
        '      <h2>{t("hero.title")}</h2>',
        '      <p aria-label={t("hero.count")}>{count}</p>',
        "    </section>",
        "  );",
        "}",
    ),
    "web/src/styles/global.css": lines(
        "/* Colours such as #ffffff live in tokens.css, never here. */",
        "body {",
        "  color: var(--color-ink);",
        "  background: var(--color-paper);",
        "}",
    ),
    "web/src/styles/tokens.css": lines(
        ":root {", "  --color-ink: #111111;", "  --color-paper: rgb(250 250 250);", "}"),
    "web/src/lib/analytics.ts": lines(
        'export const ANALYTICS_SCRIPT = "https://plausible.io/js/script.js";'),
    "tests/test_outside.py": lines('URL = "https://example.org"', "TIMEOUT_S = 30"),
}
ENTRY = lines(
    "[[allow]]",
    f'path = "{MEDIA}"',
    'rule = "R1"',
    'value = "48000"',
    'reason = "AAC sample rate Instagram requires, FACTS F45"',
)
STALE_ENTRY = lines(
    "", "[[allow]]", f'path = "{MEDIA}"', 'rule = "R1"', 'value = "44100"',
    'reason = "a sample rate the code no longer uses"',
)
NO_REASON = lines("[[allow]]", f'path = "{MEDIA}"', 'rule = "R1"', 'value = "48000"')
SHORT_REASON = NO_REASON + lines('reason = "too short"')


def git_free_env() -> dict[str, str]:
    # A git hook exports GIT_DIR; inheriting it would point the temp repo at the real one.
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def write_file(repo: Path, rel: str, body: str) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def build_repo(repo: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        write_file(repo, rel, body)
    write_file(repo, "scripts/check_literals.py", Path(__file__).resolve().read_text("utf-8"))
    if shutil.which("git"):
        subprocess.run(["git", "init", "-q"], cwd=repo, env=git_free_env(), capture_output=True,
                       check=False, timeout=SELF_TEST_TIMEOUT_S)
    return repo


def scan(repo: Path, *files: str) -> tuple[int, list[str], str]:
    done = subprocess.run([sys.executable, "scripts/check_literals.py", *files], cwd=repo,
                          env=git_free_env(), capture_output=True, text=True, check=False,
                          timeout=SELF_TEST_TIMEOUT_S)
    return done.returncode, done.stdout.splitlines(), done.stderr.strip()


def rules_in(out: list[str]) -> list[tuple[str, int]]:
    return [(m["rule"], int(m["line"])) for m in map(OUT_LINE.match, out) if m]


def repo_cases(repo: Path) -> list[tuple[str, bool, str]]:
    scanned = [rel for rel in CLEAN if kind_of(rel)]
    total = f"literal scan: 0 violations in {len(scanned)} files"
    stray = repo.parent / "stray" / "reel_studio" / "stray.py"  # breaks R3, but lives outside
    write_file(stray.parent, stray.name, CLEAN["tests/test_outside.py"])
    outside = ("tests/test_outside.py", "web/src/styles/tokens.css", str(stray))
    table: list[tuple[str, str, tuple[str, ...], Callable[[int, list[str]], bool]]] = [
        ("clean repository: full scan passes and counts files", ENTRY, (),
         lambda code, out: code == EXIT_CLEAN and out == [total]),
        ("clean files: per-file scan prints nothing", ENTRY, tuple(scanned),
         lambda code, out: code == EXIT_CLEAN and out == []),
        ("allowlist entry suppresses the planted value", ENTRY, (MEDIA,),
         lambda code, out: code == EXIT_CLEAN and out == []),
        ("planted value fails without its entry", "", (MEDIA,),
         lambda code, out: code == EXIT_FOUND and rules_in(out) == [("R1", 3)]),
        ("stale entry fails the full scan", ENTRY + STALE_ENTRY, (),
         lambda code, out: code == EXIT_FOUND and rules_in(out) == [("STALE", 7)]
         and out[0].startswith(f"{ALLOWLIST}:")),
        ("per-file scan skips the stale check", ENTRY + STALE_ENTRY, (MEDIA,),
         lambda code, out: code == EXIT_CLEAN and out == []),
        ("entry without reason exits 2", NO_REASON, (), lambda code, _: code == EXIT_ERROR),
        ("short reason exits 2", SHORT_REASON, (), lambda code, _: code == EXIT_ERROR),
        ("broken allowlist TOML exits 2", "[[allow]\n", (), lambda code, _: code == EXIT_ERROR),
        ("files outside the scanned areas are ignored", ENTRY, outside,
         lambda code, out: code == EXIT_CLEAN and out == []),
        ("missing file in a scanned area exits 2", ENTRY, ("reel_studio/missing.py",),
         lambda code, _: code == EXIT_ERROR),
    ]
    results = []
    for name, allowlist, files, check in table:
        write_file(repo, ALLOWLIST, allowlist)
        code, out, err = scan(repo, *files)
        results.append((name, check(code, out), f"exit {code}, output {out or err}"))
    return results


def self_test() -> int:
    results: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory(prefix="check-literals-") as tmp:
        plants = build_repo(Path(tmp) / "plants", {path: body for _, _, path, body, _ in PLANTS})
        for case, rule, path, _, line in PLANTS:
            code, out, err = scan(plants, path)
            ok = code == EXIT_FOUND and rules_in(out) == [(rule, line)]
            ok = ok and out[0].startswith(f"{path}:")
            results.append((f"{rule} {case}", ok, f"exit {code}, output {out or err}"))
        results += repo_cases(build_repo(Path(tmp) / "clean", {**CLEAN, ALLOWLIST: ENTRY}))
    for name, ok, detail in results:
        print(f"PASS {name}" if ok else f"FAIL {name}: {detail}")
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"self-test: {len(results) - failed} passed, {failed} failed")
    return EXIT_FOUND if failed else EXIT_CLEAN


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail when a hard-coded value leaves its home.")
    parser.add_argument("files", nargs="*", help="scan only these files (default: the repository)")
    parser.add_argument("--self-test", action="store_true", help="prove every rule in a temp repo")
    args = parser.parse_args(argv)
    if args.self_test and args.files:
        parser.error("--self-test takes no files")
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="backslashreplace")  # a C locale must not crash the gate
    try:
        return self_test() if args.self_test else run(args.files)
    except ScanError as exc:
        print(f"check_literals: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except Exception:  # any other crash is still the scanner's fault: show it, keep exit 2
        traceback.print_exc()
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
