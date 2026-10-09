"""Failure emails (docs/UX.md §3): the customer's "Your Reel didn't finish" when they gave an
address, and Kevin's alert for every failure (EDITOR.md §10). Each is claimed on the order first
(`claim_email`), so a sweep that runs twice never sends twice. A mail server that is down is
logged and never stops the caller (the dispatcher, the sweep).

The "ready" email is not sent from here yet: its button needs the order link, and the link's
token is stored only as a hash (D18), so nothing after checkout can rebuild it (Needs Kevin).
"""

from reel_studio.api.messages import failure_message
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

    def order_failed(self, order_id: str, code: ErrorCode, stage: str) -> None:
        """`stage` names where it broke when the order cannot say (no stage was ever set)."""
        doc = self._orders.get(order_id)
        if doc is None:
            return
        done = doc.get("stages_done")
        where = str(done[-1]) if isinstance(done, list) and done else stage
        email = doc.get("email")
        if self._orders.claim_email(order_id, "failed") and isinstance(email, str) and email:
            self._send(
                "failed",
                email,
                {
                    "order_id": order_id,
                    "message": failure_message(str(code)),
                    "start_url": f"{self._site}/new",
                },
            )
        if self._orders.claim_email(order_id, "kevin"):
            alert: dict[str, object] = {
                "order_id": order_id,
                "status": "failed",
                "stage": where,
                "code": str(code),
            }
            self._send("kevin", self._kevin, alert)
