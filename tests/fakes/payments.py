"""Payments port in memory: promotion codes, Checkout Sessions and signed webhook events, shaped
like the Stripe adapter's answers (FACTS F19-F24, F311)."""

import json
from collections.abc import Mapping
from datetime import datetime

from reel_studio.core.errors import BadSignature, PaymentsFailed
from reel_studio.core.ports import Record

VALID_SIGNATURE = "fake-valid-signature"


class FakePayments:
    def __init__(self) -> None:
        self.codes: dict[str, dict[str, object]] = {}
        self.sessions: dict[str, dict[str, object]] = {}
        self.created: list[dict[str, object]] = []
        self.expired: list[str] = []
        self.fail_next_checkout = False
        self.next_amount_total = 0  # what Stripe would charge for the next session

    def add_code(self, code: str, *, percent_off: float, active: bool = True) -> None:
        self.codes[code.upper()] = {
            "promo_id": f"promo_{code.lower()}",
            "code": code,
            "percent_off": percent_off,
            "active": active,
        }

    # ------------------------------------------------------------ Payments

    def find_code(self, code: str) -> Record | None:
        return self.codes.get(code.upper())  # Stripe matches codes case-insensitively (F21)

    def create_checkout(
        self, order_id: str, promo_id: str, urls: Record, expires_at: datetime
    ) -> Record:
        if self.fail_next_checkout:
            self.fail_next_checkout = False
            raise PaymentsFailed("stripe unavailable")
        session_id = f"cs_test_{len(self.sessions)}"
        self.sessions[session_id] = {
            "status": "open",
            "payment_status": "unpaid",
            "order_id": order_id,
            "email": None,  # Stripe collects it on its page
            "success_url": urls["success"],
        }
        self.created.append(
            {
                "order_id": order_id,
                "promo_id": promo_id,
                "urls": dict(urls),
                "expires_at": expires_at,
            }
        )
        return {
            "session_id": session_id,
            "url": f"fake://checkout/{session_id}",
            "amount_total": self.next_amount_total,
        }

    def parse_webhook(self, payload: bytes, signature: str) -> Record:
        if signature != VALID_SIGNATURE:
            raise BadSignature("signature does not match")
        event: dict[str, object] = json.loads(payload)
        return event

    def get_session(self, session_id: str) -> Record:
        if session_id not in self.sessions:
            raise PaymentsFailed(f"no such session {session_id}")
        return {"session_id": session_id, **self.sessions[session_id]}

    # ------------------------------------------------------------ PaymentsUpkeep

    def expire_session(self, session_id: str) -> None:
        if self.sessions.get(session_id, {}).get("status") != "open":
            raise PaymentsFailed(f"session {session_id} is not open")  # as Stripe answers
        self.expired.append(session_id)
        self.sessions[session_id]["status"] = "expired"

    def create_code(self, *, name: str, expires_at: datetime, max_redemptions: int) -> Record:
        code = f"{name.upper()}-FAKE"
        self.add_code(code, percent_off=100)
        self.codes[code.upper()].update(expires_at=expires_at, max_redemptions=max_redemptions)
        return {"code": code, "promo_id": self.codes[code.upper()]["promo_id"]}

    def expire_code(self, code: str) -> bool:
        found = self.codes.get(code.upper())
        if found is None or not found["active"]:
            return False
        found["active"] = False
        return True

    # ------------------------------------------------------------ test helpers

    def complete(self, session_id: str, email: str) -> None:
        """The customer confirmed the €0 checkout."""
        self.sessions[session_id].update(
            status="complete", payment_status="no_payment_required", email=email
        )

    def event(self, kind: str, session_id: str) -> bytes:
        """A webhook body as the adapter reduces it: the type and which session (F23)."""
        session: Mapping[str, object] = self.sessions[session_id]
        body = {"type": kind, "session_id": session_id, "order_id": session["order_id"]}
        return json.dumps(body).encode()
