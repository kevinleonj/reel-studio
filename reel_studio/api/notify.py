"""Failure emails (docs/UX.md §3): the customer's "Your Reel didn't finish" when they gave an
address, and Kevin's alert for every failure (EDITOR.md §10). Each is claimed on the order first
(`claim_email`), so a sweep that runs twice never sends twice. A mail server that is down is
logged and never stops the caller (the dispatcher, the sweep).

The "ready" email (`order_ready`, sent by the editor job) carries no link: the link's token is
stored only as a hash (D18), so nothing after checkout can rebuild it; it points to the link in
the first email instead (decided by standing orders, HANDOFF.md).
"""

from collections.abc import Callable

from reel_studio.api.deps import ApiDeps
from reel_studio.api.messages import failure_message, paused_message
from reel_studio.core.constants import BYTES_PER_GB
from reel_studio.core.errors import DeliveryFailed, ErrorCode
from reel_studio.core.logging import get_logger
from reel_studio.core.ports import Mailer, OrderStore

log = get_logger(__name__)


class Notifier:
    def __init__(self, orders: OrderStore, mailer: Mailer, *, site_url: str, kevin: str) -> None:
        self._orders = orders
        self._mailer = mailer
        self._site = site_url.rstrip("/")
        self._kevin = kevin

    def _send(self, template: str, to: str, data: dict[str, object]) -> None:
        try:
            self._mailer.send(template, to, data)
        except DeliveryFailed:
            log.exception(
                "email %s not delivered",
                template,
                extra={
                    "order_id": data.get("order_id"),
                    "stage": "notify",
                    "event": template,
                    "outcome": "error",
                },
            )

    def order_ready(self, order_id: str, *, out_days: int) -> None:
        """The customer's "Your Reel is ready", once. It carries no link: the token is stored
        only as a hash (D18), so it points to the first email's link instead."""
        doc = self._orders.get(order_id)
        if doc is None or doc["status"] != "done":
            return
        email = doc.get("email")
        if not (isinstance(email, str) and email):
            return
        result = doc.get("result")
        caption = result.get("caption") if isinstance(result, dict) else None
        lines = str(caption).splitlines() if caption else []
        hook = lines[0] if lines else ""
        if self._orders.claim_email(order_id, "ready"):
            self._send("ready", email, {"order_id": order_id, "hook": hook, "out_days": out_days})

    def order_paused(self, order_id: str, stage: str) -> None:
        """The month's spend limit paused the order (D26): Kevin's alert (D45) and the customer's
        "Your Reel is waiting", once each. Claimed apart from the failure emails, so a paused
        order that fails later still alerts Kevin."""
        doc = self._orders.get(order_id)
        if doc is None or doc["status"] != "paused":
            return
        if self._orders.claim_email(order_id, "kevin_paused"):
            alert: dict[str, object] = {
                "order_id": order_id,
                "status": "paused",
                "stage": stage,
                "code": str(ErrorCode.SPEND_LIMIT),
            }
            self._send("kevin", self._kevin, alert)
        email = doc.get("email")
        if not (isinstance(email, str) and email):
            return
        try:
            # Built before the claim: if the words cannot be read, the email stays unclaimed.
            paused: dict[str, object] = {"order_id": order_id, "message": paused_message()}
        except (OSError, ValueError, KeyError):
            log.exception(
                "customer pause email could not be built",
                extra={
                    "order_id": order_id,
                    "stage": "notify",
                    "event": "paused",
                    "outcome": "error",
                },
            )
            return
        if self._orders.claim_email(order_id, "paused"):
            self._send("paused", email, paused)

    def order_failed(self, order_id: str, code: ErrorCode, stage: str) -> None:
        """`stage` names where it broke when the order cannot say (no stage was ever set)."""
        doc = self._orders.get(order_id)
        if doc is None or doc["status"] != "failed":
            return  # a sweep that raced a finish must not say "didn't finish"
        done = doc.get("stages_done")
        where = str(done[-1]) if isinstance(done, list) and done else stage
        # Kevin first: his alert needs nothing from the copy table, so nothing below can stop it.
        if self._orders.claim_email(order_id, "kevin"):
            alert: dict[str, object] = {
                "order_id": order_id,
                "status": "failed",
                "stage": where,
                "code": str(code),
            }
            self._send("kevin", self._kevin, alert)
        email = doc.get("email")
        if not (isinstance(email, str) and email):
            return
        try:
            # Built before the claim: if the words cannot be read, the email stays unclaimed.
            failed: dict[str, object] = {
                "order_id": order_id,
                "message": failure_message(str(code)),
                "start_url": f"{self._site}/new",
            }
        except (OSError, ValueError, KeyError):
            # Nothing retries this later (the sweep reports an order once): logged for Kevin,
            # whose alert above already went out.
            log.exception(
                "customer failure email could not be built",
                extra={
                    "order_id": order_id,
                    "stage": "notify",
                    "event": "failed",
                    "outcome": "error",
                },
            )
            return
        if self._orders.claim_email(order_id, "failed"):
            self._send("failed", email, failed)


def notifier(deps: ApiDeps) -> Notifier:
    return Notifier(
        deps.orders,
        deps.mailer,
        site_url=deps.runtime.site_url,
        kevin=deps.runtime.kevin_alert_email,
    )


def launch_failed(deps: ApiDeps) -> Callable[[str], None]:
    """What launch_waiting calls for an order it had to fail: Kevin's alert and the customer's
    email, never an error into the request that started it."""
    tell = notifier(deps)

    def failed(order_id: str) -> None:
        try:
            tell.order_failed(order_id, ErrorCode.JOB_KILLED, "launch")
        except Exception:
            # Logged with its traceback; the order's own state is already written.
            log.exception(
                "failure notice not sent",
                extra={
                    "order_id": order_id,
                    "stage": "start",
                    "event": "notify",
                    "outcome": "error",
                },
            )

    return failed


def send_link(deps: ApiDeps, order_id: str, email: str, path: str) -> None:
    """The optional link email. The order already exists and the page already has the link, so
    a mail server that is down is logged, not turned into a failed checkout."""
    limits = deps.config.limits
    try:
        deps.mailer.send(
            "link",
            email,
            {
                "order_id": order_id,
                "order_url": f"{deps.runtime.site_url.rstrip('/')}{path}",
                "max_files": limits.order.max_files,
                "max_total": f"{limits.order.max_total_bytes // BYTES_PER_GB} GB",
                "out_days": limits.retention.out_days,
            },
        )
    except DeliveryFailed:
        log.exception(
            "link email not delivered",
            extra={
                "order_id": order_id,
                "stage": "checkout",
                "event": "link_email",
                "outcome": "error",
            },
        )
