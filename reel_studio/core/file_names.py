"""Which uploaded file names a store may hold: one rule for the route, which checks a batch before
reserving anything, and for the storage adapters, which check again (review round 1)."""

import re

SAFE_NAME = re.compile(r"^[^/\\\x00]+$")  # no path separator, no NUL


def check_file_name(name: str) -> str:
    if not SAFE_NAME.match(name) or name.startswith(".") or name in {"", "..", "."}:
        raise ValueError(f"unsafe file name: {name!r}")
    return name
