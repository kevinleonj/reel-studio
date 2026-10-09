"""Cloud adapter for the Mailer port: Resend's REST API over httpx (D56).

The REST call needs no SDK: `POST /emails` with a bearer key and an `Idempotency-Key` header, so
a retry after a timeout cannot send the same email twice (Resend keeps a key for 24 hours). The
template is rendered by the caller's renderer, the same one the laptop's Mailpit adapter uses.
The base URL and timeouts come with the injected httpx.Client.
"""

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from pydantic import SecretStr

from reel_studio.core import ports
from reel_studio.core.errors import CloudUnavailable
from reel_studio.core.logging import get_logger, latency_ms

log = get_logger(__name__)

# Resend REST: send one email (https://resend.com/docs/api-reference/emails/send-email).
EMAILS_PATH = "/emails"
IDEMPOTENCY_HEADER = "Idempotency-Key"
# A 409 with this name means the same key is still in flight, so trying again is safe.
CONCURRENT_KEY = "concurrent_idempotent_requests"


@dataclass(frozen=True)
class Email:
    subject: str
    html: str
    text: str


@dataclass(frozen=True)
class ResendConfig:
    api_key: SecretStr
    sender: str  # "Reel Studio <reels@...>", an address on the verified domain (D56)


@dataclass(frozen=True)
class Backoff:
    """Bounded retry: `retries` more attempts, waiting base_s, 2 x base_s, 4 x base_s ..."""

    retries: int
    base_s: float
    sleep: Callable[[float], None]

    def wait(self, attempt: int) -> None:
        if attempt:
            self.sleep(self.base_s * 2 ** (attempt - 1))


Render = Callable[[str, ports.Record], Email]


def idempotency_key(template: str, to: str, data: ports.Record) -> str:
    """Same template, address and data give the same key: a repeated send is a no-op."""
    payload = json.dumps([template, to, data], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def transient(response: httpx.Response) -> bool:
    if response.status_code == httpx.codes.TOO_MANY_REQUESTS or response.is_server_error:
        return True
    if response.status_code == httpx.codes.CONFLICT:
        try:
            return bool(response.json().get("name") == CONCURRENT_KEY)
        except ValueError:
            return False  # a body that is not JSON is not the documented transient conflict
    return False


class ResendMailer:
    def __init__(
        self, client: httpx.Client, config: ResendConfig, render: Render, backoff: Backoff
    ) -> None:
        self._client = client
        self._config = config
        self._render = render
        self._backoff = backoff

    def send(self, template: str, to: str, data: ports.Record) -> None:
        email = self._render(template, data)
        body = {
            "from": self._config.sender,
            "to": [to],
            "subject": email.subject,
            "html": email.html,
            "text": email.text,
        }
        headers = {
            "Authorization": f"Bearer {self._config.api_key.get_secret_value()}",
            IDEMPOTENCY_HEADER: idempotency_key(template, to, data),
        }
        order_id = data.get("order_id")
        problem = ""
        for attempt in range(self._backoff.retries + 1):
            self._backoff.wait(attempt)
            started = time.monotonic()
            try:
                response = self._client.post(EMAILS_PATH, json=body, headers=headers)
            except httpx.TransportError as exc:
                problem = type(exc).__name__
                _log(template, order_id, started, "retry", problem)
                continue
            if response.is_success:
                _log(template, order_id, started, "ok", str(response.status_code))
                return
            problem = f"HTTP {response.status_code}"
            if not transient(response):
                _log(template, order_id, started, "error", problem)
                raise CloudUnavailable(f"resend refused the {template} email: {problem}")
            _log(template, order_id, started, "retry", problem)
        raise CloudUnavailable(
            f"resend failed the {template} email after {self._backoff.retries + 1} attempts:"
            f" {problem}"
        )


def _log(template: str, order_id: object, started: float, outcome: str, detail: str) -> None:
    # The address and the key never reach the log (CLAUDE.md logging rule).
    log.info(
        "resend send template=%s detail=%s",
        template,
        detail,
        extra={
            "order_id": order_id,
            "stage": "mail",
            "event": "resend_send",
            "latency_ms": latency_ms(started),
            "outcome": outcome,
        },
    )
