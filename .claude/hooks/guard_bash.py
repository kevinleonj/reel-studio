#!/usr/bin/env python3
"""PreToolUse guard for Bash and PowerShell commands (Claude Code hooks, F54).

Reads the hook JSON on stdin. Exit 0 lets the command run; exit 2 blocks it and the stderr text
is shown to Claude as the reason. Python 3.9+ standard library only; git is the only program it
runs. Paths and program names are compared without case: the default macOS file system treats
Docs/ as docs/ and runs GIT as git.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn, Optional

sys.dont_write_bytecode = True                      # importing _common must leave no __pycache__ here
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

# .env keys whose VALUES are not secret and may be read (paths and ids).
SAFE_ENV_KEYS = {"OLD_KIT_DIR", "REEL_FIXTURES_DIR", "GCP_PROJECT", "GCP_REGION", "SITE_URL", "PAYMENTS"}

# (pattern, reason). Patterns run on the whole command string, case-sensitive.
RULES: list[tuple[str, str]] = [
    (r"\bterraform\b[^\n]*\b(apply|destroy)\b",
     "terraform apply/destroy is run by Kevin (bootstrap) or the deploy workflow only (D60)."),
    (r"\bgit\b[^\n]*\bpush\b[^\n]*(--force\b|--force-with-lease\b|(\s|^)-f(\s|$)|\s\+[\w/.:-]+)",
     "Force-push is not allowed."),
    (r"\bgit\b[^\n]*\bpush\b[^\n]*[\s:/](main|master)\b",
     "Do not push to main. Push your step branch and open a pull request."),
    (r"\.ci-pass", "Only `make ci` writes or reads .ci-pass."),
    (r"disableAllHooks", "Hooks may not be switched off from a session."),
    (r"(^|[\s;&|(])printenv\b", "Printing environment variables can expose keys."),
    (r"(^|[\s;&|(])env(\s*$|\s*[;&|)])", "Printing the environment can expose keys. Check names only."),
    (r"(^|[\s;&|(])export\s+-p\b", "Printing the environment can expose keys."),
    (r"\b(echo|printf)\b[^\n]*\$\{?[A-Z0-9_]*(KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*",
     "Do not print secret variables."),
    (r"\bgcloud\b[^\n]*\bsecrets\s+versions\s+access\b", "Reading secret values is not allowed."),
    (r"\bgcloud\b[^\n]*\s(delete|remove-iam-policy-binding)\b",
     "Cloud deletes go through Terraform or reelctl, never an ad-hoc gcloud command."),
    (r"\bgcloud\s+storage\s+rm\b|\bgsutil\b[^\n]*\brm\b",
     "Bucket deletes go through reelctl or lifecycle rules."),
    (r"\bdocker\b[^\n]*\binspect\b|\bdocker\s+compose\b[^\n]*\bconfig\b",
     "docker inspect / compose config print environment values."),
    (r"\bdocker\b[^\n]*\bexec\b[^\n]*\b(env|printenv|set)\b", "Printing a container's environment exposes keys."),
    (r"\bgrep\s+(-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b",
     "Recursive grep reads .env. Use rg or git grep, which skip ignored files."),
    (r"\b(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(sh|bash|zsh|python3?)\b",
     "Piping a download into a shell is not allowed."),
    (r"(^|[\s;&|(])pip3?\s+install\b", "Use `uv add <package>` (one lock file, D70)."),
    (r"\bnpm\s+(install|i)\s+(-g|--global)\b", "No global npm installs."),
    (r"\bclaude[-_]agent[-_]sdk\b",
     "The product does not use the Agent SDK (D30). Use the anthropic Messages API loop."),
    (r"\bsk_live_[A-Za-z0-9]", "A Stripe live key must never appear in a command."),
    (r"\bsk-ant-[A-Za-z0-9_-]{8,}", "A Claude API key must never appear in a command."),
]

# Rules that read the command word by word (see commands()); each reason is one line.
POWERSHELL = "Use the Bash tool in this repository."
NO_VERIFY_COMMIT = ("git commit --no-verify / -n bypasses the gitleaks pre-commit hook. "
                    "Commit without it and fix what the hook reports.")
NO_VERIFY_PUSH = "git push --no-verify bypasses the gitleaks git hooks. Push without it."
HOOKS_BYPASS = ("SKIP=gitleaks and a changed core.hooksPath switch off the gitleaks pre-commit hook. "
                "Commit normally and fix what the hook reports.")
MERGE = "Kevin merges pull requests after CI is green. Leave the pull request open."
STATE_SURGERY = ("terraform state/import/taint/untaint is state surgery, which is Kevin's. "
                 "Write what you need under 'Needs Kevin'.")
DEPLOY = ("Deploys go through Terraform and deploy.yml, not gcloud run deploy/update/replace/"
          "update-traffic or gcloud builds submit.")
STRIPE_LIVE = "Stripe live mode (--live) is never used from a session. Use test mode."
WORKTREES = "Kevin manages worktrees with scripts/dev/lane.sh; git worktree remove/prune is not run here."
CLEAN_IGNORED = ("git clean -x/-X deletes ignored files such as .env and .lane. "
                 "Use git clean -fd, or delete the files by name.")
NO_NEW_WORKFLOWS = "No new workflow files: CI is one ci.yml calling make ci; deploy is deploy.yml."

TERRAFORM_STATE = {"state", "import", "taint", "untaint"}
GCLOUD_DEPLOYS = (("run", "deploy"), ("run", "jobs", "deploy"), ("run", "services", "update"),
                  ("run", "jobs", "update"), ("run", "services", "replace"), ("run", "jobs", "replace"),
                  ("run", "services", "update-traffic"), ("builds", "submit"))
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix"}
COMMIT_VALUE_SHORT = "mFCct"         # -m <msg>, -F <file>, -C/-c <commit>, -t <file>: value attached or next word
COMMIT_ATTACHED_SHORT = "Su"         # -S[<keyid>], -u[<mode>]: a value only when attached
COMMIT_VALUE_LONG = {"--message", "--file", "--reuse-message", "--reedit-message", "--template", "--author",
                     "--date", "--cleanup", "--fixup", "--squash", "--trailer", "--pathspec-from-file"}
SHELLS = {"sh", "bash", "dash", "zsh", "ksh"}
WRAPPERS = {"sudo", "doas", "env", "command", "builtin", "exec", "nohup", "time", "nice", "timeout", "stdbuf",
            "!", "{", "if", "then", "else", "elif", "do", "while", "until"}
WRAPPER_VALUE_OPTIONS = {"sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-T", "-U", "-R"},
                         "doas": {"-u", "-C"}, "env": {"-u", "-C", "--unset", "--chdir"},
                         "nice": {"-n", "--adjustment"}, "timeout": {"-s", "-k", "--signal", "--kill-after"},
                         "stdbuf": {"-i", "-o", "-e"}}
ASSIGNERS = {"export", "declare", "typeset", "local", "readonly"}
REDIRECTS = {"<", ">", ">>", "<<", "<<<", ">&", "<&", "&>", "&>>", ">|", "<>"}
OPERATOR_CHARS = set("();<>|&")
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")

# Paths a session may not change through the shell either (guard_paths covers the edit tools).
# A trailing / marks a folder, which also matches without the slash (rm -rf .claude). None: no override.
PROTECTED: dict[str, Optional[str]] = {
    ".claude/": "REEL_ALLOW_HOOK_EDIT", ".lane": "REEL_ALLOW_HOOK_EDIT",
    "docs/DECISIONS.md": "REEL_ALLOW_DECISION_EDIT", "tests/golden/": "REEL_ALLOW_GOLDEN",
    "scripts/gates/": "REEL_ALLOW_GATE_EDIT", "scripts/check_literals.py": "REEL_ALLOW_LITERAL_EDIT",
    "tests/literal_allowlist.toml": "REEL_ALLOW_LITERAL_EDIT", ".git/hooks/": None, ".git/config": None}
WRITE_OPS = re.compile(r"(>|\bsed\s+-i|\btee\b|\bcp\b|\bmv\b|\brm\b|\btruncate\b|\bln\b|\bchmod\b|"
                       r"\bpython3?\b|\bperl\b|\bdd\b|\binstall\b|\brsync\b|\bgit\s+(checkout|restore|apply|mv|rm)\b)")
WRITE_PROGRAMS = {"tee", "cp", "mv", "rm", "truncate", "ln", "chmod", "perl", "dd", "install", "rsync"}
GIT_WRITES = {"checkout", "restore", "apply", "mv", "rm"}
COPY_PROGRAMS = {"cp", "mv", "install", "rsync", "ln"}
SAFE_PREFIXES = ("python3 .claude/hooks/selfcheck.py",)
# Running a guarded checker is not a write: `python3 scripts/check_literals.py <file>` stays allowed.
RUN_GUARDED = re.compile(r"\b(?:python3?|uv\s+run(?:\s+python3?)?)\s+[\"']?(?:[^\s\"']*/)?"
                         r"(?:scripts/gates/[\w./-]+\.py|scripts/check_literals\.py)[\"']?(?=[\s;&|)]|$)", re.I)
WORKFLOW_REF = re.compile(r"\.github/workflows(?:/([^\s;&|<>()]*))?", re.I)
WORKFLOWS = ("ci.yml", "deploy.yml")
COPY_INTO_DIR = re.compile(r"\b(cp|mv|install|rsync|ln)\b|\bgit\s+(checkout|restore)\b")

# `.env` in any case: on a Mac, cat .ENV reads .env.
ENV_REF = re.compile(r"(?<![\w.-])(?:[\w./-]*/)?(?i:\.env)(?:\.(?!(?i:example)\b)[\w-]+)?(?![\w.-])")
ENV_FILE = r"\s+(?:[\w./$\"{}-]*/)?(?i:\.env)(?![\w.-])"
NAMES_ONLY_GREP = re.compile(r"grep\s+-o\s+(['\"])\^\[A-Z_\]\*=\1" + ENV_FILE)
KEY_GREP = re.compile(r"grep\s+(-o\s+)?(['\"])\^(?:\\?\()?([A-Z_|\\]+?)(?:\\?\))?=\2" + ENV_FILE)


def block(reason: str) -> NoReturn:
    sys.stderr.write(f"Blocked by .claude/hooks/guard_bash.py: {reason}\n")
    sys.exit(2)


def unquote(text: str) -> str:
    """Drop quotes and backslashes: defeats .e""nv, .e\\nv and .cl"aude/."""
    return re.sub(r"[\"'\\\\]", "", text)


