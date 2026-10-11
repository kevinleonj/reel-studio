"""PAYMENTS=stripe: checkout with a promotion code, fulfilment, expiry and the sweep's Stripe check
(docs/ARCHITECTURE.md §2 and §7, D22, D58).

Fulfilment always re-reads the session from Stripe, so a forged or stale event changes nothing,
and every write is an idempotent order transition, so the webhook, the success page and the
sweep may all run it for the same session. The link email needs the token; the token is never
stored (D18), but it is in the session's success URL, which Stripe gives back with the session.
"""

from datetime import timedelta
from http import HTTPStatus
from typing import Annotated
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, Request

from reel_studio.api.deps import ApiDeps, deps_of
from reel_studio.api.errors import Refused, wrong_status
from reel_studio.api.notify import send_link
from reel_studio.api.tokens import hash_token, new_order_id, new_token, token_matches
from reel_studio.core.constants import FULL_DISCOUNT_PERCENT
from reel_studio.core.errors import BadSignature, CodeInactive, CodeInvalid, PaymentsFailed
from reel_studio.core.logging import get_logger
from reel_studio.core.ports import NewOrder, PaymentGateway, Record, SweepReport

log = get_logger(__name__)
router = APIRouter()

PAID = {"paid", "no_payment_required"}  # Checkout Session payment_status (F22)
COMPLETED = "checkout.session.completed"  # webhook event types (F23)
EXPIRED = "checkout.session.expired"


def gateway(deps: ApiDeps) -> PaymentGateway:
    if deps.payments is None:  # create_app refuses PAYMENTS=stripe without an adapter
        raise RuntimeError("PAYMENTS=stripe without a Payments adapter")
    return deps.payments


def failure(event: str, order_id: str | None) -> dict[str, object]:
    """Log context of a failed Stripe call; logged with `log.exception` in its except block."""
    return {"order_id": order_id, "stage": "payments", "event": event, "outcome": "error"}


def unavailable() -> Refused:
    return Refused("payments_unavailable", HTTPStatus.BAD_GATEWAY)


def checkout(deps: ApiDeps, settings: Record, code: str) -> dict[str, str]:
    """Find the code, reserve the place with the order, open the session; on a Stripe error give
    the place back in a second transaction."""
    payments = gateway(deps)
    try:
        found = payments.find_code(code) if code else None
    except PaymentsFailed:
        log.exception("stripe call failed", extra=failure("find_code", None))
        raise unavailable() from None
    if found is None or found["percent_off"] != FULL_DISCOUNT_PERCENT:
        raise CodeInvalid
    if not found["active"]:
        raise CodeInactive
    order_id, token = new_order_id(), new_token()
    expires = deps.clock.now() + timedelta(
        minutes=deps.config.limits.limits.checkout_expiry_minutes
    )
    deps.orders.create_awaiting_payment(
        NewOrder(order_id, hash_token(token), settings, "", expires)
    )
    site = deps.settings.site_url.rstrip("/")
    urls = {
        "success": f"{site}/o/{order_id}?t={token}",  # the page moves it behind # at once (§7)
        "cancel": f"{site}/new?cancel={order_id}&t={token}",
    }
    try:
        session = payments.create_checkout(order_id, str(found["promo_id"]), urls, expires)
    except PaymentsFailed:
        log.exception("stripe call failed", extra=failure("create_checkout", order_id))
        deps.orders.expire(order_id)
        raise unavailable() from None
    if session.get("amount_total") != 0:  # nullable in Stripe's spec: unknown is not zero
        # D58: a code's restrictions can leave the price due even at 100% off; nobody pays.
        log.error(
            "checkout session would charge; expired",
            extra={"order_id": order_id, "stage": "checkout", "event": "checkout"},
        )
        _close_unpaid(deps, order_id, str(session["session_id"]))
        raise CodeInvalid
    deps.orders.set_checkout(order_id, session_id=str(session["session_id"]))
    log.info(
        "checkout opened",
        extra={"order_id": order_id, "stage": "checkout", "event": "checkout", "outcome": "open"},
    )
    return {"checkout_url": str(session["url"])}


def _close_unpaid(deps: ApiDeps, order_id: str, session_id: str) -> None:
    try:
        gateway(deps).expire_session(session_id)
    except PaymentsFailed:
        # The session dies by itself at its expires_at (31 min); the place is freed now anyway.
        log.exception("stripe call failed", extra=failure("expire_session", order_id))
    deps.orders.expire(order_id)


def _belongs(doc: Record | None, session_id: str) -> bool:
    """The session is this order's: a crash before `set_checkout` leaves no id to compare."""
    if doc is None:
        return False
    stripe = doc["stripe"]
    known = stripe.get("session_id") if isinstance(stripe, dict) else None
    return known is None or known == session_id


def fulfil(deps: ApiDeps, session_id: str) -> None:
    """Pay the order of a completed session and send its link email once (§4). Raises
    PaymentsFailed when Stripe cannot be read."""
    session = gateway(deps).get_session(session_id)
    order_id = str(session["order_id"])
    doc = deps.orders.get(order_id)
    outcome = "ignored"
    if not _belongs(doc, session_id):
        outcome = "refused"  # a session that names another order
    elif session["status"] == "complete" and session["payment_status"] in PAID:
        email = session["email"] if isinstance(session["email"], str) else ""
        deps.orders.mark_paid(order_id, {"session_id": session_id, "email": email})
        after = deps.orders.get(order_id)
        outcome = str(after["status"]) if after is not None else "missing"
        if outcome == "expired":
            log.error(
                "stripe completed a checkout whose order had expired",
                extra={"order_id": order_id, "stage": "payments", "event": "fulfil"},
            )
        _link_email(deps, order_id, email, str(session["success_url"]))
    log.info(
        "fulfil",
        extra={"order_id": order_id, "stage": "payments", "event": "fulfil", "outcome": outcome},
    )


