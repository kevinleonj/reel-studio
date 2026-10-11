"""The order routes behind the `X-Order-Token` header (docs/ARCHITECTURE.md §7)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from reel_studio.api import payments
from reel_studio.api.deps import ApiDeps, client_address, deps_of, limiters_of
from reel_studio.api.errors import invalid, not_found, wrong_status
from reel_studio.api.tokens import ORDER_ID, token_matches
from reel_studio.api.views import order_view
from reel_studio.core.constants import FILE_NAME_MAX_BYTES, UTF8_MAX_BYTES_PER_CHAR
from reel_studio.core.errors import (
    BadType,
    NameTooLong,
    NoFiles,
    OrderBusy,
    PaymentsFailed,
    RateLimited,
    TooLarge,
    TooManyFiles,
)
from reel_studio.core.file_names import check_file_name
from reel_studio.core.logging import get_logger
from reel_studio.core.order_rules import WrongState, upload_key
from reel_studio.core.ports import Record

log = get_logger(__name__)
router = APIRouter(prefix="/api/orders/{order_id}")


class Order:
    """The order a request may touch: right id, right token, else the same 404."""

    def __init__(self, deps: ApiDeps, order_id: str, doc: Record) -> None:
        self.deps = deps
        self.id = order_id
        self.doc = doc

    @property
    def status(self) -> object:
        return self.doc["status"]


def authorised(
    order_id: str,
    request: Request,
    token: Annotated[str | None, Header(alias="X-Order-Token")] = None,
) -> Order:
    deps = deps_of(request)
    if not limiters_of(request).order_calls.allow(client_address(request)):
        raise RateLimited
    doc = deps.orders.get(order_id) if ORDER_ID.fullmatch(order_id) else None
    if doc is None or not token_matches(token, doc.get("token_hash")):
        raise not_found()
    return Order(deps, order_id, doc)


Authorised = Annotated[Order, Depends(authorised)]


@router.get("")
def status(order: Authorised) -> dict[str, object]:
    deps = order.deps
    position = deps.orders.queue_position(order.id) if order.status == "queued" else None
    return order_view(
        order.doc,
        storage=deps.storage,
        now=deps.clock.now(),
        minutes=deps.config.limits.web.signed_url_minutes,
        queue_position=position,
    )


@router.post("/fulfil")
def fulfil(order: Authorised) -> None:
    """Stripe's success page: the same fulfilment as the webhook (§7). With PAYMENTS=off the
    order is already paid, and an order without a session has nothing to check."""
    stripe = order.doc["stripe"]
    session_id = stripe.get("session_id") if isinstance(stripe, dict) else None
    if order.deps.settings.payments == "off" or session_id is None:
        return
    try:
        payments.fulfil(order.deps, str(session_id))
    except PaymentsFailed:
        log.exception("stripe call failed", extra=payments.failure("fulfil", order.id))
        raise payments.unavailable() from None


@router.post("/cancel")
def cancel(order: Authorised) -> dict[str, object]:
    """Stripe's Cancel: release an unpaid checkout's place, refill the form. With PAYMENTS=off
    it changes nothing once paid."""
    if order.deps.settings.payments == "off":
        order.deps.orders.expire(order.id)
    else:
        payments.cancel(order.deps, order.id, order.doc)
    return {"settings": order.doc["settings"]}


class FileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=FILE_NAME_MAX_BYTES * UTF8_MAX_BYTES_PER_CHAR)
    size: int = Field(ge=0)
    type: str


class UploadBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[FileIn]


@router.post("/uploads")
def uploads(batch: UploadBatch, order: Authorised, request: Request) -> dict[str, object]:
    """Limits are checked on the whole batch plus what is already reserved (docs/UX.md §2)."""
    in_flight = limiters_of(request).uploads_in_flight
    if not in_flight.enter(order.id):
        raise OrderBusy("uploads")  # the page's own retry comes back after Retry-After
    try:
        return _uploads(batch, order)
    finally:
        in_flight.leave(order.id)


def _uploads(batch: UploadBatch, order: Order) -> dict[str, object]:
    if order.status != "paid":
        raise wrong_status()
    if not batch.files:
        raise NoFiles
    if len({upload_key(f.name) for f in batch.files}) != len(batch.files):
        raise invalid("the same file name twice in one batch")
    for file in batch.files:
        if len(file.name.encode()) > FILE_NAME_MAX_BYTES:
            raise NameTooLong(file.name)
    try:
        for file in batch.files:
            check_file_name(file.name)
    except ValueError as error:  # before the reservation, so a refused batch holds nothing
        raise invalid(str(error)) from error
    rules = order.deps.config.limits.order
    for file in batch.files:
        if file.type not in rules.allowed_types:
            raise BadType(file.name)
    try:
        order.deps.orders.reserve_uploads(
            order.id,
            files=[{"name": f.name, "size": f.size} for f in batch.files],
            max_files=rules.max_files,
            max_bytes=rules.max_total_bytes,
        )
    except WrongState:  # Start won the race
        raise wrong_status() from None
    try:
        targets = [
            order.deps.storage.create_upload_session(order.id, f.model_dump()) for f in batch.files
        ]
    except ValueError as error:  # an unsafe file name
        raise invalid(str(error)) from error
    return {"targets": [{"name": t["name"], "upload_url": t["upload_url"]} for t in targets]}


@router.get("/files")
def files(order: Authorised) -> dict[str, object]:
    listed = order.deps.storage.list_inputs(order.id)
    return {"files": [{"name": f["name"], "size": f["size"]} for f in listed]}


STARTED = {"queued", "running", "done"}


@router.post("/start")
def start(order: Authorised) -> None:
    """Write the manifest and queue; the dispatcher (or the cloud launcher) takes the slot.
    Safe to call twice: a second Start (a double tap, a retried request) answers 200."""
    if order.status in STARTED:
        return
    if order.status != "paid":
        raise wrong_status()
    listed = [
        {"name": f["name"], "size": f["size"]} for f in order.deps.storage.list_inputs(order.id)
    ]
    if not listed:
        raise NoFiles
    # The batch check counted only finished files; sessions opened in parallel batches can
    # finish past the limits, so the limits are checked again on what actually arrived.
    rules = order.deps.config.limits.order
    total = sum(int(str(f["size"])) for f in listed)
    if len(listed) > rules.max_files:
        raise TooManyFiles
    if total > rules.max_total_bytes:
        raise TooLarge
    try:
        order.deps.orders.set_manifest(order.id, files=listed, bytes_declared=total)
        order.deps.orders.queue(order.id)
    except WrongState:
        # Another Start won the race: answer as it did when the order really is started.
        current = order.deps.orders.get(order.id)
        if current is not None and current["status"] in STARTED:
            return
        raise wrong_status() from None
    log.info(
        "order queued",
        extra={"order_id": order.id, "stage": "start", "event": "queue", "outcome": "ok"},
    )


@router.post("/viewed")
def viewed(order: Authorised) -> None:
    order.deps.orders.mark_viewed(order.id)


class FeedbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int
    comment: str = ""  # default-because: the comment is optional (UX.md §2)


@router.post("/feedback")
def feedback(body: FeedbackBody, order: Authorised) -> None:
    web = order.deps.config.limits.web
    if not 1 <= body.rating <= web.rating_max or len(body.comment) > web.comment_max_chars:
        raise invalid("rating or comment out of range")
    if order.status != "done":
        raise wrong_status()
    order.deps.orders.set_feedback(order.id, rating=body.rating, comment=body.comment)


@router.delete("/files")
def delete_files(order: Authorised) -> None:
    """ "Delete my files now" (D19): in/, work/, out/ go, then the status says so."""
    if order.status in {"running", "queued", "awaiting_payment"}:
        raise wrong_status()
    order.deps.storage.delete_order(order.id)
    order.deps.orders.mark_deleted(order.id)
    log.info(
        "files deleted",
        extra={"order_id": order.id, "stage": "delete", "event": "delete", "outcome": "ok"},
    )
