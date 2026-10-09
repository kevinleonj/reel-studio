"""GET /health, GET /api/config, POST /api/checkout (docs/ARCHITECTURE.md §7)."""

import re
from datetime import timedelta
from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from reel_studio.api.deps import ApiDeps, client_address, deps_of, limiters_of
from reel_studio.api.errors import Refused, invalid
from reel_studio.api.tokens import hash_token, new_order_id, new_token
from reel_studio.core.constants import (
    BYTES_PER_GB,
    BYTES_PER_MIB,
    EMAIL_ADDRESS_MAX_CHARS,
    INVITE_CODE_MAX_CHARS,
)
from reel_studio.core.errors import DeliveryFailed, RateLimited
from reel_studio.core.logging import get_logger
from reel_studio.core.ports import NewOrder

log = get_logger(__name__)
router = APIRouter()


class CheckoutBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Any: validated against config/styles.toml and limits.toml in `check_settings`.
    settings: dict[str, Any]
    code: str = Field(default="", max_length=INVITE_CODE_MAX_CHARS)  # hidden when PAYMENTS=off
    email: str = Field(default="", max_length=EMAIL_ADDRESS_MAX_CHARS)  # optional (UX.md §2)


# One @, a dot in the domain, no whitespace (so no CR/LF): enough to refuse header injection
# and typos; the mail server decides the rest.
EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SETTING_KEYS = {"style", "length_s", "text_lang", "keep_voice", "chips", "note"}


def check_settings(deps: ApiDeps, raw: dict[str, Any]) -> dict[str, object]:
    """The order's settings, only with values the form offers (docs/UX.md §2, D14, D15)."""
    config = deps.config
    if set(raw) != SETTING_KEYS:
        raise invalid("settings keys")
    style, length, lang = raw["style"], raw["length_s"], raw["text_lang"]
    chips, note, voice = raw["chips"], raw["note"], raw["keep_voice"]
    # Types first: a list or dict would raise TypeError in the membership tests below.
    if not (isinstance(style, str) and isinstance(lang, str) and isinstance(note, str)):
        raise invalid("types")
    if isinstance(length, bool) or not isinstance(length, int) or not isinstance(voice, bool):
        raise invalid("types")
    if not isinstance(chips, list) or not all(isinstance(c, str) for c in chips):
        raise invalid("types")
    languages = {item.code for item in config.styles.text_languages.items}
    if (
        style not in config.styles.styles
        or length not in config.limits.order.lengths_s
        or lang not in languages
    ):
        raise invalid("style, length or language")
    if len(note) > config.limits.order.note_max_chars:
        raise invalid("note too long")
    if any(c not in config.styles.chips.items for c in chips) or len(set(chips)) != len(chips):
        raise invalid("unknown chip")
    if any(len(set(group) & set(chips)) > 1 for group in config.styles.chips.exclusive):
        raise invalid("exclusive chips")
    return {
        "style": style,
        "length_s": length,
        "text_lang": lang,
        "keep_voice": voice and deps.voice_available,
        "chips": chips,
        "note": note,
    }


@router.get("/health", response_class=PlainTextResponse)
def health() -> str:
    return "ok"


@router.get("/api/config")
def app_config(request: Request) -> dict[str, object]:
    deps = deps_of(request)
    limits, styles, web = deps.config.limits, deps.config.styles, deps.config.limits.web
    analytics_on = deps.settings.ga4_measurement_id != ""
    return {
        "payments": deps.settings.payments,
        "voice_available": deps.voice_available,
        "styles": [
            {"key": key, "voice_default": s.voice_default} for key, s in styles.styles.items()
        ],
        "chips": {"items": styles.chips.items, "exclusive": styles.chips.exclusive},
        "lengths_s": limits.order.lengths_s,
        "default_length_s": limits.order.default_length_s,
        "text_languages": [item.code for item in styles.text_languages.items],
        "note_max_chars": limits.order.note_max_chars,
        "limits": {
            "max_files": limits.order.max_files,
            "max_total_bytes": limits.order.max_total_bytes,
            "max_file_minutes": limits.order.max_file_minutes,
            "allowed_types": limits.order.allowed_types,
        },
        "upload": {
            "chunk_bytes": limits.upload.chunk_mib * BYTES_PER_MIB,
            "parallel_files": limits.upload.parallel_files,
            "chunk_retries": limits.upload.chunk_retries,
            "backoff_ms": limits.upload.backoff_ms,
        },
        "timeouts": {"request_ms": web.request_timeout_ms, "chunk_ms": web.chunk_timeout_ms},
        "poll_seconds": limits.limits.poll_seconds,
        "feedback": {"rating_max": web.rating_max, "comment_max_chars": web.comment_max_chars},
        "price": None,  # the €19 anchor arrives with Stripe (STEP-07)
        "analytics": {
            "enabled": analytics_on,
            "ga4_id": deps.settings.ga4_measurement_id,
            "ads_id": deps.settings.google_ads_id,
            "tag_url": web.google_tag_url if analytics_on else "",
        },
    }


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
                "order_url": f"{deps.settings.site_url.rstrip('/')}{path}",
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


@router.post("/api/checkout", response_model=None)
def checkout(body: CheckoutBody, request: Request) -> dict[str, str] | JSONResponse:
    deps = deps_of(request)
    if not limiters_of(request).checkout.allow(client_address(request)):
        raise RateLimited
    if deps.settings.payments != "off":
        log.error(
            "checkout with PAYMENTS=stripe is not wired before STEP-07",
            extra={"event": "checkout", "outcome": "refused"},
        )
        raise Refused("payments_not_wired", HTTPStatus.NOT_IMPLEMENTED)
    settings = check_settings(deps, body.settings)
    email = body.email.strip()
    if email and not EMAIL_SHAPE.match(email):  # also refuses CR/LF: no header injection
        raise invalid("email shape")
    order_id, token = new_order_id(), new_token()
    now = deps.clock.now()
    expires = now + timedelta(minutes=deps.config.limits.limits.checkout_expiry_minutes)
    deps.orders.create_awaiting_payment(
        NewOrder(order_id, hash_token(token), settings, email, expires)
    )
    # PAYMENTS=off: the order goes straight to paid.
    deps.orders.mark_paid(order_id, {"mode": "off"})
    path = f"/o/{order_id}#t={token}"
    if email:
        send_link(deps, order_id, email, path)
    log.info(
        "order created",
        extra={"order_id": order_id, "stage": "checkout", "event": "checkout", "outcome": "paid"},
    )
    return {"order_url": path}
