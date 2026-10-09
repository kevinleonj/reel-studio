"""User-facing words come from one table, web/src/copy/en.json (CLAUDE.md "user-facing messages
come from one table"): the emails reuse the page's failure messages instead of a second copy."""

import json
from functools import cache
from pathlib import Path
from typing import Any

COPY_FILE = Path(__file__).resolve().parents[2] / "web" / "src" / "copy" / "en.json"


@cache
def _copy() -> dict[str, Any]:  # Any: the JSON table, read by key below
    loaded: dict[str, Any] = json.loads(COPY_FILE.read_text(encoding="utf-8"))
    return loaded


def failure_message(code: str) -> str:
    """The order page's words for a failure code; an unknown code reads as a cutting failure,
    as on the page (web/src/components/order/StatusViews.tsx)."""
    messages: dict[str, str] = _copy()["order"]["failed"]["messages"]
    return messages.get(code, messages["render_error"])


def paused_message() -> str:
    paused: str = _copy()["order"]["paused"]
    return paused