def env_read_allowed(cmd: str) -> bool:
    """Every .env reference must sit inside an allowed grep: names only (-o, pattern ends in '=')
    or the value of a non-secret key. Anything else touching .env is refused."""
    rest = NAMES_ONLY_GREP.sub(" ", cmd)

    def drop_if_allowed(m: re.Match[str]) -> str:
        keys = {k for k in re.split(r"\\?\|", m.group(3)) if k}
        return " " if m.group(1) or (keys and keys <= SAFE_ENV_KEYS) else m.group(0)

    rest = KEY_GREP.sub(drop_if_allowed, rest)
    plain = unquote(rest)
    if ENV_REF.search(plain):
        return False
    try:
        tokens = shlex.split(plain)
    except ValueError:
        tokens = plain.split()
    for token in tokens:                                 # defeat .en? and .*
        if any(ch in token for ch in "*?[") and fnmatch.fnmatch(".env", os.path.basename(token).lower()):
            return False
    return True


def simple_commands(cmd: str) -> list[list[str]]:
    """The words of each simple command in `cmd`, split on ; && || | & ( ) backticks and newlines.

    shlex resolves quotes and backslashes the way the shell does, so g"i"t reads as git and -\\n
    as -n, while a quoted argument such as -m "fix -n handling" stays one word."""
    text = cmd.replace("`", " ; ").replace("\n", " ; ")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:                                   # unbalanced quotes: bash refuses it as well
        tokens = unquote(text).split()
    result: list[list[str]] = []
    current: list[str] = []
    skip_target = False
    for token in tokens:
        if skip_target:                                  # the file after > or < is not an argument
            skip_target = False
        elif token in REDIRECTS:
            skip_target = True
        elif token and set(token) <= OPERATOR_CHARS:
            if current:
                result.append(current)
            current = []
        else:
            current.append(token)
    if current:
        result.append(current)
    return result