def _link_email(deps: ApiDeps, order_id: str, email: str, success_url: str) -> None:
    doc = deps.orders.get(order_id)
    if not email or doc is None or doc["status"] == "expired":
        return
    token = parse_qs(urlsplit(success_url).query).get("t", [""])[0]
    if not token_matches(token, doc["token_hash"]):
        log.error(
            "success URL token does not match the order",
            extra={"order_id": order_id, "stage": "payments", "event": "link_email"},
        )
        return
    if deps.orders.claim_email(order_id, "link"):
        send_link(deps, order_id, email, f"/o/{order_id}#t={token}")


def expire(deps: ApiDeps, order_id: str, session_id: str) -> None:
    if _belongs(deps.orders.get(order_id), session_id):
        deps.orders.expire(order_id)


def cancel(deps: ApiDeps, order_id: str, doc: Record) -> None:
    """Stripe's Cancel button: expire the open session first, so it cannot be paid after its
    place is gone; a session that completed meanwhile is fulfilled instead."""
    stripe = doc["stripe"]
    session_id = stripe.get("session_id") if isinstance(stripe, dict) else None
    if doc["status"] not in ("awaiting_payment", "expired"):
        raise wrong_status()
    if doc["status"] == "awaiting_payment" and session_id is not None:
        try:
            session = gateway(deps).get_session(str(session_id))
            if session["status"] == "complete":
                fulfil(deps, str(session_id))
                raise wrong_status()
            if session["status"] == "open":
                gateway(deps).expire_session(str(session_id))
        except PaymentsFailed:
            log.exception("stripe call failed", extra=failure("cancel", order_id))
            raise unavailable() from None
    deps.orders.expire(order_id)


def check_checkouts(deps: ApiDeps) -> list[str]:
    """Missed webhooks: each checkout past its expiry and the grace is asked about at Stripe."""
    expired = []
    for doc in deps.orders.checkouts_to_check():
        order_id = str(doc["order_id"])
        try:
            if _check_one(deps, order_id, doc):
                expired.append(order_id)
        except Exception:
            # Any error (Stripe unreachable, a session shape we cannot use) keeps this checkout
            # for the next sweep, since expiring it could drop one Stripe completed; the others
            # are still checked. Logged with its traceback.
            log.exception("checkout not checked", extra=failure("sweep_check", order_id))
    return expired


def _check_one(deps: ApiDeps, order_id: str, doc: Record) -> bool:
    """True when the checkout was expired; a completed session is fulfilled instead."""
    stripe = doc["stripe"]
    session_id = stripe.get("session_id") if isinstance(stripe, dict) else None
    if session_id is not None:
        session = gateway(deps).get_session(str(session_id))
        if session["status"] == "complete":
            fulfil(deps, str(session_id))
            return False
        if session["status"] == "open":
            gateway(deps).expire_session(str(session_id))
    deps.orders.expire(order_id)
    return True


def sweep(deps: ApiDeps) -> SweepReport:
    """The sweep (§7). Dead leases and stale orders first, since they need no outside call; then,
    with Stripe, missed checkouts are checked there before they expire."""
    if deps.settings.payments == "off":
        return deps.orders.sweep(expire_checkouts=True)
    report = deps.orders.sweep(expire_checkouts=False)
    try:
        report["expired"] = report["expired"] + check_checkouts(deps)
    except Exception:
        # The local phase already changed orders; its report carries their failure notices, so
        # it is returned whatever the Stripe phase does. Logged with its traceback.
        log.exception("checkouts not checked", extra=failure("sweep_check", None))
    return report


async def raw_body(request: Request) -> bytes:
    """The exact bytes Stripe signed; read here so the route itself can stay synchronous."""
    return await request.body()


@router.post("/api/stripe/webhook")
def webhook(request: Request, payload: Annotated[bytes, Depends(raw_body)]) -> dict[str, str]:
    deps = deps_of(request)
    if deps.settings.payments == "off":
        raise Refused("payments_off", HTTPStatus.NOT_FOUND)
    try:
        event = gateway(deps).parse_webhook(payload, request.headers.get("Stripe-Signature", ""))
    except BadSignature:
        log.warning(
            "webhook signature refused",
            extra={"stage": "payments", "event": "webhook", "outcome": "refused"},
        )
        raise Refused("bad_signature", HTTPStatus.BAD_REQUEST) from None
    kind = str(event["type"])
    if kind not in (COMPLETED, EXPIRED):  # `stripe listen` forwards every type (F313)
        return {"received": kind}
    session_id, order_id = str(event["session_id"]), str(event["order_id"])
    try:
        if kind == COMPLETED:
            fulfil(deps, session_id)
        else:
            expire(deps, order_id, session_id)
    except PaymentsFailed:
        # Not 2xx, so Stripe delivers the event again later (F23).
        log.exception("stripe call failed", extra=failure("webhook", order_id))
        raise unavailable() from None
    return {"received": kind}
