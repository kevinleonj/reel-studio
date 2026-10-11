"""Payments port on Stripe, test mode during the beta (D58; FACTS F19-F24, F311, F313).

Every call goes through one `StripeClient` built with an explicit API version, network retries and
an HTTP timeout. Each call logs once with its latency. A Stripe error becomes PaymentsFailed
`from None` with the error's class and code only: Stripe's messages can echo the success URL,
which carries the order link's token, and the log prints the whole exception chain (review W5).
"""

import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import stripe
from stripe.params import PromotionCodeCreateParams, PromotionCodeListParams
from stripe.params.checkout import SessionCreateParams

from reel_studio.core.constants import MS_PER_S, PROMO_CODE_SUFFIX_BYTES
from reel_studio.core.errors import BadSignature, PaymentsFailed
from reel_studio.core.logging import get_logger
from reel_studio.core.ports import Clock, Record

log = get_logger(__name__)

COMPLETED = "checkout.session.completed"  # the two event types the API handles (F23)
EXPIRED = "checkout.session.expired"
CODE_CHARS = re.compile(r"[^A-Z0-9]")  # promotion codes are kept to capitals and digits


def build_client(
    api_key: str, *, api_version: str, timeout_s: float, max_network_retries: int
) -> stripe.StripeClient:
    """The default HTTP client waits 80 s (F311); this one waits `timeout_s`."""
    return stripe.StripeClient(
        api_key,
        stripe_version=api_version,
        max_network_retries=max_network_retries,
        http_client=stripe.RequestsClient(timeout=timeout_s),
    )


@dataclass(frozen=True)
class StripeSetup:
    """The account's own objects (`make stripe-setup`) and the webhook check (F23)."""

    price_id: str  # the 19 EUR price (D58)
    coupon_id: str  # the 100%-off coupon friends' codes are attached to
    webhook_secret: str
    tolerance_s: int  # how old a signed event may be


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * MS_PER_S)


class StripePayments:
    def __init__(self, client: stripe.StripeClient, clock: Clock, setup: StripeSetup) -> None:
        if not setup.webhook_secret:  # refuse at startup rather than at the first webhook
            raise ValueError("STRIPE_WEBHOOK_SECRET is empty")
        self._client = client
        self._clock = clock
        self._setup = setup

    @property
    def setup(self) -> StripeSetup:
        return self._setup

    def _call[T](self, event: str, order_id: str | None, call: Callable[[], T]) -> T:
        started = time.monotonic()
        extra: dict[str, Any] = {"order_id": order_id, "stage": "payments", "event": event}
        try:
            result = call()
        except stripe.StripeError as error:
            kind, code = type(error).__name__, getattr(error, "code", None)
            log.warning(
                "stripe %s failed: %s %s",
                event,
                kind,
                code,
                extra={**extra, "latency_ms": _elapsed_ms(started), "outcome": "error"},
            )
            raise PaymentsFailed(f"{event}: {kind} {code}") from None
        log.info(
            "stripe %s",
            event,
            extra={**extra, "latency_ms": _elapsed_ms(started), "outcome": "ok"},
        )
        return result

    # ------------------------------------------------------------ Payments

    def _promotion(self, code: str, *, active: bool | None) -> Any:  # Any: a StripeObject
        params: PromotionCodeListParams = {
            "code": code,
            "expand": ["data.promotion.coupon"],
            "limit": 1,
        }
        if active is not None:
            params["active"] = active
        found = self._call(
            "find_code", None, lambda: self._client.v1.promotion_codes.list(params=params)
        )
        return found.data[0] if found.data else None

    def find_code(self, code: str) -> Record | None:
        """An active code first; else any code of that name, so a used one says so (F21)."""
        promo = self._promotion(code, active=True) or self._promotion(code, active=None)
        if promo is None:
            return None
        coupon = promo.promotion.coupon
        now = int(self._clock.now().timestamp())
        ceiling = promo.max_redemptions
        used_up = ceiling is not None and promo.times_redeemed >= ceiling
        expired = promo.expires_at is not None and promo.expires_at <= now
        return {
            "promo_id": promo.id,
            "code": promo.code,
            "percent_off": coupon.percent_off if coupon is not None and coupon.valid else None,
            "active": bool(promo.active) and not used_up and not expired,
        }

    def create_checkout(
        self, order_id: str, promo_id: str, urls: Record, expires_at: datetime
    ) -> Record:
        params: SessionCreateParams = {
            "mode": "payment",
            "line_items": [{"price": self._setup.price_id, "quantity": 1}],
            "discounts": [{"promotion_code": promo_id}],  # never with allow_promotion_codes (F21b)
            "expires_at": int(expires_at.timestamp()),
            "client_reference_id": order_id,
            "success_url": str(urls["success"]),
            "cancel_url": str(urls["cancel"]),
        }
        session = self._call(
            "create_checkout",
            order_id,
            lambda: self._client.v1.checkout.sessions.create(params=params),
        )
        return {"session_id": session.id, "url": session.url, "amount_total": session.amount_total}

    def parse_webhook(self, payload: bytes, signature: str) -> Record:
        try:
            event = self._client.construct_event(
                payload, signature, self._setup.webhook_secret, tolerance=self._setup.tolerance_s
            )
        except (stripe.SignatureVerificationError, ValueError):
            raise BadSignature("webhook signature or body refused") from None
        if event.type not in (COMPLETED, EXPIRED):
            return {"type": event.type}
        session = event.data.object
        return {
            "type": event.type,
            "session_id": session.id,
            "order_id": getattr(session, "client_reference_id", None),
        }

    def get_session(self, session_id: str) -> Record:
        session = self._call(
            "get_session",
            None,
            lambda: self._client.v1.checkout.sessions.retrieve(session_id),
        )
        details = session.customer_details
        return {
            "session_id": session.id,
            "status": session.status,
            "payment_status": session.payment_status,
            "order_id": session.client_reference_id,
            "email": details.email if details is not None else None,
            "success_url": session.success_url,
        }

    # ------------------------------------------------------------ PaymentsUpkeep

    def expire_session(self, session_id: str) -> None:
        self._call(
            "expire_session",
            None,
            lambda: self._client.v1.checkout.sessions.expire(session_id),
        )

    def create_code(self, *, name: str, expires_at: datetime, max_redemptions: int) -> Record:
        stem = CODE_CHARS.sub("", name.upper())
        code = f"{stem}-{secrets.token_hex(PROMO_CODE_SUFFIX_BYTES).upper()}"
        params: PromotionCodeCreateParams = {
            "promotion": {"type": "coupon", "coupon": self._setup.coupon_id},
            "code": code,
            "max_redemptions": max_redemptions,
            "expires_at": int(expires_at.timestamp()),
        }
        promo = self._call(
            "create_code", None, lambda: self._client.v1.promotion_codes.create(params=params)
        )
        return {"code": promo.code, "promo_id": promo.id}

    def expire_code(self, code: str) -> bool:
        promo = self._promotion(code, active=True)
        if promo is None:
            return False
        self._call(
            "expire_code",
            None,
            lambda: self._client.v1.promotion_codes.update(promo.id, params={"active": False}),
        )
        return True