def split_words(argv: list[str]) -> tuple[list[str], list[str]]:
    """(NAME=value words, command words): drops leading assignments, shell keywords and wrappers
    such as sudo, env or time. NAME=value words given to env count as assignments."""
    assigns: list[str] = []
    i = 0
    while i < len(argv):
        if ASSIGNMENT.match(argv[i]):
            assigns.append(argv[i])
            i += 1
            continue
        wrapper = os.path.basename(argv[i]).lower()
        if wrapper not in WRAPPERS:
            break
        i += 1
        while i < len(argv) and argv[i].startswith("-") and len(argv[i]) > 1:
            i += 2 if argv[i] in WRAPPER_VALUE_OPTIONS.get(wrapper, ()) else 1
        if wrapper == "timeout" and i < len(argv):
            i += 1                                       # the duration
    return assigns, argv[i:]


def commands(cmd: str, depth: int = 0) -> Iterator[tuple[str, list[str], list[str], str]]:
    """(program in lowercase, arguments, NAME=value assignments, program as written) of every
    simple command, also inside `bash -c '...'` and `eval ...`. A bare assignment such as
    `SKIP=gitleaks;` is yielded with an empty program."""
    for argv in simple_commands(cmd):
        assigns, words = split_words(argv)
        if not words:
            if assigns:
                yield "", [], assigns, ""
            continue
        raw = os.path.basename(words[0])
        prog, args = raw.lower(), words[1:]
        if prog in ASSIGNERS:                            # export SKIP=gitleaks
            assigns = assigns + [a for a in args if ASSIGNMENT.match(a)]
        yield prog, args, assigns, raw
        if depth >= 3:
            continue
        if prog in SHELLS:
            for i, arg in enumerate(args[:-1]):
                if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", arg):
                    yield from commands(args[i + 1], depth + 1)
                    break
        elif prog == "eval":
            yield from commands(" ".join(args), depth + 1)


