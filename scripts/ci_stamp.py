#!/usr/bin/env python3
"""Last step of `make ci`: write HEAD into .ci-pass, only when the working tree is clean.

The push hook and the gates compare .ci-pass with HEAD, so the stamp means "make ci passed on
exactly this commit". A dirty tree passed for files that are not in any commit, so no stamp.
Standard library only: it runs under the system python3 (3.9 on a Mac).
"""

import subprocess
import sys
from pathlib import Path

STAMP = ".ci-pass"


def git(*args: str) -> str:
    done = subprocess.run(
        ["git", "--no-optional-locks", *args], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def main() -> int:
    root = Path(git("rev-parse", "--show-toplevel"))
    if git("status", "--porcelain", "--untracked-files=normal"):
        sys.stdout.write(f"make ci passed on a dirty tree: {STAMP} not written; commit first\n")
        return 0
    head = git("rev-parse", "HEAD")
    (root / STAMP).write_text(head + "\n", encoding="utf-8")
    sys.stdout.write(f"make ci passed: {STAMP} = {head}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
