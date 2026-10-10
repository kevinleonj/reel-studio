"""The order document as the page sees it (web/src/lib/types.ts `OrderView`): no token hash, no
email (only a mask), no storage keys (signed links instead), times as elapsed seconds."""

from collections.abc import Mapping
from datetime import datetime

from reel_studio.core.ports import Record, Storage

MASK = "•••"
VERSION_FILES = {"text": "reel-with-text.mp4", "clean": "reel-clean.mp4"}


def mask_email(email: object) -> str | None:
    if not isinstance(email, str) or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    return f"{local[:1]}{MASK}@{domain}"


def _result(result: object, storage: Storage, minutes: int) -> dict[str, object] | None:
    if not isinstance(result, Mapping):
        return None
    versions = []
    for version in result.get("versions", []):
        kind, key = str(version["kind"]), str(version["key"])
        url = storage.signed_url(key, VERSION_FILES.get(kind, f"{kind}.mp4"), minutes)
        versions.append({"kind": kind, "play_url": url, "download_url": url})
    return {
        "versions": versions,
        "duration_s": result.get("duration_s", 0),
        "caption": result.get("caption", ""),
        "text_lines": result.get("text_lines", []),
        "music": result.get("music", {"mood": "", "tempo": ""}),
        "left_out": result.get("left_out", []),
        "wishes": result.get("wishes", []),
        "doubts": result.get("doubts", []),
    }


def order_view(
    doc: Record, *, storage: Storage, now: datetime, minutes: int, queue_position: int | None
) -> dict[str, object]:
    stage = doc.get("stage")
    stage_view = None
    if isinstance(stage, Mapping):
        started = stage["started_at"]
        elapsed = int((now - started).total_seconds()) if isinstance(started, datetime) else 0
        stage_view = {"name": stage["name"], "elapsed_s": max(elapsed, 0)}
    error = doc.get("error")
    return {
        "status": doc["status"],
        "settings": doc["settings"],
        "email_hint": mask_email(doc.get("email")),
        "queue_position": queue_position,
        "stage": stage_view,
        "stages_done": list(doc.get("stages_done") or []),  # type: ignore[call-overload]
        "result": _result(doc.get("result"), storage, minutes) if doc["status"] == "done" else None,
        "error": {"code": error["code"]} if isinstance(error, Mapping) else None,
        "feedback_sent": doc.get("feedback") is not None,
    }