def positional(args: list[str]) -> list[str]:
    return [a for a in args if not a.startswith("-")]


def first(args: list[str]) -> str:
    words = positional(args)
    return words[0] if words else ""


def contains(words: list[str], seq: tuple[str, ...]) -> bool:
    return any(tuple(words[i:i + len(seq)]) == seq for i in range(len(words) - len(seq) + 1))


def git_parts(args: list[str]) -> tuple[str, list[str], list[str]]:
    """(subcommand, its arguments, values of git's own -c / --config-env options)."""
    configs: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-c", "--config-env"):
            configs.extend(args[i + 1:i + 2])
            i += 2
        elif arg.startswith("--config-env="):
            configs.append(arg.split("=", 1)[1])
            i += 1
        elif arg in GIT_VALUE_OPTIONS:
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            return arg, args[i + 1:], configs
    return "", [], configs


def no_verify(option: str) -> bool:
    """--no-verify, or an abbreviation git accepts for it (git takes --no-veri; --no-ver is ambiguous)."""
    return len(option) >= len("--no-veri") and "--no-verify".startswith(option)


def commit_skips_hooks(args: list[str]) -> bool:
    """True when `git commit <args>` passes --no-verify or -n, also inside clusters such as -nm."""
    i = 0
    while i < len(args):
        arg = args[i]
        i += 1
        if arg == "--":
            break
        if arg.startswith("--"):
            if no_verify(arg):
                return True
            if arg in COMMIT_VALUE_LONG:
                i += 1                                   # --message "text": the value is the next word
            continue
        if not arg.startswith("-") or arg == "-":
            continue
        for pos, flag in enumerate(arg[1:], start=1):
            if flag == "n":
                return True
            if flag in COMMIT_VALUE_SHORT:
                if pos == len(arg) - 1:
                    i += 1                               # -m "text": the value is the next word
                break                                    # -mtext: the rest of the cluster is the value
            if flag in COMMIT_ATTACHED_SHORT:
                break
    return False


def sets_hooks_path(args: list[str]) -> bool:
    """`git config [--scope] [set] core.hooksPath <value>`; reading or unsetting it is fine."""
    words = positional(args)
    for i, word in enumerate(words):
        if word.lower() == "core.hookspath":
            return i + 1 < len(words)
    return False


