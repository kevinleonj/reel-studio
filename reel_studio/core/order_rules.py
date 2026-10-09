"""Order state transitions as pure functions (docs/ARCHITECTURE.md §4).

Both Orders adapters (the in-memory fake and Firestore) read the documents, call these functions
and write what they return, inside one transaction. A function returns None when the status
already moved on: that is what makes every transition idempotent.

Documents: `orders/{order_id}`, `limits/week-YYYY-Www` {count, cap}, `limits/capacity`
{slots: {order_id: lease_until}, paused}.
"""

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from reel_studio.core.errors import ErrorCode, WeekFull
from reel_studio.core.ports import NewOrder, QueueLimits

# Any: raw document fields as Firestore returns them; the shapes are fixed by this module.
Doc = dict[str, Any]

CAPACITY_ID = "capacity"


def week_id(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def week_doc_id(week: str) -> str:
    return f"week-{week}"


def empty_capacity() -> Doc:
    return {"slots": {}, "paused": False}


def reserve_place(week: Doc | None, cap: int) -> Doc:
    """One place per checkout, checked inside the creating transaction (F51)."""
    current = deepcopy(week) if week is not None else {"count": 0, "cap": cap}
    if current["count"] >= current["cap"]:
        raise WeekFull
    current["count"] += 1
    return current


def release_place(week: Doc | None) -> Doc | None:
    if week is None or week["count"] <= 0:
        return None
    released = deepcopy(week)
    released["count"] -= 1
    return released


def new_order(order: NewOrder, now: datetime) -> Doc:
    return {
        "order_id": order.order_id,
        "status": "awaiting_payment",
        "settings": dict(order.settings),
        "token_hash": order.token_hash,
        "email": order.email,
        "week_id": week_id(now),
        "place_held": True,
        "stripe": {},
        "files": [],
        "bytes_declared": 0,
        "queue": {},
        "stage": None,
        "stages_done": [],
        "result": None,
        "cost": None,
        "error": None,
        "feedback": None,
        "result_viewed_at": None,
        "emails": {},
        "created_at": now,
        "checkout_expires_at": order.checkout_expires_at,
        "paid_at": None,
        "finished_at": None,
    }


def _moved(doc: Doc | None, *statuses: str) -> Doc | None:
    """A copy to change, or None when the order is missing or in another status."""
    if doc is None or doc["status"] not in statuses:
        return None
    return deepcopy(doc)


def mark_paid(doc: Doc | None, stripe: dict[str, object], now: datetime) -> Doc | None:
    changed = _moved(doc, "awaiting_payment")
    if changed is not None:
        changed.update(status="paid", paid_at=now, stripe={**changed["stripe"], **stripe})
    return changed


def expire(doc: Doc | None) -> Doc | None:
    """Unconfirmed checkout: status expired; the caller releases the week's place."""
    changed = _moved(doc, "awaiting_payment")
    if changed is not None:
        changed.update(status="expired", place_held=False)
    return changed


def set_manifest(doc: Doc | None, files: list[dict[str, object]], bytes_declared: int) -> Doc:
    changed = _moved(doc, "paid")
    if changed is None:
        raise ValueError("order is not paid")
    changed.update(files=files, bytes_declared=bytes_declared)
    return changed


def queue(doc: Doc | None, now: datetime) -> Doc:
    changed = _moved(doc, "paid")
    if changed is None:
        raise ValueError("order is not paid")
    changed.update(status="queued", queue={**changed["queue"], "queued_at": now})
    return changed


def take_slot(
    doc: Doc | None, capacity: Doc, limits: QueueLimits, now: datetime, run_token: str
) -> tuple[Doc, Doc] | None:
    """queued -> running inside the slot transaction; None when no slot or not queued."""
    changed = _moved(doc, "queued")
    if changed is None or capacity["paused"] or len(capacity["slots"]) >= limits.running_max:
        return None
    lease_until = now + timedelta(minutes=limits.lease_minutes)
    changed.update(
        status="running",
        queue={
            **changed["queue"],
            "started_at": now,
            "lease_until": lease_until,
            "run_token": run_token,
        },
    )
    taken = deepcopy(capacity)
    taken["slots"][changed["order_id"]] = lease_until
    return changed, taken


def release_slot(capacity: Doc, order_id: str) -> Doc | None:
    if order_id not in capacity["slots"]:
        return None
    released = deepcopy(capacity)
    del released["slots"][order_id]
    return released


def set_stage(doc: Doc | None, name: str, now: datetime) -> Doc | None:
    changed = _moved(doc, "running")
    if changed is not None:
        _close_stage(changed)
        changed["stage"] = {"name": name, "started_at": now}
    return changed


def _close_stage(doc: Doc) -> None:
    if doc["stage"] is not None:
        doc["stages_done"] = [*doc["stages_done"], doc["stage"]["name"]]
        doc["stage"] = None


def finish(
    doc: Doc | None, result: dict[str, object], cost: dict[str, object], now: datetime
) -> Doc | None:
    changed = _moved(doc, "running")
    if changed is not None:
        _close_stage(changed)
        changed.update(status="done", result=result, cost=cost, finished_at=now)
    return changed


def fail(doc: Doc | None, code: ErrorCode, now: datetime) -> Doc | None:
    """running/queued -> failed. The week's place goes back (D22): the caller releases it when
    `place_held` was true on the input."""
    changed = _moved(doc, "running", "queued")
    if changed is not None:
        _close_stage(changed)
        changed.update(
            status="failed", error={"code": str(code)}, finished_at=now, place_held=False
        )
    return changed


def pause(doc: Doc | None, code: ErrorCode) -> Doc | None:
    """Spend limit (D26): the order waits as `paused`, keeping its place and its queue time."""
    changed = _moved(doc, "running")
    if changed is not None:
        _close_stage(changed)
        changed.update(status="paused", error={"code": str(code)})
    return changed


def mark_viewed(doc: Doc | None, now: datetime) -> Doc | None:
    changed = _moved(doc, "done")
    if changed is None or changed["result_viewed_at"] is not None:
        return None
    changed["result_viewed_at"] = now
    return changed


def set_feedback(doc: Doc | None, rating: int, comment: str, now: datetime) -> Doc | None:
    changed = _moved(doc, "done")
    if changed is not None:
        changed["feedback"] = {"rating": rating, "comment": comment, "at": now}
    return changed


def mark_deleted(doc: Doc | None) -> Doc | None:
    """ "Delete my files now" (D19): only once nothing is running on the files."""
    changed = _moved(doc, "done", "failed", "expired", "paid", "abandoned", "paused")
    if changed is not None:
        changed.update(status="deleted", place_held=False)
    return changed


def lease_expired(doc: Doc, now: datetime) -> bool:
    lease = doc["queue"].get("lease_until")
    return doc["status"] == "running" and lease is not None and lease <= now


def checkout_missed(doc: Doc, limits: QueueLimits, now: datetime) -> bool:
    deadline: datetime = doc["checkout_expires_at"] + timedelta(minutes=limits.expiry_grace_minutes)
    return doc["status"] == "awaiting_payment" and deadline <= now


def abandon(doc: Doc | None, limits: QueueLimits, now: datetime) -> Doc | None:
    """D25: paid but not started within the limit; the place is not returned."""
    changed = _moved(doc, "paid")
    if changed is None or changed["paid_at"] + timedelta(days=limits.paid_not_started_days) > now:
        return None
    changed["status"] = "abandoned"
    return changed