def clean_removes_ignored(args: list[str]) -> bool:
    """`git clean` with -x or -X (also inside -fdx), unless it is a dry run (-n, --dry-run)."""
    ignored = dry_run = False
    i = 0
    while i < len(args):
        arg = args[i]
        i += 1
        if arg == "--":
            break
        if arg.startswith("--"):
            dry_run = dry_run or (len(arg) >= 3 and "--dry-run".startswith(arg))
            if arg == "--exclude":
                i += 1
            continue
        if not arg.startswith("-") or arg == "-":
            continue
        for pos, flag in enumerate(arg[1:], start=1):
            if flag == "e":                              # -e <pattern>: the value is attached or next
                if pos == len(arg) - 1:
                    i += 1
                break
            dry_run = dry_run or flag == "n"
            ignored = ignored or flag in "xX"
    return ignored and not dry_run


def bypasses_hooks(assignment: str) -> bool:
    """SKIP=...gitleaks... (pre-commit skips that hook) or a GIT_CONFIG_* variable setting core.hooksPath."""
    name, _, value = assignment.partition("=")
    return (name == "SKIP" and "gitleaks" in value.lower()) or \
        (name.startswith("GIT_CONFIG") and "hookspath" in value.lower())


def api_merges(args: list[str]) -> bool:
    """gh api on a merge endpoint (.../pulls/N/merge, .../merges) or a GraphQL merge mutation."""
    words = positional(args)[1:]                         # after "api"
    if any(w.split("?", 1)[0].rstrip("/").lower().endswith(("/merge", "/merges")) for w in words):
        return True
    return first(args[1:]).lower() == "graphql" and \
        any("mergepullrequest" in a.lower() or "automerge" in a.lower() for a in args)


def command_rule(prog: str, args: list[str]) -> str | None:
    """The block reason for one simple command, or None."""
    if prog == "git":
        sub, rest, configs = git_parts(args)
        if sub in ("commit", "push") and any(c.lower().startswith("core.hookspath") for c in configs):
            return HOOKS_BYPASS
        if sub == "config" and sets_hooks_path(rest):
            return HOOKS_BYPASS
        if sub == "commit" and commit_skips_hooks(rest):
            return NO_VERIFY_COMMIT
        if sub == "push" and any(no_verify(a) for a in rest):
            return NO_VERIFY_PUSH
        if sub == "worktree" and first(rest) in ("remove", "prune"):
            return WORKTREES
        if sub == "clean" and clean_removes_ignored(rest):
            return CLEAN_IGNORED
    elif prog == "gh" and (contains(positional(args), ("pr", "merge")) or (first(args) == "api" and api_merges(args))):
        return MERGE
    elif prog == "terraform" and first(args) in TERRAFORM_STATE:
        return STATE_SURGERY
    elif prog == "gcloud" and any(contains(positional(args), seq) for seq in GCLOUD_DEPLOYS):
        return DEPLOY
    elif prog == "stripe" and any(a.startswith("--live") for a in args):
        return STRIPE_LIVE
    return None


def check_commands(cmd: str) -> None:
    found = list(commands(cmd))
    commits = any(prog == "git" and git_parts(args)[0] in ("commit", "push") for prog, args, _, _ in found)
    if commits and any(bypasses_hooks(a) for _, _, assigns, _ in found for a in assigns):
        block(HOOKS_BYPASS)
    for prog, args, _, raw in found:
        reason = command_rule(prog, args)
        if reason:
            block(reason)
        if raw != prog:                                  # GIT runs git on a Mac: give it the pattern rules too
            rebuilt = " ".join([prog, *args])
            for pattern, why in RULES:
                if re.search(pattern, rebuilt):
                    block(why)


def writes(text: str) -> bool:
    """A write operation: the WRITE_OPS patterns, or a writing program named in any case."""
    if WRITE_OPS.search(text):
        return True
    for prog, args, _, _ in commands(text):
        if prog in WRITE_PROGRAMS or prog.startswith("python"):
            return True
        if prog == "sed" and any(a.startswith(("-i", "--in-place")) for a in args):
            return True
        if prog == "git" and git_parts(args)[0] in GIT_WRITES:
            return True
    return False


def copies(text: str) -> bool:
    """A command that can put new files into a folder named in it (cp x .github/workflows/)."""
    return COPY_INTO_DIR.search(text) is not None or any(
        prog in COPY_PROGRAMS or (prog == "git" and git_parts(args)[0] in ("checkout", "restore"))
        for prog, args, _, _ in commands(text))


def names(path: str, low_text: str) -> bool:
    """`path` appears in lowercase text; a folder (trailing /) also matches without the slash."""
    key = path.lower()
    if not key.endswith("/"):
        return key in low_text
    return re.search(re.escape(key[:-1]) + r"(?:/|(?=[\s;&|)'\"`<>]|$))", low_text) is not None


def rm_target_bad(target: str, root: Path, temps: list[Path]) -> bool:
    if target in {"*", "/", "~", ".", ".."} or target.startswith(("~", "$HOME", "${HOME}", "..")):
        return True
    if target.startswith("/"):
        resolved = Path(target).resolve()
        return not (resolved == root or root in resolved.parents or _common.inside(resolved, temps))
    return False


def check_rm(cmd: str, root: Path) -> None:
    """Recursive rm may only target paths inside the repository or a temp folder."""
    temps = _common.temp_roots()
    for segment in re.split(r"&&|\|\||;|\|", cmd):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()
        while tokens and os.path.basename(tokens[0]).lower() in {"sudo", "command", "builtin"}:
            tokens = tokens[1:]
        if not tokens or os.path.basename(tokens[0]).lower() != "rm":
            continue
        flags = [t for t in tokens[1:] if t.startswith("-")]
        recursive = any(f in {"--recursive"} or (not f.startswith("--") and ("r" in f or "R" in f)) for f in flags)
        targets = [t for t in tokens[1:] if not t.startswith("-")]
        if recursive and any(rm_target_bad(t, root, temps) for t in targets):
            block("Recursive rm outside the repository (or on /, ~, $HOME, .., *) is not allowed.")


def check_protected(cmd: str) -> None:
    if cmd.strip().startswith(SAFE_PREFIXES):
        return
    raw, plain = RUN_GUARDED.sub(" ", cmd), RUN_GUARDED.sub(" ", unquote(cmd))
    for text in (raw, plain):
        if not writes(text):
            continue
        low = text.lower()
        for path, override in PROTECTED.items():
            if names(path, low) and (override is None or os.environ.get(override) != "1"):
                block(f"{path} is protected; it is not changed from the shell either. Ask Kevin.")
    if writes(plain):                                    # only ci.yml and deploy.yml may be written there
        for match in WORKFLOW_REF.finditer(plain):
            name = (match.group(1) or "").lower()
            if name in WORKFLOWS or (not name and not copies(plain)):
                continue
            block(NO_NEW_WORKFLOWS)


def check_push_stamp(cmd: str, root: Path) -> None:
    pushes = re.search(r"\bgit\b[^\n]*\bpush\b", cmd) or any(
        prog == "git" and git_parts(args)[0] == "push" for prog, args, _, _ in commands(cmd))
    if not pushes:
        return
    stamp = root / ".ci-pass"
    try:
        head = _common.git(root, "rev-parse", "HEAD", timeout=10).stdout.strip()
        current = stamp.read_text().strip() if stamp.exists() else ""
    except (OSError, subprocess.SubprocessError):
        block("Could not read HEAD to check the CI stamp.")
    if not current or current != head:
        block(f"Run `make ci` on this exact commit before pushing (.ci-pass must equal HEAD in {root}).")


def main() -> None:
    data = _common.read_input(sys.stdin)
    if data is None:
        block("Hook input was not JSON.")
    if data.get("tool_name") == "PowerShell":           # Claude Code offers PowerShell on native Windows only
        block(POWERSHELL)
    cmd = str(_common.tool_input(data).get("command") or "")
    for pattern, reason in RULES:
        if re.search(pattern, cmd):
            block(reason)
    check_commands(cmd)
    root = _common.repo_root(data)
    check_rm(cmd, root)
    check_protected(cmd)
    if not env_read_allowed(cmd):
        block("Do not read .env. Names only: grep -o '^[A-Z_]*=' .env")
    check_push_stamp(cmd, root)
    sys.exit(0)


if __name__ == "__main__":
    main()
